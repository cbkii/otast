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


if __name__ == "__main__":
    unittest.main()
