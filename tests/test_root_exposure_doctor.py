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

    def test_mountinfo_is_bounded_and_redacts_target_package(self) -> None:
        raw = (
            "11 10 0:1 / / rw - rootfs rootfs rw\n"
            "12 10 0:2 /data/adb/modules/foo /data/user/0/com.example.detector/cache rw - tmpfs tmpfs rw\n"
        )
        count, evidence = DOCTOR.parse_mountinfo(raw, "com.example.detector")
        self.assertEqual(count, 2)
        self.assertEqual(len(evidence), 1)
        self.assertNotIn("com.example.detector", evidence[0])
        self.assertIn("/data/user/<user>/<app>", evidence[0])

    def test_classification_attributes_module_mapping_without_calling_it_otast(self) -> None:
        processes = [
            {
                "executable_root_mappings": [
                    {
                        "path": "/data/adb/modules/vector/lib.so",
                        "module_id": "vector",
                    }
                ],
                "selected_mountinfo": [],
            }
        ]
        findings = DOCTOR.classify_findings(
            processes,
            {"mode": "Enforcing"},
            {"status": "PASS"},
            "unknown",
        )
        self.assertEqual(findings[0]["category"], "another reviewed module's exposure")
        self.assertEqual(findings[0]["module_id"], "vector")

    def test_detector_mount_headline_can_be_marked_inconsistent(self) -> None:
        findings = DOCTOR.classify_findings(
            [{"executable_root_mappings": [], "selected_mountinfo": []}],
            {"mode": "Enforcing"},
            {"status": "PASS"},
            "suspicious",
        )
        self.assertTrue(any(item["category"] == "detector/report inconsistency" for item in findings))

    def test_otast_report_failure_is_the_only_otast_semantic_signal(self) -> None:
        findings = DOCTOR.classify_findings(
            [{"executable_root_mappings": [], "selected_mountinfo": []}],
            {"mode": "Enforcing"},
            {"status": "FAIL", "returncode": 1},
            "unknown",
        )
        self.assertTrue(
            any(
                item["category"] == "OTAST-owned semantic inconsistency"
                and item["finding"] == "OTAST read-only Report returned non-zero"
                for item in findings
            )
        )

    def test_sensitive_keybox_paths_are_explicitly_refused(self) -> None:
        with self.assertRaises(DOCTOR.DoctorError):
            DOCTOR.safe_root_read("/data/adb/tricky_store/keybox.xml")

    def test_script_has_no_automatic_mutation_commands(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "resetprop -n",
            "resetprop --delete",
            "rm -rf /data",
            "magisk --denylist add",
            "magisk --denylist rm",
            "chmod 000 /data",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
