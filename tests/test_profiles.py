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
            ("ta-utl", "webui/assets/boot_hash-C0kIcwCH.js", "ta-utl-boot-hash-v4.4.js"),
        )
        for target, name, fixture_name in checks:
            digest = hashlib.sha256((FIXTURES / fixture_name).read_bytes()).hexdigest()
            self.assertIn(digest, manifest["targets"][target]["accepted_hashes"][name])

    def test_pif_autopif_transform_preserves_profile_refresh_and_removes_competing_tail(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        for fixture_name in ("pif-autopif-ea93222c.sh", "pif-autopif-8b4a00ce.sh"):
            with self.subTest(fixture=fixture_name), tempfile.TemporaryDirectory(prefix="otast-pif-auto-") as raw:
                work = Path(raw)
                source = FIXTURES / fixture_name
                first = work / "first.sh"
                second = work / "second.sh"
                command = f'''
                    . "{pif_runtime}" || exit 1
                    otast_transform_pif_autopif "{source}" "{first}" || exit 2
                    otast_transform_pif_autopif "{first}" "{second}" || exit 3
                '''
                subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
                text = first.read_text(encoding="utf-8")
                self.assertIn("# --- otast pif refresh authority BEGIN ---", text)
                self.assertIn("cat <<EOF | tee pif.prop", text)
                self.assertIn('cat "$TEMPDIR/pif.prop" > /data/adb/pif.prop', text)
                self.assertIn('sh "$MODDIR/security_patch.sh"', text)
                self.assertNotIn("rm -f $MODDIR/system.prop", text)
                self.assertNotIn("# --- otast pif final identity BEGIN ---", text)
                self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_pif_autopif_ota_transform_gates_moving_executable_update_before_body(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        fixture = FIXTURES / "pif-autopif-ota-ea93222c.sh"
        with tempfile.TemporaryDirectory(prefix="otast-pif-ota-") as raw:
            work = Path(raw)
            first = work / "first.sh"
            second = work / "second.sh"
            command = f'''
                . "{pif_runtime}" || exit 1
                otast_transform_pif_ota "{fixture}" "{first}" || exit 2
                otast_transform_pif_ota "{first}" "{second}" || exit 3
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            lines = first.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[1], "# otast managed: AutoPIF executable self-update gate")
            self.assertEqual(lines[4], "exit 0")
            self.assertIn("fetch_autopif", first.read_text(encoding="utf-8"))
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_pif_security_patch_adapter_preserves_marker_controls_without_profile_spl_writes(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        fixture = FIXTURES / "pif-security-patch-ea93222c.sh"
        with tempfile.TemporaryDirectory(prefix="otast-pif-security-") as raw:
            work = Path(raw)
            first = work / "first.sh"
            second = work / "second.sh"
            command = f'''
                . "{pif_runtime}" || exit 1
                otast_transform_pif_security_patch "{fixture}" "{first}" || exit 2
                otast_transform_pif_security_patch "{first}" "{second}" || exit 3
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            text = first.read_text(encoding="utf-8")
            self.assertIn("# otast managed: PIF auto-security-patch compatibility adapter", text)
            self.assertIn("--enable", text)
            self.assertIn("--disable", text)
            self.assertIn('touch "$AUTO_FLAG"', text)
            self.assertIn('rm -f "$AUTO_FLAG"', text)
            self.assertNotIn('rm -f "$AUTO_FLAG" "$MODDIR/system.prop"', "\n".join(text.splitlines()[:35]))
            self.assertNotIn("resetprop -n", "\n".join(text.splitlines()[:35]))
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_pif_profile_validator_accepts_distinct_valid_profiles_and_rejects_duplicate_keys(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        with tempfile.TemporaryDirectory(prefix="otast-pif-validator-") as raw:
            work = Path(raw)
            valid = work / "valid.prop"
            duplicate = work / "duplicate.prop"
            valid.write_text(
                "FINGERPRINT=google/tegu_beta/tegu:CANARY/KEEP/1:user/release-keys\n"
                "MODEL=Pixel 9a\nSECURITY_PATCH=2026-08-05\nspoofBuild=true\nspoofProps=false\n",
                encoding="utf-8",
            )
            duplicate.write_text(
                "FINGERPRINT=a\nFINGERPRINT=b\nSECURITY_PATCH=2026-08-05\n",
                encoding="utf-8",
            )
            command = f'''
                otast_stop() {{ printf '%s\\n' "$*" >&2; }}
                otast_valid_date() {{
                  case "$1" in [0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]) return 0;; *) return 1;; esac
                }}
                . "{pif_runtime}" || exit 1
                otast_validate_pif_profile_file "{valid}" || exit 2
                if otast_validate_pif_profile_file "{duplicate}"; then exit 3; fi
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)

    def test_pif_manifest_models_profile_data_as_observed_not_managed(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        pif = manifest["targets"]["playintegrityfix"]
        self.assertNotIn("pif.prop", pif["managed_paths"])
        self.assertIn("pif.prop", pif["observed_paths"])
        self.assertIn("PIF_OWNED_MUTABLE_CONFIGURATION", pif["profile_ownership"])

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

    def test_ta_v44_webui_boot_hash_save_is_read_only_and_idempotent(self) -> None:
        ta_runtime = ROOT / "module/runtime/ta.sh"
        fixture = FIXTURES / "ta-utl-boot-hash-v4.4.js"
        with tempfile.TemporaryDirectory(prefix="otast-ta-webui-test-") as raw:
            work = Path(raw)
            first = work / "boot-hash.first.js"
            second = work / "boot-hash.second.js"
            command = f'''
                . "{ta_runtime}" || exit 1
                otast_transform_ta_webui_boot_hash "{fixture}" "{first}" || exit 2
                otast_transform_ta_webui_boot_hash "{first}" "{second}" || exit 3
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            text = first.read_text(encoding="utf-8")
            self.assertIn("OTAST owns boot_hash and ro.boot.vbmeta.digest", text)
            self.assertIn("a.disabled=!0;window.trimInput=", text)
            self.assertIn("sed '/[^#]/d; /^$/d' /data/adb/boot_hash", text)
            self.assertNotIn("resetprop -n ro.boot.vbmeta.digest", text)
            self.assertNotIn("resetprop -c || true", text)
            self.assertNotIn("rm -f /data/adb/boot_hash", text)
            self.assertNotIn("> /data/adb/boot_hash", text)
            self.assertNotIn("chmod 644 /data/adb/boot_hash", text)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_ta_webui_plan_is_exact_hash_managed_for_both_aliases(self) -> None:
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        expected = "bedb09d2538e28d636ea592a58d2a2234849351d49a95175d54c4de7ccf4d5cc"
        self.assertIn("for id in TA_utl .TA_utl", profiles)
        self.assertIn('"$dir/webui/assets/boot_hash-C0kIcwCH.js" 0644', profiles)
        self.assertIn("otast_transform_ta_webui_boot_hash", profiles)
        self.assertIn("required reviewed TA UTL WebUI boot-hash asset is missing or ambiguous", profiles)
        self.assertIn("unreviewed TA UTL WebUI boot-hash asset", profiles)
        self.assertIn(expected, profiles)
        self.assertEqual(
            manifest["targets"]["ta-utl"]["accepted_hashes"]["webui/assets/boot_hash-C0kIcwCH.js"],
            [expected],
        )

    def test_yurikey_action_target_and_keybox_writers_are_neutralized(self) -> None:
        action = (ROOT / "module/runtime/templates/yurikey/action.sh").read_text(encoding="utf-8")
        target = (ROOT / "module/runtime/templates/yurikey/target_txt.sh").read_text(encoding="utf-8")
        keybox = (ROOT / "module/runtime/templates/yurikey/keybox.sh").read_text(encoding="utf-8")
        self.assertIn('exec sh "$OTAST_ENTRY" report', action)
        self.assertNotIn("memory-type anonymous", action)
        self.assertNotIn("zygiskd", action)
        self.assertIn("target regeneration is disabled", target)
        self.assertNotIn("pm list packages", target)
        self.assertIn("automatic keybox replacement is disabled", keybox)
        self.assertNotIn("curl", keybox)
        self.assertNotIn("wget", keybox)
        self.assertNotIn("base64", keybox)

    def test_vbmeta_fixer_template_never_writes_runtime_properties(self) -> None:
        template = (ROOT / "module/runtime/templates/vbmeta-fixer/service.sh").read_text(encoding="utf-8")
        self.assertIn("exit 0", template)
        self.assertNotIn("resetprop", template)
        self.assertNotIn("blockdev", template)

    def test_identity_runtime_paths_do_not_use_awk(self) -> None:
        for relative in (
            "authority.sh",
            "entry.sh",
            "pif.sh",
            "policy.sh",
            "profiles.sh",
            "report.sh",
            "ta.sh",
            "trickystore.sh",
        ):
            path = ROOT / "module/runtime" / relative
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)(^|[;&|()]\s*)awk(?:\s|$)", relative)

    def test_all_monitor_heads_are_exact_commit_ids(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        for target_id, target in manifest["targets"].items():
            monitor = target.get("monitor")
            self.assertIsInstance(monitor, dict, target_id)
            self.assertRegex(monitor["expected_head"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
