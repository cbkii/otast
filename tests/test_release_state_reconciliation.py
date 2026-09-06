from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/reconcile-release-state.py"
WRAPPER = ROOT / "scripts/release-device.sh"
VERSION = "v1.0.3"
OLD_SOURCE = "1" * 40
NEW_SOURCE = "2" * 40
OLD_ZIP = "3" * 64
RUNTIME = "4" * 64
PROOF_NAME = f"otast-{VERSION}-device-proof.json"


def load_module():
    spec = importlib.util.spec_from_file_location("otast_release_state_reconcile_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


class ReleaseStateReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    @staticmethod
    def write_state(state_dir: Path, *, phase: str, source: str = "", zip_sha: str = "", runtime: str = "") -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "assets").mkdir(exist_ok=True)
        (state_dir / "logs").mkdir(exist_ok=True)
        empty = "''"
        source_value = source or empty
        zip_value = zip_sha or empty
        runtime_value = runtime or empty
        (state_dir / "state.env").write_text(
            "\n".join(
                [
                    f"PHASE={phase}",
                    f"MODULE_SHA256={zip_value}",
                    f"RUNTIME_DIGEST={runtime_value}",
                    "BOOT_BEFORE=''",
                    "BASELINE_RESULT=NOT_REQUIRED",
                    f"SOURCE_SHA={source_value}",
                    "SETTLE_RETRIES=0",
                    "RESTORE_RETRIES=0",
                    "FIRST_APPLY_NOOP=0",
                    "REAPPLY_RESULT=''",
                    "INSTALL_CONTEXT=FRESH_INSTALL",
                    "ABORT_REASON=''",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def release(source: str, *, proof: bool = False) -> dict[str, object]:
        assets: list[dict[str, str]] = []
        if proof:
            assets.append({"name": PROOF_NAME})
        return {"isDraft": True, "targetCommitish": source, "assets": assets}

    def test_orphaned_active_state_without_remote_release_is_archived_whole(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-reconcile-") as raw:
            base = Path(raw) / "otast-release"
            state = base / VERSION
            base.mkdir(mode=0o700)
            self.write_state(state, phase="INSTALL_REBOOT", source=OLD_SOURCE, zip_sha=OLD_ZIP, runtime=RUNTIME)
            evidence = state / "root-exposure.json"
            evidence.write_text('{"kept":true}\n', encoding="utf-8")

            result = self.module.reconcile(
                state_dir=state,
                state_base=base,
                version=VERSION,
                release=None,
                proof_name=PROOF_NAME,
            )

            self.assertEqual(result["action"], "ARCHIVED")
            archive = Path(result["archive"])
            self.assertTrue((archive / "state.env").is_file())
            self.assertEqual((archive / "root-exposure.json").read_text(encoding="utf-8"), '{"kept":true}\n')
            self.assertTrue(state.is_dir())
            self.assertEqual(list(state.iterdir()), [])
            self.assertEqual(stat_mode(base / ".history"), 0o700)
            self.assertEqual(stat_mode(state), 0o700)

    def test_mismatched_unproven_draft_source_archives_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-reconcile-") as raw:
            base = Path(raw) / "otast-release"
            state = base / VERSION
            base.mkdir(mode=0o700)
            self.write_state(state, phase="BASELINE_REBOOT", source=OLD_SOURCE, zip_sha=OLD_ZIP, runtime=RUNTIME)

            result = self.module.reconcile(
                state_dir=state,
                state_base=base,
                version=VERSION,
                release=self.release(NEW_SOURCE),
                proof_name=PROOF_NAME,
            )

            self.assertEqual(result["action"], "ARCHIVED")
            self.assertEqual(result["local_source_commit"], OLD_SOURCE)
            self.assertEqual(result["hosted_source_commit"], NEW_SOURCE)
            self.assertIn("differs from hosted draft source", result["reason"])

    def test_matching_draft_source_preserves_resumable_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-reconcile-") as raw:
            base = Path(raw) / "otast-release"
            state = base / VERSION
            base.mkdir(mode=0o700)
            self.write_state(state, phase="APPLY_REBOOT", source=NEW_SOURCE, zip_sha=OLD_ZIP, runtime=RUNTIME)
            before = (state / "state.env").read_bytes()

            result = self.module.reconcile(
                state_dir=state,
                state_base=base,
                version=VERSION,
                release=self.release(NEW_SOURCE),
                proof_name=PROOF_NAME,
            )

            self.assertEqual(result["action"], "PRESERVE")
            self.assertEqual((state / "state.env").read_bytes(), before)
            self.assertFalse((base / ".history").exists())

    def test_remote_physical_proof_never_discards_local_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-reconcile-") as raw:
            base = Path(raw) / "otast-release"
            state = base / VERSION
            base.mkdir(mode=0o700)
            self.write_state(state, phase="PROOF_READY", source=OLD_SOURCE, zip_sha=OLD_ZIP, runtime=RUNTIME)

            result = self.module.reconcile(
                state_dir=state,
                state_base=base,
                version=VERSION,
                release=self.release(NEW_SOURCE, proof=True),
                proof_name=PROOF_NAME,
            )

            self.assertEqual(result["action"], "PRESERVE")
            self.assertTrue((state / "state.env").is_file())

    def test_active_state_without_source_binding_is_archived(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-reconcile-") as raw:
            base = Path(raw) / "otast-release"
            state = base / VERSION
            base.mkdir(mode=0o700)
            self.write_state(state, phase="INSTALL_REBOOT", zip_sha=OLD_ZIP, runtime=RUNTIME)

            result = self.module.reconcile(
                state_dir=state,
                state_base=base,
                version=VERSION,
                release=self.release(NEW_SOURCE),
                proof_name=PROOF_NAME,
            )

            self.assertEqual(result["action"], "ARCHIVED")
            self.assertIn("no exact hosted-draft source binding", result["reason"])

    def test_symlinked_state_component_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-reconcile-") as raw:
            base = Path(raw) / "otast-release"
            state = base / VERSION
            base.mkdir(mode=0o700)
            self.write_state(state, phase="INSTALL_REBOOT", source=OLD_SOURCE, zip_sha=OLD_ZIP, runtime=RUNTIME)
            outside = Path(raw) / "outside"
            outside.mkdir()
            (state / "unsafe").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(self.module.ReconcileError, "symlink"):
                self.module.reconcile(
                    state_dir=state,
                    state_base=base,
                    version=VERSION,
                    release=self.release(NEW_SOURCE),
                    proof_name=PROOF_NAME,
                )

    def test_wrapper_queries_source_and_invokes_reconciler_before_lifecycle(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("isDraft,assets,targetCommitish", text)
        self.assertIn("reconcile-release-state.py", text)
        self.assertIn("Reconciled orphaned local qualification state", text)
        self.assertLess(text.index("reconcile-release-state.py"), text.index("Entering bounded, resumable physical-device qualification."))


if __name__ == "__main__":
    unittest.main()
