from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "module/action.sh"


class ActionMenuTests(unittest.TestCase):
    def setUp(self) -> None:
        self.action_text = ACTION.read_text(encoding="utf-8")

    def _run_action(self, action: str | None) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir) / "module"
            runtime_dir = module_dir / "runtime"
            runtime_dir.mkdir(parents=True)
            action_path = module_dir / "action.sh"
            action_path.write_text(
                self.action_text.replace(
                    "if [ -x /system/bin/getevent ] && [ -x /system/bin/timeout ]; then",
                    "if false; then",
                ),
                encoding="utf-8",
            )
            entry_path = runtime_dir / "entry.sh"
            entry_path.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$1\" > \"$OTAST_TEST_OUTPUT\"\n",
                encoding="utf-8",
            )
            output_path = Path(temp_dir) / "selected.txt"
            env = os.environ.copy()
            env["OTAST_TEST_OUTPUT"] = str(output_path)
            if action is None:
                env.pop("OTAST_ACTION", None)
            else:
                env["OTAST_ACTION"] = action

            result = subprocess.run(
                ["sh", str(action_path)],
                text=True,
                capture_output=True,
                env=env,
                timeout=5,
                check=False,
            )
            selected = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
            return result, selected

    def _parse_events(self, events: str) -> subprocess.CompletedProcess[str]:
        prefix = self.action_text.split("\nchoice=${OTAST_ACTION:-}", 1)[0]
        harness = prefix + "\notast_key_from_events \"$OTAST_TEST_EVENTS\"\n"
        env = os.environ.copy()
        env["OTAST_TEST_EVENTS"] = events
        return subprocess.run(
            ["sh"],
            input=harness,
            text=True,
            capture_output=True,
            env=env,
            timeout=5,
            check=False,
        )

    def test_action_menu_uses_bounded_volume_events_instead_of_tty(self) -> None:
        self.assertNotIn("/dev/tty", self.action_text)
        self.assertIn("/system/bin/timeout 1 /system/bin/getevent -ql", self.action_text)
        self.assertNotRegex(self.action_text, r"getevent[^\n]*-c\s*1")
        self.assertIn("*KEY_VOLUMEUP*DOWN*", self.action_text)
        self.assertIn("*KEY_VOLUMEDOWN*DOWN*", self.action_text)
        self.assertIn("windows=30", self.action_text)
        self.assertIn("Vol+ = next, Vol- = select", self.action_text)

    def test_event_parser_ignores_non_volume_and_key_release_events(self) -> None:
        up = self._parse_events(
            "/dev/input/event0: EV_SYN SYN_REPORT 00000000\n"
            "/dev/input/event3: EV_KEY KEY_VOLUMEUP DOWN\n"
            "/dev/input/event3: EV_KEY KEY_VOLUMEUP UP"
        )
        self.assertEqual(up.returncode, 0, up.stderr)
        self.assertEqual(up.stdout.strip(), "up")

        down = self._parse_events(
            "/dev/input/event0: EV_ABS ABS_MT_POSITION_X 00000123\n"
            "/dev/input/event3: EV_KEY KEY_VOLUMEDOWN DOWN\n"
            "/dev/input/event3: EV_KEY KEY_VOLUMEDOWN UP"
        )
        self.assertEqual(down.returncode, 0, down.stderr)
        self.assertEqual(down.stdout.strip(), "down")

        release_only = self._parse_events(
            "/dev/input/event3: EV_KEY KEY_VOLUMEUP UP\n"
            "/dev/input/event0: EV_SYN SYN_REPORT 00000000"
        )
        self.assertNotEqual(release_only.returncode, 0)
        self.assertEqual(release_only.stdout, "")

    def test_noninteractive_action_override_keeps_all_runtime_mappings(self) -> None:
        expected = {
            "1": "report",
            "report": "report",
            "status": "report",
            "2": "preflight",
            "preflight": "preflight",
            "3": "verify",
            "verify": "verify",
            "4": "apply",
            "apply": "apply",
            "5": "restore",
            "restore": "restore",
        }
        for action, selected in expected.items():
            with self.subTest(action=action):
                result, actual = self._run_action(action)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(actual, selected)

    def test_missing_android_input_tools_fails_safe_to_report(self) -> None:
        # Host CI has no Android /system/bin/getevent. That exercises the same
        # safe fallback used on-device if the input tooling is unexpectedly absent.
        result, selected = self._run_action(None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(selected, "report")
        self.assertIn("defaulting to read-only Report", result.stderr)

    def test_invalid_explicit_action_is_rejected(self) -> None:
        result, selected = self._run_action("definitely-invalid")
        self.assertEqual(result.returncode, 64)
        self.assertEqual(selected, "")
        self.assertIn("Invalid OTAST action", result.stderr)


if __name__ == "__main__":
    unittest.main()
