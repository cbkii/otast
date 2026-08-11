from __future__ import annotations

import re
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

    def test_production_release_workflow_has_four_user_inputs(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertNotIn("permissions: write-all", workflow)
        self.assertIn("\npermissions:\n", workflow)
        input_block = workflow.split("    inputs:\n", 1)[1].split("\npermissions:", 1)[0]
        for key in ("action", "version", "full_validation", "physical_proof"):
            self.assertRegex(input_block, rf"(?m)^      {key}:$")
        self.assertEqual(len(re.findall(r"(?m)^      [A-Za-z_][A-Za-z0-9_]*:$", input_block)), 4)
        for removed in ("branch:", "tag:", "operation:", "versionCode:", "legacy"):
            self.assertNotIn(removed, input_block.lower())
        self.assertIn("- prepare-release", input_block)
        self.assertIn("- publish-release", input_block)
        self.assertNotIn("build-branch", input_block)
        proof_block = input_block.split("      physical_proof:\n", 1)[1]
        self.assertIn("type: boolean", proof_block)
        self.assertIn("default: true", proof_block)
        self.assertIn("Require Pixel physical-device proof before publishing", proof_block)

    def test_production_release_workflow_preserves_release_safety_contract(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("group: release-${{ github.repository }}", workflow)
        self.assertEqual(workflow.count('if [[ "$GITHUB_ACTOR" != "$GITHUB_REPOSITORY_OWNER" ]]; then'), 2)
        self.assertIn("resolve-release-version", workflow)
        self.assertIn("stamp-release", workflow)
        self.assertIn("scripts/test.sh --full", workflow)
        self.assertIn("FULL VALIDATION: SKIPPED BY OWNER", workflow)
        self.assertIn("MANDATORY RELEASE INTEGRITY: PASS", workflow)
        self.assertIn("test_release*.py", workflow)
        self.assertIn("test_public_contract.py", workflow)
        self.assertIn("build-release.sh", workflow)
        self.assertIn("verify-release", workflow)
        self.assertIn("release-manifest.json", workflow)
        self.assertIn("validate-device-release-proof.py", workflow)
        self.assertIn("select-release-candidate.py", workflow)
        self.assertIn("generate-update-json", workflow)
        self.assertIn("proven assets are immutable", workflow)
        self.assertIn("main moved during release preparation", workflow)
        self.assertIn("release-meta/", workflow)
        self.assertIn("release-update/", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("pull-requests: write", workflow)
        self.assertIn("OWNER BYPASS", workflow)
        self.assertIn("Require Pixel physical-device proof before publishing", workflow)
        self.assertIn("Draft has no Git tag yet; this is normal", workflow)
        self.assertIn("target_commitish", workflow)
        self.assertIn("Verify published tag and release identity", workflow)

        prepare_marker = "  prepare-release:\n"
        publish_marker = "  publish-release:\n"
        self.assertIn(prepare_marker, workflow)
        self.assertIn(publish_marker, workflow)
        prepare_job = workflow.split(prepare_marker, 1)[1].split(publish_marker, 1)[0]
        publish_job = workflow.split(publish_marker, 1)[1]
        self.assertIn("build-release.sh", prepare_job)
        self.assertIn("Create or refresh unproven draft", prepare_job)
        self.assertNotIn("build-release.sh", publish_job)
        self.assertNotIn("gh release create", publish_job)
        self.assertIn("--draft=false --prerelease", publish_job)
        self.assertIn("--draft=false --latest", publish_job)
        self.assertIn("if: ${{ !contains(steps.release.outputs.version, '-') }}", publish_job)
        self.assertIn("if: ${{ contains(steps.release.outputs.version, '-') }}", publish_job)

    def test_manual_publish_proof_is_optional_but_bundle_integrity_is_not(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        publish = workflow.split("  publish-release:\n", 1)[1]
        self.assertIn("REQUIRE_PHYSICAL_PROOF: ${{ inputs.physical_proof }}", publish)
        self.assertIn("[[ $REQUIRE_PHYSICAL_PROOF == true ]] && args+=(--require-proof)", publish)
        self.assertIn("elif [[ $REQUIRE_PHYSICAL_PROOF == true ]]", publish)
        self.assertIn("proof_state='NOT PROVIDED (OWNER BYPASS)'", publish)
        self.assertIn("verify-release", publish)
        self.assertIn("--checksum", publish)
        self.assertIn("--manifest", publish)

    def test_branch_build_is_a_separate_read_only_one_field_workflow(self) -> None:
        workflow = (ROOT / ".github/workflows/build-branch.yml").read_text(encoding="utf-8")
        input_block = workflow.split("    inputs:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertRegex(input_block, r"(?m)^      branch:$")
        self.assertEqual(len(re.findall(r"(?m)^      [A-Za-z_][A-Za-z0-9_]*:$", input_block)), 1)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("git ls-remote --exit-code --heads", workflow)
        self.assertIn("tools.otastctl --repo-root \"$GITHUB_WORKSPACE\" build", workflow)
        self.assertIn("validate-zip", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("name: otast-branch-${{ github.run_id }}-${{ github.run_attempt }}", workflow)
        for forbidden in ("gh release", "update.json", "device-proof", "build-release", "verify-release"):
            self.assertNotIn(forbidden, workflow)

    def test_release_metadata_has_no_stale_display_version_duplication(self) -> None:
        customize = (ROOT / "module/customize.sh").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        release_docs = (ROOT / "docs/RELEASES.md").read_text(encoding="utf-8")
        self.assertIn('s/^version=//p', customize)
        self.assertIn('"$MODPATH/module.prop"', customize)
        self.assertNotIn("v1.0.0-rc.3", customize)
        self.assertNotIn("v1.0.0-rc.3", readme)
        self.assertIn("GitHub Releases", readme)
        self.assertIn("RELEASE.md", release_docs)
        self.assertNotIn("defaults to validation only", release_docs)

    def test_source_tree_has_no_symlinks_or_unsafe_git_path(self) -> None:
        git_path = ROOT / ".git"
        self.assertFalse(git_path.is_symlink())
        if git_path.exists():
            self.assertTrue(git_path.is_dir())
        self.assertEqual([path for path in ROOT.rglob("*") if path.is_symlink()], [])


if __name__ == "__main__":
    unittest.main()
