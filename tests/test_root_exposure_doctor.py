from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/root-exposure-doctor.py"
SPEC = importlib.util.spec_from_file_location("otast_root_exposure_doctor", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
DOCTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DOCTOR
SPEC.loader.exec_module(DOCTOR)


class RootExposureDoctorTests(unittest.TestCase):
    def test_maps_only_reports_executable_root_stack_mappings(self) -> None:
        raw = "\n".join(
            (
                "1000-2000 r--p 00000000 00:00 0 /data/adb/modules/ignored/read-only.bin",
                "2000-3000 r-xp 00000000 00:00 0 /data/adb/modules/inline_hook_invalidate/lib64/libhook.so",
                "3000-4000 r-xp 00000000 00:00 0 /data/adb/zygisk/zygisk64.so",
                "4000-5000 r-xp 00000000 00:00 0 /data/user/0/com.example.detector/lib/normal.so",
            )
        )
        count, evidence, module_ids = DOCTOR.parse_maps(raw, "com.example.detector")
        self.assertEqual(count, 4)
        self.assertEqual(module_ids, {"inline_hook_invalidate"})
        paths = [item["path"] for item in evidence]
        self.assertIn("/data/adb/modules/inline_hook_invalidate/lib64/libhook.so", paths)
        self.assertIn("/data/adb/zygisk/zygisk64.so", paths)
        self.assertFalse(any("read-only.bin" in path for path in paths))
        self.assertFalse(any("com.example.detector" in path for path in paths))

    def test_mount_snapshot_retains_exact_bounded_lines_and_tokens(self) -> None:
        raw = (
            "tmpfs /data/adb/modules/foo tmpfs rw,seclabel 0 0\n"
            "/dev/block/dm-0 /system ext4 ro,seclabel 0 0\n"
        )
        count, lines, matches = DOCTOR.parse_mount_table(raw, "com.example.detector", "mounts")
        self.assertEqual(count, 2)
        self.assertEqual(lines[1], "/dev/block/dm-0 /system ext4 ro,seclabel 0 0")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["source"], "mounts")
        self.assertIn("/data/adb/", matches[0]["tokens"])
        self.assertIn("/modules/", matches[0]["tokens"])

    def test_policy_matcher_handles_exact_and_wildcard_rules(self) -> None:
        edges = {edge["id"]: edge for edge in DOCTOR.POLICY_EDGES}
        self.assertTrue(
            DOCTOR.match_policy_line(
                "allow zygote adb_data_file dir search",
                edges["zygote_adb_data_file_search"],
            )
        )
        self.assertTrue(
            DOCTOR.match_policy_line(
                "allow * xposed_data {file dir} *",
                edges["untrusted_app_xposed_data_read"],
            )
        )
        self.assertFalse(
            DOCTOR.match_policy_line(
                "allow untrusted_app xposed_data dir search",
                edges["untrusted_app_xposed_data_read"],
            )
        )

    def test_classification_attributes_module_mapping_without_calling_it_otast(self) -> None:
        processes = [
            {
                "executable_root_mappings": [
                    {
                        "path": "/data/adb/modules/vector/lib.so",
                        "module_id": "vector",
                    }
                ],
                "mount_token_matches": [],
                "mountinfo_token_matches": [],
            }
        ]
        findings = DOCTOR.classify_findings(
            processes,
            {"mode": "Enforcing"},
            {"status": "PASS"},
            "unknown",
            {"status": "UNAVAILABLE"},
            {"status": "UNAVAILABLE"},
        )
        self.assertEqual(findings[0]["category"], "another reviewed module's exposure")
        self.assertEqual(findings[0]["module_id"], "vector")

    def test_detector_mount_headline_can_be_marked_inconsistent(self) -> None:
        findings = DOCTOR.classify_findings(
            [{"executable_root_mappings": [], "mount_token_matches": [], "mountinfo_token_matches": []}],
            {"mode": "Enforcing"},
            {"status": "PASS"},
            "suspicious",
            {"status": "UNAVAILABLE"},
            {"status": "UNAVAILABLE"},
        )
        self.assertTrue(any(item["category"] == "detector/report inconsistency" for item in findings))

    def test_otast_report_timeout_is_coverage_limitation_not_semantic_failure(self) -> None:
        findings = DOCTOR.classify_findings(
            [{"executable_root_mappings": [], "mount_token_matches": [], "mountinfo_token_matches": []}],
            {"mode": "Enforcing"},
            {"status": "TIMEOUT"},
            "unknown",
            {"status": "UNAVAILABLE"},
            {"status": "UNAVAILABLE"},
        )
        self.assertTrue(
            any(
                item["category"] == "diagnostic coverage limitation"
                and "timed out" in item["finding"]
                for item in findings
            )
        )
        self.assertFalse(any(item["category"] == "OTAST-owned semantic inconsistency" for item in findings))

    def test_subprocess_timeout_is_contained_as_result(self) -> None:
        result = DOCTOR.run_command(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout=1,
            max_output=1024,
        )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, 124)

    def test_ihe_non_target_mapping_is_explicitly_explained(self) -> None:
        findings = DOCTOR.classify_findings(
            [
                {
                    "executable_root_mappings": [
                        {
                            "path": "/data/adb/modules/inline_hook_invalidate/zygisk/arm64-v8a.so",
                            "module_id": "inline_hook_invalidate",
                        }
                    ],
                    "mount_token_matches": [],
                    "mountinfo_token_matches": [],
                }
            ],
            {"mode": "Enforcing"},
            {"status": "PASS"},
            "unknown",
            {"status": "AVAILABLE", "target_package_present": False},
            {"status": "UNAVAILABLE"},
        )
        self.assertTrue(any("Inline Hook Invalidate" in item["finding"] for item in findings))

    def test_sensitive_keybox_paths_are_explicitly_refused_without_root_probe(self) -> None:
        DOCTOR.ROOT = None
        with self.assertRaises(DOCTOR.DoctorError):
            DOCTOR.safe_root_read("/data/adb/tricky_store/keybox.xml")
        self.assertIsNone(DOCTOR.ROOT)

    def test_script_has_no_automatic_mutation_commands(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "resetprop -n",
            "resetprop --delete",
            "magisk --denylist add",
            "magisk --denylist rm",
            "zygiskd enforce-denylist",
            "chmod 000 /data",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
