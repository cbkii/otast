from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CompatibilityPolicyTests(unittest.TestCase):
    def _run_version_check(self, version: str, version_code: int, expected: int) -> str:
        common = ROOT / "module/runtime/common.sh"
        with tempfile.TemporaryDirectory(prefix="otast-version-compat-") as raw:
            root = Path(raw)
            module = root / "data/adb/modules/Yurikey"
            module.mkdir(parents=True)
            (module / "module.prop").write_text(
                "id=Yurikey\n"
                "name=Yurikey Manager\n"
                f"version={version}\n"
                f"versionCode={version_code}\n"
                "author=Yurikey Dev\n",
                encoding="utf-8",
            )
            command = f'''
                ADB_ROOT="{root / 'data/adb'}"
                . "{common}" || exit 90
                otast_require_module_version_range "{module}" Yurikey 'v3.0.,3.0.' 305 399
            '''
            result = subprocess.run(
                ["busybox", "sh", "-c", command],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, expected, result.stdout)
            return result.stdout

    def test_yurikey_306_is_accepted_without_source_hash_identity(self) -> None:
        self._run_version_check("3.0.6", 306, 0)
        self._run_version_check("v3.0.6", 306, 0)

    def test_yurikey_other_minor_line_is_rejected(self) -> None:
        output = self._run_version_check("v3.1.0", 310, 1)
        self.assertIn("unsupported Yurikey version", output)

    def test_yurikey_out_of_range_code_is_rejected(self) -> None:
        output = self._run_version_check("v3.0.4", 304, 1)
        self.assertIn("supported range 305..399", output)

    def test_yurikey_whole_file_neutralizers_do_not_use_exact_hash_gate(self) -> None:
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        yurikey = profiles.split("otast_plan_yurikey() {", 1)[1].split("otast_plan_vbmeta_fixer() {", 1)[0]
        self.assertIn("otast_require_module_version_range", yurikey)
        self.assertIn("_otast_plan_compatible_file", yurikey)
        self.assertNotIn("_otast_plan_exact_file", yurikey)
        self.assertNotIn("unsupported exact-replacement hash", yurikey)

    def test_structure_sensitive_and_unmigrated_targets_remain_exact_hash_gated(self) -> None:
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        vbmeta = profiles.split("otast_plan_vbmeta_fixer() {", 1)[1].split("otast_plan_all() {", 1)[0]
        self.assertIn("_otast_plan_transformed_file pif-autopif", profiles)
        self.assertIn("_otast_plan_transformed_file ta-prop", profiles)
        self.assertIn("_otast_plan_transformed_file ta-webui-boot-hash", profiles)
        self.assertIn("_otast_plan_exact_file", vbmeta)
        self.assertIn("bedb09d2538e28d636ea592a58d2a2234849351d49a95175d54c4de7ccf4d5cc", profiles)


if __name__ == "__main__":
    unittest.main()
