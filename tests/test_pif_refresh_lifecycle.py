from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.otastctl.build import build_module
from tools.otastctl.fake_root import _new_root, _run, _simulate_managed_boot

ROOT = Path(__file__).resolve().parents[1]


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


def _transaction_count(adb_root: Path) -> int:
    root = adb_root / "otast/transactions"
    return len([path for path in root.glob("*") if path.is_dir() and not path.is_symlink()])


class PifRefreshLifecycleTests(unittest.TestCase):
    def test_global_profile_edits_require_explicit_mirror_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-profile-refresh-") as raw:
            root = Path(raw)
            module_zip = build_module(ROOT, root / "dist")
            adb_root, entry, originals = _new_root(root / "fake", module_zip, staged_pif=True)

            _run(entry, adb_root, "preflight")
            _run(entry, adb_root, "apply")
            _simulate_managed_boot(adb_root)
            _run(entry, adb_root, "verify")

            custom = adb_root / "pif.prop"
            active = adb_root / "modules/playintegrityfix/pif.prop"
            staged = adb_root / "modules_update/playintegrityfix/pif.prop"
            tricky_patch = adb_root / "tricky_store/security_patch.txt"
            tricky_before = tricky_patch.read_bytes()

            refreshed = _profile_text(
                "google/shiba_beta/shiba:CANARY/ZP11.260717.006/16004061:user/release-keys",
                "Pixel 8",
                "2026-08-05",
                comment="WebUI or AutoPIF global refresh",
            )
            custom.write_text(refreshed, encoding="utf-8")
            custom.chmod(0o600)

            stale = _run(entry, adb_root, "verify", expect=1)
            self.assertIn("PIF fallback profile is not synchronized", stale.stdout)
            report = _run(entry, adb_root, "report")
            self.assertIn("pif_canonical_profile_role=GLOBAL_CUSTOM", report.stdout)
            self.assertIn("pif_profile_MODEL=Pixel 8", report.stdout)
            self.assertIn("pif_active_profile_relation=MIRROR_UPDATE_REQUIRED", report.stdout)
            self.assertIn("pif_staged_profile_relation=MIRROR_UPDATE_REQUIRED", report.stdout)

            before = _transaction_count(adb_root)
            reconcile = _run(entry, adb_root, "apply")
            after = _transaction_count(adb_root)
            self.assertEqual(after, before + 1)
            self.assertIn("REBOOT_REQUIRED", reconcile.stdout)
            self.assertEqual(active.read_text(encoding="utf-8"), refreshed)
            self.assertEqual(staged.read_text(encoding="utf-8"), refreshed)
            self.assertEqual(tricky_patch.read_bytes(), tricky_before)
            _run(entry, adb_root, "verify")

            # A PIF-owned option change on the global source follows the same
            # explicit reconcile boundary; OTAST never rewrites the source.
            toggled = custom.read_text(encoding="utf-8").replace(
                "spoofProvider=false", "spoofProvider=true"
            )
            custom.write_text(toggled, encoding="utf-8")
            custom.chmod(0o600)
            _run(entry, adb_root, "verify", expect=1)
            _run(entry, adb_root, "apply")
            self.assertEqual(custom.read_text(encoding="utf-8"), toggled)
            self.assertEqual(active.read_text(encoding="utf-8"), toggled)
            self.assertEqual(staged.read_text(encoding="utf-8"), toggled)

            # Restore relinquishes the mirrors to their pre-OTAST packaged
            # fallbacks but must leave the current canonical global source alone.
            _run(entry, adb_root, "restore")
            self.assertEqual(custom.read_text(encoding="utf-8"), toggled)
            self.assertEqual(
                active.read_bytes(),
                originals["modules/playintegrityfix/pif.prop"],
            )
            self.assertEqual(
                staged.read_bytes(),
                originals["modules_update/playintegrityfix/pif.prop"],
            )

    def test_direct_non_source_fallback_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-fallback-drift-") as raw:
            root = Path(raw)
            module_zip = build_module(ROOT, root / "dist")
            adb_root, entry, _ = _new_root(root / "fake", module_zip, staged_pif=True)

            _run(entry, adb_root, "apply")
            _simulate_managed_boot(adb_root)
            _run(entry, adb_root, "verify")

            active = adb_root / "modules/playintegrityfix/pif.prop"
            managed = active.read_bytes()
            active.write_text(
                _profile_text(
                    "google/panther_beta/panther:CANARY/ZP11.260717.006/16004061:user/release-keys",
                    "Pixel 7",
                    "2026-08-05",
                    comment="unexpected non-source fallback mutation",
                ),
                encoding="utf-8",
            )
            active.chmod(0o644)

            verify = _run(entry, adb_root, "verify", expect=1)
            self.assertIn("PIF fallback profile is not synchronized", verify.stdout)
            apply = _run(entry, adb_root, "apply", expect=1)
            self.assertIn("managed target drift detected", apply.stdout)
            restore = _run(entry, adb_root, "restore", expect=1)
            self.assertIn("managed target drift detected", restore.stdout)

            active.write_bytes(managed)
            active.chmod(0o644)
            _run(entry, adb_root, "restore")

    def test_autopif_and_updater_remain_upstream_owned(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-upstream-executables-") as raw:
            root = Path(raw)
            module_zip = build_module(ROOT, root / "dist")
            adb_root, entry, _ = _new_root(root / "fake", module_zip, staged_pif=True)

            paths = [
                adb_root / role / "playintegrityfix" / name
                for role in ("modules", "modules_update")
                for name in ("autopif.sh", "autopif_ota.sh")
            ]
            before = {path: path.read_bytes() for path in paths}

            _run(entry, adb_root, "preflight")
            _run(entry, adb_root, "apply")

            for path, expected in before.items():
                self.assertEqual(path.read_bytes(), expected, path)
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("review-gated by OTAST", text)
                self.assertNotIn("otast managed: AutoPIF executable self-update gate", text)

            report = _run(entry, adb_root, "report")
            self.assertIn("pif_autopif_lifecycle=UPSTREAM_PRESERVED", report.stdout)
            self.assertIn("pif_autopif_self_update_policy=UPSTREAM_PRESERVED", report.stdout)


if __name__ == "__main__":
    unittest.main()
