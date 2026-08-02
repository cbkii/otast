from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.otastctl.fake_root import qualify_fake_root

ROOT = Path(__file__).resolve().parents[1]


class FakeRootTests(unittest.TestCase):
    def test_exact_zip_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            evidence = qualify_fake_root(ROOT, Path(raw))
            self.assertEqual(evidence["result"], "PASS")
            self.assertTrue(evidence["scenarios"]["strict_exclusions_preserved"])
            self.assertTrue(evidence["scenarios"]["unknown_hash_rejected"])


if __name__ == "__main__":
    unittest.main()
