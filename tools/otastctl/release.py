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
VERSION_RE = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)(?:-([0-9A-Za-z][0-9A-Za-z.-]*))?$")
SOURCE_SHA_RE = re.compile(r"^(?:unknown|[0-9a-f]{40}|[0-9a-f]{64})$")
MANIFEST_KEYS = {
    "schema_version",
    "version",
    "version_code",
    "source_commit",
    "zip_filename",
    "zip_sha256",
    "checksum_filename",
    "release_tag",
}


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


def _version_match(version: str) -> re.Match[str]:
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise OtastError(f"invalid release version: {version}")
    return match


def version_core(version: str) -> tuple[int, int, int]:
    match = _version_match(version)
    return tuple(int(value) for value in match.group(1, 2, 3))  # type: ignore[return-value]


def is_prerelease(version: str) -> bool:
    return _version_match(version).group(4) is not None


def bump_patch(version: str) -> str:
    if is_prerelease(version):
        raise OtastError("stable update channel cannot use a prerelease version")
    major, minor, patch = version_core(version)
    return f"v{major}.{minor}.{patch + 1}"


def expected_asset_name(version: str) -> str:
    _version_match(version)
    return f"otast-{version}.zip"


def expected_update_metadata(version: str, version_code: int) -> dict[str, object]:
    asset = expected_asset_name(version)
    if type(version_code) is not int or version_code <= 0:
        raise OtastError("versionCode must be a positive integer")
    return {
        "version": version,
        "versionCode": version_code,
        "zipUrl": f"https://github.com/{REPOSITORY}/releases/download/{version}/{asset}",
        "changelog": CHANGELOG_URL,
    }


def resolve_release_identity(
    stable: dict[str, object],
    current: dict[str, str],
    *,
    requested_version: str = "",
) -> dict[str, object]:
    stable = validate_update_metadata(stable)
    stable_version = str(stable["version"])
    stable_code = int(stable["versionCode"])
    if is_prerelease(stable_version):
        raise OtastError("stable update channel unexpectedly points to a prerelease")

    current_version = current.get("version", "")
    current_code_text = current.get("versionCode", "")
    current_update = current.get("updateJson", "")
    _version_match(current_version)
    if not current_code_text.isdigit() or int(current_code_text) <= 0:
        raise OtastError("module.prop versionCode must be positive")
    current_code = int(current_code_text)
    if current_update != UPDATE_JSON_URL:
        raise OtastError("module.prop updateJson is not the stable OTAST update channel")
    if current_code < stable_code:
        raise OtastError("module.prop versionCode is behind the stable update channel")

    requested = requested_version.strip()
    reused = False
    if requested:
        _version_match(requested)
        if version_core(requested) <= version_core(stable_version):
            raise OtastError("requested release version must be newer than the stable release")
        candidate = requested
        if current_version == candidate and current_code > stable_code:
            version_code = current_code
            reused = True
        else:
            version_code = max(stable_code, current_code) + 1
    elif current_version != stable_version and current_code > stable_code:
        if version_core(current_version) <= version_core(stable_version):
            raise OtastError("unpublished source version is not newer than the stable release")
        candidate = current_version
        version_code = current_code
        reused = True
    else:
        candidate = bump_patch(stable_version)
        version_code = max(stable_code, current_code) + 1

    return {
        "stable_version": stable_version,
        "stable_version_code": stable_code,
        "version": candidate,
        "version_code": version_code,
        "prerelease": is_prerelease(candidate),
        "reused_candidate": reused,
    }


def resolve_release_identity_from_repo(repo_root: Path, *, requested_version: str = "") -> dict[str, object]:
    stable = load_update_metadata(repo_root / "update.json")
    current = module_metadata(repo_root / "module/module.prop")
    return resolve_release_identity(stable, current, requested_version=requested_version)


