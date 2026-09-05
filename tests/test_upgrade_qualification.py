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
        # qualify_upgrade_path raises a scenario-specific OtastError at the point of
        # failure. A successful return is therefore the actual no-exception
        # qualification assertion; only the evidence schema/key contract is checked
        # here rather than re-asserting hard-coded True values.
        with tempfile.TemporaryDirectory() as raw:
            evidence = qualify_upgrade_path(ROOT, Path(raw))
        self.assertEqual(evidence["result"], "PASS")
        self.assertEqual(
            set(evidence["scenarios"]),
            {
                "synthetic_stable_to_candidate",
                "self_managed_system_prop_rehydrated_transactionally",
                "existing_managed_state_adopted",
                "modules_update_state_preserved",
                "original_backups_preserved",
                "second_apply_noop",
                "candidate_reinstall_safe",
                "active_staged_disagreement_rejected",
                "contradictory_state_rejected",
            },
        )

    def test_published_v1_0_2_runtime_upgrades_to_candidate(self) -> None:
        if not git_ref_available(ROOT, PUBLISHED_PREDECESSOR_REF):
            self.skipTest(
                f"{PUBLISHED_PREDECESSOR_REF} Git history is unavailable in this source export"
            )
        # As above, the qualification implementation raises at the exact failing
        # lifecycle stage. Do not duplicate those guards with vacuous True checks.
        with tempfile.TemporaryDirectory() as raw:
            evidence = qualify_published_predecessor(ROOT, Path(raw))
        self.assertEqual(evidence["result"], "PASS")
        self.assertEqual(evidence["predecessor_ref"], PUBLISHED_PREDECESSOR_REF)
        self.assertRegex(evidence["predecessor_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            set(evidence["scenarios"]),
            {
                "published_predecessor_preflight_apply_verify",
                "candidate_preflight_apply_verify",
                "legacy_pif_profile_state_retired",
                "pif_profile_bytes_preserved_during_ownership_retirement",
                "predecessor_original_backups_preserved",
                "candidate_may_add_new_first_time_backups",
                "second_apply_noop",
                "pif_profile_refresh_survives_noop_apply_and_restore",
                "candidate_restore_recovers_non_pif_pre_otast_bytes",
                "managed_state_removed_after_restore",
            },
        )


if __name__ == "__main__":
    unittest.main()
