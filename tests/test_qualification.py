from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.build import build_module, source_runtime_digest
from tools.otastctl.qualification import (
    classify_root_exposure_report,
    load_qualification_registry,
    proof_reuse_decision,
    validate_qualification_registry,
)
from tools.otastctl.runtime_digest import runtime_digest_from_zip
from tools.otastctl.util import sha256_file

ROOT = Path(__file__).resolve().parents[1]


class QualificationTests(unittest.TestCase):
    def test_repository_qualification_registry_is_valid_and_conservative(self) -> None:
        result = validate_qualification_registry(ROOT)
        self.assertGreaterEqual(result["records"], 1)
        registry = load_qualification_registry(ROOT)
        records = registry["records"]
        self.assertFalse(any(record.get("device") == "shiba" for record in records.values()))
        legacy = records["tegu-CP1A.260305.018-v1.0.3-legacy-proof"]
        self.assertEqual(legacy["current_state"], "STALE_RUNTIME_DIGEST_UNBOUND")
        self.assertIsNone(legacy["runtime_digest"])
        self.assertEqual(legacy["page_size_qualification"]["4096"], "UNQUALIFIED")
        self.assertEqual(legacy["page_size_qualification"]["16384"], "UNQUALIFIED")

    def test_host_only_provenance_change_keeps_runtime_digest_but_changes_zip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            first = build_module(ROOT, base / "one", commit_sha="1" * 40)
            second = build_module(ROOT, base / "two", commit_sha="2" * 40)
            self.assertNotEqual(sha256_file(first), sha256_file(second))
            self.assertEqual(runtime_digest_from_zip(first), runtime_digest_from_zip(second))
            self.assertEqual(runtime_digest_from_zip(first), source_runtime_digest(ROOT))

    def test_runtime_module_byte_change_invalidates_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copytree(ROOT / "module", root / "module")
            before = source_runtime_digest(root)
            path = root / "module/otast.conf"
            path.write_bytes(path.read_bytes() + b"\n# runtime digest regression\n")
            self.assertNotEqual(before, source_runtime_digest(root))

    def test_stale_legacy_proof_cannot_be_reused(self) -> None:
        registry = load_qualification_registry(ROOT)
        record = registry["records"]["tegu-CP1A.260305.018-v1.0.3-legacy-proof"]
        result = proof_reuse_decision(record, current_runtime_digest="1" * 64, current_source_commit="2" * 40)
        self.assertFalse(result["reusable"])

    def test_root_exposure_external_attribution_is_accepted_without_mutation(self) -> None:
        report = {
            "read_only": True,
            "result": "PASS_WITH_WARNINGS",
            "fatal_reason": "",
            "findings": [
                {"category": "another reviewed module's exposure", "finding": "Vector mapping"},
                {"category": "another reviewed module's exposure", "finding": "Zygisk Next mapping"},
            ],
        }
        classified = classify_root_exposure_report(report)
        self.assertEqual(classified["result"], "PASS_WITH_ATTRIBUTION")

    def test_root_exposure_otast_failure_or_unknown_is_not_cosmetically_passed(self) -> None:
        fail = classify_root_exposure_report(
            {
                "read_only": True,
                "result": "PASS",
                "fatal_reason": "",
                "findings": [{"category": "OTAST-owned semantic inconsistency"}],
            }
        )
        self.assertEqual(fail["result"], "FAIL")
        unknown = classify_root_exposure_report(
            {
                "read_only": True,
                "result": "PASS_WITH_WARNINGS",
                "fatal_reason": "",
                "findings": [{"category": "unknown/needs investigation"}],
            }
        )
        self.assertEqual(unknown["result"], "INCONCLUSIVE")

    def test_qualification_registry_contains_no_key_material_fields(self) -> None:
        raw = (ROOT / "compatibility/qualification-registry.json").read_text(encoding="utf-8").lower()
        for forbidden in ("private_key", "privatekey", "certificate_chain", "keybox_xml"):
            self.assertNotIn(forbidden, raw)
        json.loads(raw)


if __name__ == "__main__":
    unittest.main()
