from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.otastctl.monitor import monitor_targets

ROOT = Path(__file__).resolve().parents[1]


class MonitorTests(unittest.TestCase):
    def test_reviewed_heads_pass(self) -> None:
        def fake(url: str, **_: object) -> dict[str, object]:
            for target in __import__("json").loads(
                (ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8")
            )["targets"].values():
                monitor = target.get("monitor")
                if monitor and f"/{monitor['repository']}/" in url and url.endswith(f"/{monitor['branch']}"):
                    return {"sha": monitor["expected_head"]}
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as raw, patch("tools.otastctl.monitor._github_json", side_effect=fake):
            report = monitor_targets(ROOT, Path(raw))
            self.assertEqual(report["result"], "PASS")
            self.assertTrue(all(item["status"] == "supported" for item in report["targets"]))

    def test_changed_head_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch(
            "tools.otastctl.monitor._github_json", return_value={"sha": "f" * 40}
        ):
            report = monitor_targets(ROOT, Path(raw))
            self.assertEqual(report["result"], "REVIEW_REQUIRED")
            self.assertTrue(any(item["status"] == "review-required" for item in report["targets"]))


if __name__ == "__main__":
    unittest.main()
