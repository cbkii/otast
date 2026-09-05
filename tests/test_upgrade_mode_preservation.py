from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.build import build_module
from tools.otastctl.fake_root import _new_root, _run, _simulate_managed_boot
from tools.otastctl.upgrade_qualification import _install_candidate, _stamp_synthetic_predecessor

ROOT = Path(__file__).resolve().parents[1]


def state_mode_snapshot(adb_root: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for base in (adb_root / "otast/records", adb_root / "otast/backups"):
        if not base.exists():
            continue
        if base.is_symlink() or not base.is_dir():
            raise AssertionError(f"unsafe OTAST state directory: {base}")
        for path in sorted(base.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            result[path.relative_to(adb_root).as_posix()] = stat.S_IMODE(path.stat().st_mode)
    if not result:
        raise AssertionError("fixture produced no state/backup files")
    return result


class UpgradeModePreservationTests(unittest.TestCase):
    def test_upgrade_and_reinstall_preserve_state_and_backup_modes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-upgrade-mode-") as raw:
            base = Path(raw)
            module_zip = build_module(ROOT, base / "dist")
            adb_root, predecessor_entry, _ = _new_root(base / "root", module_zip)
            _stamp_synthetic_predecessor(adb_root / "modules/otast/module.prop")

            _run(predecessor_entry, adb_root, "preflight")
            _run(predecessor_entry, adb_root, "apply")
            _simulate_managed_boot(adb_root)
            _run(predecessor_entry, adb_root, "verify")
            predecessor_modes = state_mode_snapshot(adb_root)

            candidate_entry = _install_candidate(module_zip, adb_root)
            _run(candidate_entry, adb_root, "preflight")
            _run(candidate_entry, adb_root, "apply")
            self.assertEqual(state_mode_snapshot(adb_root), predecessor_modes)

            reinstalled_entry = _install_candidate(module_zip, adb_root)
            _run(reinstalled_entry, adb_root, "preflight")
            _run(reinstalled_entry, adb_root, "apply")
            self.assertEqual(state_mode_snapshot(adb_root), predecessor_modes)


if __name__ == "__main__":
    unittest.main()
