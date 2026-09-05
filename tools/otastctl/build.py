from __future__ import annotations

import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .qualification import registry_provenance
from .runtime_digest import RUNTIME_DIGEST_ALGORITHM, digest_entries, runtime_digest_from_zip
from .util import OtastError, atomic_write, iter_regular_files, mode_for_zip, sha256_file

FIXED_TIME = (2020, 1, 1, 0, 0, 0)
ENTRYPOINTS = {
    "action.sh",
    "customize.sh",
    "post-fs-data.sh",
    "service.sh",
    "uninstall.sh",
    "runtime/entry.sh",
}
RUNTIME_LIBRARIES = {
    "runtime/common.sh",
    "runtime/authority.sh",
    "runtime/transaction.sh",
    "runtime/profiles.sh",
    "runtime/report.sh",
}
REQUIRED = ENTRYPOINTS | RUNTIME_LIBRARIES | {"module.prop", "skip_mount", "otast.conf"}
RELEASE_PROPERTIES_KEYS = {
    "schema_version",
    "version",
    "version_code",
    "commit_sha",
    "runtime_digest_algorithm",
    "runtime_digest",
    "compatibility_registry_schema",
    "compatibility_registry_sha256",
    "qualification_registry_schema",
    "qualification_registry_sha256",
}
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^(?:unknown|[0-9a-f]{40}|[0-9a-f]{64})$")


def module_metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or "=" not in line:
            raise OtastError("module.prop contains a malformed line")
        key, value = line.split("=", 1)
        if key in values or not key or not value:
            raise OtastError("module.prop contains duplicate or empty metadata")
        values[key] = value
    for key in ("id", "name", "version", "versionCode", "author", "description", "updateJson"):
        if key not in values:
            raise OtastError(f"module.prop is missing: {key}")
    if values["id"] != "otast":
        raise OtastError("module ID must be otast")
    if VERSION_RE.fullmatch(values["version"]) is None:
        raise OtastError("module version must be a canonical vMAJOR.MINOR.PATCH value")
    if not values["versionCode"].isdigit() or int(values["versionCode"]) <= 0:
        raise OtastError("versionCode must be positive")
    return values


def runtime_payload_entries(module: Path) -> list[tuple[str, bytes, int]]:
    entries: list[tuple[str, bytes, int]] = []
    for path in iter_regular_files(module):
        rel = path.relative_to(module).as_posix()
        if rel == "AGENTS.md" or rel.startswith("var/"):
            continue
        mode = mode_for_zip(path)
        if rel in ENTRYPOINTS:
            mode = 0o755
        else:
            mode = 0o644
        entries.append((rel, path.read_bytes(), mode))
    return sorted(entries, key=lambda item: item[0])


def source_runtime_digest(repo_root: Path) -> str:
    return digest_entries(runtime_payload_entries(repo_root / "module"))


