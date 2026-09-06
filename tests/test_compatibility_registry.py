from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.compatibility import (
    IMPACT_CLASSES,
    classify_changed_paths,
    classify_target_paths,
    load_registry,
    render_compatibility_status,
    validate_registry,
)
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]
PIF_DELTA = ROOT / "tests/fixtures/upstream/pif-b994391-to-2f8199a.json"


class CompatibilityRegistryTests(unittest.TestCase):
    def _validate_mutated(self, mutate) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "compatibility/platforms").mkdir(parents=True)
            (root / "module/runtime").mkdir(parents=True)
            registry = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
            platform = json.loads((ROOT / "compatibility/platforms/android-16.json").read_text(encoding="utf-8"))
            mutate(registry)
            (root / "compatibility/supported-targets.json").write_text(
                json.dumps(registry, indent=2) + "\n", encoding="utf-8"
            )
            (root / "compatibility/platforms/android-16.json").write_text(
                json.dumps(platform, indent=2) + "\n", encoding="utf-8"
            )
            (root / "module/runtime/platform.sh").write_text(
                (ROOT / "module/runtime/platform.sh").read_text(encoding="utf-8"), encoding="utf-8"
            )
            validate_registry(root)

    def test_registry_validates_current_contract(self) -> None:
        result = validate_registry(ROOT)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["schema_version"], 5)
        self.assertIn("tegu", result["devices"])

    def test_platform_profile_covers_pixel_family_contract(self) -> None:
        registry = load_registry(ROOT)
        support = registry["support_model"]
        self.assertEqual(support["device_family"], "Google Pixel")
        self.assertEqual(support["family_architecture"]["tier"], "DESIGN_COMPATIBLE")
        self.assertEqual(support["undeclared_device_tier"], "UNQUALIFIED")
        self.assertEqual(support["release_reference"]["device"], "tegu")
        self.assertEqual(support["release_reference"]["tier"], "DEVICE_VALIDATED")

    def test_all_managed_targets_have_distribution_identity(self) -> None:
        registry = load_registry(ROOT)
        for target_id, target in registry["targets"].items():
            self.assertEqual(target["target_role"], "MANAGED", target_id)
            self.assertIn("distribution_identity", target, target_id)
            self.assertEqual(target["distribution_identity"]["repository"], target["monitor"]["repository"])

    def test_observed_dependencies_are_read_only(self) -> None:
        registry = load_registry(ROOT)
        for dependency_id, dependency in registry["observed_dependencies"].items():
            self.assertEqual(dependency["mode"], "READ_ONLY", dependency_id)

    def test_explicit_conflicts_do_not_overlap_managed_module_ids(self) -> None:
        registry = load_registry(ROOT)
        conflicts = {
            module_id
            for conflict in registry["conflicts"].values()
            for module_id in conflict["module_ids"]
        }
        managed = {
            module_id
            for target in registry["targets"].values()
            for module_id in target["module_ids"]
        }
        self.assertFalse(conflicts & managed)

    def test_conflicting_target_module_identity_is_rejected(self) -> None:
        def mutate(registry: dict[str, object]) -> None:
            targets = registry["targets"]  # type: ignore[index]
            assert isinstance(targets, dict)
            target = targets["yurikey"]
            assert isinstance(target, dict)
            target["module_ids"] = ["AshLooper"]
            distribution = target["distribution_identity"]
            assert isinstance(distribution, dict)
            distribution["module_id"] = "AshLooper"

        with self.assertRaisesRegex(OtastError, "overlaps explicit conflict"):
            self._validate_mutated(mutate)

    def test_distribution_identity_records_installable_release_asset(self) -> None:
        tricky = load_registry(ROOT)["targets"]["trickystore"]["distribution_identity"]
        self.assertEqual(tricky["source_type"], "RELEASE_ASSET")
        self.assertEqual(tricky["module_id"], "tricky_store")
        self.assertEqual(tricky["version_code"], 172)
        self.assertTrue(tricky["asset_name"].endswith(".zip"))
        self.assertEqual(len(tricky["asset_sha256"]), 64)

    def test_current_pif_upstream_delta_is_native_dependency_change(self) -> None:
        fixture = json.loads(PIF_DELTA.read_text(encoding="utf-8"))
        self.assertEqual(fixture["base"], "b994391970b51a2dfefed0e1d420dd6b017756e8")
        self.assertEqual(fixture["head"], "2f8199a90a150ad98921438608e1e0e951ba2d5f")
        result = classify_target_paths(ROOT, "playintegrityfix", fixture["changed_paths"])
        self.assertEqual(result["impact"], "NATIVE_DEPENDENCY_CHANGED")
        self.assertTrue(result["requires_review"])

    def test_semantic_impact_classes_cover_each_surface(self) -> None:
        registry = load_registry(ROOT)
        pif = registry["targets"]["playintegrityfix"]
        yurikey = registry["targets"]["yurikey"]
        cases = (
            (pif, [".github/workflows/test.yml"], "DOCS_OR_CI_ONLY"),
            (pif, ["module/action.sh"], "PRESERVED_SURFACE_CHANGED"),
            (yurikey, ["key"], "PRESERVED_SURFACE_CHANGED"),
            (pif, ["gradle/libs.versions.toml"], "NATIVE_DEPENDENCY_CHANGED"),
            (yurikey, ["action.sh"], "MANAGED_WHOLE_FILE_CHANGED"),
            (pif, ["module/autopif.sh"], "STRUCTURE_SENSITIVE_CHANGED"),
            (pif, ["module/module.prop"], "MODULE_IDENTITY_CHANGED"),
            (pif, ["some/new/unknown.file"], "UNKNOWN_PACKAGE_CHANGE"),
        )
        observed = set()
        for record, paths, expected in cases:
            result = classify_changed_paths(record, paths)
            self.assertEqual(result["impact"], expected)
            observed.add(expected)
        self.assertEqual(observed, set(IMPACT_CLASSES))

    def test_specific_structure_sensitive_rule_beats_broad_preserved_rule(self) -> None:
        record = load_registry(ROOT)["targets"]["ta-utl"]
        result = classify_changed_paths(record, ["webui/assets/boot_hash-C0kIcwCH.js"])
        self.assertEqual(result["impact"], "STRUCTURE_SENSITIVE_CHANGED")

    def test_unsafe_changed_paths_are_rejected(self) -> None:
        record = load_registry(ROOT)["targets"]["playintegrityfix"]
        for unsafe in ("/absolute/path", "../escape", "safe/../../escape"):
            with self.assertRaisesRegex(OtastError, "unsafe changed path"):
                classify_changed_paths(record, [unsafe])

    def test_generated_compatibility_status_is_current(self) -> None:
        actual = (ROOT / "docs/COMPATIBILITY-STATUS.md").read_text(encoding="utf-8")
        self.assertEqual(actual, render_compatibility_status(ROOT))
        self.assertIn("Undeclared device/build tier: `UNQUALIFIED`", actual)


if __name__ == "__main__":
    unittest.main()
