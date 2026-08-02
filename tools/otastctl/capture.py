from __future__ import annotations

import os
import stat
import tarfile
import shutil
from pathlib import Path, PurePosixPath

from .util import OtastError, ensure_within

MAX_MEMBERS = 4096
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def safe_extract_capture(archive: Path, destination: Path) -> None:
    if archive.is_symlink() or not archive.is_file():
        raise OtastError(f"capture archive is missing or unsafe: {archive}")
    if destination.exists() or destination.is_symlink():
        raise OtastError(f"capture destination already exists: {destination}")
    destination.mkdir(parents=True, mode=0o700)
    total = 0
    try:
        with tarfile.open(archive, "r:") as handle:
            members = handle.getmembers()
            if len(members) > MAX_MEMBERS:
                raise OtastError("capture archive contains too many members")
            names: set[str] = set()
            for member in members:
                pure = PurePosixPath(member.name)
                if not member.name or pure.is_absolute() or ".." in pure.parts or "\\" in member.name:
                    raise OtastError(f"unsafe capture member path: {member.name!r}")
                canonical = pure.as_posix()
                if canonical != member.name.rstrip("/") or canonical in names:
                    raise OtastError(f"duplicate or non-canonical capture member: {member.name!r}")
                names.add(canonical)
                if not (member.isdir() or member.isfile() or member.issym()):
                    raise OtastError(f"unsupported capture member type: {member.name}")
                if member.mode & 0o7000:
                    raise OtastError(f"capture member has special permission bits: {member.name}")
                if member.isfile():
                    total += member.size
                    if member.size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                        raise OtastError("capture archive exceeds bounded extraction size")

            for member in members:
                pure = PurePosixPath(member.name)
                target = ensure_within(destination.joinpath(*pure.parts), destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                if any(parent.is_symlink() for parent in target.parents if parent != destination.parent):
                    raise OtastError(f"capture extraction parent is a symlink: {member.name}")
                if member.isdir():
                    target.mkdir(exist_ok=True)
                    target.chmod(member.mode & 0o777 or 0o755)
                    continue
                if member.issym():
                    if "\x00" in member.linkname:
                        raise OtastError(f"capture symlink contains NUL: {member.name}")
                    os.symlink(member.linkname, target)
                    continue
                extracted = handle.extractfile(member)
                if extracted is None:
                    raise OtastError(f"cannot read capture member: {member.name}")
                with target.open("wb") as output:
                    remaining = member.size
                    while remaining:
                        chunk = extracted.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise OtastError(f"truncated capture member: {member.name}")
                        output.write(chunk)
                        remaining -= len(chunk)
                target.chmod(member.mode & 0o777 or 0o644)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
