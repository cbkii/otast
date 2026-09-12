from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.capabilities import render_capability_ownership, validate_capabilities

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/upstream"


class CapabilityOwnershipTests(unittest.TestCase):
    def test_capability_registry_and_generated_document_are_current(self) -> None:
        result = validate_capabilities(ROOT)
        self.assertEqual(result["schema_version"], 1)
        self.assertIn("pif_profile", result["exclusive_capabilities"])
        self.assertIn("package_provenance", result["exclusive_capabilities"])
        self.assertEqual(
            (ROOT / "docs/CAPABILITY-OWNERSHIP.md").read_text(encoding="utf-8"),
            render_capability_ownership(ROOT),
        )

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
        installer = (ROOT / "module/customize.sh").read_text(encoding="utf-8")
        self.assertIn("runtime/capabilities-v3.sh", installer)


if __name__ == "__main__":
    unittest.main()
