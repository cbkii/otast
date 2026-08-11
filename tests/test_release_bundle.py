from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.build import module_metadata
from tools.otastctl.release import (
    CHANGELOG_URL,
    REPOSITORY,
    UPDATE_JSON_URL,
    build_release_bundle,
    expected_update_metadata,
    load_update_metadata,
    resolve_release_identity,
    select_proven_draft,
    stamp_release_metadata,
    verify_release_bundle,
    write_update_metadata,
)
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]
TEST_COMMIT = "1" * 40


def stable(version: str = "v1.0.0", code: int = 100004) -> dict[str, object]:
    return expected_update_metadata(version, code)


def current(version: str = "v1.0.0", code: int = 100004) -> dict[str, str]:
    return {
        "id": "otast",
        "name": "OTAST",
        "version": version,
        "versionCode": str(code),
        "author": "cbkii",
        "description": "test",
        "updateJson": UPDATE_JSON_URL,
    }


def release_record(version: str, *, proven: bool = True, draft: bool = True) -> dict[str, object]:
    zip_name = f"otast-{version}.zip"
    assets = [zip_name, f"{zip_name}.sha256", "release-manifest.json"]
    if proven:
        assets.append(f"otast-{version}-device-proof.json")
    return {
        "draft": draft,
        "prerelease": "-" in version,
        "tag_name": version,
        "assets": [{"name": name} for name in assets],
    }


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.temp = Path(self._temp.name)
        self.output = self.temp / "arbitrary" / "nested" / "release"
        report = build_release_bundle(ROOT, self.output, commit_sha=TEST_COMMIT)
        self.zip_path = Path(report["zip_path"])
        self.checksum_path = Path(report["checksum_path"])
        self.manifest_path = Path(report["manifest_path"])

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_release_verification_is_independent_of_caller_cwd(self) -> None:
        unrelated = self.temp / "unrelated"
        unrelated.mkdir()
        original = Path.cwd()
        os.chdir(unrelated)
        try:
            report = verify_release_bundle(self.zip_path, self.checksum_path, self.manifest_path)
        finally:
            os.chdir(original)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["source_commit"], TEST_COMMIT)

    def test_tampered_zip_is_rejected(self) -> None:
        with self.zip_path.open("ab") as handle:
            handle.write(b"tamper")
        with self.assertRaises(OtastError):
            verify_release_bundle(self.zip_path, self.checksum_path, self.manifest_path)

    def test_wrong_checksum_basename_is_rejected(self) -> None:
        digest = json.loads(self.manifest_path.read_text(encoding="utf-8"))["zip_sha256"]
        self.checksum_path.write_text(f"{digest}  wrong.zip\n", encoding="utf-8")
        with self.assertRaises(OtastError):
            verify_release_bundle(self.zip_path, self.checksum_path, self.manifest_path)

    def test_renamed_checksum_sidecar_is_rejected(self) -> None:
        renamed = self.checksum_path.with_name("renamed.sha256")
        self.checksum_path.replace(renamed)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["checksum_filename"] = renamed.name
        self.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(OtastError):
            verify_release_bundle(self.zip_path, renamed, self.manifest_path)

    def test_wrong_checksum_digest_is_rejected(self) -> None:
        self.checksum_path.write_text(f"{'0' * 64}  {self.zip_path.name}\n", encoding="utf-8")
        with self.assertRaises(OtastError):
            verify_release_bundle(self.zip_path, self.checksum_path, self.manifest_path)

    def test_manifest_mismatch_is_rejected(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["version_code"] += 1
        self.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(OtastError):
            verify_release_bundle(self.zip_path, self.checksum_path, self.manifest_path)

    def test_manifest_extra_field_is_rejected(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["unexpected"] = "value"
        self.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(OtastError):
            verify_release_bundle(self.zip_path, self.checksum_path, self.manifest_path)

    def test_boolean_version_codes_are_rejected(self) -> None:
        for value in (True, False):
            with self.subTest(value=value):
                with self.assertRaises(OtastError):
                    expected_update_metadata("v1.0.0", value)

                path = self.temp / f"update-{str(value).lower()}.json"
                path.write_text(
                    json.dumps(
                        {
                            "version": "v1.0.0",
                            "versionCode": value,
                            "zipUrl": f"https://github.com/{REPOSITORY}/releases/download/v1.0.0/otast-v1.0.0.zip",
                            "changelog": CHANGELOG_URL,
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(OtastError):
                    load_update_metadata(path)

    def test_auto_version_bumps_stable_patch_and_version_code(self) -> None:
        resolved = resolve_release_identity(stable(), current())
        self.assertEqual(resolved["version"], "v1.0.1")
        self.assertEqual(resolved["version_code"], 100005)
        self.assertFalse(resolved["reused_candidate"])

    def test_explicit_version_uses_automatic_monotonic_code(self) -> None:
        resolved = resolve_release_identity(stable(), current(), requested_version="v1.1.0")
        self.assertEqual(resolved["version"], "v1.1.0")
        self.assertEqual(resolved["version_code"], 100005)

    def test_existing_unpublished_candidate_is_reused(self) -> None:
        resolved = resolve_release_identity(stable(), current("v1.0.1", 100005))
        self.assertEqual(resolved["version"], "v1.0.1")
        self.assertEqual(resolved["version_code"], 100005)
        self.assertTrue(resolved["reused_candidate"])

    def test_explicit_existing_candidate_reuses_code(self) -> None:
        resolved = resolve_release_identity(
            stable(), current("v1.1.0-rc1", 100005), requested_version="v1.1.0-rc1"
        )
        self.assertEqual(resolved["version_code"], 100005)
        self.assertTrue(resolved["prerelease"])

    def test_invalid_or_non_advancing_version_is_rejected(self) -> None:
        for value in ("1.0.1", "v1", "v1.0.0", "v0.9.9"):
            with self.subTest(value=value), self.assertRaises(OtastError):
                resolve_release_identity(stable(), current(), requested_version=value)

    def test_stamp_updates_candidate_but_not_stable_update_json(self) -> None:
        repo = self.temp / "repo"
        shutil.copytree(ROOT / "module", repo / "module")
        shutil.copy2(ROOT / "update.json", repo / "update.json")
        shutil.copy2(ROOT / "CHANGELOG.md", repo / "CHANGELOG.md")
        before_update = (repo / "update.json").read_bytes()
        stamp_release_metadata(repo, version="v1.0.1", version_code=100005, notes="- Simplified release UX.")
        metadata = module_metadata(repo / "module/module.prop")
        self.assertEqual(metadata["version"], "v1.0.1")
        self.assertEqual(metadata["versionCode"], "100005")
        self.assertEqual(metadata["updateJson"], UPDATE_JSON_URL)
        self.assertEqual((repo / "update.json").read_bytes(), before_update)
        changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(changelog.count("## v1.0.1"), 1)

    def test_stamp_is_idempotent_for_changelog_section(self) -> None:
        repo = self.temp / "repo-idempotent"
        shutil.copytree(ROOT / "module", repo / "module")
        shutil.copy2(ROOT / "update.json", repo / "update.json")
        shutil.copy2(ROOT / "CHANGELOG.md", repo / "CHANGELOG.md")
        for notes in ("- First notes.", "- Updated notes."):
            stamp_release_metadata(repo, version="v1.0.1", version_code=100005, notes=notes)
        changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(changelog.count("## v1.0.1"), 1)
        self.assertIn("- Updated notes.", changelog)
        self.assertNotIn("- First notes.", changelog)

    def test_select_single_proven_draft(self) -> None:
        selected = select_proven_draft([release_record("v1.0.1")])
        self.assertEqual(selected["version"], "v1.0.1")

    def test_select_proven_draft_rejects_zero_or_multiple(self) -> None:
        with self.assertRaises(OtastError):
            select_proven_draft([release_record("v1.0.1", proven=False)])
        with self.assertRaises(OtastError):
            select_proven_draft([release_record("v1.0.1"), release_record("v1.1.0")])

    def test_select_explicit_proven_draft(self) -> None:
        selected = select_proven_draft(
            [release_record("v1.0.1"), release_record("v1.1.0")], requested_version="v1.1.0"
        )
        self.assertEqual(selected["version"], "v1.1.0")
        with self.assertRaises(OtastError):
            select_proven_draft([release_record("v1.1.0", proven=False)], requested_version="v1.1.0")

    def test_update_metadata_is_generated_from_release_manifest(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        expected = expected_update_metadata(manifest["version"], manifest["version_code"])
        generated = self.temp / "update.json"
        self.assertEqual(write_update_metadata(self.manifest_path, generated), expected)
        self.assertEqual(load_update_metadata(generated), expected)
        self.assertEqual(expected["zipUrl"], f"https://github.com/{REPOSITORY}/releases/download/{manifest['version']}/{manifest['zip_filename']}")
        self.assertEqual(expected["changelog"], CHANGELOG_URL)

    def test_stable_repository_update_metadata_is_valid(self) -> None:
        current_update = load_update_metadata(ROOT / "update.json")
        self.assertEqual(current_update["changelog"], CHANGELOG_URL)
        self.assertTrue(str(current_update["zipUrl"]).startswith(f"https://github.com/{REPOSITORY}/releases/download/"))
        module_prop = (ROOT / "module/module.prop").read_text(encoding="utf-8")
        self.assertIn(f"updateJson={UPDATE_JSON_URL}", module_prop)


if __name__ == "__main__":
    unittest.main()
