from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/release-device.sh"


def extract_gh_shim() -> str:
    text = WRAPPER.read_text(encoding="utf-8")
    begin = 'cat >"$SHIM_DIR/gh" <<\'SHIM\'\n'
    start = text.index(begin) + len(begin)
    end = text.index("\nSHIM\n", start)
    return text[start:end] + "\n"


class ReleaseGhShimTests(unittest.TestCase):
    def run_delete(self, mode: str, *, timeout_seconds: int = 90) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="otast-release-gh-shim-") as raw:
            root = Path(raw)
            shim = root / "gh"
            shim.write_text(extract_gh_shim(), encoding="utf-8")
            shim.chmod(0o755)

            marker = root / "release-exists"
            marker.write_text("1\n", encoding="utf-8")
            real = root / "real-gh"
            real.write_text(
                "#!/usr/bin/env bash\n"
                "marker=${FAKE_RELEASE_MARKER:?}\n"
                "mode=${FAKE_DELETE_MODE:?}\n"
                "if [[ ${1:-} == release && ${2:-} == delete ]]; then\n"
                "  case $mode in\n"
                "    success) rm -f -- \"$marker\"; exit 0 ;;\n"
                "    partial) rm -f -- \"$marker\"; exit 1 ;;\n"
                "    failure) exit 1 ;;\n"
                "    hang) sleep 30; exit 0 ;;\n"
                "  esac\n"
                "fi\n"
                "if [[ ${1:-} == release && ${2:-} == view ]]; then\n"
                "  [[ -f $marker ]]\n"
                "  exit $?\n"
                "fi\n"
                "exit 99\n",
                encoding="utf-8",
            )
            real.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "OTAST_REAL_GH": str(real),
                    "OTAST_SHIM_STATE": str(root / "operation"),
                    "OTAST_GH_TIMEOUT_SECONDS": str(timeout_seconds),
                    "FAKE_RELEASE_MARKER": str(marker),
                    "FAKE_DELETE_MODE": mode,
                }
            )
            return subprocess.run(
                [
                    str(shim),
                    "release",
                    "delete",
                    "v1.0.3",
                    "-R",
                    "cbkii/otast",
                    "--cleanup-tag",
                    "--yes",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=10,
                check=False,
            )

    def test_partial_success_is_normalized_when_release_is_gone(self) -> None:
        result = self.run_delete("partial")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_delete_failure_is_preserved_when_release_still_exists(self) -> None:
        result = self.run_delete("failure")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_normal_delete_success_remains_success(self) -> None:
        result = self.run_delete("success")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stalled_github_command_is_bounded(self) -> None:
        result = self.run_delete("hang", timeout_seconds=1)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("timed out after 1s", result.stderr)


if __name__ == "__main__":
    unittest.main()
