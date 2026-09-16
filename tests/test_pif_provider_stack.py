from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.pif_providers import (
    classify_provider_changed_paths,
    validate_pif_providers,
)
from tools.otastctl.stack_observers import validate_stack_observers

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "module/runtime/common.sh"
PROVIDER = ROOT / "module/runtime/pif-provider-v4.sh"
CAPABILITIES = ROOT / "module/runtime/capabilities-v3.sh"
OBSERVERS = ROOT / "module/runtime/stack-observers-v4.sh"

INJECT_MODULE_PROP = """id=playintegrityfix
name=Play Integrity Fix [INJECT]
version=v4.7-1-inject-s
versionCode=471
author=chiteroman, KOWX712
description=Universal modular fix for Play Integrity on devices running Android 8-17
updateJson=https://fastly.jsdelivr.net/gh/KOWX712/playintegrityfix@inject_s/update.json
"""
FORK_MODULE_PROP = """id=playintegrityfix
name=Play Integrity Fork
version=v18
versionCode=180000
author=osm0sis & chiteroman @ xda-developers
description=Fix Play Integrity <A13 verdicts and Google Wallet/RCS on Android 7+
updateJson=https://raw.githubusercontent.com/osm0sis/PlayIntegrityFork/main/update.json
"""
VALID_FORK_PROP = """MANUFACTURER=Google
MODEL=Pixel 9a
FINGERPRINT=google/tegu_beta/tegu:CANARY/ABC/123:user/release-keys
SECURITY_PATCH=2026-08-05
*.security_patch=2026-08-05
spoofBuild=1
spoofProps=0
spoofProvider=0
spoofSignature=0
spoofVendingFinger=0
spoofVendingSdk=0
verboseLogs=0
"""


