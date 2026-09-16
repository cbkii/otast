from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.capabilities import render_capability_ownership, validate_capabilities
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/upstream"


class CapabilityOwnershipTests(unittest.TestCase):
    def test_capability_registry_and_generated_document_are_current(self) -> None:
        result = validate_capabilities(ROOT)
        self.assertEqual(result["schema_version"], 1)
        self.assertIn("pif_profile", result["exclusive_capabilities"])
        self.assertIn("package_provenance", result["exclusive_capabilities"])
        self.assertEqual(result["direct_writers"]["pif_profile"], ["playintegrityfix"])
        self.assertEqual(result["direct_writers"]["platform_system_spl"], ["otast"])
        self.assertEqual(
            (ROOT / "docs/CAPABILITY-OWNERSHIP.md").read_text(encoding="utf-8"),
            render_capability_ownership(ROOT),
        )

    def test_static_registry_rejects_two_direct_integrations_for_exclusive_capability(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-cap-registry-") as raw:
            root = Path(raw)
            (root / "compatibility").mkdir()
            (root / "docs").mkdir()
            shutil.copy2(ROOT / "compatibility/supported-targets.json", root / "compatibility/supported-targets.json")
            document = json.loads((ROOT / "compatibility/capabilities.json").read_text(encoding="utf-8"))
            document["integrations"]["second-pif-writer"] = {
                "role": "PROVIDER",
                "module_ids": ["second_pif_writer"],
                "writes": ["pif_profile"],
            }
            (root / "compatibility/capabilities.json").write_text(
                json.dumps(document, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(OtastError, "exclusive capability has multiple direct writer integrations"):
                validate_capabilities(root)

    def test_runtime_writer_table_matches_registry_except_protected_non_targets(self) -> None:
        registry = json.loads((ROOT / "compatibility/capabilities.json").read_text(encoding="utf-8"))
        supported = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        strict = set(supported["strict_exclusions"])
        expected_integrations: dict[str, dict[str, set[str]]] = {}
        for integration_id, record in registry["integrations"].items():
            writes = set(record.get("writes", []))
            if not writes:
                continue
            module_ids = set(record.get("module_ids", []))
            if module_ids & strict:
                continue
            expected_integrations[integration_id] = {
                "module_ids": module_ids,
                "writes": writes,
            }
        expected_exclusive = {
            capability_id
            for capability_id, record in registry["capabilities"].items()
            if record.get("exclusive") is True
        }

        runtime = ROOT / "module/runtime/capabilities-v3.sh"
        command = f'''
            ADB_ROOT=/data/adb
            otast_stop() {{ :; }}
            . "{runtime}" || exit 1
            for integration in $(_otast_cap_writer_integrations); do
              printf 'integration=%s\\n' "$integration"
              for module_id in $(_otast_cap_integration_module_ids "$integration"); do
                printf 'module=%s:%s\\n' "$integration" "$module_id"
              done
              for capability in $(_otast_cap_integration_writes "$integration"); do
                printf 'write=%s:%s\\n' "$integration" "$capability"
              done
            done
            for capability in $(_otast_cap_exclusive_ids); do
              printf 'exclusive=%s\\n' "$capability"
            done
        '''
        result = subprocess.run(
            ["busybox", "sh", "-c", command],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            timeout=20,
        )
        actual_integrations: set[str] = set()
        actual_modules: dict[str, set[str]] = {}
        actual_writes: dict[str, set[str]] = {}
        actual_exclusive: set[str] = set()
        for line in result.stdout.splitlines():
            if line.startswith("integration="):
                integration = line.split("=", 1)[1]
                actual_integrations.add(integration)
                actual_modules.setdefault(integration, set())
                actual_writes.setdefault(integration, set())
            elif line.startswith("module="):
                integration, module_id = line.split("=", 1)[1].split(":", 1)
                actual_modules.setdefault(integration, set()).add(module_id)
            elif line.startswith("write="):
                integration, capability = line.split("=", 1)[1].split(":", 1)
                actual_writes.setdefault(integration, set()).add(capability)
            elif line.startswith("exclusive="):
                actual_exclusive.add(line.split("=", 1)[1])
            else:
                self.fail(f"unexpected runtime capability parity output: {line}")

        self.assertEqual(actual_integrations, set(expected_integrations))
        self.assertEqual(actual_exclusive, expected_exclusive)
        for integration_id, expected in expected_integrations.items():
            self.assertEqual(actual_modules.get(integration_id, set()), expected["module_ids"])
            self.assertEqual(actual_writes.get(integration_id, set()), expected["writes"])

    def test_ash_and_bki_are_write_protected_non_targets_not_hard_stop_identity_governors(self) -> None:
        registry = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        capabilities = json.loads((ROOT / "compatibility/capabilities.json").read_text(encoding="utf-8"))
        self.assertNotIn("legacy-identity-governors", registry["conflicts"])
        protected = registry["conflicts"]["protected-non-targets"]
        self.assertEqual(protected["severity"], "REVIEW_REQUIRED")
        self.assertNotEqual(protected["severity"], "HARD_STOP")
        self.assertEqual(set(protected["module_ids"]), set(registry["strict_exclusions"]))
        self.assertEqual(capabilities["integrations"]["ashrexcue"]["role"], "NON_TARGET_OPERATIONAL_DEPENDENCY")
        self.assertEqual(capabilities["integrations"]["better-known-installed"]["role"], "NON_TARGET_PROVIDER")
        self.assertEqual(capabilities["integrations"]["better-known-installed"]["writes"], ["package_provenance"])

    def test_legacy_writers_are_compatibility_adapters_not_preferred_owners(self) -> None:
        registry = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        capabilities = json.loads((ROOT / "compatibility/capabilities.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["targets"]["ta-utl"]["management_role"], "COMPATIBILITY_ADAPTER")
        self.assertEqual(registry["targets"]["yurikey"]["management_role"], "LEGACY_COMPATIBILITY_ADAPTER")
        self.assertFalse(registry["targets"]["yurikey"]["preferred"])
        self.assertEqual(registry["targets"]["vbmeta-fixer"]["management_role"], "LEGACY_COMPATIBILITY_ADAPTER")
        self.assertFalse(registry["targets"]["vbmeta-fixer"]["preferred"])
        self.assertIn("yurikey", capabilities["preferred_stack"]["not_preferred"])
        self.assertIn("vbmeta-fixer", capabilities["preferred_stack"]["not_preferred"])

    def test_runtime_generic_conflict_handles_disable_staged_and_report_only(self) -> None:
        common = ROOT / "module/runtime/common.sh"
        runtime = ROOT / "module/runtime/capabilities-v3.sh"
        with tempfile.TemporaryDirectory(prefix="otast-cap-runtime-") as raw:
            adb_root = Path(raw) / "data/adb"
            active = adb_root / "modules"
            staged = adb_root / "modules_update"
            (active / "synthetic_zygisk_a").mkdir(parents=True)
            (active / "synthetic_zygisk_b").mkdir(parents=True)
            command = f'''
                ADB_ROOT="{adb_root}"
                . "{common}" || exit 1
                . "{runtime}" || exit 2
                _otast_cap_writer_integrations() {{ printf '%s\\n' provider-a provider-b; }}
                _otast_cap_integration_module_ids() {{
                  case "$1" in
                    provider-a) printf '%s\\n' synthetic_zygisk_a ;;
                    provider-b) printf '%s\\n' synthetic_zygisk_b ;;
                    *) return 1 ;;
                  esac
                }}
                _otast_cap_integration_writes() {{
                  case "$1" in
                    provider-a|provider-b) printf '%s\\n' zygisk_provider ;;
                    *) return 1 ;;
                  esac
                }}
                if otast_validate_capability_ownership; then exit 10; fi
                OTAST_CAPABILITY_REPORT_ONLY=1
                otast_validate_capability_ownership || exit 11
                case "$OTAST_CAPABILITY_LAST_CONFLICT" in *zygisk_provider*) ;; *) exit 12 ;; esac
                OTAST_CAPABILITY_REPORT_ONLY=0
                touch "$ADB_ROOT/modules/synthetic_zygisk_b/disable" || exit 13
                otast_validate_capability_ownership || exit 14
                mkdir -p "$ADB_ROOT/modules_update/synthetic_zygisk_a" || exit 15
                otast_validate_capability_ownership || exit 16
                rm -f "$ADB_ROOT/modules/synthetic_zygisk_b/disable" || exit 17
                touch "$ADB_ROOT/modules/synthetic_zygisk_b/remove" || exit 18
                otast_validate_capability_ownership || exit 19
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)
            self.assertTrue((staged / "synthetic_zygisk_a").is_dir())

    def test_runtime_does_not_name_strict_exclusion_non_targets(self) -> None:
        runtime = (ROOT / "module/runtime/capabilities-v3.sh").read_text(encoding="utf-8")
        registry = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        for module_id in registry["strict_exclusions"]:
            self.assertNotIn(module_id, runtime)

    @staticmethod
    def _transform_ta(source: Path, output: Path) -> None:
        pif_runtime = ROOT / "module/runtime/pif.sh"
        ta_runtime = ROOT / "module/runtime/ta.sh"
        command = f'''
            ADB_ROOT=/data/adb
            otast_stop() {{ printf '%s\\n' "$*" >&2; }}
            . "{pif_runtime}" || exit 1
            . "{ta_runtime}" || exit 2
            otast_transform_ta_prop "{source}" "{output}" || exit 3
        '''
        subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)

    def test_effective_ta_transform_moves_disable_guard_before_every_fixture_property_writer(self) -> None:
        fixture = FIXTURES / "ta-utl-prop-v4.4.sh"
        with tempfile.TemporaryDirectory(prefix="otast-cap-ta-") as raw:
            output = Path(raw) / "prop.out"
            self._transform_ta(fixture, output)
            text = output.read_text(encoding="utf-8")
            guard = text.index("# --- otast target-only prop guard BEGIN ---")
            first_runtime_write = text.index("resetprop -w sys.boot_completed 0")
            sensitive = text.index('check_reset_prop "ro.boot.verifiedbootstate" "green"')
            self.assertLess(guard, first_runtime_write)
            self.assertLess(guard, sensitive)
            self.assertIn('if [ -f "/data/adb/disable_prop_handler" ]; then', text)
            self.assertIn("# --- otast vbmeta ownership BEGIN ---", text)

    def test_prior_v2_ta_adapter_is_migrated_without_requiring_removed_upstream_block(self) -> None:
        fixture = FIXTURES / "ta-utl-prop-v4.4.sh"
        with tempfile.TemporaryDirectory(prefix="otast-cap-ta-migrate-") as raw:
            root = Path(raw)
            current = root / "current.sh"
            self._transform_ta(fixture, current)
            text = current.read_text(encoding="utf-8")
            begin = text.index("# --- otast target-only prop guard BEGIN ---")
            end_marker = "# --- otast target-only prop guard END ---\n"
            end = text.index(end_marker, begin) + len(end_marker)
            prior = root / "prior-v2.sh"
            prior.write_text(text[:begin] + text[end:], encoding="utf-8")
            prior.chmod(0o755)
            self.assertIn("# --- otast vbmeta ownership BEGIN ---", prior.read_text(encoding="utf-8"))
            self.assertNotIn("# Reset vbmeta related prop", prior.read_text(encoding="utf-8"))

            migrated = root / "migrated.sh"
            self._transform_ta(prior, migrated)
            migrated_text = migrated.read_text(encoding="utf-8")
            self.assertIn("# --- otast target-only prop guard BEGIN ---", migrated_text)
            self.assertIn("# --- otast vbmeta ownership BEGIN ---", migrated_text)
            self.assertNotIn("# Reset vbmeta related prop", migrated_text)

    def test_ta_guard_is_transactionally_managed_and_webui_writer_remains_neutralized(self) -> None:
        runtime = (ROOT / "module/runtime/capabilities-v3.sh").read_text(encoding="utf-8")
        registry = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        self.assertIn("otast_plan_add ta-disable-prop-handler", runtime)
        self.assertIn("otast_transform_ta_webui_boot_hash", runtime)
        self.assertIn("/data/adb/disable_prop_handler", registry["targets"]["ta-utl"]["managed_paths"])

    def test_pif_configuration_only_simplification_is_intentionally_rejected(self) -> None:
        arch = (ROOT / "module/runtime/architecture-v2.sh").read_text(encoding="utf-8")
        capabilities = json.loads((ROOT / "compatibility/capabilities.json").read_text(encoding="utf-8"))
        self.assertIn("otast_transform_pif_security_patch", arch)
        self.assertIn("MARKER_PRESERVED_WRITES_SUPPRESSED", arch)
        self.assertIn("trickystore_patch", capabilities["integrations"]["otast"]["writes"])
        self.assertIn("global_sensitive_props", capabilities["integrations"]["playintegrityfix"]["writes"])
        self.assertIn("PIF profile patch retained; competing TrickyStore writer suppressed", arch)

    def test_runtime_sources_capability_layer_after_pr41_state_machine(self) -> None:
        entry = (ROOT / "module/runtime/entry.sh").read_text(encoding="utf-8")
        self.assertLess(entry.index('pif-migration-v2.sh'), entry.index('capabilities-v3.sh'))
        self.assertLess(entry.index('capabilities-v3.sh'), entry.index('report.sh'))
        self.assertIn("otast_validate_capability_ownership", entry)
        self.assertIn("otast_verify_capability_ownership", entry)
        self.assertIn("otast_report_capability_ownership", entry)
        self.assertIn("OTAST_CAPABILITY_REPORT_ONLY=1", entry)
        installer = (ROOT / "module/customize.sh").read_text(encoding="utf-8")
        self.assertIn("runtime/capabilities-v3.sh", installer)


if __name__ == "__main__":
    unittest.main()
