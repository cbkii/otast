from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate-device-release-proof.py"
RELEASE_SCRIPT = ROOT / "scripts/release-device.sh"
LIFECYCLE_SCRIPT = ROOT / "scripts/release-device-lifecycle.sh"


def load_validator():
    spec = importlib.util.spec_from_file_location("otast_release_proof_test", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReleaseDeviceTests(unittest.TestCase):
    def make_proof(self, root: Path, *, apply_result: str = "PASS") -> tuple[Path, Path, str]:
        module_zip = root / "otast-v1.0.0.zip"
        with zipfile.ZipFile(module_zip, "w") as archive:
            archive.writestr("module.prop", "id=otast\nversion=v1.0.0\n")
            archive.writestr(
                "release.properties",
                "schema_version=1\nversion=v1.0.0\nversion_code=100004\ncommit_sha=diagnostic-only\n",
            )
        module_sha = hashlib.sha256(module_zip.read_bytes()).hexdigest()
        proof = root / "otast-v1.0.0-device-proof.json"
        proof.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "result": "PASS",
                    "version": "v1.0.0",
                    "source_commit": "diagnostic-only",
                    "module_sha256": module_sha,
                    "device": "tegu",
                    "sdk": 36,
                    "phases": {
                        "baseline": "NOT_REQUIRED",
                        "install_reboot": "PASS",
                        "apply_reboot": apply_result,
                        "verify_noop_restore": "PASS",
                        "restore_reboot_report": "PASS",
                    },
                    "generated_utc": "2026-08-10T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return proof, module_zip, module_sha

    def test_device_proof_accepts_asset_bound_contract_without_commit_gate(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, module_sha = self.make_proof(Path(raw))
            value = module.validate_proof(proof, module_zip, version="v1.0.0")
            self.assertEqual(value["module_sha256"], module_sha)

    def test_device_proof_accepts_schema1_only_as_asset_bound_migration(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, module_sha = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["schema_version"] = 1
            value.pop("source_commit", None)
            value["commit_sha"] = "this-legacy-commit-is-diagnostic-only"
            proof.write_text(json.dumps(value) + "\n", encoding="utf-8")

            accepted = module.validate_proof(proof, module_zip, version="v1.0.0")
            self.assertEqual(accepted["module_sha256"], module_sha)

            module_zip.write_bytes(module_zip.read_bytes() + b"different")
            with self.assertRaises(module.ProofError):
                module.validate_proof(proof, module_zip, version="v1.0.0")

    def test_device_proof_accepts_already_current_first_apply(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, _ = self.make_proof(Path(raw), apply_result="SKIPPED_NO_CHANGES")
            value = module.validate_proof(proof, module_zip, version="v1.0.0")
            self.assertEqual(value["phases"]["apply_reboot"], "SKIPPED_NO_CHANGES")

    def test_device_proof_rejects_asset_hash_mismatch(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, _ = self.make_proof(Path(raw))
            module_zip.write_bytes(module_zip.read_bytes() + b"different")
            with self.assertRaises(module.ProofError):
                module.validate_proof(proof, module_zip, version="v1.0.0")

    def test_device_proof_rejects_missing_noop_restore_phase(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, _ = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["phases"]["verify_noop_restore"] = "FAILED"
            proof.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(module.ProofError):
                module.validate_proof(proof, module_zip, version="v1.0.0")

    def test_release_wizard_uses_canonical_versioning_and_new_workflow_api(self) -> None:
        text = RELEASE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("resolve_release_identity", text)
        self.assertIn('LIFECYCLE_SCRIPT="$SCRIPT_DIR/release-device-lifecycle.sh"', text)
        self.assertIn("operation=draft", text)
        self.assertIn("action=prepare-release", text)
        self.assertIn("action=publish-release", text)
        self.assertIn("full_validation=true", text)
        self.assertIn('legacy_args+=(--version "$VERSION" --no-publish)', text)
        self.assertIn("Physical proof remains preserved", text)
        self.assertIn("mark_private_state_complete", text)
        self.assertIn("stable update.json", text)
        self.assertIn("versionCode remains automatic", text)
        self.assertNotIn("LEGACY_RELEASE_COMMIT", text)
        self.assertNotIn("contents/scripts/release-device.sh?ref=", text)

    def test_release_wizard_preserves_proven_lifecycle_in_current_source(self) -> None:
        wrapper = RELEASE_SCRIPT.read_text(encoding="utf-8")
        lifecycle = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
        self.assertTrue(LIFECYCLE_SCRIPT.is_file())
        self.assertFalse(LIFECYCLE_SCRIPT.is_symlink())
        self.assertIn('bash "$LIFECYCLE_SCRIPT"', wrapper)
        for token in (
            "physical release proof requires tegu / SDK 36",
            "magisk --install-module",
            "run_boot_recover_best_effort",
            "Apply failed; recovering transaction state and retrying once",
            "Restore failed; attempting boot-recover and one retry",
            "persistent external writer conflict",
            "NO_CHANGES_REQUIRED",
            "REBOOT_REQUIRED",
            "/proc/sys/kernel/random/boot_id",
            "validate-device-release-proof.py",
            "gh release upload",
        ):
            self.assertIn(token, lifecycle)
        self.assertNotIn("magisk --install-module", wrapper)
        self.assertNotIn("runtime/entry.sh apply", wrapper)

    def test_release_wizard_retries_partial_publication_without_requalification(self) -> None:
        text = RELEASE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("A previous publish attempt may have made the exact proven release public", text)
        self.assertIn("has_proof == yes && $is_draft == false", text)
        self.assertIn("dispatch_publication", text)
        first_public_check = text.index("has_proof == yes && $is_draft == false")
        lifecycle_run = text.index('bash "$LIFECYCLE_SCRIPT"')
        self.assertLess(first_public_check, lifecycle_run)

    def test_release_wizard_help_needs_no_device_or_network(self) -> None:
        result = subprocess.run(
            ["bash", str(RELEASE_SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("automatic next", result.stdout)
        self.assertIn("versionCode remains automatic", result.stdout)
        self.assertIn("otast release", result.stdout)
        self.assertIn("--no-publish", result.stdout)


if __name__ == "__main__":
    unittest.main()
