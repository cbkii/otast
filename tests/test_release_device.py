from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools.otastctl.build import build_module
from tools.otastctl.qualification import registry_provenance
from tools.otastctl.runtime_digest import RUNTIME_DIGEST_ALGORITHM, runtime_digest_from_zip
from tools.otastctl.util import sha256_file

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate-device-release-proof.py"
RELEASE_SCRIPT = ROOT / "scripts/release-device.sh"
LIFECYCLE_SCRIPT = ROOT / "scripts/release-device-lifecycle.sh"
TEST_COMMIT = "1" * 40


def load_validator():
    spec = importlib.util.spec_from_file_location("otast_release_proof_test", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReleaseDeviceTests(unittest.TestCase):
    def make_proof(self, root: Path, *, root_result: str = "PASS_WITH_ATTRIBUTION") -> tuple[Path, Path, dict[str, object]]:
        module = load_validator()
        module_zip = build_module(ROOT, root / "dist", commit_sha=TEST_COMMIT)
        with zipfile.ZipFile(module_zip) as archive:
            prop = {
                k: v
                for k, v in (
                    line.split("=", 1)
                    for line in archive.read("module.prop").decode("utf-8").splitlines()
                    if "=" in line
                )
            }
        reference = module.release_reference(ROOT)
        runtime_digest = runtime_digest_from_zip(module_zip)
        evidence = {
            "schema_version": 1,
            "result": "PASS",
            "read_only": True,
            "device": {
                "codename": reference["device"],
                "model": reference["model"],
                "manufacturer": reference["manufacturer"],
                "build_id": reference["build"],
                "fingerprint": reference["fingerprint"],
                "platform_profile": reference["platform_profile"],
                "sdk": str(reference["sdk"]),
                "sdk_full": "36.0",
                "system_spl": reference["system_spl"],
                "vendor_spl": reference["vendor_spl"],
                "authority_sha256": reference["authority_sha256"],
                "authority": reference["authority_boot"],
                "kernel": "Linux tegu 6.1-test",
                "runtime_page_size": "4096",
                "primary_abi": "arm64-v8a",
                "abi_list": "arm64-v8a,armeabi-v7a",
            },
            "magisk": {"version": "30.6:MAGISK:R", "version_code": "30600"},
            "managed_targets": {"playintegrityfix": {"module": {"id": "playintegrityfix", "version": "test"}}},
            "observed_dependencies": {
                "zygisk-next": {"module": {"id": "rezygisk", "version": "test"}},
                "vector": {"module": {"id": "vector", "version": "test"}},
                "inline-hook-invalidate": {"module": {"id": "inline_hook_invalidate", "version": "test"}},
            },
            "native_runtime_evidence": {
                "schema_version": 1,
                "collector": "runtime-compatibility-evidence",
                "read_only": True,
                "platform": {
                    "runtime_page_size": "4096",
                    "android_sdk": str(reference["sdk"]),
                },
                "modules": [
                    {"module_id": "rezygisk", "status": "AVAILABLE"},
                    {"module_id": "vector", "status": "AVAILABLE"},
                ],
            },
            "root_exposure_attribution": {"result": root_result, "reason": "fixture"},
            "external_acceptance": {
                "tricky_store_health": "PASS",
                "local_attestation": "PASS",
                "play_integrity": {"basic": "PASS", "device": "PASS", "strong": "PASS"},
                "play_store_certification": "CERTIFIED",
            },
            "validation_failures": [],
            "privacy": {
                "keybox_material_exported": False,
                "arbitrary_module_enumeration": False,
                "mutation_performed": False,
            },
        }
        value: dict[str, object] = {
            "schema_version": 4,
            "result": "PASS",
            "evidence_kind": "DIRECT_PHYSICAL",
            "version": prop["version"],
            "version_code": int(prop["versionCode"]),
            "qualified_source_commit": TEST_COMMIT,
            "current_source_commit": TEST_COMMIT,
            "qualified_zip_sha256": sha256_file(module_zip),
            "current_zip_sha256": sha256_file(module_zip),
            "runtime_digest_algorithm": RUNTIME_DIGEST_ALGORITHM,
            "runtime_digest": runtime_digest,
            "registry_provenance": registry_provenance(ROOT),
            "device_evidence": evidence,
            "installation_context": "UPGRADE_FROM_STABLE",
            "phases": {
                "baseline": "PASS",
                "install_reboot": "PASS",
                "preflight": "PASS",
                "apply": "PASS",
                "post_apply_reboot": "PASS",
                "verify": "PASS",
                "second_apply_noop": "PASS",
                "restore": "PASS",
                "restore_reboot_report": "PASS",
                "reapply": "PASS",
            },
            "generated_utc": "2026-09-03T00:00:00Z",
        }
        proof = root / f"otast-{prop['version']}-device-proof.json"
        proof.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return proof, module_zip, value

    @staticmethod
    def write_proof(proof: Path, value: dict[str, object]) -> None:
        proof.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_device_proof_accepts_exact_runtime_bound_contract(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            value = module.validate_proof(proof, module_zip, version=str(expected["version"]))
            self.assertEqual(value["current_zip_sha256"], sha256_file(module_zip))
            self.assertEqual(value["runtime_digest"], runtime_digest_from_zip(module_zip))

    def test_device_proof_rejects_legacy_schema(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["schema_version"] = 2
            self.write_proof(proof, value)
            with self.assertRaises(module.ProofError):
                module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_device_proof_rejects_runtime_or_zip_mismatch(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["runtime_digest"] = "0" * 64
            self.write_proof(proof, value)
            with self.assertRaises(module.ProofError):
                module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_device_proof_rejects_wrong_device_identity(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["device_evidence"]["device"]["codename"] = "shiba"
            self.write_proof(proof, value)
            with self.assertRaisesRegex(module.ProofError, "codename"):
                module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_device_proof_rejects_wrong_registry_provenance(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["registry_provenance"]["compatibility_registry_sha256"] = "0" * 64
            self.write_proof(proof, value)
            with self.assertRaisesRegex(module.ProofError, "registry provenance"):
                module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_device_proof_rejects_tampered_zip(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            with zipfile.ZipFile(module_zip, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("tampered.txt", b"tampered")
            with self.assertRaises(module.ProofError):
                module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_runtime_reuse_requires_current_qualification_record(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["evidence_kind"] = "RUNTIME_EQUIVALENT_REUSE"
            value["runtime_equivalence"] = {
                "result": "PASS",
                "qualified_runtime_digest": value["runtime_digest"],
                "current_runtime_digest": value["runtime_digest"],
                "ci_equivalence": "PASS",
            }
            self.write_proof(proof, value)
            with mock.patch.object(module, "find_current_qualification", return_value=None):
                with self.assertRaisesRegex(module.ProofError, "CURRENT qualification"):
                    module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_runtime_reuse_rejects_wrong_qualified_source_and_zip(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["evidence_kind"] = "RUNTIME_EQUIVALENT_REUSE"
            value["runtime_equivalence"] = {
                "result": "PASS",
                "qualified_runtime_digest": value["runtime_digest"],
                "current_runtime_digest": value["runtime_digest"],
                "ci_equivalence": "PASS",
                "qualification_record_id": "fixture",
            }
            self.write_proof(proof, value)
            record = {
                "qualified_source_commit": "2" * 40,
                "zip_sha256": "3" * 64,
            }
            with mock.patch.object(module, "find_current_qualification", return_value=("fixture", record)):
                with self.assertRaisesRegex(module.ProofError, "qualified source"):
                    module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_release_reference_rejects_empty_security_patch_authority(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            shutil.copytree(ROOT / "compatibility", repo / "compatibility")
            shutil.copytree(ROOT / "authority", repo / "authority")
            registry = json.loads((repo / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
            fixture = repo / str(registry["support_model"]["release_reference"]["authority_fixture"])
            text = fixture.read_text(encoding="utf-8")
            fixture.write_text(text.replace("ro.build.version.security_patch=2026-03-05", "ro.build.version.security_patch="), encoding="utf-8")
            with self.assertRaises(module.ProofError):
                module.release_reference(repo)

    def test_device_proof_accepts_attributed_external_root_findings(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw), root_result="PASS_WITH_ATTRIBUTION")
            value = module.validate_proof(proof, module_zip, version=str(expected["version"]))
            self.assertEqual(value["device_evidence"]["root_exposure_attribution"]["result"], "PASS_WITH_ATTRIBUTION")

    def test_device_proof_rejects_inconclusive_root_findings(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw), root_result="INCONCLUSIVE")
            with self.assertRaises(module.ProofError):
                module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_device_proof_rejects_missing_external_release_gate(self) -> None:
        module = load_validator()
        with tempfile.TemporaryDirectory() as raw:
            proof, module_zip, expected = self.make_proof(Path(raw))
            value = json.loads(proof.read_text(encoding="utf-8"))
            value["device_evidence"]["external_acceptance"]["play_integrity"]["strong"] = "FAIL"
            self.write_proof(proof, value)
            with self.assertRaises(module.ProofError):
                module.validate_proof(proof, module_zip, version=str(expected["version"]))

    def test_release_wizard_uses_canonical_versioning_and_single_workflow_api(self) -> None:
        text = RELEASE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("resolve_release_identity", text)
        self.assertIn('LIFECYCLE_SCRIPT="$SCRIPT_DIR/release-device-lifecycle.sh"', text)
        self.assertIn("operation=draft", text)
        self.assertIn("physical_proof=true", text)
        self.assertIn("full_validation=true", text)
        self.assertIn("full_validation=false", text)
        self.assertNotIn("action=prepare-release", text)
        self.assertNotIn("action=publish-release", text)
        self.assertIn('lifecycle_args+=(--version "$VERSION" --no-publish)', text)
        self.assertIn("Physical proof remains preserved", text)
        self.assertIn("mark_private_state_complete", text)
        self.assertIn("stable update.json", text)
        self.assertIn("versionCode remains automatic", text)
        self.assertIn("authoritative GitHub Release workflow", text)

    def test_release_lifecycle_is_registry_driven_and_runtime_bound(self) -> None:
        text = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("load_release_reference", text)
        self.assertNotIn("DEVICE != tegu", text)
        self.assertNotIn('"device": "tegu"', text)
        self.assertIn("runtime_digest=", text)
        self.assertIn("EVIDENCE_REQUIRED", text)
        self.assertIn("collect-device-qualification.py", text)
        self.assertIn("root-exposure.json", text)
        self.assertIn("external-acceptance.json", text)
        self.assertIn("REAPPLY_REBOOT", text)
        self.assertIn("second Apply did not reach NO_CHANGES_REQUIRED", text)
        self.assertIn("magisk --install-module", text)
        self.assertIn("run_boot_recover_best_effort", text)
        self.assertIn("persistent external writer conflict", text)
        self.assertIn("/proc/sys/kernel/random/boot_id", text)
        self.assertIn("validate-device-release-proof.py", text)
        self.assertIn("gh release upload", text)

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
