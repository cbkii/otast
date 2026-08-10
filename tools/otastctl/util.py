from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Iterable


class OtastError(RuntimeError):
    """Controlled OTAST host-tool failure."""


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def stable_json(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(mode)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def ensure_within(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise OtastError(f"path escapes root: {path}") from exc
    return resolved


def copy_tree_no_follow(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise OtastError(f"unsafe source tree: {source}")
    if destination.exists():
        raise OtastError(f"destination already exists: {destination}")
    shutil.copytree(source, destination, symlinks=True)


def iter_regular_files(root: Path) -> Iterable[Path]:
    import os
    found_paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        dpath = Path(dirpath)
        for d in dirnames:
            path = dpath / d
            if path.is_symlink():
                found_paths.append(path)
        for f in filenames:
            path = dpath / f
            found_paths.append(path)
    for path in sorted(found_paths):
        if path.is_symlink() or not path.is_file():
            continue
        yield path


def mode_for_zip(path: Path) -> int:
    mode = stat.S_IMODE(path.stat().st_mode)
    return 0o755 if mode & 0o111 else 0o644
