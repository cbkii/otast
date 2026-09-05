from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.otastctl.upgrade_qualification import (
    PUBLISHED_PREDECESSOR_REF,
    git_ref_available,
    qualify_published_predecessor,
    qualify_upgrade_path,
)

ROOT = Path(__file__).resolve().parents[1]


class UpgradeQualificationTests(unittest.TestCase):
    def test_managed_upgrade_and_reinstall_are_transactionally_safe(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            evidence = qualify_upgrade_path(ROOT, Path(raw))
        self.assertEqual(evidence["result"], "PASS")
        scenarios = evidence["scenarios"]
        for name in (
            "synthetic_stable_to_candidate",
            "self_managed_system_prop_rehydrated_transactionally",
            "existing_managed_state_adopted",
            "modules_update_state_preserved",
            "original_backups_preserved",
            "second_apply_noop",
            "candidate_reinstall_safe",
            "active_staged_disagreement_rejected",
            "contradictory_state_rejected",
        ):
            with self.subTest(name=name):
                self.assertTrue(scenarios[name])

    def test_published_v1_0_2_runtime_upgrades_to_candidate(self) -> None:
        if not git_ref_available(ROOT, PUBLISHED_PREDECESSOR_REF):
            self.skipTest(
                f"{PUBLISHED_PREDECESSOR_REF} Git history is unavailable in this source export"
            )
        with tempfile.TemporaryDirectory() as raw:
            evidence = qualify_published_predecessor(ROOT, Path(raw))
        self.assertEqual(evidence["result"], "PASS")
        self.assertEqual(evidence["predecessor_ref"], PUBLISHED_PREDECESSOR_REF)
        self.assertEqual(len(evidence["predecessor_commit"]), 40)
        for name, passed in evidence["scenarios"].items():
            with self.subTest(name=name):
                self.assertTrue(passed)


if __name__ == "__main__":
    unittest.main()
