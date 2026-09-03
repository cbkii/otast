#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"[0-9a-f]{64}")
VERSION_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.]+)?")
APPLY_RESULTS = {"PASS", "PASS_AFTER_SETTLING_REBOOT", "SKIPPED_NO_CHANGES"}
PROOF_SCHEMA_VERSION = 3
ROOT = Path(__file__).resolve().parents[1]


class ProofError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_properties(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProofError(f"{label} is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProofError(f"{label} must be an object")
    return value


def release_reference(repo_root: Path = ROOT) -> dict[str, object]:
    registry = _load_json(repo_root / "compatibility/supported-targets.json", "compatibility registry")
    support = registry.get("support_model")
    if not isinstance(support, dict):
        raise ProofError("compatibility registry has no support_model")
    reference = support.get("release_reference")
    devices = support.get("devices")
    platforms = registry.get("platforms")
    if not isinstance(reference, dict) or not isinstance(devices, dict) or not isinstance(platforms, dict):
        raise ProofError("compatibility release-reference contract is incomplete")

    device = reference.get("device")
    build = reference.get("build")
    profile_id = reference.get("platform_profile")
    tier = reference.get("tier")
    if not all(isinstance(value, str) and value for value in (device, build, profile_id, tier)):
        raise ProofError("compatibility release reference is malformed")
    if tier not in {"DEVICE_VALIDATED", "RELEASE_QUALIFIED"}:
        raise ProofError("release reference is not physically validated")
    device_record = devices.get(device)
    if not isinstance(device_record, dict):
        raise ProofError("release reference device is not declared")
    if device_record.get("tier") != tier or build not in device_record.get("qualified_builds", []):
        raise ProofError("release reference disagrees with device qualification")
    platform_record = platforms.get(profile_id)
    if not isinstance(platform_record, dict) or platform_record.get("status") != "SUPPORTED":
        raise ProofError("release reference platform is not supported")
    profile_path = platform_record.get("profile")
    if not isinstance(profile_path, str) or not profile_path.startswith("compatibility/platforms/"):
        raise ProofError("release reference platform path is invalid")
    profile = _load_json(repo_root / profile_path, "release-reference platform profile")
    sdk = profile.get("sdk")
    android_release = profile.get("android_release")
    if not isinstance(sdk, int) or isinstance(sdk, bool) or sdk <= 0:
        raise ProofError("release-reference platform SDK is invalid")
    if not isinstance(android_release, str) or not android_release:
        raise ProofError("release-reference Android release is invalid")
    return {
        "device": device,
        "model": reference.get("model", device_record.get("model", "")),
        "build": build,
        "platform_profile": profile_id,
        "android_release": android_release,
        "sdk": sdk,
        "tier": tier,
    }


def validate_proof(
    proof_path: Path,
    module_zip: Path,
    *,
    version: str,
    repo_root: Path = ROOT,
) -> dict[str, object]:
    if not VERSION_RE.fullmatch(version):
        raise ProofError(f"invalid expected version: {version!r}")
    if proof_path.is_symlink() or not proof_path.is_file():
        raise ProofError("proof file is missing or unsafe")
    if module_zip.is_symlink() or not module_zip.is_file():
        raise ProofError("module ZIP is missing or unsafe")

    try:
        value = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProofError(f"cannot read proof JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProofError("proof root must be an object")

    if value.get("schema_version") != PROOF_SCHEMA_VERSION:
        raise ProofError(f"unsupported proof schema; expected {PROOF_SCHEMA_VERSION}")
    if value.get("result") != "PASS":
        raise ProofError("device proof is not PASS")
    if value.get("version") != version:
        raise ProofError("proof version does not match release")

    reference = release_reference(repo_root)
    for key in ("device", "build", "platform_profile", "sdk"):
        if value.get(key) != reference[key]:
            raise ProofError(f"proof {key} does not match compatibility release reference")

    try:
        with zipfile.ZipFile(module_zip) as archive:
            module_prop = archive.read("module.prop").decode("utf-8")
            release_props = archive.read("release.properties").decode("utf-8")
    except (OSError, KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ProofError(f"cannot inspect module ZIP metadata: {exc}") from exc

    metadata = parse_properties(module_prop)
    release = parse_properties(release_props)
    if metadata.get("id") != "otast" or metadata.get("version") != version:
        raise ProofError("draft ZIP module identity/version does not match release")
    if release.get("version") != version:
        raise ProofError("draft ZIP release.properties version does not match release")

    recorded_sha = value.get("module_sha256")
    if not isinstance(recorded_sha, str) or not SHA256_RE.fullmatch(recorded_sha):
        raise ProofError("proof module SHA-256 is malformed")
    actual_sha = sha256_file(module_zip)
    if recorded_sha != actual_sha:
        raise ProofError("proof module SHA-256 does not match draft asset")

    phases = value.get("phases")
    if not isinstance(phases, dict):
        raise ProofError("proof phases are missing")
    if phases.get("baseline") not in {"PASS", "NOT_REQUIRED"}:
        raise ProofError("baseline phase is not proven")
    if phases.get("install_reboot") != "PASS":
        raise ProofError("install reboot phase is not PASS")
    if phases.get("apply_reboot") not in APPLY_RESULTS:
        raise ProofError("Apply phase is not an accepted successful result")
    if phases.get("verify_noop_restore") != "PASS":
        raise ProofError("Verify/no-op/Restore phase is not PASS")
    if phases.get("restore_reboot_report") != "PASS":
        raise ProofError("post-Restore reboot/report phase is not PASS")

    source = value.get("source_commit")
    if source is not None and not isinstance(source, str):
        raise ProofError("source_commit metadata must be a string when present")

    generated = value.get("generated_utc")
    if not isinstance(generated, str) or not generated:
        raise ProofError("generated_utc metadata is missing")

    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a sanitized physical-device OTAST release proof.")
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--module-zip", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        value = validate_proof(args.proof, args.module_zip, version=args.version)
    except ProofError as exc:
        print(f"STOP: {exc}")
        return 1
    print(
        "PASS: physical release proof matches exact release asset and compatibility release reference "
        f"{value['device']}/{value['build']} {value['module_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
