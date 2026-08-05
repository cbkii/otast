#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path


class GuardError(RuntimeError):
    pass


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _assert_no_symlink_components(path: Path, start: Path, label: str) -> None:
    path_abs = _absolute_without_resolving(path)
    start_abs = _absolute_without_resolving(start)
    try:
        relative = path_abs.relative_to(start_abs)
    except ValueError as exc:
        raise GuardError(f"{label} is outside {start_abs}: {path_abs}") from exc

    current = start_abs
    components = (Path(), *[Path(part) for part in relative.parts])
    for component in components:
        if component != Path():
            current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            # Non-existing descendants are allowed for cache destinations. Existing
            # ancestors have already been checked.
            continue
        if stat.S_ISLNK(info.st_mode):
            raise GuardError(f"{label} contains a symbolic-link component: {current}")


def require_non_root(operation: str) -> int:
    uid = os.geteuid()
    if uid == 0:
        raise GuardError(
            f"{operation} must run as the normal Termux user, not root; "
            "only the dedicated capture helper may invoke a narrow read-only su command"
        )
    return uid


def upstream_cache_root() -> Path:
    return (Path.home() / ".cache/otast/upstream-candidates").resolve(strict=False)


def assert_upstream_cache_path(path: Path, label: str) -> Path:
    uid = require_non_root(label)
    allowed_lexical = _absolute_without_resolving(Path.home() / ".cache/otast/upstream-candidates")
    candidate_lexical = _absolute_without_resolving(path)
    try:
        candidate_lexical.relative_to(allowed_lexical)
    except ValueError as exc:
        raise GuardError(f"{label} must remain below {allowed_lexical}: {candidate_lexical}") from exc

    _assert_no_symlink_components(candidate_lexical, allowed_lexical, label)
    resolved_allowed = allowed_lexical.resolve(strict=False)
    resolved_candidate = candidate_lexical.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_allowed)
    except ValueError as exc:
        raise GuardError(f"{label} resolves outside {resolved_allowed}: {resolved_candidate}") from exc

    # Existing cache roots must belong to the invoking Termux UID.
    for existing in (allowed_lexical, candidate_lexical):
        if existing.exists():
            info = existing.stat()
            if info.st_uid != uid:
                raise GuardError(
                    f"{label} is not owned by the invoking Termux UID {uid}: "
                    f"{existing} (owner {info.st_uid})"
                )
    return resolved_candidate


def assert_fake_root(path: Path, operation: str = "fake-root operation") -> Path:
    uid = require_non_root(operation)
    allowed_lexical = _absolute_without_resolving(Path.home() / ".cache/otast/fake-roots")
    root_lexical = _absolute_without_resolving(path)
    try:
        relative = root_lexical.relative_to(allowed_lexical)
    except ValueError as exc:
        raise GuardError(f"fake root is outside {allowed_lexical}: {root_lexical}") from exc
    if not relative.parts:
        raise GuardError(f"refusing to use the fake-root parent itself: {root_lexical}")

    adb_lexical = root_lexical / "data/adb"
    marker_lexical = adb_lexical / ".otast-fake-root"
    _assert_no_symlink_components(adb_lexical, allowed_lexical, "fake root")

    if not root_lexical.is_dir():
        raise GuardError(f"fake root does not exist or is not a directory: {root_lexical}")
    if not adb_lexical.is_dir():
        raise GuardError(f"fake data/adb does not exist or is not a directory: {adb_lexical}")

    marker_info = marker_lexical.lstat() if marker_lexical.exists() else None
    if marker_info is None or not stat.S_ISREG(marker_info.st_mode):
        raise GuardError(f"fake-root marker is missing or not a regular file: {marker_lexical}")

    for owned_path in (root_lexical, adb_lexical, marker_lexical):
        owner = owned_path.stat().st_uid
        if owner != uid:
            raise GuardError(
                f"fake-root identity check failed: {owned_path} is owned by {owner}, "
                f"not the invoking Termux UID {uid}"
            )

    resolved_allowed = allowed_lexical.resolve(strict=False)
    resolved_root = root_lexical.resolve(strict=True)
    resolved_adb = adb_lexical.resolve(strict=True)
    try:
        resolved_root.relative_to(resolved_allowed)
        resolved_adb.relative_to(resolved_root)
    except ValueError as exc:
        raise GuardError("fake-root resolution escaped the allowed disposable-root boundary") from exc

    live_adb = Path("/data/adb")
    if resolved_adb == live_adb.resolve(strict=False):
        raise GuardError("fake data/adb resolves to live /data/adb")
    try:
        if live_adb.exists() and os.path.samefile(resolved_adb, live_adb):
            raise GuardError("fake data/adb is the same filesystem object as live /data/adb")
    except PermissionError:
        # Path equality above remains sufficient when the normal Termux UID cannot stat live /data/adb.
        pass

    return resolved_root


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="OTAST local non-root and path-containment guard")
    sub = root.add_subparsers(dest="command", required=True)

    non_root = sub.add_parser("non-root", help="require execution as the normal Termux user")
    non_root.add_argument("operation", nargs="?", default="OTAST operation")

    fake = sub.add_parser("fake-root", help="validate a marked disposable fake root")
    fake.add_argument("path")
    fake.add_argument("--operation", default="fake-root operation")

    upstream = sub.add_parser("upstream-root", help="validate an upstream evidence/cache path")
    upstream.add_argument("path")
    upstream.add_argument("--label", default="upstream evidence root")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "non-root":
            uid = require_non_root(args.operation)
            value = {"result": "PASS", "operation": args.operation, "uid": uid}
        elif args.command == "fake-root":
            path = assert_fake_root(Path(args.path), args.operation)
            value = {"result": "PASS", "fake_root": str(path), "uid": os.geteuid()}
        elif args.command == "upstream-root":
            path = assert_upstream_cache_path(Path(args.path), args.label)
            value = {"result": "PASS", "path": str(path), "uid": os.geteuid()}
        else:
            raise GuardError(f"unknown guard command: {args.command}")
        print(json.dumps(value, sort_keys=True))
        return 0
    except (GuardError, OSError, ValueError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
