from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/release-device.sh"
VALIDATOR = ROOT / "scripts/validate-device-release-proof.py"


class ReleaseSourceProvenanceTests(unittest.TestCase):
    def test_wrapper_uses_github_main_metadata_not_dirty_local_identity(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("fetch_remote_file update.json", text)
        self.assertIn("fetch_remote_file module/module.prop", text)
        self.assertIn('git -C "$REPO_ROOT" show "origin/main:$path"', text)
        self.assertIn("local checkout is dirty; leaving it untouched. Release assets still target GitHub main.", text)
        self.assertIn("local branch is", text)
        self.assertIn("GitHub-main release metadata", text)

    def test_proof_validator_rebinds_local_capture_to_exact_release_provenance(self) -> None:
        text = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn('value.get("current_source_commit") != current_source', text)
        self.assertIn('value.get("current_zip_sha256") != current_zip_sha', text)
        self.assertIn('proof_provenance != provenance', text)
        self.assertIn('release_props.get(key) != str(expected)', text)


if __name__ == "__main__":
    unittest.main()
