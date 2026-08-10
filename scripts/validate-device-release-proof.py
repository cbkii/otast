#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

SHA256_RE = re.compile(r"[0-9a-f]{64}")
VERSION_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.]+)?")
APPLY_RESULTS = {"PASS", "PASS_AFTER_SETTLING_REBOOT", "SKIPPED_NO_CHANGES"}


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


def validate_proof(
    proof_path: Path,
    module_zip: Path,
    *,
    version: str,
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

    if value.get("schema_version") not in {1, 2}:
        raise ProofError("unsupported proof schema")
    if value.get("result") != "PASS":
        raise ProofError("device proof is not PASS")
    if value.get("version") != version:
        raise ProofError("proof version does not match release")
    if value.get("device") != "tegu":
        raise ProofError("proof device is not tegu")
    if value.get("sdk") != 36:
        raise ProofError("proof SDK is not 36")

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

    # Source commit is diagnostic metadata only. It is deliberately not a release gate.
    source = value.get("source_commit")
    if source is not None and not isinstance(source, str):
        raise ProofError("source_commit metadata must be a string when present")

    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a sanitized physical-device OTAST release proof."
    )
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--module-zip", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        value = validate_proof(
            args.proof,
            args.module_zip,
            version=args.version,
        )
    except ProofError as exc:
        print(f"STOP: {exc}")
        return 1
    print(
        "PASS: physical release proof matches exact release asset "
        f"{value['module_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
