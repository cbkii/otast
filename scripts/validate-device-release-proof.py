#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.otastctl.qualification import registry_provenance  # noqa: E402
from tools.otastctl.runtime_digest import RUNTIME_DIGEST_ALGORITHM, runtime_digest_from_zip  # noqa: E402

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.]+)?$")
PROOF_SCHEMA_VERSION = 4
ROOT_RESULTS = {"PASS", "PASS_WITH_ATTRIBUTION"}
APPLY_RESULTS = {"PASS", "SKIPPED_NO_CHANGES", "PASS_AFTER_SETTLING_REBOOT"}
REAPPLY_RESULTS = {"PASS", "SKIPPED_ALREADY_CURRENT"}


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
        if key in result:
            raise ProofError(f"duplicate property in embedded metadata: {key}")
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
    platforms = registry.get("platforms")
    if not isinstance(support, dict) or not isinstance(platforms, dict):
        raise ProofError("compatibility support model is incomplete")
    reference = support.get("release_reference")
    devices = support.get("devices")
    if not isinstance(reference, dict) or not isinstance(devices, dict):
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
    fixture_path = reference.get("authority_fixture")
    if not isinstance(fixture_path, str) or not fixture_path.startswith("authority/"):
        raise ProofError("release-reference authority fixture is invalid")
    authority_path = repo_root / fixture_path
    authority_raw = authority_path.read_bytes()
    authority_values: dict[str, str] = {}
    for line in authority_raw.decode("utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        authority_values[key] = value
    return {
        "device": device,
        "model": reference.get("model", device_record.get("model", "")),
        "manufacturer": authority_values.get("ro.product.manufacturer", ""),
        "build": build,
        "fingerprint": authority_values.get("ro.build.fingerprint", ""),
        "platform_profile": profile_id,
        "android_release": profile.get("android_release"),
        "sdk": profile.get("sdk"),
        "system_spl": authority_values.get("ro.build.version.security_patch", ""),
        "vendor_spl": authority_values.get("ro.vendor.build.security_patch", ""),
        "authority_sha256": hashlib.sha256(authority_raw).hexdigest(),
        "authority_boot": {
            key: authority_values.get(key, "")
            for key in (
                "boot.img.sha256",
                "ro.boot.vbmeta.digest",
                "ro.boot.vbmeta.size",
                "ro.boot.vbmeta.avb_version",
                "ro.boot.avb_version",
            )
        },
    }


def _require_pass(value: object, label: str) -> None:
    if value != "PASS":
        raise ProofError(f"{label} is not PASS")


def _validate_device_evidence(evidence: object, reference: dict[str, object]) -> dict[str, Any]:
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise ProofError("device evidence schema is missing or unsupported")
    if evidence.get("result") != "PASS" or evidence.get("read_only") is not True:
        raise ProofError("device evidence is not a read-only PASS capture")
    privacy = evidence.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("keybox_material_exported") is not False or privacy.get("mutation_performed") is not False:
        raise ProofError("device evidence privacy boundary is not proven")
    device = evidence.get("device")
    if not isinstance(device, dict):
        raise ProofError("device evidence identity is missing")
    expected = {
        "codename": reference["device"],
        "model": reference["model"],
        "manufacturer": reference["manufacturer"],
        "build_id": reference["build"],
        "fingerprint": reference["fingerprint"],
        "platform_profile": reference["platform_profile"],
        "sdk": str(reference["sdk"]),
        "system_spl": reference["system_spl"],
        "vendor_spl": reference["vendor_spl"],
        "authority_sha256": reference["authority_sha256"],
    }
    for key, wanted in expected.items():
        if str(device.get(key, "")) != str(wanted):
            raise ProofError(f"device evidence {key} does not match release reference")
    if device.get("authority") != reference["authority_boot"]:
        raise ProofError("device evidence boot/VBMeta authority does not match release reference")
    page_size = str(device.get("runtime_page_size", ""))
    if not page_size.isdigit() or int(page_size) <= 0:
        raise ProofError("device evidence runtime page size is invalid")
    if not str(device.get("kernel", "")).strip():
        raise ProofError("device evidence kernel identity is missing")
    if not str(device.get("primary_abi", "")).strip():
        raise ProofError("device evidence primary ABI is missing")
    magisk = evidence.get("magisk")
    if not isinstance(magisk, dict) or not str(magisk.get("version", "")).strip() or not str(magisk.get("version_code", "")).strip():
        raise ProofError("device evidence Magisk identity is missing")
    managed = evidence.get("managed_targets")
    if not isinstance(managed, dict) or not managed:
        raise ProofError("device evidence managed-target identities are missing")
    root = evidence.get("root_exposure_attribution")
    if not isinstance(root, dict) or root.get("result") not in ROOT_RESULTS:
        raise ProofError("root-exposure attribution is not an accepted release result")
    external = evidence.get("external_acceptance")
    if not isinstance(external, dict):
        raise ProofError("external release acceptance evidence is missing")
    _require_pass(external.get("tricky_store_health"), "Tricky Store health")
    _require_pass(external.get("local_attestation"), "local attestation")
    integrity = external.get("play_integrity")
    if not isinstance(integrity, dict):
        raise ProofError("Play Integrity evidence is missing")
    for verdict in ("basic", "device", "strong"):
        _require_pass(integrity.get(verdict), f"Play Integrity {verdict}")
    if external.get("play_store_certification") != "CERTIFIED":
        raise ProofError("Play Store certification is not CERTIFIED")
    return evidence


def validate_proof(
    proof_path: Path,
    module_zip: Path,
    *,
    version: str,
    repo_root: Path = ROOT,
) -> dict[str, object]:
    if not VERSION_RE.fullmatch(version):
        raise ProofError(f"invalid expected version: {version!r}")
    value = _load_json(proof_path, "proof file")
    if module_zip.is_symlink() or not module_zip.is_file():
        raise ProofError("module ZIP is missing or unsafe")
    if value.get("schema_version") != PROOF_SCHEMA_VERSION:
        raise ProofError(f"unsupported proof schema; expected {PROOF_SCHEMA_VERSION}")
    if value.get("result") != "PASS" or value.get("version") != version:
        raise ProofError("device proof result/version is not valid")
    evidence_kind = value.get("evidence_kind")
    if evidence_kind not in {"DIRECT_PHYSICAL", "RUNTIME_EQUIVALENT_REUSE"}:
        raise ProofError("device proof evidence_kind is invalid")

    try:
        with zipfile.ZipFile(module_zip) as archive:
            module_prop = parse_properties(archive.read("module.prop").decode("utf-8"))
            release_props = parse_properties(archive.read("release.properties").decode("utf-8"))
    except (OSError, KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ProofError(f"cannot inspect module ZIP metadata: {exc}") from exc
    if module_prop.get("id") != "otast" or module_prop.get("version") != version:
        raise ProofError("draft ZIP module identity/version does not match release")
    if release_props.get("schema_version") != "2" or release_props.get("version") != version:
        raise ProofError("draft ZIP release.properties schema/version mismatch")
    version_code = module_prop.get("versionCode")
    if not isinstance(version_code, str) or not version_code.isdigit():
        raise ProofError("draft ZIP versionCode is invalid")
    if value.get("version_code") != int(version_code):
        raise ProofError("proof versionCode does not match module ZIP")

    current_source = release_props.get("commit_sha", "")
    if SHA40_RE.fullmatch(current_source) is None:
        raise ProofError("draft ZIP source commit is not a full Git SHA")
    current_zip_sha = sha256_file(module_zip)
    current_runtime = runtime_digest_from_zip(module_zip)
    if value.get("current_source_commit") != current_source:
        raise ProofError("proof current source commit does not match module ZIP")
    if value.get("current_zip_sha256") != current_zip_sha:
        raise ProofError("proof current ZIP SHA-256 does not match module ZIP")
    if value.get("runtime_digest_algorithm") != RUNTIME_DIGEST_ALGORITHM or value.get("runtime_digest") != current_runtime:
        raise ProofError("proof runtime digest does not match module ZIP")
    if release_props.get("runtime_digest_algorithm") != RUNTIME_DIGEST_ALGORITHM or release_props.get("runtime_digest") != current_runtime:
        raise ProofError("embedded runtime digest does not match module ZIP")

    provenance = registry_provenance(repo_root)
    proof_provenance = value.get("registry_provenance")
    if proof_provenance != provenance:
        raise ProofError("proof registry provenance does not match current release source")
    for key, expected in provenance.items():
        if release_props.get(key) != str(expected):
            raise ProofError(f"embedded {key} does not match current repository")

    qualified_source = value.get("qualified_source_commit")
    qualified_zip = value.get("qualified_zip_sha256")
    if not isinstance(qualified_source, str) or SHA40_RE.fullmatch(qualified_source) is None:
        raise ProofError("qualified source commit is invalid")
    if not isinstance(qualified_zip, str) or SHA256_RE.fullmatch(qualified_zip) is None:
        raise ProofError("qualified ZIP SHA-256 is invalid")
    if evidence_kind == "DIRECT_PHYSICAL":
        if qualified_source != current_source or qualified_zip != current_zip_sha:
            raise ProofError("direct physical proof must qualify the exact current source and ZIP")
    else:
        equivalence = value.get("runtime_equivalence")
        if not isinstance(equivalence, dict) or equivalence.get("result") != "PASS":
            raise ProofError("runtime-equivalent proof has no PASS equivalence evidence")
        if equivalence.get("qualified_runtime_digest") != current_runtime or equivalence.get("current_runtime_digest") != current_runtime:
            raise ProofError("runtime-equivalent proof digest mismatch")
        _require_pass(equivalence.get("ci_equivalence"), "runtime-equivalence CI")

    reference = release_reference(repo_root)
    _validate_device_evidence(value.get("device_evidence"), reference)

    phases = value.get("phases")
    if not isinstance(phases, dict):
        raise ProofError("proof phases are missing")
    if phases.get("baseline") not in {"PASS", "NOT_REQUIRED"}:
        raise ProofError("baseline phase is not proven")
    _require_pass(phases.get("install_reboot"), "install reboot")
    _require_pass(phases.get("preflight"), "Preflight")
    if phases.get("apply") not in APPLY_RESULTS:
        raise ProofError("first Apply phase is not proven")
    if phases.get("post_apply_reboot") not in {"PASS", "SKIPPED_NO_CHANGES"}:
        raise ProofError("post-Apply reboot phase is not proven")
    _require_pass(phases.get("verify"), "post-reboot Verify")
    _require_pass(phases.get("second_apply_noop"), "second Apply no-op")
    _require_pass(phases.get("restore"), "Restore")
    _require_pass(phases.get("restore_reboot_report"), "post-Restore reboot/report")
    if phases.get("reapply") not in REAPPLY_RESULTS:
        raise ProofError("re-Apply phase is not proven")

    generated = value.get("generated_utc")
    if not isinstance(generated, str) or not generated:
        raise ProofError("generated_utc metadata is missing")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a sanitized runtime-bound physical-device OTAST release proof.")
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--module-zip", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        value = validate_proof(args.proof, args.module_zip, version=args.version)
    except (ProofError, OSError, ValueError) as exc:
        print(f"STOP: {exc}")
        return 1
    print(
        "PASS: physical release proof matches exact release asset/runtime and compatibility evidence "
        f"{value['current_zip_sha256']} {value['runtime_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
