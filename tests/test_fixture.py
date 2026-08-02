from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.fake_root import clone_fixture_root
from tools.otastctl.fixture import reset_fixture, sanitize_fixture
from tools.otastctl.util import OtastError


ROOT = Path(__file__).resolve().parents[1]


class FixtureTests(unittest.TestCase):
    def test_sensitive_files_excluded_and_absolute_adb_link_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source = base / "source"
            destination = base / "sanitized"
            (source / "data/adb/modules/.TA_utl").mkdir(parents=True)
            (source / "data/adb/modules/.TA_utl/prop.sh").write_text("ok\n", encoding="utf-8")
            os.symlink("/data/adb/modules/.TA_utl/prop.sh", source / "data/adb/modules/TA_utl-link")
            (source / "data/adb/keybox.xml").write_text("secret\n", encoding="utf-8")
            manifest = sanitize_fixture(source, destination)
            self.assertIn("data/adb/keybox.xml", manifest["excluded"])
            link = destination / "data/adb/modules/TA_utl-link"
            self.assertTrue(link.is_symlink())
            self.assertFalse(os.readlink(link).startswith("/"))

    def test_external_symlink_rejected_and_partial_output_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source = base / "source"
            source.mkdir()
            os.symlink("/etc/passwd", source / "bad")
            destination = base / "sanitized"
            with self.assertRaises(OtastError):
                sanitize_fixture(source, destination)
            self.assertFalse(destination.exists())


    def test_clone_installs_exact_candidate_zip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            fixture = base / "fixture"
            (fixture / "data/adb").mkdir(parents=True)
            (fixture / "data/adb/ota.prop").write_text("fixture-authority\n", encoding="utf-8")
            allowed = base / "cache"
            destination = allowed / "run"
            report = clone_fixture_root(ROOT, fixture, destination, allowed)
            module = destination / "data/adb/modules/otast"
            self.assertEqual(report["result"], "PASS")
            self.assertIn("id=otast\n", (module / "module.prop").read_text(encoding="utf-8"))
            self.assertTrue((module / "release.properties").is_file())
            self.assertEqual((module / "runtime/entry.sh").stat().st_mode & 0o777, 0o755)
            self.assertEqual((module / "runtime/common.sh").stat().st_mode & 0o777, 0o644)

    def test_reset_is_confined_to_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source = base / "source"
            source.mkdir()
            (source / "x").write_text("x", encoding="utf-8")
            allowed = base / "cache"
            reset_fixture(source, allowed / "run", allowed)
            self.assertEqual((allowed / "run/x").read_text(), "x")
            with self.assertRaises(OtastError):
                reset_fixture(source, base / "outside", allowed)


if __name__ == "__main__":
    unittest.main()