def _replace_property(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    matches = [index for index, line in enumerate(lines) if line.startswith(f"{key}=")]
    if len(matches) != 1:
        raise OtastError(f"module.prop must contain exactly one {key} entry")
    lines[matches[0]] = f"{key}={value}"
    return "\n".join(lines) + "\n"


def _normalize_release_notes(notes: str) -> str:
    lines = []
    for line in notes.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("chore(release): prepare "):
            continue
        lines.append(line.rstrip())
    normalized = "\n".join(lines).strip()
    return normalized or "- Release metadata and validated package refresh."


def update_changelog_section(changelog: Path, version: str, notes: str) -> None:
    _version_match(version)
    text = changelog.read_text(encoding="utf-8")
    normalized = _normalize_release_notes(notes)
    section = f"## {version}\n\n{normalized}\n\n"
    heading = re.compile(rf"(?m)^## {re.escape(version)}(?:\s.*)?$")
    match = heading.search(text)
    if match:
        next_heading = re.search(r"(?m)^## ", text[match.end() :])
        end = match.end() + (next_heading.start() if next_heading else len(text[match.end() :]))
        replacement = section.rstrip() + "\n\n"
        text = text[: match.start()] + replacement + text[end:].lstrip("\n")
    else:
        first_heading = re.search(r"(?m)^## ", text)
        if first_heading:
            text = text[: first_heading.start()] + section + text[first_heading.start() :]
        else:
            text = text.rstrip() + "\n\n" + section
    atomic_write(changelog, text.encode("utf-8"))


def stamp_release_metadata(
    repo_root: Path,
    *,
    version: str,
    version_code: int,
    notes: str | None = None,
) -> dict[str, object]:
    expected_asset_name(version)
    if type(version_code) is not int or version_code <= 0:
        raise OtastError("versionCode must be a positive integer")
    module_prop = repo_root / "module/module.prop"
    text = module_prop.read_text(encoding="utf-8")
    text = _replace_property(text, "version", version)
    text = _replace_property(text, "versionCode", str(version_code))
    atomic_write(module_prop, text.encode("utf-8"))
    if notes is not None:
        update_changelog_section(repo_root / "CHANGELOG.md", version, notes)
    metadata = module_metadata(module_prop)
    if metadata["version"] != version or int(metadata["versionCode"]) != version_code:
        raise OtastError("release metadata stamp did not persist expected module identity")
    if metadata["updateJson"] != UPDATE_JSON_URL:
        raise OtastError("release metadata stamp changed the stable update channel")
    return {"version": version, "version_code": version_code, "prerelease": is_prerelease(version)}


def _release_asset_names(release: dict[str, object]) -> set[str]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return set()
    result: set[str] = set()
    for asset in assets:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str):
            result.add(str(asset["name"]))
    return result


def select_proven_draft(releases: object, *, requested_version: str = "") -> dict[str, object]:
    if not isinstance(releases, list):
        raise OtastError("GitHub release data must be a JSON array")
    eligible: list[dict[str, object]] = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") is not True:
            continue
        version = release.get("tag_name")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            continue
        zip_name = expected_asset_name(version)
        required = {
            zip_name,
            f"{zip_name}.sha256",
            "release-manifest.json",
            f"otast-{version}-device-proof.json",
        }
        if required.issubset(_release_asset_names(release)):
            eligible.append(release)

    requested = requested_version.strip()
    if requested:
        _version_match(requested)
        matches = [release for release in eligible if release.get("tag_name") == requested]
        if len(matches) != 1:
            raise OtastError(f"no physically proven release draft exists for {requested}")
        chosen = matches[0]
    else:
        if not eligible:
            raise OtastError("no physically proven release draft exists")
        if len(eligible) != 1:
            versions = ", ".join(sorted(str(release.get("tag_name")) for release in eligible))
            raise OtastError(f"multiple physically proven release drafts exist: {versions}")
        chosen = eligible[0]

    version = str(chosen["tag_name"])
    return {"version": version, "prerelease": is_prerelease(version)}


