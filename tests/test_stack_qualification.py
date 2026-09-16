from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.stack_qualification import (
    stack_binding_digest,
    stack_binding_reuse_decision,
    validate_stack_binding,
    validate_stack_bound_qualification,
)
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]
SHA = "1" * 64


def sample_binding() -> dict[str, object]:
    return {
        "schema_version": 1,
        "pif_provider": {
            "id": "kowx-inject-s",
            "version": "v4.7-1-inject-s",
            "source": "KOWX712/PlayIntegrityFix@73552eec78f1e733573192333e9a7453b8de0662",
            "profile_sha256": SHA,
        },
        "trickystore": {
            "version": "v3.1.0",
            "source": "beakthoven/TrickyStoreOSS@v3.1.0",
            "policy_sha256": "2" * 64,
        },
        "zygisk_provider": {
            "id": "rezygisk",
            "version": "v1.0.0",
            "source": "PerformanC/ReZygisk@release",
            "module_prop_sha256": "3" * 64,
        },
        "vector": {
            "state": "PRESENT",
            "version": "reviewed",
            "source": "module-prop-bound",
            "module_prop_sha256": "4" * 64,
        },
        "bki": {
            "state": "PRESENT",
            "version": "v1.6.1",
            "source": "module-prop-bound",
            "module_prop_sha256": "5" * 64,
        },
        "concealment": [
            {
                "id": "treat_wheel",
                "version": "v0.0.10",
                "source": "PerformanC/Treat-Wheel-Zygisk",
                "evidence_sha256": "6" * 64,
            }
        ],
        "zygisk_detach": {
            "state": "PRESENT",
            "version": "v1.23.2",
            "config_sha256": "7" * 64,
            "critical_targets": [],
        },
        "page_size": 4096,
        "external_acceptance": {
            "play_integrity": {"status": "PASS", "verdicts": ["MEETS_DEVICE_INTEGRITY"]},
            "play_protect_certification": {"status": "PASS"},
            "wallet": {"status": "NOT_TESTED"},
            "banking_or_app_root_detection": {"status": "NOT_TESTED"},
        },
    }


class StackQualificationTests(unittest.TestCase):
    def test_current_repository_allows_legacy_stale_record_without_stack_binding(self) -> None:
        result = validate_stack_bound_qualification(ROOT)
        self.assertEqual(result["current_records"], 0)
        self.assertEqual(result["records_with_stack_binding"], 0)
        self.assertTrue(result["all_current_records_bound"])

    def test_binding_validates_and_material_change_invalidates_reuse(self) -> None:
        binding = sample_binding()
        result = validate_stack_binding(ROOT, binding)
        self.assertEqual(result["pif_provider"], "kowx-inject-s")
        self.assertEqual(result["digest"], stack_binding_digest(binding))
        unchanged = stack_binding_reuse_decision(binding, copy.deepcopy(binding))
        self.assertTrue(unchanged["reusable"])
        changed = copy.deepcopy(binding)
        changed["pif_provider"]["profile_sha256"] = "8" * 64  # type: ignore[index]
        decision = stack_binding_reuse_decision(binding, changed)
        self.assertFalse(decision["reusable"])
        self.assertEqual(decision["reason"], "material stack binding changed")

    def test_external_acceptance_dimensions_are_independent_and_critical_detach_fails(self) -> None:
        binding = sample_binding()
        binding["external_acceptance"]["wallet"] = {"status": "FAIL"}  # type: ignore[index]
        # Wallet failure is recorded independently and does not rewrite PI/certification evidence.
        validate_stack_binding(ROOT, binding)
        self.assertEqual(binding["external_acceptance"]["play_integrity"]["status"], "PASS")  # type: ignore[index]
        detached = copy.deepcopy(binding)
        detached["zygisk_detach"]["critical_targets"] = ["com.google.android.gms"]  # type: ignore[index]
        with self.assertRaisesRegex(OtastError, "cannot bind detached qualification-critical"):
            validate_stack_binding(ROOT, detached)

    def test_current_record_without_stack_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-stack-current-") as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "compatibility", root / "compatibility")
            shutil.copytree(ROOT / "authority", root / "authority")
            shutil.copytree(ROOT / "docs", root / "docs")
            registry_path = root / "compatibility/qualification-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            record = next(iter(registry["records"].values()))
            record["current_state"] = "CURRENT"
            record["runtime_digest"] = "9" * 64
            registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(OtastError, "CURRENT qualification lacks full stack binding"):
                validate_stack_bound_qualification(root)

    def test_fork_binding_is_allowed_but_registry_preference_stays_inject_s(self) -> None:
        binding = sample_binding()
        binding["pif_provider"] = {
            "id": "osm0sis-fork-v18",
            "version": "v18",
            "source": "osm0sis/PlayIntegrityFork@6d2307ff5037519982205e66bda1132d0d8cc4da",
            "profile_sha256": "a" * 64,
        }
        validate_stack_binding(ROOT, binding)
        providers = json.loads((ROOT / "compatibility/pif-providers.json").read_text(encoding="utf-8"))
        self.assertEqual(providers["preferred_provider"], "kowx-inject-s")
        self.assertEqual(
            providers["providers"]["osm0sis-fork-v18"]["preference_qualification"],
            "UNQUALIFIED_ON_TEGU_EXACT_STACK",
        )


if __name__ == "__main__":
    unittest.main()
