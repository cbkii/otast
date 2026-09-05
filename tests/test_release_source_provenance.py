from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools.otastctl.build import build_module
from tools.otastctl.qualification import registry_provenance

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/release-device.sh"
VALIDATOR = ROOT / "scripts/validate-device-release-proof.py"
QUALIFICATION = ROOT / "tools/otastctl/qualification.py"
TEST_COMMIT = "4" * 40


class ReleaseSourceProvenanceTests(unittest.TestCase):
    def test_wrapper_uses_github_main_metadata_not_dirty_local_identity(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("fetch_remote_file update.json", text)
        self.assertIn("fetch_remote_file module/module.prop", text)
        self.assertIn('"$REAL_GIT" -C "$REPO_ROOT" show "origin/main:$path"', text)
        self.assertIn("local checkout is dirty; leaving it untouched. Release assets still target GitHub main.", text)
        self.assertIn("local branch is", text)
        self.assertIn("GitHub-main release metadata", text)

    def test_physical_proof_writer_uses_exact_candidate_registry_provenance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-proof-provenance-") as raw:
            module_zip = build_module(ROOT, Path(raw), commit_sha=TEST_COMMIT)
            with zipfile.ZipFile(module_zip) as archive:
                props = dict(
                    line.split("=", 1)
                    for line in archive.read("release.properties").decode("utf-8").splitlines()
                    if "=" in line
                )
            expected = {
                "compatibility_registry_schema": int(props["compatibility_registry_schema"]),
                "compatibility_registry_sha256": props["compatibility_registry_sha256"],
                "qualification_registry_schema": int(props["qualification_registry_schema"]),
                "qualification_registry_sha256": props["qualification_registry_sha256"],
            }
            with mock.patch.dict(
                os.environ,
                {"ZIP_PATH_VALUE": str(module_zip), "SOURCE_VALUE": TEST_COMMIT},
                clear=False,
            ):
                self.assertEqual(registry_provenance(ROOT), expected)

    def test_proof_validator_rebinds_local_capture_to_exact_release_provenance(self) -> None:
        validator = VALIDATOR.read_text(encoding="utf-8")
        qualification = QUALIFICATION.read_text(encoding="utf-8")
        self.assertIn("_embedded_registry_provenance(release_props)", validator)
        self.assertIn('proof_provenance != provenance', validator)
        self.assertIn("does not match exact candidate ZIP", validator)
        self.assertIn('os.environ.get("ZIP_PATH_VALUE")', qualification)
        self.assertIn("_candidate_zip_registry_provenance", qualification)


if __name__ == "__main__":
    unittest.main()
