from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable

from .util import OtastError

RUNTIME_DIGEST_ALGORITHM = "otast-runtime-v1"
PROVENANCE_ONLY_ZIP_PATHS = {"release.properties"}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _frame(digest: "hashlib._Hash", label: bytes, value: bytes) -> None:
    digest.update(label)
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def digest_entries(entries: Iterable[tuple[str, bytes, int]]) -> str:
    """Hash the exact install/runtime payload independently of release provenance.

    The contract covers each shipped module-tree member's relative path, normalized
    file mode and bytes. ``release.properties`` is generated release provenance,
    is not part of ``module/`` and is explicitly outside the runtime digest. Release
    validation separately proves that it cannot add another runtime/install input.
    """
    normalized: list[tuple[str, bytes, int]] = []
    seen: set[str] = set()
    for name, data, mode in entries:
        if name in PROVENANCE_ONLY_ZIP_PATHS:
            continue
        posix = PurePosixPath(name)
        if not name or posix.is_absolute() or ".." in posix.parts or "\\" in name:
            raise OtastError(f"unsafe runtime-digest path: {name}")
        if name in seen:
            raise OtastError(f"duplicate runtime-digest path: {name}")
        seen.add(name)
        if not isinstance(data, bytes):
            raise OtastError(f"runtime-digest member is not bytes: {name}")
        normalized.append((name, data, stat.S_IMODE(mode)))

    if not normalized:
        raise OtastError("runtime payload is empty")

    digest = hashlib.sha256()
    _frame(digest, b"algorithm\0", RUNTIME_DIGEST_ALGORITHM.encode("ascii"))
    for name, data, mode in sorted(normalized, key=lambda item: item[0]):
        _frame(digest, b"path\0", name.encode("utf-8"))
        _frame(digest, b"mode\0", f"{mode:04o}".encode("ascii"))
        _frame(digest, b"bytes\0", data)
    return digest.hexdigest()


def runtime_digest_from_zip(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"module ZIP is missing or unsafe: {path}")
    entries: list[tuple[str, bytes, int]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            seen: set[str] = set()
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.filename in seen:
                    raise OtastError(f"module ZIP contains duplicate path: {info.filename}")
                seen.add(info.filename)
                mode = (info.external_attr >> 16) & 0o7777
                entries.append((info.filename, archive.read(info.filename), mode))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise OtastError(f"cannot compute runtime digest from module ZIP: {path}") from exc
    return digest_entries(entries)


def validate_runtime_digest(value: object) -> str:
    if not isinstance(value, str) or HEX64_RE.fullmatch(value) is None:
        raise OtastError("runtime digest must be lowercase SHA-256")
    return value
