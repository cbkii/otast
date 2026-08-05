from __future__ import annotations

import json
import re
import stat
import unittest
from pathlib import Path

from tools.otastctl.build import ENTRYPOINTS, module_metadata
from tools.otastctl.privacy import scan_repository

ROOT = Path(__file__).resolve().parents[1]


class PublicRepositoryContractTests(unittest.TestCase):
    def test_identity_and_update_channel_are_coherent(self) -> None:
        metadata = module_metadata(ROOT / "module/module.prop")
        update = json.loads((ROOT / "update.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["id"], "otast")
        self.assertEqual(update["version"], metadata["version"])
        self.assertEqual(update["versionCode"], int(metadata["versionCode"]))
        self.assertIn("cbkii/otast", metadata["updateJson"])
        self.assertIn("cbkii/otast", update["zipUrl"])
        legacy_name = "ota" + "sst"
        self.assertNotIn(legacy_name, "\n".join((metadata["updateJson"], update["zipUrl"])))

    def test_no_local_source_dependency_or_legacy_release_identity(self) -> None:
        findings = scan_repository(ROOT)
        self.assertFalse([item for item in findings if item.startswith("termux-home:")])
        metadata_text = "\n".join(
            (
                (ROOT / "module/module.prop").read_text(encoding="utf-8"),
                (ROOT / "update.json").read_text(encoding="utf-8"),
            )
        )
        self.assertNotRegex(metadata_text, r"(?i)\botasst\b|\bota-sot\b")
        self.assertNotIn("$HOME/repos/", metadata_text)

    def test_source_modes_match_roles(self) -> None:
        for relative in ENTRYPOINTS:
            mode = (ROOT / "module" / relative).stat().st_mode & 0o777
            self.assertEqual(mode, 0o755, relative)
        for relative in (
            "module/runtime/common.sh",
            "module/runtime/authority.sh",
            "module/runtime/transaction.sh",
            "module/runtime/pif.sh",
            "module/runtime/ta.sh",
            "module/runtime/profiles.sh",
            "module/runtime/report.sh",
        ):
            self.assertEqual((ROOT / relative).stat().st_mode & 0o777, 0o644, relative)
        for path in (ROOT / "scripts").rglob("*.sh"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o755, path.relative_to(ROOT).as_posix())

        for relative in (
            "scripts/otast-maintenance.py",
            "scripts/otast_safety_guard.py",
            "scripts/upstream-target-package.py",
        ):
            self.assertEqual((ROOT / relative).stat().st_mode & 0o777, 0o755, relative)

    def test_capture_allowlist_is_narrow(self) -> None:
        capture = (ROOT / "scripts/capture-device-fixture.sh").read_text(encoding="utf-8")
        allowed_modules = {
            "playintegrityfix",
            "tricky_store",
            "Yurikey",
            "TA_utl",
            ".TA_utl",
            "vbmeta-fixer",
        }
        captured = set(re.findall(r"^data/adb/modules(?:_update)?/([^/\n]+)$", capture, re.MULTILINE))
        self.assertEqual(captured, allowed_modules)
        for forbidden in ("AshLooper", "AshReXcue", "BetterKnownInstalled", "BKI"):
            self.assertNotIn(f"data/adb/modules/{forbidden}", capture)
        for key in (
            "ro.boot.vbmeta.digest",
            "ro.boot.vbmeta.size",
            "ro.boot.vbmeta.avb_version",
            "ro.boot.avb_version",
        ):
            self.assertIn(key, capture)
        self.assertIn("legacy ota-sot/otasst governor traces remain", capture)
        self.assertIn("/data/adb/post-fs-data.d/000-$legacy_otasst.sh", capture)

    def test_release_workflow_uses_static_valid_permissions_and_exact_target(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertNotIn("contents: ${{", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn('--target "$GITHUB_SHA"', workflow)
        self.assertIn('[[ "$GITHUB_ACTOR" == "$GITHUB_REPOSITORY_OWNER" ]]', workflow)

    def test_source_tree_has_no_symlinks_or_unsafe_git_path(self) -> None:
        git_path = ROOT / ".git"
        self.assertFalse(git_path.is_symlink())
        if git_path.exists():
            self.assertTrue(git_path.is_dir())
        self.assertEqual([path for path in ROOT.rglob("*") if path.is_symlink()], [])


if __name__ == "__main__":
    unittest.main()
