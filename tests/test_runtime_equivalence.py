from __future__ import annotations

import unittest

from tools.otastctl.qualification import proof_reuse_decision


class RuntimeEquivalenceTests(unittest.TestCase):
    def test_identical_runtime_digest_preserves_qualified_and_current_source_provenance(self) -> None:
        digest = "a" * 64
        qualified_source = "b" * 40
        current_source = "c" * 40
        record = {
            "current_state": "CURRENT",
            "runtime_digest": digest,
            "qualified_source_commit": qualified_source,
        }

        decision = proof_reuse_decision(
            record,
            current_runtime_digest=digest,
            current_source_commit=current_source,
        )

        self.assertTrue(decision["reusable"])
        self.assertEqual(decision["qualified_source_commit"], qualified_source)
        self.assertEqual(decision["current_source_commit"], current_source)
        self.assertEqual(decision["runtime_digest"], digest)

    def test_changed_runtime_digest_invalidates_reuse(self) -> None:
        record = {
            "current_state": "CURRENT",
            "runtime_digest": "a" * 64,
            "qualified_source_commit": "b" * 40,
        }
        decision = proof_reuse_decision(
            record,
            current_runtime_digest="d" * 64,
            current_source_commit="c" * 40,
        )
        self.assertFalse(decision["reusable"])
        self.assertEqual(decision["reason"], "runtime payload digest changed")

    def test_unbound_or_stale_record_cannot_be_reused(self) -> None:
        decision = proof_reuse_decision(
            {
                "current_state": "STALE_RUNTIME_DIGEST_UNBOUND",
                "runtime_digest": None,
                "qualified_source_commit": "b" * 40,
            },
            current_runtime_digest="a" * 64,
            current_source_commit="c" * 40,
        )
        self.assertFalse(decision["reusable"])
        self.assertIn("not CURRENT/runtime-bound", decision["reason"])


if __name__ == "__main__":
    unittest.main()