def _parse_release_properties(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or "=" not in line:
            raise OtastError("release.properties contains a malformed line")
        key, value = line.split("=", 1)
        if not key or not value or key in values:
            raise OtastError("release.properties contains duplicate or empty metadata")
        values[key] = value
    if set(values) != RELEASE_PROPERTIES_KEYS:
        raise OtastError("release.properties fields do not match schema 2")
    return values


def _validate_release_properties(release: dict[str, str], metadata: dict[str, str]) -> None:
    if release["schema_version"] != "2":
        raise OtastError("release.properties schema_version mismatch")
    if release["version"] != metadata["version"] or VERSION_RE.fullmatch(release["version"]) is None:
        raise OtastError("release.properties version does not match module.prop")
    if release["version_code"] != metadata["versionCode"] or not release["version_code"].isdigit() or int(release["version_code"]) <= 0:
        raise OtastError("release.properties version_code does not match module.prop")
    if COMMIT_RE.fullmatch(release["commit_sha"]) is None:
        raise OtastError("release.properties commit_sha is invalid")
    if release["runtime_digest_algorithm"] != RUNTIME_DIGEST_ALGORITHM:
        raise OtastError("release.properties runtime digest algorithm mismatch")
    if HEX64_RE.fullmatch(release["runtime_digest"]) is None:
        raise OtastError("release.properties runtime_digest is invalid")
    for key in ("compatibility_registry_schema", "qualification_registry_schema"):
        if not release[key].isdigit() or int(release[key]) <= 0:
            raise OtastError(f"release.properties {key} is invalid")
    for key in ("compatibility_registry_sha256", "qualification_registry_sha256"):
        if HEX64_RE.fullmatch(release[key]) is None:
            raise OtastError(f"release.properties {key} is invalid")


def build_module(repo_root: Path, output_dir: Path, commit_sha: str = "unknown") -> Path:
    module = repo_root / "module"
    metadata = module_metadata(module / "module.prop")
    if COMMIT_RE.fullmatch(commit_sha) is None:
        raise OtastError("commit SHA must be unknown or lowercase 40/64 hex")
    output_dir.mkdir(parents=True, exist_ok=True)
    version = metadata["version"].removeprefix("v")
    output = output_dir / f"otast-v{version}.zip"
    temp = output.with_suffix(".zip.tmp")
    temp.unlink(missing_ok=True)

    entries = runtime_payload_entries(module)
    runtime_digest = digest_entries(entries)
    provenance = registry_provenance(repo_root)
    release = (
        "schema_version=2\n"
        f"version={metadata['version']}\n"
        f"version_code={metadata['versionCode']}\n"
        f"commit_sha={commit_sha}\n"
        f"runtime_digest_algorithm={RUNTIME_DIGEST_ALGORITHM}\n"
        f"runtime_digest={runtime_digest}\n"
        f"compatibility_registry_schema={provenance['compatibility_registry_schema']}\n"
        f"compatibility_registry_sha256={provenance['compatibility_registry_sha256']}\n"
        f"qualification_registry_schema={provenance['qualification_registry_schema']}\n"
        f"qualification_registry_sha256={provenance['qualification_registry_sha256']}\n"
    ).encode()
    entries.append(("release.properties", release, 0o644))

    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data, mode in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temp.replace(output)
    validate_module_zip(output)
    if runtime_digest_from_zip(output) != runtime_digest:
        raise OtastError("built ZIP runtime digest differs from source runtime payload")
    atomic_write(output_dir / f"{output.name}.sha256", f"{sha256_file(output)}  {output.name}\n".encode())
    return output


def validate_module_zip(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"module ZIP is missing or unsafe: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            names = [info.filename for info in archive.infolist()]
            if len(names) != len(set(names)):
                raise OtastError("module ZIP contains duplicate paths")
            missing = REQUIRED - set(names)
            if missing:
                raise OtastError("module ZIP is missing: " + ", ".join(sorted(missing)))
            if "release.properties" not in names:
                raise OtastError("module ZIP is missing release.properties")
            for info in archive.infolist():
                posix = PurePosixPath(info.filename)
                if posix.is_absolute() or ".." in posix.parts or "\\" in info.filename or posix.as_posix() != info.filename:
                    raise OtastError(f"unsafe ZIP path: {info.filename}")
                mode = (info.external_attr >> 16) & 0o777
                if info.filename in ENTRYPOINTS and mode != 0o755:
                    raise OtastError(f"wrong executable mode for {info.filename}: {mode:04o}")
                if info.filename not in ENTRYPOINTS and mode != 0o644:
                    raise OtastError(f"wrong regular-file mode for {info.filename}: {mode:04o}")
                if info.file_size > 8 * 1024 * 1024:
                    raise OtastError(f"oversized ZIP member: {info.filename}")
            if archive.testzip() is not None:
                raise OtastError("module ZIP is corrupt")
            metadata = module_metadata_from_text(archive.read("module.prop").decode("utf-8"))
            release = _parse_release_properties(archive.read("release.properties").decode("utf-8"))
            _validate_release_properties(release, metadata)
    except OtastError:
        raise
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise OtastError(f"cannot validate module ZIP: {path}") from exc
    if runtime_digest_from_zip(path) != release["runtime_digest"]:
        raise OtastError("release.properties runtime digest does not match module ZIP payload")


def module_metadata_from_text(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or "=" not in line:
            raise OtastError("module.prop contains a malformed line")
        key, value = line.split("=", 1)
        if key in values or not key or not value:
            raise OtastError("module.prop contains duplicate or empty metadata")
        values[key] = value
    for key in ("id", "name", "version", "versionCode", "author", "description", "updateJson"):
        if key not in values:
            raise OtastError(f"module.prop is missing: {key}")
    if values["id"] != "otast":
        raise OtastError("module ID must be otast")
    if VERSION_RE.fullmatch(values["version"]) is None:
        raise OtastError("module version must be a canonical vMAJOR.MINOR.PATCH value")
    if not values["versionCode"].isdigit() or int(values["versionCode"]) <= 0:
        raise OtastError("versionCode must be positive")
    return values
