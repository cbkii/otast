from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.build import build_module
from tools.otastctl.fake_root import _new_root, _run, _simulate_managed_boot

ROOT = Path(__file__).resolve().parents[1]
PIF_RUNTIME = ROOT / "module/runtime/pif.sh"
AUTOPIF_FIXTURE = ROOT / "tests/fixtures/upstream/pif-autopif-8b4a00ce.sh"


def _profile_text(
    fingerprint: str,
    model: str,
    patch: str,
    *,
    spoof_provider: bool = False,
    comment: str = "",
) -> str:
    prefix = f"# {comment}\n" if comment else ""
    return (
        prefix
        + f"FINGERPRINT={fingerprint}\n"
        + "MANUFACTURER=Google\n"
        + f"MODEL={model}\n"
        + f"SECURITY_PATCH={patch}\n"
        + "spoofBuild=true\n"
        + "spoofProps=false\n"
        + f"spoofProvider={'true' if spoof_provider else 'false'}\n"
        + "spoofSignature=false\n"
        + "spoofVendingBuild=true\n"
        + "spoofVendingSdk=false\n"
        + "DEBUG=false\n"
    )


def _shell() -> list[str]:
    busybox = shutil.which("busybox")
    return [busybox, "sh"] if busybox else ["sh"]


def _transaction_count(adb_root: Path) -> int:
    root = adb_root / "otast/transactions"
    return len([path for path in root.glob("*") if path.is_dir() and not path.is_symlink()])


