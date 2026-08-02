from __future__ import annotations

import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

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
    if not values["versionCode"].isdigit() or int(values["versionCode"]) <= 0:
        raise OtastError("versionCode must be positive")
    return values


def build_module(repo_root: Path, output_dir: Path, commit_sha: str = "unknown") -> Path:
    module = repo_root / "module"
    metadata = module_metadata(module / "module.prop")
    if commit_sha != "unknown" and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit_sha):
        raise OtastError("commit SHA must be unknown or lowercase 40/64 hex")
    output_dir.mkdir(parents=True, exist_ok=True)
    version = metadata["version"].removeprefix("v")
    output = output_dir / f"otast-v{version}.zip"
    temp = output.with_suffix(".zip.tmp")
    temp.unlink(missing_ok=True)
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
    release = (
        "schema_version=1\n"
        f"version={metadata['version']}\n"
        f"version_code={metadata['versionCode']}\n"
        f"commit_sha={commit_sha}\n"
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
    atomic_write(output_dir / f"{output.name}.sha256", f"{sha256_file(output)}  {output.name}\n".encode())
    return output


def validate_module_zip(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"module ZIP is missing or unsafe: {path}")
    with zipfile.ZipFile(path) as archive:
        names = [info.filename for info in archive.infolist()]
        if len(names) != len(set(names)):
            raise OtastError("module ZIP contains duplicate paths")
        missing = REQUIRED - set(names)
        if missing:
            raise OtastError("module ZIP is missing: " + ", ".join(sorted(missing)))
        for info in archive.infolist():
            posix = PurePosixPath(info.filename)
            if posix.is_absolute() or ".." in posix.parts or "\\" in info.filename:
                raise OtastError(f"unsafe ZIP path: {info.filename}")
            mode = (info.external_attr >> 16) & 0o777
            if info.filename in ENTRYPOINTS and mode != 0o755:
                raise OtastError(f"wrong executable mode for {info.filename}: {mode:04o}")
            if info.file_size > 8 * 1024 * 1024:
                raise OtastError(f"oversized ZIP member: {info.filename}")
        if archive.testzip() is not None:
            raise OtastError("module ZIP is corrupt")
        metadata = archive.read("module.prop").decode("utf-8")
        if "id=otast\n" not in metadata:
            raise OtastError("module ZIP has the wrong identity")
