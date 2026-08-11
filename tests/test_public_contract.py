from __future__ import annotations

import re
import stat
import unittest
from pathlib import Path

from tools.otastctl.build import ENTRYPOINTS, module_metadata
from tools.otastctl.privacy import scan_repository
from tools.otastctl.release import UPDATE_JSON_URL, load_update_metadata

ROOT = Path(__file__).resolve().parents[1]


class PublicRepositoryContractTests(unittest.TestCase):
    def test_identity_and_update_channel_are_coherent(self) -> None:
        metadata = module_metadata(ROOT / "module/module.prop")
        update = load_update_metadata(ROOT / "update.json")
        self.assertEqual(metadata["id"], "otast")
        self.assertEqual(metadata["updateJson"], UPDATE_JSON_URL)
        self.assertGreaterEqual(int(metadata["versionCode"]), int(update["versionCode"]))
        self.assertIn("cbkii/otast", update["zipUrl"])
        legacy_name = "ota" + "sst"
        self.assertNotIn(legacy_name, "\n".join((metadata["updateJson"], str(update["zipUrl"]))))

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
            "scripts/validate-device-release-proof.py",
        ):
            self.assertEqual((ROOT / relative).stat().st_mode & 0o777, 0o755, relative)

    def test_release_qualification_proves_exact_built_zip(self) -> None:
        qualifier = (ROOT / "scripts/qualify-release-candidate.sh").read_text(encoding="utf-8")
        proof = (ROOT / "scripts/prove-device-fake-root.sh").read_text(encoding="utf-8")
        reset = (ROOT / "scripts/reset-fake-magisk-root.sh").read_text(encoding="utf-8")
        cli = (ROOT / "tools/otastctl/cli.py").read_text(encoding="utf-8")
        self.assertIn('--module-zip "$zip_a"', qualifier)
        self.assertIn("--module-zip PATH", proof)
        self.assertIn('reset_args+=("$module_zip")', proof)
        self.assertIn('restore_reset_args+=("$module_zip")', proof)
        self.assertIn('clone_args+=(--module-zip "$candidate_zip")', reset)
        self.assertIn('clone.add_argument("--module-zip"', cli)

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

    def test_release_workflow_has_isolated_branch_build_and_proven_publish(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertNotIn("permissions: write-all", workflow)
        self.assertIn("- prepare-release", workflow)
        self.assertIn("- publish-release", workflow)
        self.assertIn("- build-branch", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("build-release.sh", workflow)
        self.assertIn("verify-release", workflow)
        self.assertIn("validate-device-release-proof.py", workflow)
        self.assertIn("generate-update-json", workflow)
        self.assertIn("release-manifest.json", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("inputs.operation == 'draft'", workflow)
        self.assertIn("inputs.operation == 'publish'", workflow)

        branch_job = workflow.split("  build-branch:\n", 1)[1].split("  prepare-release:\n", 1)[0]
        self.assertIn("git ls-remote --exit-code --heads", branch_job)
        self.assertIn("actions/upload-artifact@v4", branch_job)
        self.assertIn("validate-zip", branch_job)
        self.assertNotIn("gh release", branch_job)
        self.assertNotIn("update.json", branch_job)
        self.assertNotIn("device-proof", branch_job)

        publish_job = workflow.split("  publish-release:\n", 1)[1]
        self.assertNotIn("build-release.sh", publish_job)
        self.assertNotIn("gh release create", publish_job)
        self.assertIn("validate-device-release-proof.py", publish_job)
        self.assertIn("draft=false --latest", publish_job)
        self.assertIn("contents/update.json", publish_job)

    def test_source_tree_has_no_symlinks_or_unsafe_git_path(self) -> None:
        git_path = ROOT / ".git"
        self.assertFalse(git_path.is_symlink())
        if git_path.exists():
            self.assertTrue(git_path.is_dir())
        self.assertEqual([path for path in ROOT.rglob("*") if path.is_symlink()], [])


if __name__ == "__main__":
    unittest.main()
