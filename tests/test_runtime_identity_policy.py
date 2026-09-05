from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIF = ROOT / "module/runtime/pif.sh"
POLICY = ROOT / "module/runtime/policy.sh"
AUTHORITY = ROOT / "module/runtime/authority.sh"
PROFILES = ROOT / "module/runtime/profiles.sh"
ENTRY = ROOT / "module/runtime/entry.sh"


class RuntimeIdentityPolicyTests(unittest.TestCase):
    def test_policy_is_sourced_after_pif_and_before_profiles(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        self.assertLess(text.index('. "$MODDIR/pif.sh"'), text.index('. "$MODDIR/policy.sh"'))
        self.assertLess(text.index('. "$MODDIR/policy.sh"'), text.index('. "$MODDIR/profiles.sh"'))

    def test_pif_identity_takeover_is_retired_fail_closed(self) -> None:
        authority = AUTHORITY.read_text(encoding="utf-8")
        self.assertIn("otast.pif.identity=ota is retired", authority)
        self.assertNotIn('case "$OTAST_PIF_IDENTITY_POLICY" in preserve|ota)', authority)
        self.assertNotIn("otast_transform_pif_prop", POLICY.read_text(encoding="utf-8"))
        profiles = PROFILES.read_text(encoding="utf-8")
        self.assertNotIn("otast_transform_pif_prop", profiles)
        self.assertNotIn("pif-global-prop", profiles)
        self.assertNotIn("pif-prop-$role", profiles)

    def test_pif_profiles_are_observed_while_conflicting_writers_remain_managed(self) -> None:
        profiles = PROFILES.read_text(encoding="utf-8")
        self.assertIn('otast_validate_pif_profile_file "$ADB_ROOT/pif.prop"', profiles)
        self.assertIn('otast_validate_pif_profile_file "$dir/pif.prop"', profiles)
        self.assertIn("pif-autopif-$role", profiles)
        self.assertIn("pif-autopif-ota-$role", profiles)
        self.assertIn("pif-security-patch-$role", profiles)

    def test_lock_state_contract_is_conservative_pixel_subset(self) -> None:
        text = POLICY.read_text(encoding="utf-8")
        for expected in (
            "ro.boot.flash.locked",
            "ro.boot.vbmeta.device_state",
            "ro.boot.verifiedbootstate",
            "ro.boot.veritymode",
            "vendor.boot.vbmeta.device_state",
            "vendor.boot.verifiedbootstate",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("ro.oem_unlock_supported", text)
        self.assertNotIn("ro.boot.warranty_bit", text)
        self.assertNotIn("ro.warranty_bit", text)

    def test_verify_checks_live_spl_software_boot_state_and_pif_profile_safety(self) -> None:
        entry = ENTRY.read_text(encoding="utf-8")
        policy = POLICY.read_text(encoding="utf-8")
        verify = entry.split("_otast_verify()", 1)[1].split("_otast_restore()", 1)[0]
        self.assertIn("otast_validate_pif_profiles_current", verify)
        self.assertIn("otast_compare_live_strict_runtime_identity", verify)
        self.assertIn("otast_verify_trickystore_health", verify)
        self.assertIn("ro.build.version.security_patch:OTAST_SYSTEM_PATCH", policy)
        self.assertIn("ro.vendor.build.security_patch:OTAST_VENDOR_PATCH", policy)
        self.assertIn("ro.boot.flash.locked:OTAST_EXPECT_FLASH_LOCKED", policy)
        self.assertIn("ro.boot.verifiedbootstate:OTAST_EXPECT_VERIFIED_BOOT_STATE", policy)

    def test_runtime_planner_owns_otast_and_pif_system_props(self) -> None:
        text = POLICY.read_text(encoding="utf-8")
        self.assertIn("otast-runtime-system-prop", text)
        self.assertIn("pif-runtime-system-prop-$role", text)
        self.assertIn("ro.build.version.security_patch=$OTAST_SYSTEM_PATCH", text)
        self.assertIn("ro.vendor.build.security_patch=$OTAST_VENDOR_PATCH", text)
        self.assertNotIn("$MODDIR/../system.prop", text)
        self.assertIn("path=${MODDIR%/runtime}/system.prop", text)
        self.assertIn('unexpected OTAST runtime directory: $MODDIR', text)

    def test_report_exposes_two_tier_pif_profile_lifecycle(self) -> None:
        text = POLICY.read_text(encoding="utf-8")
        for expected in (
            "pif_custom_profile_path",
            "pif_custom_profile_state",
            "pif_fallback_profile_path",
            "pif_fallback_profile_state",
            "pif_effective_profile_path",
            "pif_effective_profile_role",
            "pif_profiles_relation",
            "pif_profile_security_patch",
            "pif_autopif_engine_state",
            "pif_autopif_self_update_policy=OTAST_REVIEW_GATED",
            "pif_auto_security_patch_requested",
            "pif_auto_security_patch_effective_policy=OTAST_OTA_AUTHORITY",
        ):
            self.assertIn(expected, text)
        self.assertIn("ACTIVE_FALLBACK", text)
        self.assertIn("DISTINCT_EXPECTED", text)
        self.assertIn("ro.boot.verifiedbooterror", text)
        self.assertIn("ro.boot.verifyerrorpart", text)

    def test_legacy_profile_ownership_is_retired_before_restore(self) -> None:
        pif = PIF.read_text(encoding="utf-8")
        entry = ENTRY.read_text(encoding="utf-8")
        for state_id in ("pif-global-prop", "pif-prop-active", "pif-prop-staged"):
            self.assertIn(state_id, pif)
        self.assertIn("pif-profile-ownership-v1", pif)
        apply = entry.split("_otast_apply()", 1)[1].split("_otast_verify()", 1)[0]
        self.assertLess(
            apply.index("otast_apply_plan"),
            apply.index("otast_pif_retire_legacy_profile_state"),
        )
        restore = entry.split("_otast_restore()", 1)[1].split("_otast_report()", 1)[0]
        self.assertLess(
            restore.index("otast_pif_retire_legacy_profile_state"),
            restore.index("otast_restore_all"),
        )


if __name__ == "__main__":
    unittest.main()
