from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
ACTION_SHA = re.compile(r"^\s*uses:\s+[^@\s]+@([0-9a-f]{40})(?:\s+#.*)?$")


class WorkflowHardeningTests(unittest.TestCase):
    def test_all_external_actions_are_pinned_to_commit_sha(self) -> None:
        seen = 0
        failures: list[str] = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if not stripped.startswith("uses:"):
                    continue
                seen += 1
                if ACTION_SHA.fullmatch(line) is None:
                    failures.append(f"{workflow.name}:{number}: {stripped}")
        self.assertGreater(seen, 0)
        self.assertEqual(failures, [], "floating GitHub Actions references:\n" + "\n".join(failures))

    def test_dependabot_maintains_github_actions_pins(self) -> None:
        dependabot = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        self.assertIn('package-ecosystem: "github-actions"', dependabot)
        self.assertIn("interval: weekly", dependabot)

    def test_release_runs_fresh_monitor_before_any_release_mutation(self) -> None:
        release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        monitor = release.index("- name: Fresh compatibility target monitor")
        stamp = release.index("- name: Stamp candidate metadata")
        persist = release.index("- name: Persist version bump to main")
        draft = release.index("- name: Create hosted draft")
        self.assertLess(monitor, stamp)
        self.assertLess(monitor, persist)
        self.assertLess(monitor, draft)
        self.assertIn("scripts/otast-maintenance.py monitor", release)
        self.assertIn("Upload target-monitor evidence", release)

    def test_stable_release_cannot_bypass_full_validation_or_physical_proof(self) -> None:
        release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        self.assertIn(
            "inputs.full_validation || steps.version.outputs.prerelease != 'true'",
            release,
        )
        self.assertIn(
            "$has_proof != true && ($PRERELEASE != true || $REQUIRE_PROOF == true)",
            release,
        )
        self.assertIn("stable is always required", release)

    def test_target_monitor_runs_daily(self) -> None:
        monitor = (WORKFLOWS / "target-monitor.yml").read_text(encoding="utf-8")
        self.assertRegex(monitor, r"(?m)^\s*- cron:\s*['\"]?[^\n]+['\"]?$")


if __name__ == "__main__":
    unittest.main()
