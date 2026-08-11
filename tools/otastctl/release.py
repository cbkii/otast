from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from .build import build_module, module_metadata, validate_module_zip
from .util import OtastError, atomic_write, sha256_file, stable_json

REPOSITORY = "cbkii/otast"
UPDATE_JSON_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/update.json"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/CHANGELOG.md"
VERSION_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_SHA_RE = re.compile(r"^(?:unknown|[0-9a-f]{40}|[0-9a-f]{64})$")


def _parse_properties(text: str, *, label: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        if not raw or "=" not in raw:
            raise OtastError(f"{label} contains a malformed line")
        key, value = raw.split("=", 1)
        if not key or not value or key in values:
            raise OtastError(f"{label} contains duplicate or empty metadata")
        values[key] = value
    return values


def expected_asset_name(version: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise OtastError(f"invalid release version: {version}")
    return f"otast-{version}.zip"


def expected_update_metadata(version: str, version_code: int) -> dict[str, object]:
    asset = expected_asset_name(version)
    if version_code <= 0:
        raise OtastError("versionCode must be positive")
    return {
        "version": version,
        "versionCode": version_code,
        "zipUrl": f"https://github.com/{REPOSITORY}/releases/download/{version}/{asset}",
        "changelog": CHANGELOG_URL,
    }


def _read_checksum(checksum_path: Path, expected_basename: str) -> str:
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OtastError(f"cannot read checksum sidecar: {checksum_path}") from exc
    if len(lines) != 1:
        raise OtastError("checksum sidecar must contain exactly one line")
    match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", lines[0])
    if not match:
        raise OtastError("checksum sidecar has invalid format")
    digest, basename = match.groups()
    if basename != expected_basename:
        raise OtastError(f"checksum sidecar names {basename}, expected {expected_basename}")
    return digest


def build_release_bundle(repo_root: Path, output_dir: Path, *, commit_sha: str = "unknown") -> dict[str, object]:
    if not SOURCE_SHA_RE.fullmatch(commit_sha):
        raise OtastError("source commit must be unknown or lowercase 40/64 hex")
    metadata = module_metadata(repo_root / "module/module.prop")
    version = metadata["version"]
    version_code = int(metadata["versionCode"])
    expected_asset_name(version)

    zip_path = build_module(repo_root, output_dir, commit_sha=commit_sha)
    checksum_path = output_dir / f"{zip_path.name}.sha256"
    digest = _read_checksum(checksum_path, zip_path.name)
    calculated = sha256_file(zip_path)
    if digest != calculated:
        raise OtastError("generated checksum does not match generated module ZIP")

    manifest = {
        "schema_version": 1,
        "version": version,
        "version_code": version_code,
        "source_commit": commit_sha,
        "zip_filename": zip_path.name,
        "zip_sha256": calculated,
        "checksum_filename": checksum_path.name,
        "release_tag": version,
    }
    manifest_path = output_dir / "release-manifest.json"
    atomic_write(manifest_path, stable_json(manifest).encode("utf-8"))
    verify_release_bundle(zip_path, checksum_path, manifest_path)
    return {
        **manifest,
        "zip_path": str(zip_path),
        "checksum_path": str(checksum_path),
        "manifest_path": str(manifest_path),
    }


def verify_release_bundle(zip_path: Path, checksum_path: Path, manifest_path: Path) -> dict[str, object]:
    validate_module_zip(zip_path)
    recorded_digest = _read_checksum(checksum_path, zip_path.name)
    actual_digest = sha256_file(zip_path)
    if recorded_digest != actual_digest:
        raise OtastError("release ZIP SHA-256 does not match checksum sidecar")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OtastError(f"invalid release manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise OtastError("release manifest schema_version must be 1")

    version = manifest.get("version")
    version_code = manifest.get("version_code")
    source_commit = manifest.get("source_commit")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise OtastError("release manifest version is invalid")
    if not isinstance(version_code, int) or version_code <= 0:
        raise OtastError("release manifest version_code is invalid")
    if not isinstance(source_commit, str) or not SOURCE_SHA_RE.fullmatch(source_commit):
        raise OtastError("release manifest source_commit is invalid")

    expected_zip = expected_asset_name(version)
    if manifest.get("release_tag") != version:
        raise OtastError("release manifest tag/version mismatch")
    if manifest.get("zip_filename") != expected_zip or zip_path.name != expected_zip:
        raise OtastError("release manifest ZIP filename mismatch")
    if manifest.get("checksum_filename") != checksum_path.name:
        raise OtastError("release manifest checksum filename mismatch")
    if manifest.get("zip_sha256") != actual_digest:
        raise OtastError("release manifest ZIP SHA-256 mismatch")

    with zipfile.ZipFile(zip_path) as archive:
        embedded_metadata = _parse_properties(archive.read("module.prop").decode("utf-8"), label="embedded module.prop")
        release_properties = _parse_properties(
            archive.read("release.properties").decode("utf-8"), label="embedded release.properties"
        )

    if embedded_metadata.get("id") != "otast":
        raise OtastError("embedded module ID mismatch")
    if embedded_metadata.get("version") != version:
        raise OtastError("embedded module version does not match release manifest")
    if embedded_metadata.get("versionCode") != str(version_code):
        raise OtastError("embedded module versionCode does not match release manifest")
    if embedded_metadata.get("updateJson") != UPDATE_JSON_URL:
        raise OtastError("embedded module updateJson is not the stable OTAST update channel")
    if release_properties.get("version") != version:
        raise OtastError("release.properties version mismatch")
    if release_properties.get("version_code") != str(version_code):
        raise OtastError("release.properties version_code mismatch")
    if release_properties.get("commit_sha") != source_commit:
        raise OtastError("release.properties source commit mismatch")

    return {
        "result": "PASS",
        "version": version,
        "version_code": version_code,
        "source_commit": source_commit,
        "zip_filename": zip_path.name,
        "zip_sha256": actual_digest,
        "checksum_filename": checksum_path.name,
        "manifest_filename": manifest_path.name,
    }


def validate_update_metadata(data: object, *, expected: dict[str, object] | None = None) -> dict[str, object]:
    if not isinstance(data, dict):
        raise OtastError("update metadata must be a JSON object")
    required = {"version", "versionCode", "zipUrl", "changelog"}
    if set(data) != required:
        raise OtastError("update metadata must contain exactly version, versionCode, zipUrl and changelog")
    version = data.get("version")
    version_code = data.get("versionCode")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise OtastError("update metadata version is invalid")
    if not isinstance(version_code, int) or version_code <= 0:
        raise OtastError("update metadata versionCode is invalid")
    canonical = expected_update_metadata(version, version_code)
    if data != canonical:
        raise OtastError("update metadata URLs do not match the canonical OTAST release/update channel")
    if expected is not None and data != expected:
        raise OtastError("update metadata does not match the requested release manifest")
    return canonical


def load_update_metadata(path: Path, *, expected: dict[str, object] | None = None) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OtastError(f"invalid update metadata: {path}") from exc
    return validate_update_metadata(data, expected=expected)


def update_metadata_from_manifest(manifest_path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OtastError(f"invalid release manifest: {manifest_path}") from exc
    version = manifest.get("version") if isinstance(manifest, dict) else None
    version_code = manifest.get("version_code") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not isinstance(version_code, int):
        raise OtastError("release manifest cannot generate update metadata")
    return expected_update_metadata(version, version_code)


def write_update_metadata(manifest_path: Path, output_path: Path) -> dict[str, object]:
    data = update_metadata_from_manifest(manifest_path)
    atomic_write(output_path, stable_json(data).encode("utf-8"))
    return data
