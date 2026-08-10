from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.otastctl.privacy import require_public_safe, scan_repository
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]


class PrivacyTests(unittest.TestCase):
    def test_repository_is_public_safe(self) -> None:
        require_public_safe(ROOT)

    def test_private_key_marker_detected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            marker = "-----BEGIN " + "PRIVATE KEY-----\n"
            (root / "bad.txt").write_text(marker, encoding="utf-8")
            self.assertTrue(any(item.startswith("private-key:") for item in scan_repository(root)))
            with self.assertRaises(OtastError):
                require_public_safe(root)

    def test_every_eligible_file_is_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            marker = "github_" + "pat_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n"
            (root / "first.txt").write_text(marker, encoding="utf-8")
            (root / "last.txt").write_text("safe\n", encoding="utf-8")
            findings = scan_repository(root)
            self.assertIn("github-token:first.txt", findings)

    def test_empty_and_skipped_directories_are_harmless(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "empty").mkdir()
            skipped = root / "reports"
            skipped.mkdir()
            marker = "github_" + "pat_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n"
            skipped.joinpath("bad.txt").write_text(marker, encoding="utf-8")
            self.assertEqual(scan_repository(root), [])

    def test_file_and_directory_symlinks_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target_file = root / "target.txt"
            target_file.write_text("safe\n", encoding="utf-8")
            target_dir = root / "target-dir"
            target_dir.mkdir()
            file_link = root / "file-link"
            dir_link = root / "dir-link"
            file_link.symlink_to(target_file.name)
            dir_link.symlink_to(target_dir.name, target_is_directory=True)
            findings = scan_repository(root)
            self.assertIn("symlink:file-link", findings)
            self.assertIn("symlink:dir-link", findings)


if __name__ == "__main__":
    unittest.main()
