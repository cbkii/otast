from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RuntimeContractTests(unittest.TestCase):
    def test_no_automatic_apply_service(self) -> None:
        service = (ROOT / "module/service.sh").read_text(encoding="utf-8")
        post_fs = (ROOT / "module/post-fs-data.sh").read_text(encoding="utf-8")
        self.assertNotIn(" apply", service)
        self.assertIn("boot-recover", post_fs)
        self.assertNotIn(" apply", post_fs)

    def test_pif_managed_surface_is_minimal(self) -> None:
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        for path in ("action.sh", "post-fs-data.sh", "service.sh", "common_func.sh"):
            self.assertNotIn(f"playintegrityfix/{path}", profiles)
        for path in ("autopif.sh", "autopif_ota.sh", "pif.prop", "security_patch.sh", "system.prop"):
            self.assertIn(f"playintegrityfix/{path}", profiles)

    def test_pif_manifest_and_runtime_autopif_allowlists_match(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        pif = manifest["targets"]["playintegrityfix"]
        runtime = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        for name in ("autopif.sh", "autopif_ota.sh"):
            expected = pif["accepted_hashes"][name]
            match = re.search(
                rf'otast_plan_pif_autopif "[^"\n]+/{re.escape(name)}" "([^"\n]+)" "([^"\n]+)" "([^"\n]+)"',
                runtime,
            )
            self.assertIsNotNone(match, name)
            assert match is not None
            self.assertEqual([value for value in match.groups() if value], expected)

    def test_legacy_governor_and_pif_auto_patch_contract(self) -> None:
        common = (ROOT / "module/runtime/common.sh").read_text(encoding="utf-8")
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        self.assertIn("otast_check_legacy_governors", common)
        self.assertIn("000-$legacy_otasst.sh", common)
        self.assertIn("persistent runtime trace", common)
        self.assertIn("$OTAST_PIF_AUTO_PATCH_FLAG", profiles)
        self.assertNotIn("otast_check_legacy_governors", profiles)
        self.assertIn("regular Auto Security Patch marker", profiles)
        self.assertIn("not a regular file", profiles)
        self.assertNotIn("rm -f \"$OTAST_PIF_AUTO_PATCH_FLAG\"", profiles)

    def test_runtime_authority_is_pixel_family_not_model_pinned(self) -> None:
        authority = (ROOT / "module/runtime/authority.sh").read_text(encoding="utf-8")
        platform = (ROOT / "module/runtime/platform.sh").read_text(encoding="utf-8")
        entry = (ROOT / "module/runtime/entry.sh").read_text(encoding="utf-8")
        self.assertNotIn('[ "$OTAST_DEVICE" = tegu ]', authority)
        self.assertIn("otast_platform_validate_product", authority)
        self.assertIn("OTAST_PLATFORM_ANDROID_RELEASE='16'", platform)
        self.assertIn("OTAST_PLATFORM_SDK='36'", platform)
        self.assertIn("OTAST_PLATFORM_MANUFACTURER='Google'", platform)
        self.assertIn("OTAST_PLATFORM_MODEL_PREFIX='Pixel '", platform)
        self.assertIn("OTAST_PLATFORM_FINGERPRINT_VENDOR='google'", platform)
        self.assertIn("OTAST_PLATFORM_FINGERPRINT_SUFFIX=':user/release-keys'", platform)
        self.assertIn('. "$MODDIR/platform.sh"', entry)
        self.assertLess(entry.index('platform.sh"'), entry.index('authority.sh"'))

    def test_runtime_requires_independent_vendor_security_patch(self) -> None:
        authority = (ROOT / "module/runtime/authority.sh").read_text(encoding="utf-8")
        self.assertIn("OTAST_VENDOR_PATCH=$(otast_authority_value ro.vendor.build.security_patch)", authority)
        self.assertNotIn("otast_authority_optional ro.vendor.build.security_patch", authority)
        self.assertIn("required independent vendor security patch", authority)
        self.assertIn("ro.vendor.build.security_patch", authority)

    def test_id_validation_uses_predicate_not_printing_helper(self) -> None:
        common = ROOT / "module/runtime/common.sh"
        runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "module/runtime").glob("*.sh"))
        self.assertIn("otast_id_valid()", common.read_text(encoding="utf-8"))
        for bad in (
            'otast_safe_id "$prefix" >/dev/null',
            'otast_safe_id "$id" >/dev/null',
            'otast_safe_id "$_otast_id" >/dev/null',
            'otast_safe_id "$_otast_target" >/dev/null',
        ):
            self.assertNotIn(bad, runtime_text)

    def test_runtime_never_names_strict_exclusions(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        exclusions = manifest["strict_exclusions"]
        runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "module").rglob("*.sh"))
        for exclusion in exclusions:
            self.assertNotIn(exclusion, runtime_text)

    def test_boot_hash_and_live_vbmeta_contract(self) -> None:
        authority = (ROOT / "module/runtime/authority.sh").read_text(encoding="utf-8")
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        report = (ROOT / "module/runtime/report.sh").read_text(encoding="utf-8")
        for key in (
            "boot.img.sha256",
            "ro.boot.vbmeta.digest",
            "ro.boot.vbmeta.size",
            "ro.boot.vbmeta.avb_version",
            "ro.boot.avb_version",
        ):
            self.assertIn(key, authority)
        self.assertIn("otast_compare_bootloader_vbmeta", authority)
        self.assertIn("androidboot.vbmeta.digest", authority)
        self.assertIn("androidboot.vbmeta.avb_version", authority)
        self.assertIn("ro.boot.vbmeta.digest", profiles)
        self.assertIn("ro.boot.vbmeta.avb_version", profiles)
        self.assertIn("ro.boot.avb_version", profiles)
        self.assertIn("OTAST_VBMETA_SIZE", report)

    def test_runtime_vbmeta_contract_excludes_artifact_size(self) -> None:
        authority = (ROOT / "module/runtime/authority.sh").read_text(encoding="utf-8")
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        self.assertNotIn("ro.boot.vbmeta.size:OTAST_VBMETA_SIZE", authority)
        self.assertNotRegex(profiles, r'otast_add_property_plan\s+[^\n]*ro\.boot\.vbmeta\.size')
        self.assertNotIn("resetprop ro.boot.vbmeta.size", profiles)

    def test_compatibility_manifest_and_platform_profile_match(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        profile = json.loads((ROOT / "compatibility/platforms/android-16.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["platforms"]["android-16"]["profile"], "compatibility/platforms/android-16.json")
        self.assertEqual(profile["sdk"], 36)
        self.assertEqual(profile["android_release"], "16")
        self.assertIn("ro.build.version.security_patch", profile["authority"]["required_keys"])
        self.assertIn("ro.vendor.build.security_patch", profile["authority"]["required_keys"])
        self.assertIn("runtime_page_size", profile["native_environment_evidence"])


if __name__ == "__main__":
    unittest.main()