def run_ash(command: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["busybox", "sh", "-c", command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
        timeout=30,
    )


class PifProviderStackTests(unittest.TestCase):
    def test_provider_registry_and_stack_observer_registry_validate(self) -> None:
        providers = validate_pif_providers(ROOT)
        self.assertEqual(providers["preferred_provider"], "kowx-inject-s")
        self.assertEqual(
            providers["providers"]["osm0sis-fork-v18"]["status"],
            "SUPPORTED_CANDIDATE_PHYSICAL_QUALIFICATION_REQUIRED",
        )
        observers = validate_stack_observers(ROOT)
        self.assertEqual(observers["zygisk_module_providers"], ["rezygisk", "zygisksu"])

    def test_semantic_provider_impact_fails_closed_for_writer_and_unknown_changes(self) -> None:
        registry = json.loads((ROOT / "compatibility/pif-providers.json").read_text(encoding="utf-8"))
        fork = registry["providers"]["osm0sis-fork-v18"]
        docs = classify_provider_changed_paths(fork, ["README.md"])
        self.assertEqual(docs["impact"], "DOCS_OR_CI_ONLY")
        self.assertTrue(docs["automatic_promotion_allowed"])
        writer = classify_provider_changed_paths(fork, ["module/autopif4.sh"])
        self.assertEqual(writer["impact"], "TARGET_WRITER")
        self.assertTrue(writer["requires_review"])
        unknown = classify_provider_changed_paths(fork, ["module/new-unclassified-runtime.bin"])
        self.assertEqual(unknown["impact"], "AMBIGUOUS_UNKNOWN_WRITER_BEHAVIOR")
        self.assertFalse(unknown["automatic_promotion_allowed"])
        removed = classify_provider_changed_paths(
            fork,
            ["module/autopif4.sh"],
            removed_paths=["module/autopif4.sh"],
        )
        self.assertEqual(removed["impact"], "REMOVED_WRITER_CAPABILITY")

    def _provider_state(self, active: str | None, staged: str | None, *, disable_active: bool = False) -> str:
        with tempfile.TemporaryDirectory(prefix="otast-provider-detect-") as raw:
            adb = Path(raw) / "data/adb"
            for role, content in (("modules", active), ("modules_update", staged)):
                if content is None:
                    continue
                directory = adb / role / "playintegrityfix"
                directory.mkdir(parents=True)
                (directory / "module.prop").write_text(content, encoding="utf-8")
            if disable_active and active is not None:
                (adb / "modules/playintegrityfix/disable").touch()
            command = f'''
                ADB_ROOT="{adb}"
                OTAST_STATE_ROOT="$ADB_ROOT/otast"
                OTAST_TMP_ROOT="$OTAST_STATE_ROOT/tmp"
                . "{COMMON}" || exit 1
                . "{PROVIDER}" || exit 2
                printf '%s|%s|%s|%s\\n' "$OTAST_PIF_PROVIDER" "$OTAST_PIF_PROVIDER_ACTIVE" "$OTAST_PIF_PROVIDER_STAGED" "$OTAST_PIF_PROVIDER_CONFLICT"
            '''
            return run_ash(command).stdout.strip()

    def test_exact_provider_detection_and_same_provider_staging(self) -> None:
        self.assertEqual(
            self._provider_state(INJECT_MODULE_PROP, None),
            "KOWX_INJECT_S|KOWX_INJECT_S|NONE|NONE",
        )
        self.assertEqual(
            self._provider_state(FORK_MODULE_PROP, FORK_MODULE_PROP),
            "OSM0SIS_FORK_V18|OSM0SIS_FORK_V18|OSM0SIS_FORK_V18|NONE",
        )
        self.assertEqual(
            self._provider_state(FORK_MODULE_PROP, None, disable_active=True),
            "NONE|NONE|NONE|NONE",
        )

    def test_unknown_and_cross_provider_staging_fail_closed(self) -> None:
        unknown = self._provider_state("id=playintegrityfix\nname=Unknown\nversion=x\nversionCode=1\n", None)
        self.assertTrue(unknown.startswith("UNKNOWN|UNKNOWN|NONE|"))
        mixed = self._provider_state(INJECT_MODULE_PROP, FORK_MODULE_PROP)
        self.assertEqual(mixed, "MIXED|KOWX_INJECT_S|OSM0SIS_FORK_V18|KOWX_INJECT_S,OSM0SIS_FORK_V18")

    def test_fork_prop_validator_accepts_reviewed_prop_shape_and_rejects_duplicate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-fork-prop-") as raw:
            adb = Path(raw) / "data/adb"
            module = adb / "modules/playintegrityfix"
            module.mkdir(parents=True)
            (module / "module.prop").write_text(FORK_MODULE_PROP, encoding="utf-8")
            profile = module / "custom.pif.prop"
            profile.write_text(VALID_FORK_PROP, encoding="utf-8")
            command = f'''
                ADB_ROOT="{adb}"
                OTAST_STATE_ROOT="$ADB_ROOT/otast"
                OTAST_TMP_ROOT="$OTAST_STATE_ROOT/tmp"
                otast_effective_module_dirs() {{ [ "$1" = playintegrityfix ] && printf '%s\\n' "$ADB_ROOT/modules/playintegrityfix"; }}
                _otast_pif_module_effective() {{ [ -d "$1" ] && [ ! -e "$1/disable" ] && [ ! -e "$1/remove" ]; }}
                . "{COMMON}" || exit 1
                . "{PROVIDER}" || exit 2
                otast_validate_pif_fork_prop_file "{profile}" || exit 3
            '''
            run_ash(command)
            profile.write_text(VALID_FORK_PROP + "SECURITY_PATCH=2026-09-05\n", encoding="utf-8")
            duplicate = run_ash(command, check=False)
            self.assertNotEqual(duplicate.returncode, 0)

    def test_json_only_fork_fails_but_prop_precedence_allows_sibling_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-fork-json-") as raw:
            adb = Path(raw) / "data/adb"
            module = adb / "modules/playintegrityfix"
            module.mkdir(parents=True)
            (module / "module.prop").write_text(FORK_MODULE_PROP, encoding="utf-8")
            (module / "custom.pif.json").write_text('{"FINGERPRINT":"x"}\n', encoding="utf-8")
            command = f'''
                ADB_ROOT="{adb}"
                OTAST_STATE_ROOT="$ADB_ROOT/otast"
                OTAST_TMP_ROOT="$OTAST_STATE_ROOT/tmp"
                . "{COMMON}" || exit 1
                otast_effective_module_dirs() {{ [ "$1" = playintegrityfix ] && printf '%s\\n' "$ADB_ROOT/modules/playintegrityfix"; }}
                _otast_pif_module_effective() {{ [ -d "$1" ] && [ ! -e "$1/disable" ] && [ ! -e "$1/remove" ]; }}
                . "{PROVIDER}" || exit 2
                otast_validate_pif_profiles_current
            '''
            first = run_ash(command, check=False)
            self.assertNotEqual(first.returncode, 0)
            (module / "custom.pif.prop").write_text(VALID_FORK_PROP, encoding="utf-8")
            run_ash(command)

    def test_fork_transform_preserves_warnings_and_killpi_but_removes_trickystore_writer(self) -> None:
        source_text = '''#!/system/bin/sh
if [ "$DIR" = /data/adb/modules/playintegrityfix/autopif4 ]; then
  TS_DIR=/data/adb/tricky_store;
  if [ -d /data/adb/teesim -o -d /data/adb/omk ]; then
    warn "TEESimulator v4.x/Oh My KeyMint must be configured manually, ensure patch levels match *.security_patch";
  elif [ -d "$TS_DIR" ]; then
    TS_SECPAT=$TS_DIR/security_patch.txt;
    touch $TS_SECPAT;
    if [ -f /data/adb/modules/tricky_store/libTrickyStoreOSS.so ]; then
      echo all= > $TS_SECPAT;
    fi;
    cat $TS_SECPAT;
  fi;
  if [ -f /data/adb/modules/playintegrityfix/killpi.sh ]; then
    sh /data/adb/modules/playintegrityfix/killpi.sh 2>&1 || true;
  fi;
fi;
'''
        with tempfile.TemporaryDirectory(prefix="otast-fork-transform-") as raw:
            root = Path(raw)
            source = root / "autopif4.sh"
            output = root / "out.sh"
            source.write_text(source_text, encoding="utf-8")
            command = f'''
                ADB_ROOT=/data/adb
                OTAST_STATE_ROOT=/data/adb/otast
                OTAST_TMP_ROOT=/data/adb/otast/tmp
                . "{COMMON}" || exit 1
                otast_shell_file_valid() {{ sh -n "$1"; }}
                . "{PROVIDER}" || exit 2
                _otast_transform_pif_fork_autopif4 "{source}" "{output}" || exit 3
            '''
            run_ash(command)
            text = output.read_text(encoding="utf-8")
            self.assertIn("TEESimulator v4.x/Oh My KeyMint", text)
            self.assertIn("killpi.sh", text)
            self.assertIn("otast fork trickystore ownership BEGIN", text)
            self.assertNotIn("TS_SECPAT=", text)
            self.assertNotIn("touch $TS_SECPAT", text)

    @staticmethod
    def _detach_bytes(packages: list[str]) -> bytes:
        data = bytearray()
        for package in packages:
            encoded = bytearray()
            for index, char in enumerate(package.encode("ascii")):
                encoded.append(char)
                if index != len(package) - 1:
                    encoded.append(0)
            if len(encoded) > 255:
                raise ValueError("test package too long")
            data.append(len(encoded))
            data.extend(encoded)
        return bytes(data)

    def test_stack_observer_parses_detach_database_and_blocks_critical_package(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-detach-") as raw:
            adb = Path(raw) / "data/adb"
            module = adb / "modules/zygisk-detach"
            module.mkdir(parents=True)
            (module / "module.prop").write_text("id=zygisk-detach\nversion=v1\n", encoding="utf-8")
            config = adb / "zygisk-detach/detach.bin"
            config.parent.mkdir(parents=True)
            config.write_bytes(self._detach_bytes(["com.example.app", "com.google.android.gms"]))
            command = f'''
                ADB_ROOT="{adb}"
                OTAST_STATE_ROOT="$ADB_ROOT/otast"
                . "{COMMON}" || exit 1
                . "{CAPABILITIES}" || exit 2
                . "{OBSERVERS}" || exit 3
                _otast_stack_detach_list "{config}" || exit 4
                _otast_stack_collect_detach || exit 5
                printf 'critical=%s\\n' "$OTAST_STACK_DETACH_CRITICAL"
            '''
            result = run_ash(command)
            self.assertIn("com.example.app", result.stdout)
            self.assertIn("com.google.android.gms", result.stdout)
            self.assertIn("critical=com.google.android.gms", result.stdout)

    def test_stack_qualification_rejects_two_module_zygisk_providers_and_accepts_same_id_active_staged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-zygisk-") as raw:
            adb = Path(raw) / "data/adb"
            (adb / "modules/rezygisk").mkdir(parents=True)
            (adb / "modules/zygisksu").mkdir(parents=True)
            command = f'''
                ADB_ROOT="{adb}"
                OTAST_STATE_ROOT="$ADB_ROOT/otast"
                . "{COMMON}" || exit 1
                . "{CAPABILITIES}" || exit 2
                . "{OBSERVERS}" || exit 3
                if otast_validate_qualification_environment; then exit 9; fi
            '''
            run_ash(command)
            (adb / "modules/zygisksu/remove").touch()
            (adb / "modules_update/rezygisk").mkdir(parents=True)
            command_ok = command.replace("if otast_validate_qualification_environment; then exit 9; fi", "otast_validate_qualification_environment || exit 9")
            run_ash(command_ok)

    def test_runtime_observer_does_not_name_strict_bki_ash_non_targets(self) -> None:
        runtime = OBSERVERS.read_text(encoding="utf-8")
        supported = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        for module_id in supported["strict_exclusions"]:
            self.assertNotIn(module_id, runtime)

    def test_entry_sources_provider_before_capabilities_and_observers_are_read_only_qualification(self) -> None:
        entry = (ROOT / "module/runtime/entry.sh").read_text(encoding="utf-8")
        self.assertLess(entry.index("pif-migration-v2.sh"), entry.index("pif-provider-v4.sh"))
        self.assertLess(entry.index("pif-provider-v4.sh"), entry.index("capabilities-v3.sh"))
        self.assertLess(entry.index("capabilities-v3.sh"), entry.index("stack-observers-v4.sh"))
        self.assertIn("otast_validate_pif_provider", entry)
        self.assertIn("_otast_qualify", entry)
        self.assertIn("QUALIFICATION_ENVIRONMENT_READY", entry)


if __name__ == "__main__":
    unittest.main()
