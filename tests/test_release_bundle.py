from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.release import (
    CHANGELOG_URL,
    REPOSITORY,
    UPDATE_JSON_URL,
    build_release_bundle,
    expected_update_metadata,
    load_update_metadata,
    verify_release_bundle,
    write_update_metadata,
)
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]
TEST_COMMIT = "1" * 40


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

    def test_update_metadata_is_generated_from_release_manifest(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        expected = expected_update_metadata(manifest["version"], manifest["version_code"])
        generated = self.temp / "update.json"
        self.assertEqual(write_update_metadata(self.manifest_path, generated), expected)
        self.assertEqual(load_update_metadata(generated), expected)
        self.assertEqual(expected["zipUrl"], f"https://github.com/{REPOSITORY}/releases/download/{manifest['version']}/{manifest['zip_filename']}")
        self.assertEqual(expected["changelog"], CHANGELOG_URL)

    def test_stable_repository_update_metadata_is_valid(self) -> None:
        current = load_update_metadata(ROOT / "update.json")
        self.assertEqual(current["changelog"], CHANGELOG_URL)
        self.assertTrue(str(current["zipUrl"]).startswith(f"https://github.com/{REPOSITORY}/releases/download/"))
        module_prop = (ROOT / "module/module.prop").read_text(encoding="utf-8")
        self.assertIn(f"updateJson={UPDATE_JSON_URL}", module_prop)


if __name__ == "__main__":
    unittest.main()
