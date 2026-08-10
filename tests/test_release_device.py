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


def load_validator():
    spec = importlib.util.spec_from_file_location("otast_release_proof_test", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReleaseDeviceTests(unittest.TestCase):
    def make_proof(self, root: Path) -> tuple[Path, Path, str, str]:
        module_zip = root / "otast-v1.0.0.zip"
        commit = "9" * 40
        with zipfile.ZipFile(module_zip, "w") as archive:
            archive.writestr("module.prop", "id=otast\nversion=v1.0.0\n")
            archive.writestr(
                "release.properties",
                f"schema_version=1\nversion=v1.0.0\nversion_code=100004\ncommit_sha={commit}\n",
            )
        module_sha = hashlib.sha256(module_zip.read_bytes()).hexdigest()
        proof = root / "otast-v1.0.0-device-proof.json"
        proof.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "result": "PASS",
                    "version": "v1.0.0",
                    "commit_sha": commit,
                    "module_sha256": module_sha,
                    "device": "tegu",
                    "sdk": 36,
                    "phases": {
                        "baseline": "NOT_REQUIRED",
                        "install_reboot": "PASS",
                        "apply_reboot": "PASS",
                        "verify_noop_restore": "PASS",
                        "restore_reboot_report": "PASS",
                    },
                    "generated_utc": "2026-08-10T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return proof, module_zip, module_sha, commit

    def test_device_proof_accepts_exact_sanitized_contract(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, module_sha, commit = self.make_proof(Path(raw))
            value = module.validate_proof(
                proof,
                module_zip,
                version="v1.0.0",
                commit_sha=commit,
            )
            self.assertEqual(value["module_sha256"], module_sha)

    def test_device_proof_rejects_asset_hash_mismatch(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, _, commit = self.make_proof(Path(raw))
            module_zip.write_bytes(module_zip.read_bytes() + b"different")
            with self.assertRaises(module.ProofError):
                module.validate_proof(
                    proof,
                    module_zip,
                    version="v1.0.0",
                    commit_sha=commit,
                )

    def test_device_proof_rejects_missing_noop_phase(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, _, commit = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["phases"]["verify_noop_restore"] = "FAILED"
            proof.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(module.ProofError):
                module.validate_proof(
                    proof,
                    module_zip,
                    version="v1.0.0",
                    commit_sha=commit,
                )

    def test_release_wizard_has_fail_closed_phase_contract(self) -> None:
        text = RELEASE_SCRIPT.read_text(encoding="utf-8")
        for token in (
            "BASELINE_REBOOT",
            "INSTALL_REBOOT",
            "APPLY_REBOOT",
            "RESTORE_REBOOT",
            "PROOF_READY",
            "NO_CHANGES_REQUIRED",
            "REBOOT_REQUIRED",
            "/proc/sys/kernel/random/boot_id",
            "magisk --install-module",
            "validate-device-release-proof.py",
            "gh release upload",
            "dispatch_release_workflow publish",
        ):
            self.assertIn(token, text)
        self.assertIn("existing managed state is not CURRENT", text)
        self.assertIn("managed state remains after Restore/reboot", text)

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
        self.assertIn("after each requested reboot", result.stdout)


if __name__ == "__main__":
    unittest.main()
