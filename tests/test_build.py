from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.otastctl.build import ENTRYPOINTS, build_module, validate_module_zip
from tools.otastctl.util import sha256_file

ROOT = Path(__file__).resolve().parents[1]


class BuildTests(unittest.TestCase):
    def test_module_build_is_deterministic_and_native(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            first = build_module(ROOT, base / "one", commit_sha="a" * 40)
            second = build_module(ROOT, base / "two", commit_sha="a" * 40)
            self.assertEqual(sha256_file(first), sha256_file(second))
            validate_module_zip(first)
            with zipfile.ZipFile(first) as archive:
                names = set(archive.namelist())
                self.assertIn("module.prop", names)
                self.assertNotIn("module/module.prop", names)
                self.assertFalse(any(name.startswith("META-INF/") for name in names))
                for name in ENTRYPOINTS:
                    self.assertEqual((archive.getinfo(name).external_attr >> 16) & 0o777, 0o755)
                self.assertEqual((archive.getinfo("runtime/common.sh").external_attr >> 16) & 0o777, 0o644)
                release = archive.read("release.properties").decode("utf-8")
                self.assertIn("commit_sha=" + "a" * 40 + "\n", release)
                self.assertFalse(any(name.startswith("tools/") or name.startswith("tests/") for name in names))


if __name__ == "__main__":
    unittest.main()
