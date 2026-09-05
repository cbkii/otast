from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from .build import build_module
from .fake_root import _extract_exact_zip, _new_root, _run, _simulate_managed_boot
from .util import OtastError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_snapshot(adb_root: Path) -> dict[str, str]:
    records = adb_root / "otast/records"
    if not records.is_dir() or records.is_symlink():
        raise OtastError("upgrade qualification has no safe managed-state directory")
    snapshot: dict[str, str] = {}
    for state in sorted(records.glob("*.state")):
        if state.is_symlink() or not state.is_file():
            raise OtastError(f"unsafe managed-state record: {state}")
        snapshot[state.relative_to(adb_root).as_posix()] = _sha256(state)
        backup = ""
        for line in state.read_text(encoding="utf-8").splitlines():
            if line.startswith("backup="):
                backup = line.split("=", 1)[1]
                break
        if backup:
            backup_path = Path(backup)
            try:
                relative = backup_path.resolve(strict=True).relative_to(adb_root.resolve(strict=True))
            except (OSError, ValueError) as exc:
                raise OtastError(f"managed-state backup escapes fake ADB root: {backup}") from exc
            if backup_path.is_symlink() or not backup_path.is_file():
                raise OtastError(f"managed-state backup is missing or unsafe: {backup}")
            snapshot[f"backup:{relative.as_posix()}"] = _sha256(backup_path)
    if not snapshot:
        raise OtastError("upgrade qualification captured no managed state")
    return snapshot


def _transaction_count(adb_root: Path) -> int:
    root = adb_root / "otast/transactions"
    return len([path for path in root.glob("*") if path.is_dir() and not path.is_symlink()])


def _install_candidate(module_zip: Path, adb_root: Path) -> Path:
    destination = adb_root / "modules/otast"
    if destination.is_symlink():
        raise OtastError("candidate module destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    module_dir = _extract_exact_zip(module_zip, destination)
    return module_dir / "runtime/entry.sh"


def _stamp_synthetic_predecessor(module_prop: Path) -> None:
    lines: list[str] = []
    saw_version = False
    saw_code = False
    for line in module_prop.read_text(encoding="utf-8").splitlines():
        if line.startswith("version="):
            lines.append("version=v0.0.0-upgrade-fixture")
            saw_version = True
        elif line.startswith("versionCode="):
            raw = line.split("=", 1)[1]
            if not raw.isdigit() or int(raw) <= 1:
                raise OtastError("candidate versionCode cannot produce a predecessor fixture")
            lines.append(f"versionCode={int(raw) - 1}")
            saw_code = True
        else:
            lines.append(line)
    if not saw_version or not saw_code:
        raise OtastError("candidate module.prop lacks version identity")
    module_prop.write_text("\n".join(lines) + "\n", encoding="utf-8")
    module_prop.chmod(0o644)


def qualify_upgrade_path(repo_root: Path, output_dir: Path) -> dict[str, object]:
    """Exercise managed-state upgrade/reinstall boundaries against a fake Magisk root.

    The predecessor uses the candidate runtime with an older synthetic module
    identity. This isolates the upgrade contract itself: records/backups, active
    and staged targets, transactional self-file rehydration, no-op repeat Apply,
    reinstall, and fail-closed contradictory state. Runtime-byte changes are
    separately guarded by the canonical digest.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    module_zip = build_module(repo_root, output_dir)

    with tempfile.TemporaryDirectory(prefix="otast-upgrade-") as raw:
        base = Path(raw)
        adb_root, predecessor_entry, _ = _new_root(base / "managed", module_zip)
        _stamp_synthetic_predecessor(adb_root / "modules/otast/module.prop")

        _run(predecessor_entry, adb_root, "preflight")
        _run(predecessor_entry, adb_root, "apply")
        _simulate_managed_boot(adb_root)
        _run(predecessor_entry, adb_root, "verify")

        staged_record = adb_root / "otast/records/pif-autopif-staged.state"
        if not staged_record.is_file():
            raise OtastError("predecessor did not create managed state for modules_update")
        before_upgrade = _state_snapshot(adb_root)

        # Replacing a Magisk module removes the generated system.prop from the
        # old module directory while persistent OTAST records survive. Candidate
        # Apply must rehydrate that one self-owned file transactionally without
        # replacing original backups or weakening drift handling for other paths.
        candidate_entry = _install_candidate(module_zip, adb_root)
        _run(candidate_entry, adb_root, "preflight")
        transactions_before = _transaction_count(adb_root)
        upgrade_apply = _run(candidate_entry, adb_root, "apply")
        transactions_after = _transaction_count(adb_root)
        if transactions_after != transactions_before + 1:
            raise OtastError("candidate upgrade did not use exactly one rehydration transaction")
        if _state_snapshot(adb_root) != before_upgrade:
            raise OtastError("candidate upgrade rewrote predecessor state or original backups")

        # Once rehydrated, a second Apply must be a genuine no-op.
        before_noop = _transaction_count(adb_root)
        no_op_apply = _run(candidate_entry, adb_root, "apply")
        after_noop = _transaction_count(adb_root)
        if after_noop != before_noop:
            raise OtastError("second candidate Apply created a transaction despite no changes")

        # Reinstalling the same candidate repeats only the expected self-file
        # rehydration transaction and still preserves the first original backup.
        reinstalled_entry = _install_candidate(module_zip, adb_root)
        _run(reinstalled_entry, adb_root, "preflight")
        before_reinstall = _transaction_count(adb_root)
        reinstall_apply = _run(reinstalled_entry, adb_root, "apply")
        after_reinstall = _transaction_count(adb_root)
        if after_reinstall != before_reinstall + 1:
            raise OtastError("candidate reinstall did not use exactly one rehydration transaction")
        if _state_snapshot(adb_root) != before_upgrade:
            raise OtastError("candidate reinstall rewrote managed state or original backups")

        staged_path = adb_root / "modules_update/playintegrityfix/autopif.sh"
        staged_bytes = staged_path.read_bytes()
        staged_path.write_text("contradictory staged drift\n", encoding="utf-8")
        staged_path.chmod(0o755)
        before_reject = _state_snapshot(adb_root)
        disagreement = _run(reinstalled_entry, adb_root, "apply", expect=1)
        if _state_snapshot(adb_root) != before_reject:
            raise OtastError("active/staged disagreement changed managed state before failing")
        staged_path.write_bytes(staged_bytes)
        staged_path.chmod(0o755)

        state = adb_root / "otast/records/pif-autopif-active.state"
        original_state = state.read_bytes()
        state.write_bytes(original_state.replace(b"version=1\n", b"version=999\n", 1))
        corrupt = _run(reinstalled_entry, adb_root, "apply", expect=1)
        if state.read_bytes() == original_state:
            raise OtastError("corrupt-state scenario unexpectedly rewrote the invalid record")

        return {
            "schema_version": 1,
            "result": "PASS",
            "scenarios": {
                "synthetic_stable_to_candidate": upgrade_apply.returncode == 0,
                "self_managed_system_prop_rehydrated_transactionally": transactions_after == transactions_before + 1,
                "existing_managed_state_adopted": True,
                "modules_update_state_preserved": True,
                "original_backups_preserved": True,
                "second_apply_noop": no_op_apply.returncode == 0 and after_noop == before_noop,
                "candidate_reinstall_safe": reinstall_apply.returncode == 0 and after_reinstall == before_reinstall + 1,
                "active_staged_disagreement_rejected": disagreement.returncode == 1,
                "contradictory_state_rejected": corrupt.returncode == 1,
            },
        }
