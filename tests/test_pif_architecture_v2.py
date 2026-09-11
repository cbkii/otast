from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/upstream"
PIF = ROOT / "module/runtime/pif.sh"
ARCH = ROOT / "module/runtime/architecture-v2.sh"


class PifArchitectureV2Tests(unittest.TestCase):
    def _transform(self, fixture_name: str) -> tuple[bytes, str]:
        with tempfile.TemporaryDirectory(prefix="otast-pif-v2-") as raw:
            work = Path(raw)
            source = FIXTURES / fixture_name
            first = work / "first.sh"
            second = work / "second.sh"
            command = f'''
                otast_stop() {{ printf '%s\\n' "$*" >&2; }}
                otast_valid_date() {{ return 0; }}
                . "{PIF}" || exit 1
                . "{ARCH}" || exit 2
                otast_transform_pif_security_patch "{source}" "{first}" || exit 3
                otast_transform_pif_security_patch "{first}" "{second}" || exit 4
                busybox sh -n "{first}" || exit 5
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            return first.read_bytes(), first.read_text(encoding="utf-8")

    def test_legacy_compact_writer_is_surgically_bounded(self) -> None:
        _, text = self._transform("pif-security-patch-ea93222c.sh")
        self.assertIn("# --- otast pif patch-domain boundary BEGIN ---", text)
        self.assertIn('touch "$AUTO_FLAG"', text)
        self.assertIn('rm -f "$AUTO_FLAG"', text)
        self.assertNotIn('> "$TARGET_FILE"', text)
        self.assertNotIn('> $TARGET_FILE', text)
        self.assertNotIn("cat << EOF > $MODDIR/system.prop", text)
        self.assertNotIn("resetprop -n", text)

    def test_planner_never_manages_autopif_executables(self) -> None:
        text = ARCH.read_text(encoding="utf-8")
        planner = text.split("otast_plan_pif()", 1)[1].split("otast_plan_strict_runtime_identity()", 1)[0]
        self.assertNotIn("autopif.sh", planner)
        self.assertNotIn("autopif_ota.sh", planner)
        self.assertIn("security_patch.sh", planner)


if __name__ == "__main__":
    unittest.main()
