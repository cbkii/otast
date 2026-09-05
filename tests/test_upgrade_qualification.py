from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.otastctl.upgrade_qualification import qualify_upgrade_path

ROOT = Path(__file__).resolve().parents[1]


class UpgradeQualificationTests(unittest.TestCase):
    def test_managed_upgrade_and_reinstall_are_transactionally_safe(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            evidence = qualify_upgrade_path(ROOT, Path(raw))
        self.assertEqual(evidence["result"], "PASS")
        scenarios = evidence["scenarios"]
        for name in (
            "synthetic_stable_to_candidate",
            "existing_managed_state_adopted",
            "modules_update_state_preserved",
            "original_backups_preserved",
            "candidate_reinstall_noop",
            "active_staged_disagreement_rejected",
            "contradictory_state_rejected",
            "no_upgrade_transaction_when_runtime_identical",
        ):
            with self.subTest(name=name):
                self.assertTrue(scenarios[name])


if __name__ == "__main__":
    unittest.main()