class PifRefreshLifecycleTests(unittest.TestCase):
    def test_autopif_random_and_selected_device_paths_survive_otast_transform(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-selection-") as raw:
            output = Path(raw) / "autopif.sh"
            command = f'''
                . "{PIF_RUNTIME}" || exit 1
                otast_transform_pif_autopif "{AUTOPIF_FIXTURE}" "{output}" || exit 2
            '''
            subprocess.run(_shell() + ["-c", command], check=True, timeout=20)
            text = output.read_text(encoding="utf-8")

        # No PRODUCT supplied -> upstream random Canary selection remains intact.
        self.assertIn("set_random_beta()", text)
        self.assertIn("rand_index=$(( $$ % count ))", text)
        self.assertIn('if [ -z "$PRODUCT" ] || ! echo "$PRODUCT_LIST" | grep -q "$PRODUCT"; then', text)
        self.assertIn("\tset_random_beta", text)

        # Valid PRODUCT supplied -> upstream selected-device path remains intact.
        self.assertIn('DEVICE="$(echo "$PRODUCT" | sed \'s/_beta//\')"', text)
        self.assertIn('cat "$TEMPDIR/pif.prop" > /data/adb/pif.prop', text)
        self.assertIn('sh "$MODDIR/security_patch.sh"', text)
        self.assertNotIn("rm -f $MODDIR/system.prop", text)

    def test_webui_style_profile_edits_module_update_and_restore_are_external(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-external-writers-") as raw:
            root = Path(raw)
            module_zip = build_module(ROOT, root / "dist")
            adb_root, entry, _ = _new_root(root / "fake", module_zip, staged_pif=True)

            _run(entry, adb_root, "preflight")
            _run(entry, adb_root, "apply")
            _simulate_managed_boot(adb_root)
            _run(entry, adb_root, "verify")

            custom = adb_root / "pif.prop"
            active = adb_root / "modules/playintegrityfix/pif.prop"
            staged = adb_root / "modules_update/playintegrityfix/pif.prop"
            tricky_patch = adb_root / "tricky_store/security_patch.txt"
            active_system_prop = adb_root / "modules/playintegrityfix/system.prop"
            staged_system_prop = adb_root / "modules_update/playintegrityfix/system.prop"

            ota_contract_before = {
                "tricky": tricky_patch.read_bytes(),
                "active_system": active_system_prop.read_bytes(),
                "staged_system": staged_system_prop.read_bytes(),
            }

            # WebUI GitHub-fetch equivalent: selected profile identity changes.
            custom.write_text(
                _profile_text(
                    "google/shiba_beta/shiba:CANARY/ZP11.260717.006/16004061:user/release-keys",
                    "Pixel 8",
                    "2026-08-05",
                    comment="WebUI GitHub fetch equivalent",
                ),
                encoding="utf-8",
            )
            custom.chmod(0o600)
            _run(entry, adb_root, "verify")

            # WebUI option-toggle equivalent: same profile, one PIF-owned boolean changes.
            toggled = custom.read_text(encoding="utf-8").replace(
                "spoofProvider=false", "spoofProvider=true"
            )
            custom.write_text(toggled, encoding="utf-8")
            custom.chmod(0o600)
            toggle_bytes = custom.read_bytes()
            _run(entry, adb_root, "verify")

            # Supported PIF module update/reset may independently replace active and staged fallbacks.
            active.write_text(
                _profile_text(
                    "google/panther_beta/panther:CANARY/ZP11.260717.006/16004061:user/release-keys",
                    "Pixel 7",
                    "2026-08-05",
                    comment="active packaged fallback after module update",
                ),
                encoding="utf-8",
            )
            active.chmod(0o644)
            staged.write_text(
                _profile_text(
                    "google/bluejay_beta/bluejay:CANARY/ZP11.260717.006/16004061:user/release-keys",
                    "Pixel 6a",
                    "2026-08-05",
                    comment="staged future fallback after module update",
                ),
                encoding="utf-8",
            )
            staged.chmod(0o644)
            active_bytes = active.read_bytes()
            staged_bytes = staged.read_bytes()
            _run(entry, adb_root, "verify")

            report_custom = _run(entry, adb_root, "report")
            self.assertIn("pif_effective_profile_role=CUSTOM", report_custom.stdout)
            self.assertIn("pif_profile_model=Pixel 8", report_custom.stdout)

            # PIF recovery/reset deletes global custom: active fallback wins, never staged.
            custom.unlink()
            _run(entry, adb_root, "verify")
            report_fallback = _run(entry, adb_root, "report")
            self.assertIn("pif_custom_profile_state=ABSENT", report_fallback.stdout)
            self.assertIn("pif_effective_profile_role=ACTIVE_FALLBACK", report_fallback.stdout)
            self.assertIn("pif_profile_model=Pixel 7", report_fallback.stdout)
            self.assertNotIn("pif_profile_model=Pixel 6a", report_fallback.stdout)
            self.assertFalse(custom.exists())

            # PIF/WebUI may recreate the global custom profile later.
            custom.write_bytes(toggle_bytes)
            custom.chmod(0o600)

            before_noop = _transaction_count(adb_root)
            no_op = _run(entry, adb_root, "apply")
            after_noop = _transaction_count(adb_root)
            self.assertEqual(before_noop, after_noop)
            self.assertIn("NO_CHANGES_REQUIRED", no_op.stdout)
            self.assertEqual(custom.read_bytes(), toggle_bytes)
            self.assertEqual(active.read_bytes(), active_bytes)
            self.assertEqual(staged.read_bytes(), staged_bytes)
            self.assertEqual(tricky_patch.read_bytes(), ota_contract_before["tricky"])
            self.assertEqual(active_system_prop.read_bytes(), ota_contract_before["active_system"])
            self.assertEqual(staged_system_prop.read_bytes(), ota_contract_before["staged_system"])

            # Restore relinquishes OTAST writers but must not roll PIF-owned profile data back.
            _run(entry, adb_root, "restore")
            self.assertEqual(custom.read_bytes(), toggle_bytes)
            self.assertEqual(active.read_bytes(), active_bytes)
            self.assertEqual(staged.read_bytes(), staged_bytes)

    def test_webui_invoked_autopif_self_update_gate_cannot_replace_engine(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-webui-update-") as raw:
            root = Path(raw)
            module_zip = build_module(ROOT, root / "dist")
            adb_root, entry, _ = _new_root(root / "fake", module_zip, staged_pif=False)
            _run(entry, adb_root, "apply")

            pif_dir = adb_root / "modules/playintegrityfix"
            engine = pif_dir / "autopif.sh"
            updater = pif_dir / "autopif_ota.sh"
            engine_before = engine.read_bytes()

            env = os.environ.copy()
            env["ADB_ROOT"] = str(adb_root)
            result = subprocess.run(
                _shell() + [str(updater)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("review-gated by OTAST", result.stdout)
            self.assertEqual(engine.read_bytes(), engine_before)


if __name__ == "__main__":
    unittest.main()
