from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/upstream"
NEW_FIXTURE = FIXTURES / "pif-security-patch-73552eec.sh"
NEW_SHA256 = "f24517231c21856c4603f14e9d1ad8d38af5e6753a8060837320e66337ed5012"
NEW_HEAD = "73552eec78f1e733573192333e9a7453b8de0662"


class PifResetpropRebuildCompatibilityTests(unittest.TestCase):
    def test_reviewed_resetprop_rebuild_writer_is_bound_to_exact_source(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        pif = manifest["targets"]["playintegrityfix"]

        self.assertEqual(hashlib.sha256(NEW_FIXTURE.read_bytes()).hexdigest(), NEW_SHA256)
        self.assertIn(NEW_SHA256, pif["accepted_hashes"]["security_patch.sh"])
        self.assertEqual(pif["monitor"]["expected_head"], NEW_HEAD)
        self.assertEqual(pif["distribution_identity"]["reviewed_commit"], NEW_HEAD)

    def test_resetprop_rebuild_body_remains_unreachable_after_otast_adapter(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        for fixture_name in (
            "pif-security-patch-ea93222c.sh",
            "pif-security-patch-73552eec.sh",
        ):
            with self.subTest(fixture=fixture_name), tempfile.TemporaryDirectory(prefix="otast-pif-security-") as raw:
                work = Path(raw)
                source = FIXTURES / fixture_name
                first = work / "first.sh"
                second = work / "second.sh"
                command = f'''
                    . "{pif_runtime}" || exit 1
                    otast_transform_pif_security_patch "{source}" "{first}" || exit 2
                    otast_transform_pif_security_patch "{first}" "{second}" || exit 3
                '''
                subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
                text = first.read_text(encoding="utf-8")
                active_prefix = "\n".join(text.splitlines()[:35])

                self.assertIn("# otast managed: PIF auto-security-patch compatibility adapter", text)
                self.assertIn("--enable", active_prefix)
                self.assertIn("--disable", active_prefix)
                self.assertIn('touch "$AUTO_FLAG"', active_prefix)
                self.assertIn('rm -f "$AUTO_FLAG"', active_prefix)
                self.assertNotIn('rm -f "$AUTO_FLAG" "$MODDIR/system.prop"', active_prefix)
                self.assertNotIn("resetprop -n", active_prefix)
                self.assertEqual(first.read_bytes(), second.read_bytes())

                if fixture_name.endswith("73552eec.sh"):
                    self.assertIn('grep -q "rebuild"', text)
                    self.assertIn('resetprop -n "$PROP" "$SECURITY_PATCH"', text)
                    self.assertLess(text.index("exit 0"), text.index('grep -q "rebuild"'))


if __name__ == "__main__":
    unittest.main()
