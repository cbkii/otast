#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
VERSION_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.]+)?")
REQUIRED_PHASES = {
    "install_reboot": "PASS",
    "apply_reboot": "PASS",
    "verify_noop_restore": "PASS",
    "restore_reboot_report": "PASS",
}


class ProofError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_proof(
    proof_path: Path,
    module_zip: Path,
    *,
    version: str,
    commit_sha: str,
) -> dict[str, object]:
    if not VERSION_RE.fullmatch(version):
        raise ProofError(f"invalid expected version: {version!r}")
    if not COMMIT_RE.fullmatch(commit_sha):
        raise ProofError("expected commit must be a lowercase full commit SHA")
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

    if value.get("schema_version") != 1:
        raise ProofError("unsupported proof schema")
    if value.get("result") != "PASS":
        raise ProofError("device proof is not PASS")
    if value.get("version") != version:
        raise ProofError("proof version does not match release")
    if value.get("commit_sha") != commit_sha:
        raise ProofError("proof commit does not match release target")
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
    metadata = dict(
        line.split("=", 1)
        for line in module_prop.splitlines()
        if line and "=" in line
    )
    release = dict(
        line.split("=", 1)
        for line in release_props.splitlines()
        if line and "=" in line
    )
    if metadata.get("id") != "otast" or metadata.get("version") != version:
        raise ProofError("draft ZIP module identity/version does not match release")
    if release.get("version") != version or release.get("commit_sha") != commit_sha:
        raise ProofError("draft ZIP release.properties does not match release target")

    recorded_sha = value.get("module_sha256")
    if not isinstance(recorded_sha, str) or not SHA256_RE.fullmatch(recorded_sha):
        raise ProofError("proof module SHA-256 is malformed")
    actual_sha = sha256_file(module_zip)
    if recorded_sha != actual_sha:
        raise ProofError("proof module SHA-256 does not match draft asset")

    phases = value.get("phases")
    if not isinstance(phases, dict):
        raise ProofError("proof phases are missing")
    baseline = phases.get("baseline")
    if baseline not in {"PASS", "NOT_REQUIRED"}:
        raise ProofError("baseline phase is not proven")
    for key, expected in REQUIRED_PHASES.items():
        if phases.get(key) != expected:
            raise ProofError(f"required phase is not {expected}: {key}")

    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a sanitized physical-device OTAST release proof."
    )
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--module-zip", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    try:
        value = validate_proof(
            args.proof,
            args.module_zip,
            version=args.version,
            commit_sha=args.commit,
        )
    except ProofError as exc:
        print(f"STOP: {exc}")
        return 1
    print(
        "PASS: physical release proof matches exact draft asset "
        f"{value['module_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
