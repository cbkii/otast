from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


class ReleaseWorkflowSurfaceTests(unittest.TestCase):
    def test_release_readiness_workflow_is_removed(self) -> None:
        self.assertFalse((WORKFLOWS / "release-readiness.yml").exists())

    def test_release_yml_is_the_only_release_named_workflow(self) -> None:
        release_named = sorted(path.name for path in WORKFLOWS.glob("*release*.yml"))
        self.assertEqual(release_named, ["release.yml"])


if __name__ == "__main__":
    unittest.main()
