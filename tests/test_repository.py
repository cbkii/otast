from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.otastctl.repository import build_source_zip, validate_source_zip
from tools.otastctl.util import sha256_file

ROOT = Path(__file__).resolve().parents[1]


class RepositoryPackageTests(unittest.TestCase):
    def test_source_package_is_deterministic_and_clean(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            one = build_source_zip(ROOT, base / "one.zip")
            two = build_source_zip(ROOT, base / "two.zip")
            self.assertEqual(sha256_file(one), sha256_file(two))
            validate_source_zip(one)
            with zipfile.ZipFile(one) as archive:
                names = archive.namelist()
                self.assertTrue(all(name.startswith("otast/") for name in names))
                self.assertFalse(any("/.git/" in name for name in names))
                self.assertFalse(any("/reports/" in name for name in names))
                self.assertFalse(any("/__pycache__/" in name or name.endswith(".pyc") for name in names))
                self.assertEqual((archive.getinfo("otast/scripts/test.sh").external_attr >> 16) & 0o777, 0o755)
                self.assertEqual((archive.getinfo("otast/module/runtime/common.sh").external_attr >> 16) & 0o777, 0o644)


if __name__ == "__main__":
    unittest.main()
