from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "scripts/select-release-candidate.py"


def load_selector():
    spec = importlib.util.spec_from_file_location("otast_release_selector_test", SELECTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def record(version: str, *, proof: bool = False, draft: bool = True, target: str = "a" * 40) -> dict[str, object]:
    zip_name = f"otast-{version}.zip"
    assets = [zip_name, f"{zip_name}.sha256", "release-manifest.json"]
    if proof:
        assets.append(f"otast-{version}-device-proof.json")
    return {
        "tag_name": version,
        "draft": draft,
        "prerelease": False,
        "target_commitish": target,
        "assets": [{"name": name} for name in assets],
    }


class ReleaseSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selector = load_selector()

    def test_optional_proof_accepts_complete_unproven_draft(self) -> None:
        selected = self.selector.select_candidate([record("v1.0.1")], require_proof=False)
        self.assertEqual(selected["version"], "v1.0.1")
        self.assertFalse(selected["proof_present"])
        self.assertTrue(selected["draft"])

    def test_required_proof_rejects_unproven_draft_with_actionable_error(self) -> None:
        with self.assertRaisesRegex(self.selector.SelectionError, "uncheck Require physical device proof"):
            self.selector.select_candidate([record("v1.0.1")], require_proof=True)

    def test_required_proof_accepts_proven_draft(self) -> None:
        selected = self.selector.select_candidate([record("v1.0.1", proof=True)], require_proof=True)
        self.assertTrue(selected["proof_present"])

    def test_optional_proof_still_requires_complete_bundle_assets(self) -> None:
        incomplete = record("v1.0.1")
        incomplete["assets"] = [{"name": "otast-v1.0.1.zip"}]
        with self.assertRaisesRegex(self.selector.SelectionError, "run prepare-release first"):
            self.selector.select_candidate([incomplete], require_proof=False)

    def test_blank_version_requires_exactly_one_eligible_draft(self) -> None:
        with self.assertRaisesRegex(self.selector.SelectionError, "multiple eligible"):
            self.selector.select_candidate(
                [record("v1.0.1"), record("v1.1.0")],
                require_proof=False,
            )

    def test_explicit_version_can_resume_published_release(self) -> None:
        selected = self.selector.select_candidate(
            [record("v1.0.1", draft=False)],
            requested_version="v1.0.1",
            require_proof=False,
        )
        self.assertFalse(selected["draft"])
        self.assertEqual(selected["version"], "v1.0.1")

    def test_blank_version_ignores_published_release(self) -> None:
        with self.assertRaisesRegex(self.selector.SelectionError, "no complete OTAST release draft"):
            self.selector.select_candidate([record("v1.0.1", draft=False)], require_proof=False)

    def test_prerelease_is_derived_from_tag(self) -> None:
        value = record("v1.1.0-rc1", proof=True)
        value["prerelease"] = False
        selected = self.selector.select_candidate([value], require_proof=True)
        self.assertTrue(selected["prerelease"])

    def test_paginated_gh_api_shape_is_flattened(self) -> None:
        selected = self.selector.select_candidate([[record("v1.0.1")]], require_proof=False)
        self.assertEqual(selected["target_commitish"], "a" * 40)


if __name__ == "__main__":
    unittest.main()
