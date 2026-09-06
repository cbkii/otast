from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release-target-gate.py"


def load_module():
    spec = importlib.util.spec_from_file_location("otast_release_target_gate_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReleaseTargetGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.registry = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))

    def monitor(self, target: str, status: str) -> dict[str, object]:
        record = self.registry["targets"][target]
        monitor = record["monitor"]
        return {
            "schema_version": 2,
            "result": "REVIEW_REQUIRED" if status != "supported" else "SUPPORTED",
            "targets": [
                {
                    "target": target,
                    "repository": monitor["repository"],
                    "ref": monitor.get("branch", monitor.get("ref", "main")),
                    "expected_head": monitor["expected_head"],
                    "observed_head": "f" * 40,
                    "status": status,
                    "error": "",
                }
            ],
        }

    def fetch_for_trickystore(self, url: str) -> dict[str, object]:
        distribution = self.registry["targets"]["trickystore"]["distribution_identity"]
        if "/commits/" in url:
            return {"sha": distribution["reviewed_commit"]}
        if "/releases/tags/" in url:
            return {
                "draft": False,
                "tag_name": distribution["release"],
                "assets": [
                    {
                        "name": distribution["asset_name"],
                        "digest": f"sha256:{distribution['asset_sha256']}",
                    }
                ],
            }
        raise AssertionError(url)

    def test_release_asset_branch_drift_is_advisory_when_pinned_artifact_is_exact(self) -> None:
        rc, result = self.module.evaluate(
            ROOT,
            self.monitor("trickystore", "review-required"),
            fetch=self.fetch_for_trickystore,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(result["result"], "PASS")
        row = result["targets"][0]
        self.assertEqual(row["release_status"], "pinned-artifact-supported")
        self.assertTrue(row["advisory_branch_drift"])

    def test_branch_built_target_drift_still_blocks_release(self) -> None:
        rc, result = self.module.evaluate(
            ROOT,
            self.monitor("playintegrityfix", "review-required"),
            fetch=lambda _: self.fail("branch target must not use release-asset lookup"),
        )
        self.assertEqual(rc, 10)
        self.assertEqual(result["result"], "REVIEW_REQUIRED")
        self.assertEqual(result["targets"][0]["release_status"], "review-required")

    def test_release_asset_digest_mismatch_fails_closed(self) -> None:
        def fetch(url: str) -> dict[str, object]:
            value = self.fetch_for_trickystore(url)
            if "/releases/tags/" in url:
                value["assets"][0]["digest"] = "sha256:" + "0" * 64  # type: ignore[index]
            return value

        with self.assertRaisesRegex(self.module.GateError, "digest changed"):
            self.module.evaluate(
                ROOT,
                self.monitor("trickystore", "review-required"),
                fetch=fetch,
            )

    def test_release_tag_movement_fails_closed(self) -> None:
        def fetch(url: str) -> dict[str, object]:
            if "/commits/" in url:
                return {"sha": "0" * 40}
            return self.fetch_for_trickystore(url)

        with self.assertRaisesRegex(self.module.GateError, "release ref moved"):
            self.module.evaluate(
                ROOT,
                self.monitor("trickystore", "review-required"),
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
