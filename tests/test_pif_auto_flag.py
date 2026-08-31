from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.build import build_module
from tools.otastctl.fake_root import _new_root, _run

ROOT = Path(__file__).resolve().parents[1]


class PifAutoPatchFlagTests(unittest.TestCase):
    def test_existing_flag_bytes_and_mode_survive_apply_restore(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-auto-flag-") as raw:
            root = Path(raw)
            dist = root / "dist"
            module_zip = build_module(ROOT, dist)
            adb_root, entry, _ = _new_root(root / "fake", module_zip, staged_pif=False)

            flag = adb_root / "tricky_store/pif_auto_security_patch"
            flag.write_bytes(b"enabled-by-user\n")
            flag.chmod(0o640)
            expected_bytes = flag.read_bytes()
            expected_mode = stat.S_IMODE(flag.stat().st_mode)

            preflight = _run(entry, adb_root, "preflight")
            self.assertIn("will neutralize its reviewed global writer on Apply", preflight.stdout)

            _run(entry, adb_root, "apply")
            self.assertFalse(flag.is_symlink())
            self.assertTrue(flag.is_file())
            self.assertEqual(flag.read_bytes(), expected_bytes)
            self.assertEqual(stat.S_IMODE(flag.stat().st_mode), expected_mode)

            _run(entry, adb_root, "restore")
            self.assertFalse(flag.is_symlink())
            self.assertTrue(flag.is_file())
            self.assertEqual(flag.read_bytes(), expected_bytes)
            self.assertEqual(stat.S_IMODE(flag.stat().st_mode), expected_mode)


if __name__ == "__main__":
    unittest.main()
