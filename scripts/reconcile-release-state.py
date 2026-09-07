#!/usr/bin/env python3
"""Reconcile private Termux release state with the hosted OTAST candidate.

This is host-only state management. It never reads or mutates /data/adb.

The physical lifecycle may resume only when its private state is bound to the
same hosted draft source commit. If a previous candidate is orphaned or a new
unproven draft replaced it, preserve the entire old state directory in private
history and restart host state from a clean START boundary. Exact ZIP/runtime
checks remain the lifecycle's responsibility once the source binding matches.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_STOP = 20

PHASES = {
    "START",
    "BASELINE_REBOOT",
    "INSTALL_REBOOT",
    "APPLY_REBOOT",
    "EVIDENCE_REQUIRED",
    "RESTORE_REBOOT",
    "REAPPLY_REBOOT",
    "ABORT_RESTORE_REBOOT",
    "PROOF_READY",
    "PUBLISHING",
    "COMPLETE",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SIMPLE_VALUE = re.compile(r"^[A-Za-z0-9._+-]+$")
SAFE_VERSION = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")


class ReconcileError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalState:
    exists: bool
    phase: str = "START"
    source_sha: str = ""
    module_sha256: str = ""
    runtime_digest: str = ""
    has_payload: bool = False
    has_auxiliary_payload: bool = False


def _require_private_dir(path: Path, *, allow_missing: bool = False) -> None:
    if path.is_symlink():
        raise ReconcileError(f"private state path is unsafe: {path}")
    if not path.exists():
        if allow_missing:
            return
        raise ReconcileError(f"private state path is missing: {path}")
    if not path.is_dir():
        raise ReconcileError(f"private state path is unsafe: {path}")


def _decode_simple_value(raw: str, *, label: str, pattern: re.Pattern[str] | None = None) -> str:
    value = raw.strip()
    if value in {"", "''", '""'}:
        return ""
    # The lifecycle writes these fields with printf %q. Valid candidate-binding
    # fields never require shell escaping, so accept only canonical simple tokens.
    if not SIMPLE_VALUE.fullmatch(value):
        raise ReconcileError(f"private state {label} is not in canonical simple form")
    if pattern is not None and not pattern.fullmatch(value):
        raise ReconcileError(f"private state {label} is malformed: {value!r}")
    return value


def _scan_state_payload(state_dir: Path) -> tuple[bool, bool]:
    """Return (has_any_file, has_file_other_than_state_env), validating symlinks."""
    if state_dir.is_symlink():
        raise ReconcileError(f"private state path is unsafe: {state_dir}")
    if not state_dir.exists():
        return False, False
    has_payload = False
    has_auxiliary = False
    for root, dirs, files in os.walk(state_dir, followlinks=False):
        root_path = Path(root)
        for name in dirs:
            candidate = root_path / name
            if candidate.is_symlink():
                raise ReconcileError(f"private state contains a directory symlink: {candidate}")
        for name in files:
            candidate = root_path / name
            if candidate.is_symlink():
                raise ReconcileError(f"private state contains a file symlink: {candidate}")
            if not candidate.is_file():
                raise ReconcileError(f"private state contains a non-regular file: {candidate}")
            has_payload = True
            if candidate != state_dir / "state.env":
                has_auxiliary = True
    return has_payload, has_auxiliary


def load_local_state(state_dir: Path) -> LocalState:
    if state_dir.is_symlink():
        raise ReconcileError(f"private state path is unsafe: {state_dir}")
    if not state_dir.exists():
        return LocalState(False)
    _require_private_dir(state_dir)
    has_payload, has_auxiliary = _scan_state_payload(state_dir)
    state_file = state_dir / "state.env"
    if not state_file.exists():
        return LocalState(True, has_payload=has_payload, has_auxiliary_payload=has_auxiliary)
    if state_file.is_symlink() or not state_file.is_file():
        raise ReconcileError(f"private release state file is unsafe: {state_file}")
    if state_file.stat().st_size > 64 * 1024:
        raise ReconcileError("private release state file is unexpectedly large")

    wanted: dict[str, str] = {}
    try:
        lines = state_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ReconcileError(f"cannot read private release state: {exc}") from exc
    for line in lines:
        if not line or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key in {"PHASE", "SOURCE_SHA", "MODULE_SHA256", "RUNTIME_DIGEST"}:
            if key in wanted:
                raise ReconcileError(f"duplicate private release state key: {key}")
            wanted[key] = raw

    phase = _decode_simple_value(wanted.get("PHASE", "START"), label="PHASE") or "START"
    if phase not in PHASES:
        raise ReconcileError(f"private release PHASE is unknown: {phase!r}")
    source = _decode_simple_value(wanted.get("SOURCE_SHA", ""), label="SOURCE_SHA", pattern=HEX40)
    module_sha = _decode_simple_value(wanted.get("MODULE_SHA256", ""), label="MODULE_SHA256", pattern=HEX64)
    runtime = _decode_simple_value(wanted.get("RUNTIME_DIGEST", ""), label="RUNTIME_DIGEST", pattern=HEX64)
    return LocalState(True, phase, source, module_sha, runtime, has_payload, has_auxiliary)


def _release_asset_has_proof(release: dict[str, Any], proof_name: str) -> bool:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReconcileError("GitHub release asset inventory is malformed")
    return any(isinstance(item, dict) and item.get("name") == proof_name for item in assets)


def load_release(path: Path | None, *, release_absent: bool, proof_name: str) -> dict[str, Any] | None:
    if release_absent:
        if path is not None:
            raise ReconcileError("release JSON and --release-absent are mutually exclusive")
        return None
    if path is None:
        raise ReconcileError("release JSON is required unless --release-absent is used")
    if path.is_symlink() or not path.is_file():
        raise ReconcileError(f"release-state JSON is missing or unsafe: {path}")
    if path.stat().st_size > 1024 * 1024:
        raise ReconcileError("release-state JSON is unexpectedly large")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconcileError(f"cannot parse release-state JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ReconcileError("release-state JSON must be an object")
    if not isinstance(value.get("isDraft"), bool):
        raise ReconcileError("release-state JSON is missing boolean isDraft")
    target = value.get("targetCommitish")
    if not isinstance(target, str) or not HEX40.fullmatch(target):
        raise ReconcileError(f"hosted release targetCommitish is not an exact commit: {target!r}")
    _release_asset_has_proof(value, proof_name)
    return value


def reconciliation_reason(local: LocalState, release: dict[str, Any] | None, proof_name: str) -> str | None:
    if not local.exists or not local.has_payload:
        return None

    if release is None:
        if (
            local.phase != "START"
            or local.source_sha
            or local.module_sha256
            or local.runtime_digest
            or local.has_auxiliary_payload
        ):
            return "local qualification state is bound to a candidate that no longer has a hosted release"
        return None

    if _release_asset_has_proof(release, proof_name):
        # The wrapper must not discard local evidence once GitHub has accepted a
        # physical proof. Publication/recovery owns this state from here.
        return None

    target = str(release["targetCommitish"])
    if local.source_sha:
        if local.source_sha != target:
            return f"local qualification source {local.source_sha} differs from hosted draft source {target}"
        return None

    if local.phase != "START" or local.module_sha256 or local.runtime_digest or local.has_auxiliary_payload:
        return "local qualification state/evidence exists without an exact hosted-draft source binding"
    return None


def _archive_token(local: LocalState) -> str:
    for value in (local.source_sha, local.module_sha256, local.runtime_digest):
        if value:
            return value[:12]
    return "orphan"


def archive_state(state_dir: Path, *, state_base: Path, version: str, local: LocalState) -> Path:
    _require_private_dir(state_base)
    _require_private_dir(state_dir)
    history = state_base / ".history"
    if history.exists() or history.is_symlink():
        _require_private_dir(history)
    else:
        history.mkdir(mode=0o700)
    try:
        history.chmod(0o700)
    except OSError as exc:
        raise ReconcileError(f"cannot secure private history directory: {exc}") from exc

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{version}-{stamp}-{_archive_token(local)}"
    destination = history / stem
    suffix = 0
    while destination.exists() or destination.is_symlink():
        suffix += 1
        if suffix > 99:
            raise ReconcileError("cannot allocate a unique private history path")
        destination = history / f"{stem}-{suffix}"

    try:
        state_dir.rename(destination)
        state_dir.mkdir(mode=0o700)
        state_dir.chmod(0o700)
    except OSError as exc:
        # If rename succeeded but recreation failed, the archive remains intact.
        # Stop rather than run the lifecycle without a known current-state root.
        raise ReconcileError(f"cannot archive/recreate private release state: {exc}") from exc
    return destination


def reconcile(
    *,
    state_dir: Path,
    state_base: Path,
    version: str,
    release: dict[str, Any] | None,
    proof_name: str,
) -> dict[str, Any]:
    if not SAFE_VERSION.fullmatch(version):
        raise ReconcileError(f"unsafe release version: {version!r}")
    _require_private_dir(state_base)
    local = load_local_state(state_dir)
    reason = reconciliation_reason(local, release, proof_name)
    target = None if release is None else release.get("targetCommitish")
    if reason is None:
        return {
            "schema_version": 1,
            "action": "PRESERVE" if local.exists else "NONE",
            "reason": "state is empty/default or matches the hosted candidate",
            "local_phase": local.phase,
            "local_source_commit": local.source_sha or None,
            "hosted_source_commit": target,
            "archive": None,
        }
    archive = archive_state(state_dir, state_base=state_base, version=version, local=local)
    return {
        "schema_version": 1,
        "action": "ARCHIVED",
        "reason": reason,
        "local_phase": local.phase,
        "local_source_commit": local.source_sha or None,
        "hosted_source_commit": target,
        "archive": str(archive),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile private OTAST release state with a hosted candidate.")
    parser.add_argument("--state-base", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--proof-name", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--release-json", type=Path)
    group.add_argument("--release-absent", action="store_true")
    args = parser.parse_args()

    try:
        state_base = args.state_base.expanduser().absolute()
        state_dir = args.state_dir.expanduser().absolute()
        if state_dir.parent != state_base:
            raise ReconcileError("state directory is not an immediate child of the private state base")
        release = load_release(args.release_json, release_absent=args.release_absent, proof_name=args.proof_name)
        value = reconcile(
            state_dir=state_dir,
            state_base=state_base,
            version=args.version,
            release=release,
            proof_name=args.proof_name,
        )
        print(json.dumps(value, indent=2, sort_keys=True))
        return EXIT_OK
    except ReconcileError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return EXIT_STOP


if __name__ == "__main__":
    raise SystemExit(main())
