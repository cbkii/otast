from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath

from .util import OtastError, atomic_write, sha256_file

FIXED_TIME = (2020, 1, 1, 0, 0, 0)
EXCLUDED_PARTS = {".git", "dist", "reports", "__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
HOST_ENTRYPOINT_PREFIX = "otast/scripts/"
MODULE_ENTRYPOINTS = {
    "otast/module/action.sh",
    "otast/module/customize.sh",
    "otast/module/post-fs-data.sh",
    "otast/module/service.sh",
    "otast/module/uninstall.sh",
    "otast/module/runtime/entry.sh",
}
REQUIRED = {
    "otast/README.md",
    "otast/LICENSE",
    "otast/module/module.prop",
    "otast/scripts/test.sh",
    "otast/tools/otastctl/__main__.py",
}


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    import os
    found_paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_PARTS]
        rel_dir = Path(dirpath).relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel_dir.parts):
            continue
        dpath = Path(dirpath)
        for d in dirnames:
            path = dpath / d
            if path.is_symlink():
                found_paths.append(path)
        for f in filenames:
            if f in EXCLUDED_PARTS or f.endswith(tuple(EXCLUDED_SUFFIXES)):
                continue
            path = dpath / f
            found_paths.append(path)
    for path in sorted(found_paths):
        rel = path.relative_to(root)
        if path.is_symlink():
            raise OtastError(f"public source tree contains a symlink: {rel}")
        if not path.is_file():
            continue
        files.append(path)
    return files


def build_source_zip(root: Path, output: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise OtastError(f"repository root is missing or unsafe: {root}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in _source_files(root):
            rel = path.relative_to(root).as_posix()
            name = f"otast/{rel}"
            mode = 0o755 if name.startswith(HOST_ENTRYPOINT_PREFIX) or name in MODULE_ENTRYPOINTS else 0o644
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(output)
    validate_source_zip(output)
    atomic_write(output.parent / f"{output.name}.sha256", f"{sha256_file(output)}  {output.name}\n".encode())
    return output


def validate_source_zip(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"source ZIP is missing or unsafe: {path}")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise OtastError("source ZIP contains duplicate paths")
        missing = REQUIRED - set(names)
        if missing:
            raise OtastError("source ZIP is missing: " + ", ".join(sorted(missing)))
        for info in infos:
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts or "\\" in info.filename:
                raise OtastError(f"unsafe source ZIP path: {info.filename}")
            if not pure.parts or pure.parts[0] != "otast":
                raise OtastError(f"source ZIP path is outside otast/: {info.filename}")
            if any(part in EXCLUDED_PARTS for part in pure.parts):
                raise OtastError(f"excluded path leaked into source ZIP: {info.filename}")
            raw_mode = (info.external_attr >> 16) & 0o177777
            kind = stat.S_IFMT(raw_mode)
            if kind not in (0, stat.S_IFREG):
                raise OtastError(f"source ZIP contains a non-regular member: {info.filename}")
            mode = raw_mode & 0o777
            expected_mode = 0o755 if info.filename.startswith(HOST_ENTRYPOINT_PREFIX) or info.filename in MODULE_ENTRYPOINTS else 0o644
            if mode != expected_mode:
                raise OtastError(
                    f"source ZIP mode is not canonical: {info.filename} {mode:04o} expected {expected_mode:04o}"
                )
            if info.file_size > 8 * 1024 * 1024:
                raise OtastError(f"oversized source ZIP member: {info.filename}")
        if archive.testzip() is not None:
            raise OtastError("source ZIP is corrupt")
