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


def _install_candidate(module_zip: Path, adb_root: Path) -> Path:
    destination = adb_root / "modules/otast"
    if destination.is_symlink():
        raise OtastError("candidate module destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    module_dir = _extract_exact_zip(module_zip, destination)
    return module_dir / "runtime/entry.sh"


def qualify_upgrade_path(repo_root: Path, output_dir: Path) -> dict[str, object]:
    """Exercise managed-state upgrade/reinstall boundaries against a fake Magisk root.

    The predecessor uses the candidate runtime with an older module identity. This
    intentionally isolates the upgrade contract itself: records/backups, active and
    staged targets, no-op adoption, reinstall, and fail-closed contradictory state.
    Runtime-byte changes are qualified separately by the canonical runtime digest.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    module_zip = build_module(repo_root, output_dir)

    with tempfile.TemporaryDirectory(prefix="otast-upgrade-") as raw:
        base = Path(raw)
        adb_root, predecessor_entry, _ = _new_root(base / "managed", module_zip)

        module_prop = adb_root / "modules/otast/module.prop"
        text = module_prop.read_text(encoding="utf-8")
        text = text.replace("version=v1.0.3", "version=v1.0.2")
        text = text.replace("versionCode=10003", "versionCode=10002")
        module_prop.write_text(text, encoding="utf-8")
        module_prop.chmod(0o644)

        _run(predecessor_entry, adb_root, "preflight")
        _run(predecessor_entry, adb_root, "apply")
        _simulate_managed_boot(adb_root)
        _run(predecessor_entry, adb_root, "verify")

        staged_record = adb_root / "otast/records/pif-autopif-staged.state"
        if not staged_record.is_file():
            raise OtastError("predecessor did not create managed state for modules_update")
        before_upgrade = _state_snapshot(adb_root)

        candidate_entry = _install_candidate(module_zip, adb_root)
        _run(candidate_entry, adb_root, "preflight")
        transactions_before = len(list((adb_root / "otast/transactions").glob("*")))
        upgrade_apply = _run(candidate_entry, adb_root, "apply")
        transactions_after = len(list((adb_root / "otast/transactions").glob("*")))
        if transactions_after != transactions_before:
            raise OtastError("compatible predecessor-to-candidate upgrade created a new transaction")
        if _state_snapshot(adb_root) != before_upgrade:
            raise OtastError("candidate upgrade rewrote predecessor state or original backups")

        reinstalled_entry = _install_candidate(module_zip, adb_root)
        _run(reinstalled_entry, adb_root, "preflight")
        reinstall_apply = _run(reinstalled_entry, adb_root, "apply")
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
                "existing_managed_state_adopted": True,
                "modules_update_state_preserved": True,
                "original_backups_preserved": True,
                "candidate_reinstall_noop": reinstall_apply.returncode == 0,
                "active_staged_disagreement_rejected": disagreement.returncode == 1,
                "contradictory_state_rejected": corrupt.returncode == 1,
                "no_upgrade_transaction_when_runtime_identical": transactions_after == transactions_before,
            },
        }
