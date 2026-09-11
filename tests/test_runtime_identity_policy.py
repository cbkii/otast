from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "module/runtime/policy.sh"
AUTHORITY = ROOT / "module/runtime/authority.sh"
PROFILES = ROOT / "module/runtime/profiles.sh"
ARCH = ROOT / "module/runtime/architecture-v2.sh"
ENTRY = ROOT / "module/runtime/entry.sh"


class RuntimeIdentityPolicyTests(unittest.TestCase):
    def test_v2_policy_is_sourced_after_profiles(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        self.assertLess(text.index('. "$MODDIR/pif.sh"'), text.index('. "$MODDIR/policy.sh"'))
        self.assertLess(text.index('. "$MODDIR/policy.sh"'), text.index('. "$MODDIR/profiles.sh"'))
        self.assertLess(text.index('. "$MODDIR/profiles.sh"'), text.index('. "$MODDIR/architecture-v2.sh"'))
        self.assertLess(text.index('. "$MODDIR/architecture-v2.sh"'), text.index('. "$MODDIR/report.sh"'))

    def test_pif_identity_takeover_remains_retired(self) -> None:
        authority = AUTHORITY.read_text(encoding="utf-8")
        self.assertIn("otast.pif.identity=ota is retired", authority)
        self.assertNotIn('case "$OTAST_PIF_IDENTITY_POLICY" in preserve|ota)', authority)
        self.assertNotIn("otast_transform_pif_prop", POLICY.read_text(encoding="utf-8"))
        self.assertNotIn("otast_transform_pif_prop", PROFILES.read_text(encoding="utf-8"))

    def test_canonical_profile_precedence_and_transactional_mirrors(self) -> None:
        text = ARCH.read_text(encoding="utf-8")
        self.assertIn("OTAST_PIF_ARCHITECTURE=canonical-mirror-v2", text)
        select = text.split("_otast_pif_select_canonical()", 1)[1].split("otast_validate_pif_profiles_current()", 1)[0]
        self.assertLess(select.index("GLOBAL_CUSTOM"), select.index("ACTIVE_FALLBACK"))
        self.assertLess(select.index("ACTIVE_FALLBACK"), select.index("STAGED_FALLBACK"))
        self.assertIn('if [ "$dir/pif.prop" != "$OTAST_PIF_CANONICAL_PATH" ]', text)
        self.assertIn('"pif-mirror-$role" playintegrityfix "$dir/pif.prop"', text)
        self.assertIn("MIRROR_UPDATE_REQUIRED", text)
        self.assertIn("otast_verify_pif_profile_coherence", text)

    def test_autopif_and_updater_are_upstream_owned(self) -> None:
        text = ARCH.read_text(encoding="utf-8")
        planner = text.split("otast_plan_pif()", 1)[1].split("otast_plan_strict_runtime_identity()", 1)[0]
        self.assertNotIn("pif-autopif-$role", planner)
        self.assertNotIn("pif-autopif-ota-$role", planner)
        self.assertIn("pif-security-patch-$role", text)
        self.assertIn("pif_autopif_lifecycle=UPSTREAM_PRESERVED", text)
        self.assertIn("pif_autopif_self_update_policy=UPSTREAM_PRESERVED", text)

    def test_security_patch_intervention_is_surgical(self) -> None:
        text = ARCH.read_text(encoding="utf-8")
        transform = text.split("otast_transform_pif_security_patch()", 1)[1].split("_otast_v2_plan_security_patch()", 1)[0]
        self.assertIn("otast pif patch-domain boundary BEGIN", transform)
        self.assertIn("competing TrickyStore writer suppressed", transform)
        self.assertIn("profile-derived PIF system.prop write suppressed", transform)
        self.assertIn("profile-derived resetprop writes suppressed", transform)
        self.assertIn("seen_domain", transform)
        self.assertIn("seen_system", transform)
        self.assertIn("seen_reset", transform)
        self.assertNotIn("exit 0", transform)

    def test_runtime_system_prop_contains_only_ota_spl(self) -> None:
        text = ARCH.read_text(encoding="utf-8")
        planner = text.split("otast_plan_strict_runtime_identity()", 1)[1].split("_otast_v2_boot_error_present()", 1)[0]
        self.assertIn("ro.build.version.security_patch=$OTAST_SYSTEM_PATCH", planner)
        self.assertIn("ro.vendor.build.security_patch=$OTAST_VENDOR_PATCH", planner)
        for forbidden in (
            "ro.boot.flash.locked=",
            "ro.boot.vbmeta.device_state=",
            "ro.boot.verifiedbootstate=",
            "ro.boot.veritymode=",
            "vendor.boot.vbmeta.device_state=",
            "vendor.boot.verifiedbootstate=",
        ):
            self.assertNotIn(forbidden, planner)

    def test_verify_rejects_green_with_verification_error_evidence(self) -> None:
        text = ARCH.read_text(encoding="utf-8")
        verify = text.split("otast_verify_boot_presentation_consistency()", 1)[1].split("otast_compare_live_strict_runtime_identity()", 1)[0]
        self.assertIn("ro.boot.verifiedbootstate", verify)
        self.assertIn("ro.boot.verifiedbooterror", verify)
        self.assertIn("ro.boot.verifyerrorpart", verify)
        self.assertIn('state" = green', verify)
        self.assertIn("contradictory verified-boot presentation", verify)

    def test_report_separates_raw_runtime_and_pif_domains(self) -> None:
        text = ARCH.read_text(encoding="utf-8")
        for expected in (
            "pif_profile_architecture",
            "pif_profile_precedence",
            "pif_canonical_profile_path",
            "pif_canonical_profile_role",
            "pif_active_profile_relation",
            "pif_staged_profile_relation",
            "pif_autopif_self_update_policy=UPSTREAM_PRESERVED",
            "pif_security_patch_writer_policy=OTAST_SURGICAL_PATCH_DOMAIN_BOUNDARY",
            "raw_%s=%s",
            "live_%s=%s",
            "ro.boot.verifiedbooterror",
            "ro.boot.verifyerrorpart",
        ):
            self.assertIn(expected, text)

    def test_v1_writer_ownership_is_restored_then_retired(self) -> None:
        text = ARCH.read_text(encoding="utf-8")
        for state_id in (
            "pif-autopif-active",
            "pif-autopif-staged",
            "pif-autopif-ota-active",
            "pif-autopif-ota-staged",
            "pif-runtime-system-prop-active",
            "pif-runtime-system-prop-staged",
        ):
            self.assertIn(state_id, text)
        self.assertIn("_otast_pif_restore_deprecated_writer", text)
        self.assertIn("pif-writer-ownership-v2", text)
        self.assertIn("pif-profile-ownership-v1", text)

    def test_identity_runtime_paths_do_not_use_awk(self) -> None:
        for relative in (
            "authority.sh",
            "entry.sh",
            "pif.sh",
            "policy.sh",
            "profiles.sh",
            "architecture-v2.sh",
            "report.sh",
            "ta.sh",
            "trickystore.sh",
        ):
            path = ROOT / "module/runtime" / relative
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)(^|[;&|()]\s*)awk(?:\s|$)", relative)


if __name__ == "__main__":
    unittest.main()
