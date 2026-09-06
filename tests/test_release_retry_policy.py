from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "scripts/release-device-lifecycle.sh"


class ReleaseRetryPolicyTests(unittest.TestCase):
    def test_compatibility_review_is_non_retryable(self) -> None:
        text = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("deterministic compatibility review", text)
        self.assertIn("Fresh target/dependency .*status 10", text)
        self.assertIn("((watch_rc == 10)) && return 10", text)
        self.assertIn("((dispatch_rc == 10))", text)
        self.assertIn("not retrying the identical workflow", text)


if __name__ == "__main__":
    unittest.main()
