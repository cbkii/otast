from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIF = ROOT / "module/runtime/pif.sh"
POLICY = ROOT / "module/runtime/policy.sh"
ENTRY = ROOT / "module/runtime/entry.sh"


class RuntimeIdentityPolicyTests(unittest.TestCase):
    def test_policy_is_sourced_after_pif_and_before_profiles(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        self.assertLess(text.index('. "$MODDIR/pif.sh"'), text.index('. "$MODDIR/policy.sh"'))
        self.assertLess(text.index('. "$MODDIR/policy.sh"'), text.index('. "$MODDIR/profiles.sh"'))

    def _run_transform(self, source_text: str, identity: str) -> str:
        with tempfile.TemporaryDirectory(prefix="otast-policy-") as raw:
            work = Path(raw)
            source = work / "pif.prop"
            output = work / "out.prop"
            source.write_text(source_text, encoding="utf-8")
            command = f'''
                . "{PIF}" || exit 1
                . "{POLICY}" || exit 2
                OTAST_PIF_IDENTITY_POLICY={identity}
                OTAST_FINGERPRINT='google/tegu/tegu:16/CP1A.260305.018/14887507:user/release-keys'
                OTAST_MANUFACTURER=Google
                OTAST_MODEL='Pixel 9a'
                OTAST_DEVICE=tegu
                OTAST_SYSTEM_PATCH=2026-03-05
                OTAST_PIF_SPOOF_BUILD=preserve
                OTAST_PIF_SPOOF_PROPS=preserve
                OTAST_PIF_SPOOF_PROVIDER=preserve
                OTAST_PIF_SPOOF_SIGNATURE=preserve
                OTAST_PIF_SPOOF_VENDING_BUILD=preserve
                OTAST_PIF_SPOOF_VENDING_SDK=preserve
                OTAST_PIF_DEBUG=preserve
                otast_transform_pif_prop "{source}" "{output}" || exit 3
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=10)
            return output.read_text(encoding="utf-8")

    def test_pif_preserve_identity_keeps_attestation_profile_security_patch(self) -> None:
        text = self._run_transform(
            "FINGERPRINT=google/oriole_beta/oriole:CANARY/KEEP/1:user/release-keys\n"
            "MODEL=Pixel 6\n"
            "SECURITY_PATCH=2026-07-05\n"
            "spoofBuild=true\n"
            "spoofProps=false\n",
            "preserve",
        )
        self.assertIn("FINGERPRINT=google/oriole_beta/oriole:CANARY/KEEP/1:user/release-keys", text)
        self.assertIn("MODEL=Pixel 6", text)
        self.assertIn("SECURITY_PATCH=2026-07-05", text)
        self.assertIn("spoofBuild=true", text)
        self.assertIn("spoofProps=false", text)
        self.assertNotIn("SECURITY_PATCH=2026-03-05", text)

    def test_explicit_pif_ota_identity_takeover_reconciles_profile_patch(self) -> None:
        text = self._run_transform(
            "FINGERPRINT=google/oriole_beta/oriole:CANARY/KEEP/1:user/release-keys\n"
            "MODEL=Pixel 6\n"
            "SECURITY_PATCH=2026-07-05\n"
            "spoofBuild=true\n"
            "spoofProps=false\n",
            "ota",
        )
        self.assertIn(
            "FINGERPRINT=google/tegu/tegu:16/CP1A.260305.018/14887507:user/release-keys",
            text,
        )
        self.assertIn("MODEL=Pixel 9a", text)
        self.assertIn("SECURITY_PATCH=2026-03-05", text)
        self.assertNotIn("SECURITY_PATCH=2026-07-05", text)

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

    def test_verify_checks_live_spl_and_software_boot_state(self) -> None:
        entry = ENTRY.read_text(encoding="utf-8")
        policy = POLICY.read_text(encoding="utf-8")
        verify = entry.split("_otast_verify()", 1)[1].split("_otast_restore()", 1)[0]
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

    def test_report_separates_profile_patch_from_platform_patch(self) -> None:
        text = POLICY.read_text(encoding="utf-8")
        self.assertIn("pif_effective_profile_path", text)
        self.assertIn("pif_profile_security_patch", text)
        self.assertIn("pif_profile_spoofProps", text)
        self.assertIn("pif_profile_patch_scope", text)
        self.assertIn("ro.boot.verifiedbooterror", text)
        self.assertIn("ro.boot.verifyerrorpart", text)


if __name__ == "__main__":
    unittest.main()
