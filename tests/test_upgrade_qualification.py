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
        self.assertEqual(
            set(evidence["scenarios"]),
            {
                "synthetic_stable_to_candidate",
                "self_managed_system_prop_rehydrated_transactionally",
                "existing_v2_managed_state_adopted",
                "modules_update_mirror_state_preserved",
                "original_backups_preserved",
                "second_apply_noop",
                "candidate_reinstall_safe",
                "fallback_mirror_drift_rejected",
                "contradictory_state_rejected",
            },
        )

    def test_published_v1_0_2_runtime_upgrades_to_candidate(self) -> None:
        if not git_ref_available(ROOT, PUBLISHED_PREDECESSOR_REF):
            self.skipTest(
                f"{PUBLISHED_PREDECESSOR_REF} Git history is unavailable in this source export"
            )
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
                "legacy_pif_writer_state_retired",
                "canonical_pif_source_preserved_during_migration",
                "fallbacks_reconciled_to_canonical",
                "predecessor_original_backups_preserved",
                "candidate_may_add_v2_mirror_backups",
                "pif_refresh_requires_explicit_reconcile",
                "pif_refresh_reconciled_transactionally",
                "second_apply_noop",
                "canonical_refresh_survives_restore",
                "candidate_restore_recovers_true_fallback_originals",
                "candidate_restore_recovers_non_pif_pre_otast_bytes",
                "managed_state_removed_after_restore",
            },
        )


if __name__ == "__main__":
    unittest.main()
