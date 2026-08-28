from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FIXTURES = ROOT / "tests/fixtures/upstream"


class ProfileTests(unittest.TestCase):
    def test_template_hashes_and_accepted_hashes_are_exact(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        templates = {
            "yurikey": ROOT / "module/runtime/templates/yurikey",
            "vbmeta-fixer": ROOT / "module/runtime/templates/vbmeta-fixer",
        }
        for target, base in templates.items():
            declared = manifest["targets"][target]["managed_templates"]
            for name, expected in declared.items():
                with self.subTest(target=target, template=name):
                    self.assertRegex(expected, HEX64)
                    self.assertEqual(hashlib.sha256((base / name).read_bytes()).hexdigest(), expected)
        for target in manifest["targets"].values():
            for category in ("accepted_hashes", "observed_only_hashes"):
                for hashes in target.get(category, {}).values():
                    for value in hashes:
                        self.assertRegex(value, HEX64)

    def test_reviewed_writer_fixtures_match_allowlists(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        checks = (
            ("playintegrityfix", "autopif.sh", "pif-autopif-ea93222c.sh"),
            ("playintegrityfix", "autopif.sh", "pif-autopif-8b4a00ce.sh"),
            ("playintegrityfix", "autopif_ota.sh", "pif-autopif-ota-ea93222c.sh"),
            ("playintegrityfix", "security_patch.sh", "pif-security-patch-ea93222c.sh"),
            ("ta-utl", "prop.sh", "ta-utl-prop-v4.4.sh"),
        )
        for target, name, fixture_name in checks:
            digest = hashlib.sha256((FIXTURES / fixture_name).read_bytes()).hexdigest()
            self.assertIn(digest, manifest["targets"][target]["accepted_hashes"][name])

    def _pif_env(self, identity: str = "ota") -> str:
        return f'''
            OTAST_FINGERPRINT='google/tegu/tegu:16/TEST/1:user/release-keys'
            OTAST_MANUFACTURER='Google'
            OTAST_MODEL='Pixel 9a'
            OTAST_SYSTEM_PATCH='2026-03-05'
            OTAST_DEVICE='tegu'
            OTAST_PIF_IDENTITY_POLICY='{identity}'
            OTAST_PIF_SPOOF_BUILD='true'
            OTAST_PIF_SPOOF_PROPS='true'
            OTAST_PIF_SPOOF_PROVIDER='true'
            OTAST_PIF_SPOOF_SIGNATURE='true'
            OTAST_PIF_SPOOF_VENDING_BUILD='true'
            OTAST_PIF_SPOOF_VENDING_SDK='true'
            OTAST_PIF_DEBUG='false'
        '''

    def test_pif_transform_preserves_lifecycle_and_unknown_configuration(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        with tempfile.TemporaryDirectory(prefix="otast-pif-test-") as raw:
            work = Path(raw)
            prop = work / "pif.prop"
            auto = work / "autopif.sh"
            ota = work / "autopif_ota.sh"
            security = work / "security_patch.sh"
            prop.write_text(
                "# retain-comment\nFINGERPRINT=old\nCUSTOM_OPTION=retain-me\nspoofBuild=false\n",
                encoding="utf-8",
            )
            for destination, source in (
                (auto, FIXTURES / "pif-autopif-ea93222c.sh"),
                (ota, FIXTURES / "pif-autopif-ota-ea93222c.sh"),
                (security, FIXTURES / "pif-security-patch-ea93222c.sh"),
            ):
                destination.write_bytes(source.read_bytes())
            command = f'''
                . "{pif_runtime}" || exit 1
                {self._pif_env("ota")}
                otast_transform_pif_prop "{prop}" "{work / 'pif.out'}" || exit 2
                otast_transform_pif_autopif "{auto}" "{work / 'auto.out'}" || exit 3
                otast_transform_pif_ota "{ota}" "{work / 'ota.out'}" || exit 4
                otast_transform_pif_security_patch "{security}" "{work / 'security.out'}" || exit 5
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            prop_text = (work / "pif.out").read_text(encoding="utf-8")
            self.assertIn("# retain-comment", prop_text)
            self.assertIn("CUSTOM_OPTION=retain-me", prop_text)
            self.assertIn("FINGERPRINT=google/tegu/tegu:16/TEST/1:user/release-keys", prop_text)
            self.assertIn("spoofBuild=true", prop_text)
            auto_text = (work / "auto.out").read_text(encoding="utf-8")
            self.assertIn("# --- otast pif authority BEGIN ---", auto_text)
            self.assertIn("# --- otast pif final identity BEGIN ---", auto_text)
            self.assertIn("# --- otast pif output identity BEGIN ---", auto_text)
            self.assertIn("PRODUCT=$PRODUCT", auto_text)
            self.assertIn("DEVICE=$DEVICE", auto_text)
            ota_text = (work / "ota.out").read_text(encoding="utf-8")
            self.assertTrue(ota_text.startswith((FIXTURES / "pif-autopif-ota-ea93222c.sh").read_text(encoding="utf-8")))
            self.assertIn('sh "$OTAST_ENTRY" preflight', ota_text)
            security_text = (work / "security.out").read_text(encoding="utf-8")
            self.assertIn("# otast managed", security_text)
            self.assertIn("exit 0", security_text.splitlines()[:5])
            self.assertIn("Tricky Store Security Patch Util", security_text)

    def test_pif_preserve_mode_leaves_identity_and_booleans_unchanged(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        with tempfile.TemporaryDirectory(prefix="otast-pif-preserve-") as raw:
            work = Path(raw)
            prop = work / "pif.prop"
            prop.write_text(
                "FINGERPRINT=google/tegu_beta/tegu:CANARY/KEEP/1:user/release-keys\n"
                "MODEL=Pixel 9a\n"
                "SECURITY_PATCH=2026-08-05\n"
                "spoofBuild=true\n"
                "spoofProps=false\n"
                "spoofVendingSdk=false\n",
                encoding="utf-8",
            )
            command = f'''
                . "{pif_runtime}" || exit 1
                OTAST_FINGERPRINT='google/tegu/tegu:16/OTA/1:user/release-keys'
                OTAST_MANUFACTURER='Google'
                OTAST_MODEL='Pixel 9a'
                OTAST_SYSTEM_PATCH='2026-03-05'
                OTAST_DEVICE='tegu'
                OTAST_PIF_IDENTITY_POLICY='preserve'
                OTAST_PIF_SPOOF_BUILD='preserve'
                OTAST_PIF_SPOOF_PROPS='preserve'
                OTAST_PIF_SPOOF_PROVIDER='preserve'
                OTAST_PIF_SPOOF_SIGNATURE='preserve'
                OTAST_PIF_SPOOF_VENDING_BUILD='preserve'
                OTAST_PIF_SPOOF_VENDING_SDK='preserve'
                OTAST_PIF_DEBUG='preserve'
                otast_transform_pif_prop "{prop}" "{work / 'out'}" || exit 2
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            self.assertEqual((work / "out").read_text(encoding="utf-8"), prop.read_text(encoding="utf-8"))

    def test_current_pif_autopif_transform_preserves_authority_contract(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        fixture = FIXTURES / "pif-autopif-8b4a00ce.sh"
        with tempfile.TemporaryDirectory(prefix="otast-pif-current-test-") as raw:
            work = Path(raw)
            output = work / "autopif.out"
            command = f'''
                . "{pif_runtime}" || exit 1
                {self._pif_env("ota")}
                otast_transform_pif_autopif "{fixture}" "{output}" || exit 2
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            transformed = output.read_text(encoding="utf-8")
            self.assertIn("sort -ru | head -n1", transformed)
            self.assertNotIn("| grep 'qpr' |", transformed)
            self.assertIn("# --- otast pif authority BEGIN ---", transformed)
            self.assertIn("# --- otast pif final identity BEGIN ---", transformed)
            self.assertIn("# --- otast pif output identity BEGIN ---", transformed)
            self.assertIn("MODEL='Pixel 9a'", transformed)
            self.assertIn("PRODUCT='tegu_beta'", transformed)
            self.assertIn("DEVICE='tegu'", transformed)
            self.assertIn(
                "FINGERPRINT='google/tegu/tegu:16/TEST/1:user/release-keys'",
                transformed,
            )
            self.assertIn("PRODUCT=$PRODUCT", transformed)
            self.assertIn("DEVICE=$DEVICE", transformed)

    def test_ta_v44_transform_disables_only_vbmeta_block(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        ta_runtime = ROOT / "module/runtime/ta.sh"
        fixture = FIXTURES / "ta-utl-prop-v4.4.sh"
        with tempfile.TemporaryDirectory(prefix="otast-ta-test-") as raw:
            output = Path(raw) / "prop.out"
            command = f'. "{pif_runtime}"; . "{ta_runtime}"; otast_transform_ta_prop "{fixture}" "{output}"'
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            text = output.read_text(encoding="utf-8")
            self.assertIn("# --- otast vbmeta ownership BEGIN ---", text)
            self.assertNotIn('resetprop -n ro.boot.vbmeta.digest "$hash_value"', text)
            self.assertNotIn('empty_reset_prop "ro.boot.vbmeta.size"', text)
            self.assertIn('check_reset_prop "ro.boot.verifiedbootstate" "green"', text)
            self.assertIn('contains_reset_prop "ro.bootmode" "recovery" "unknown"', text)
            self.assertIn("resetprop -c || true", text)

    def test_yurikey_action_and_target_regenerator_are_neutralized(self) -> None:
        action = (ROOT / "module/runtime/templates/yurikey/action.sh").read_text(encoding="utf-8")
        target = (ROOT / "module/runtime/templates/yurikey/target_txt.sh").read_text(encoding="utf-8")
        self.assertIn('exec sh "$OTAST_ENTRY" report', action)
        self.assertNotIn("memory-type anonymous", action)
        self.assertNotIn("zygiskd", action)
        self.assertIn("target regeneration is disabled", target)
        self.assertNotIn("pm list packages", target)
        self.assertNotIn("rm -rf", target)

    def test_vbmeta_fixer_template_never_writes_runtime_properties(self) -> None:
        template = (ROOT / "module/runtime/templates/vbmeta-fixer/service.sh").read_text(encoding="utf-8")
        self.assertIn("exit 0", template)
        self.assertNotIn("resetprop", template)
        self.assertNotIn("blockdev", template)

    def test_runtime_does_not_use_awk(self) -> None:
        for path in (ROOT / "module/runtime").rglob("*.sh"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)(^|[;&|()]\s*)awk(?:\s|$)", path.relative_to(ROOT).as_posix())

    def test_all_monitor_heads_are_exact_commit_ids(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        for target_id, target in manifest["targets"].items():
            monitor = target.get("monitor")
            self.assertIsInstance(monitor, dict, target_id)
            self.assertRegex(monitor["expected_head"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
