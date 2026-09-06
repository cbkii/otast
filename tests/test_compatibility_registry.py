from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.compatibility import (
    IMPACT_CLASSES,
    QUALIFICATION_TIERS,
    classify_changed_paths,
    classify_target_paths,
    load_platform,
    load_registry,
    render_compatibility_status,
    validate_registry,
)
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]
PIF_DELTA = ROOT / "tests/fixtures/upstream/pif-b994-to-2f8199-paths.json"


class CompatibilityRegistryTests(unittest.TestCase):
    def test_registry_and_android_16_profile_validate(self) -> None:
        result = validate_registry(ROOT)
        self.assertEqual(result["schema_version"], 5)
        self.assertEqual(result["device_family"], "Google Pixel")
        self.assertEqual(result["platforms"]["android-16"], {"android_release": "16", "sdk": 36})
        self.assertEqual(set(load_registry(ROOT)["support_model"]["qualification_tiers"]), QUALIFICATION_TIERS)

    def test_unknown_platform_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(OtastError, "unknown or unsupported platform profile"):
            load_platform(ROOT, "android-17")

    def test_platform_profile_contains_native_runtime_evidence_contract(self) -> None:
        profile = load_platform(ROOT, "android-16")
        native = profile["native_environment_evidence"]
        self.assertIn("PAGE_SIZE", native["runtime_page_size"])
        self.assertIn("ro.product.cpu.abi", native["primary_abi"])
        self.assertIn("ro.product.cpu.abilist", native["abi_list"])
        self.assertIn("native", native["native_library_inventory"].lower())
        self.assertIn("readelf", native["elf_load_alignment"])
        self.assertIn("Zygisk", native["zygisk_identity"])

    def test_support_tiers_separate_family_architecture_from_device_qualification(self) -> None:
        support = load_registry(ROOT)["support_model"]
        self.assertEqual(support["family_architecture"]["tier"], "DESIGN_COMPATIBLE")
        self.assertEqual(support["undeclared_device_tier"], "UNQUALIFIED")
        self.assertEqual(support["devices"]["tegu"]["tier"], "DEVICE_VALIDATED")
        self.assertEqual(support["devices"]["shiba"]["tier"], "DESIGN_COMPATIBLE")
        self.assertEqual(support["devices"]["shiba"]["qualified_builds"], [])
        self.assertNotEqual(support["release_reference"]["tier"], "RELEASE_QUALIFIED")

    def test_managed_observed_and_conflicting_module_id_sets_are_distinct(self) -> None:
        registry = load_registry(ROOT)
        managed = {
            module_id
            for record in registry["targets"].values()
            for module_id in record["module_ids"]
        }
        observed = {
            module_id
            for record in registry["observed_dependencies"].values()
            for module_id in record.get("module_ids", [])
        }
        conflicts = {
            module_id
            for record in registry["conflicts"].values()
            for module_id in record["module_ids"]
        }
        self.assertTrue(managed.isdisjoint(observed))
        self.assertTrue(managed.isdisjoint(conflicts))
        self.assertTrue(observed.isdisjoint(conflicts))
        self.assertIn("rezygisk", observed)
        self.assertIn("zygisksu", observed)
        self.assertIn("vector", observed)
        self.assertIn("inline_hook_invalidate", observed)
        for record in registry["observed_dependencies"].values():
            self.assertEqual(record["mode"], "READ_ONLY")
            self.assertNotIn("managed_paths", record)

    def _validate_mutated(self, mutate) -> None:  # type: ignore[no-untyped-def]
        with tempfile.TemporaryDirectory(prefix="otast-compat-") as raw:
            temp = Path(raw)
            (temp / "compatibility/platforms").mkdir(parents=True)
            (temp / "module/runtime").mkdir(parents=True)
            (temp / "docs").mkdir(parents=True)
            (temp / "authority").mkdir(parents=True)
            registry = copy.deepcopy(load_registry(ROOT))
            mutate(registry)
            (temp / "compatibility/supported-targets.json").write_text(
                json.dumps(registry, indent=2) + "\n", encoding="utf-8"
            )
            shutil.copy2(ROOT / "compatibility/platforms/android-16.json", temp / "compatibility/platforms/android-16.json")
            shutil.copy2(ROOT / "module/runtime/platform.sh", temp / "module/runtime/platform.sh")
            shutil.copy2(
                ROOT / "authority/reference-tegu-CP1A.260305.018.ota.prop",
                temp / "authority/reference-tegu-CP1A.260305.018.ota.prop",
            )
            (temp / "docs/COMPATIBILITY-STATUS.md").write_text("stale\n", encoding="utf-8")
            validate_registry(temp)

    def test_duplicate_managed_observed_ownership_is_rejected(self) -> None:
        def mutate(registry: dict[str, object]) -> None:
            dependencies = registry["observed_dependencies"]  # type: ignore[index]
            assert isinstance(dependencies, dict)
            dependencies["bad-overlap"] = {
                "mode": "READ_ONLY",
                "kind": "test",
                "module_ids": ["Yurikey"],
            }

        with self.assertRaisesRegex(OtastError, "also declared as an observed module"):
            self._validate_mutated(mutate)

    def test_managed_conflict_overlap_is_rejected(self) -> None:
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
