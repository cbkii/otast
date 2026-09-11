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

    def test_resetprop_rebuild_writer_uses_v2_surgical_boundary(self) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        arch_runtime = ROOT / "module/runtime/architecture-v2.sh"
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
                    otast_stop() {{ printf '%s\\n' "$*" >&2; }}
                    otast_valid_date() {{ return 0; }}
                    . "{pif_runtime}" || exit 1
                    . "{arch_runtime}" || exit 2
                    otast_transform_pif_security_patch "{source}" "{first}" || exit 3
                    otast_transform_pif_security_patch "{first}" "{second}" || exit 4
                '''
                subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
                text = first.read_text(encoding="utf-8")

                self.assertIn("# --- otast pif patch-domain boundary BEGIN ---", text)
                self.assertIn("--enable", text)
                self.assertIn("--disable", text)
                self.assertIn('touch "$AUTO_FLAG"', text)
                self.assertIn('rm -f "$AUTO_FLAG"', text)
                self.assertNotIn("# otast managed: PIF auto-security-patch compatibility adapter", text)
                self.assertNotIn('> "$TARGET_FILE"', text)
                self.assertNotIn('> $TARGET_FILE', text)
                self.assertNotIn("cat << EOF > $MODDIR/system.prop", text)
                self.assertNotIn("resetprop -n", text)
                self.assertEqual(first.read_bytes(), second.read_bytes())

                if fixture_name.endswith("73552eec.sh"):
                    # The reviewed rebuild-capable source may change how PIF
                    # performs its own resetprop work, but v2 strips that entire
                    # cross-domain write block instead of short-circuiting the
                    # helper before the rest of its upstream control flow.
                    self.assertNotIn('grep -q "rebuild"', text)
                    self.assertNotIn('resetprop -n "$PROP" "$SECURITY_PATCH"', text)


if __name__ == "__main__":
    unittest.main()
