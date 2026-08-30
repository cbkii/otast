from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PixelDeviceScopeTests(unittest.TestCase):
    def test_end_user_module_text_is_model_agnostic(self) -> None:
        module_prop = (ROOT / "module/module.prop").read_text(encoding="utf-8")
        customize = (ROOT / "module/customize.sh").read_text(encoding="utf-8")
        runtime_authority = (ROOT / "module/runtime/authority.sh").read_text(encoding="utf-8")

        for text in (module_prop, customize, runtime_authority):
            self.assertNotIn("Pixel 9a", text)

        self.assertIn("Google Pixel devices on Android 16", module_prop)
        self.assertIn("Validating Google Pixel Android 16", customize)
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

    def test_public_docs_state_family_scope_and_physical_test_matrix(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs/INSTALLATION.md").read_text(encoding="utf-8")
        supported = (ROOT / "docs/SUPPORTED-TARGETS.md").read_text(encoding="utf-8")
        limitations = (ROOT / "docs/LIMITATIONS.md").read_text(encoding="utf-8")

        self.assertIn("Google Pixel devices running Android 16", readme)
        self.assertIn("Pixel-device model-agnostic", readme)
        self.assertIn("Pixel 9a", readme)
        self.assertIn("Pixel 8", readme)
        self.assertIn("Other Pixel models", readme)

        self.assertIn("Google Pixel device.", installation)
        self.assertNotIn("Pixel 9a (`tegu`).", installation)
        for text in (installation, supported, limitations):
            self.assertIn("Pixel 9a", text)
            self.assertIn("Pixel 8", text)


if __name__ == "__main__":
    unittest.main()
