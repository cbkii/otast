from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path, PurePosixPath

from .util import OtastError, atomic_write, ensure_within, stable_json

SENSITIVE_PARTS = {
    "keybox.xml",
    "keybox",
    "magisk.db",
    "keystore.db",
    "credentials.json",
    "service-account.json",
}
SENSITIVE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key", ".p12", ".pfx"}
PRIVATE_MARKER = b"-----BEGIN " + b"PRIVATE KEY-----"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _safe_symlink_target(source: Path, destination: Path, path: Path, rel: Path) -> str:
    raw = os.readlink(path)
    if "\x00" in raw:
        raise OtastError(f"fixture symlink target contains NUL: {rel}")
    if raw.startswith("/data/adb/"):
        mapped = destination / "data/adb" / raw.removeprefix("/data/adb/")
        return os.path.relpath(mapped, start=(destination / rel).parent)
    if raw.startswith("/"):
        raise OtastError(f"fixture symlink points outside fake /data/adb: {rel} -> {raw}")
    pure = PurePosixPath(raw)
    lexical = PurePosixPath(*rel.parent.parts, *pure.parts)
    stack: list[str] = []
    for part in lexical.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise OtastError(f"fixture symlink escapes capture root: {rel} -> {raw}")
            stack.pop()
        else:
            stack.append(part)
    return raw


def sanitize_fixture(source: Path, destination: Path) -> dict[str, object]:
    if source.is_symlink() or not source.is_dir():
        raise OtastError(f"fixture source is missing or unsafe: {source}")
    if destination.exists() or destination.is_symlink():
        raise OtastError(f"fixture destination already exists: {destination}")
    destination.mkdir(parents=True, mode=0o700)
    inventory: list[dict[str, object]] = []
    excluded: list[str] = []
    total = 0
    try:
        for path in sorted(source.rglob("*")):
            rel = path.relative_to(source)
            target = ensure_within(destination / rel, destination)
            lower_parts = {part.lower() for part in rel.parts}
            sensitive_name = (
                bool(lower_parts & SENSITIVE_PARTS)
                or path.suffix.lower() in SENSITIVE_SUFFIXES
                or "keybox" in path.name.lower()
            )
            if sensitive_name:
                excluded.append(rel.as_posix())
                continue
            if path.is_symlink():
                rewritten = _safe_symlink_target(source, destination, path, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(rewritten, target)
                inventory.append({"path": rel.as_posix(), "type": "symlink", "target": rewritten})
                continue
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not path.is_file():
                excluded.append(rel.as_posix())
                continue
            size = path.stat().st_size
            total += size
            if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise OtastError(f"fixture exceeds bounded file size: {rel}")
            data = path.read_bytes()
            if PRIVATE_MARKER in data:
                excluded.append(rel.as_posix())
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            mode = path.stat().st_mode & 0o777
            target.chmod(mode)
            inventory.append(
                {
                    "path": rel.as_posix(),
                    "type": "file",
                    "mode": f"{mode:04o}",
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        manifest = {
            "schema_version": 2,
            "inventory": inventory,
            "excluded": sorted(excluded),
        }
        atomic_write(destination / "fixture-manifest.json", stable_json(manifest).encode(), 0o600)
        return manifest
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def reset_fixture(source: Path, destination: Path, allowed_root: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise OtastError(f"sanitized fixture is missing or unsafe: {source}")
    allowed_root.mkdir(parents=True, exist_ok=True)
    if allowed_root.is_symlink():
        raise OtastError(f"allowed fixture root is a symlink: {allowed_root}")
    ensure_within(destination, allowed_root)
    if destination.is_symlink():
        destination.unlink()
    elif destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)
