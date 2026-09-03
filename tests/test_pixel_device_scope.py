from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PixelDeviceScopeTests(unittest.TestCase):
    def test_end_user_module_text_is_model_agnostic(self) -> None:
        module_prop = (ROOT / "module/module.prop").read_text(encoding="utf-8")
        customize = (ROOT / "module/customize.sh").read_text(encoding="utf-8")
        runtime_authority = (ROOT / "module/runtime/authority.sh").read_text(encoding="utf-8")
        platform = (ROOT / "module/runtime/platform.sh").read_text(encoding="utf-8")

        for text in (module_prop, customize, runtime_authority):
            self.assertNotIn("Pixel 9a", text)
            self.assertNotIn("Pixel 8", text)

        self.assertIn("Google Pixel devices on Android 16", module_prop)
        self.assertIn("Validating Google Pixel", customize)
        self.assertIn("$OTAST_PLATFORM_ID", customize)
        self.assertIn("OTAST_PLATFORM_ANDROID_RELEASE='16'", platform)
        self.assertNotIn("install the module and reboot", customize)

    def test_installer_success_is_followed_by_actionable_next_steps(self) -> None:
        customize = (ROOT / "module/customize.sh").read_text(encoding="utf-8")
        success = customize.index("SUCCESS !!")
        next_steps = customize.index("- Next steps:")
        self.assertLess(success, next_steps)
        for required in (
            "1. Reboot the device.",
            "2. Open Magisk > Modules > OTAST > Action.",
            "3. Select Preflight (read-only).",
            "4. If Preflight passes, run Action again and select Apply.",
            "5. If Apply reports REBOOT_REQUIRED, reboot again.",
            "6. Run Action > Verify (read-only) after that reboot.",
            "Do not run Apply before the first reboot.",
        ):
            self.assertIn(required, customize)

    def test_machine_readable_scope_does_not_overclaim_pixel_models(self) -> None:
        registry = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        support = registry["support_model"]
        self.assertEqual(support["device_family"], "Google Pixel")
        self.assertEqual(support["family_architecture"]["tier"], "DESIGN_COMPATIBLE")
        self.assertEqual(support["undeclared_device_tier"], "UNQUALIFIED")

        tegu = support["devices"]["tegu"]
        self.assertEqual(tegu["model"], "Pixel 9a")
        self.assertEqual(tegu["tier"], "DEVICE_VALIDATED")
        self.assertEqual(tegu["qualified_builds"], ["CP1A.260305.018"])

        shiba = support["devices"]["shiba"]
        self.assertEqual(shiba["model"], "Pixel 8")
        self.assertEqual(shiba["tier"], "DESIGN_COMPATIBLE")
        self.assertEqual(shiba["qualified_builds"], [])

    def test_public_docs_use_generated_qualification_status(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        supported = (ROOT / "docs/SUPPORTED-TARGETS.md").read_text(encoding="utf-8")
        status = (ROOT / "docs/COMPATIBILITY-STATUS.md").read_text(encoding="utf-8")

        self.assertIn("COMPATIBILITY-STATUS.md", readme)
        self.assertIn("COMPATIBILITY-STATUS.md", supported)
        self.assertIn("`tegu` | Pixel 9a | `android-16` | `DEVICE_VALIDATED`", status)
        self.assertIn("`shiba` | Pixel 8 | `android-16` | `DESIGN_COMPATIBLE` | none", status)
        self.assertIn("Undeclared device/build tier: `UNQUALIFIED`", status)


if __name__ == "__main__":
    unittest.main()