def load_release_list(path: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtastError(f"invalid GitHub release data: {path}") from exc
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise OtastError("GitHub release data must be a JSON array of objects")
    return data


def _read_checksum(checksum_path: Path, expected_basename: str) -> str:
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
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


def _load_manifest(manifest_path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtastError(f"invalid release manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise OtastError("release manifest must be a JSON object")
    if set(manifest) != MANIFEST_KEYS:
        raise OtastError("release manifest fields do not match schema 1")
    if manifest.get("schema_version") != 1:
        raise OtastError("release manifest schema_version must be 1")
    return manifest


def _manifest_identity(manifest: dict[str, object]) -> tuple[str, int, str]:
    version = manifest.get("version")
    version_code = manifest.get("version_code")
    source_commit = manifest.get("source_commit")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise OtastError("release manifest version is invalid")
    if type(version_code) is not int or version_code <= 0:
        raise OtastError("release manifest version_code is invalid")
    if not isinstance(source_commit, str) or not SOURCE_SHA_RE.fullmatch(source_commit):
        raise OtastError("release manifest source_commit is invalid")
    if manifest.get("release_tag") != version:
        raise OtastError("release manifest tag/version mismatch")
    return version, version_code, source_commit


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
    actual_digest = sha256_file(zip_path)
    manifest = _load_manifest(manifest_path)
    version, version_code, source_commit = _manifest_identity(manifest)

    expected_zip = expected_asset_name(version)
    expected_checksum = f"{expected_zip}.sha256"
    if zip_path.name != expected_zip or manifest.get("zip_filename") != expected_zip:
        raise OtastError("release manifest ZIP filename mismatch")
    if checksum_path.name != expected_checksum or manifest.get("checksum_filename") != expected_checksum:
        raise OtastError("release checksum filename mismatch")

    recorded_digest = _read_checksum(checksum_path, expected_zip)
    if recorded_digest != actual_digest:
        raise OtastError("release ZIP SHA-256 does not match checksum sidecar")
    if manifest.get("zip_sha256") != actual_digest:
        raise OtastError("release manifest ZIP SHA-256 mismatch")

    try:
        with zipfile.ZipFile(zip_path) as archive:
            embedded_text = archive.read("module.prop").decode("utf-8")
            release_text = archive.read("release.properties").decode("utf-8")
    except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise OtastError("release ZIP embedded metadata is missing, corrupt or not UTF-8") from exc

    embedded_metadata = _parse_properties(embedded_text, label="embedded module.prop")
    release_properties = _parse_properties(release_text, label="embedded release.properties")

    if embedded_metadata.get("id") != "otast":
        raise OtastError("embedded module ID mismatch")
    if embedded_metadata.get("version") != version:
        raise OtastError("embedded module version does not match release manifest")
    if embedded_metadata.get("versionCode") != str(version_code):
        raise OtastError("embedded module versionCode does not match release manifest")
    if embedded_metadata.get("updateJson") != UPDATE_JSON_URL:
        raise OtastError("embedded module updateJson is not the stable OTAST update channel")
    if release_properties.get("schema_version") != "1":
        raise OtastError("release.properties schema_version mismatch")
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
    if type(version_code) is not int or version_code <= 0:
        raise OtastError("update metadata versionCode is invalid")
    if is_prerelease(version):
        raise OtastError("stable update metadata cannot advertise a prerelease")
    canonical = expected_update_metadata(version, version_code)
    if data != canonical:
        raise OtastError("update metadata URLs do not match the canonical OTAST release/update channel")
    if expected is not None and data != expected:
        raise OtastError("update metadata does not match the requested release manifest")
    return canonical


def load_update_metadata(path: Path, *, expected: dict[str, object] | None = None) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtastError(f"invalid update metadata: {path}") from exc
    return validate_update_metadata(data, expected=expected)


def update_metadata_from_manifest(manifest_path: Path) -> dict[str, object]:
    manifest = _load_manifest(manifest_path)
    version, version_code, _ = _manifest_identity(manifest)
    if is_prerelease(version):
        raise OtastError("prerelease manifest cannot update the stable Magisk channel")
    expected_zip = expected_asset_name(version)
    if manifest.get("zip_filename") != expected_zip:
        raise OtastError("release manifest ZIP filename mismatch")
    if manifest.get("checksum_filename") != f"{expected_zip}.sha256":
        raise OtastError("release manifest checksum filename mismatch")
    return expected_update_metadata(version, version_code)


def write_update_metadata(manifest_path: Path, output_path: Path) -> dict[str, object]:
    data = update_metadata_from_manifest(manifest_path)
    atomic_write(output_path, stable_json(data).encode("utf-8"))
    return data
