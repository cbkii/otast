from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.build import build_module
from tools.otastctl.fake_root import _new_root, _run, _simulate_managed_boot

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/upstream"


def _profile(fingerprint: str, model: str = "Pixel fixture") -> str:
    return (
        f"FINGERPRINT={fingerprint}\n"
        "MANUFACTURER=Google\n"
        f"MODEL={model}\n"
        "SECURITY_PATCH=2026-08-05\n"
        "spoofBuild=true\n"
        "spoofProps=false\n"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state_value(path: Path, key: str) -> str:
    prefix = f"{key}="
    values = [
        line[len(prefix) :]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]
    if len(values) != 1:
        raise AssertionError(f"state key {key!r} is missing or duplicated in {path}")
    return values[0]


class PifStateMachineRegressionTests(unittest.TestCase):
    def test_direct_restore_after_global_deletion_never_rolls_back_active_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-direct-restore-") as raw:
            work = Path(raw)
            module_zip = build_module(ROOT, work / "dist")
            adb_root, entry, _ = _new_root(work / "fake", module_zip, staged_pif=False)

            _run(entry, adb_root, "apply")
            active = adb_root / "modules/playintegrityfix/pif.prop"
            source_bytes = active.read_bytes()
            (adb_root / "pif.prop").unlink()

            report = _run(entry, adb_root, "report")
            self.assertIn("pif_canonical_profile_role=ACTIVE_FALLBACK", report.stdout)
            self.assertIn("pif_profile_ownership_state=MIGRATION_PENDING", report.stdout)

            _run(entry, adb_root, "restore")
            self.assertEqual(active.read_bytes(), source_bytes)
            self.assertFalse((adb_root / "otast/records/pif-mirror-active.state").exists())
            generations = sorted(
                (adb_root / "otast/retired/pif-mirror-source-v2/pif-mirror-active").glob("g*/state")
            )
            self.assertEqual(len(generations), 1)

    def test_repeated_source_mirror_cycles_keep_generation_backups_immutable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-mirror-generations-") as raw:
            work = Path(raw)
            module_zip = build_module(ROOT, work / "dist")
            adb_root, entry, _ = _new_root(work / "fake", module_zip, staged_pif=False)

            _run(entry, adb_root, "apply")
            active = adb_root / "modules/playintegrityfix/pif.prop"
            global_profile = adb_root / "pif.prop"

            global_profile.unlink()
            _run(entry, adb_root, "apply")

            global_profile.write_bytes(active.read_bytes())
            global_profile.chmod(0o600)
            _run(entry, adb_root, "apply")
            self.assertTrue((adb_root / "otast/records/pif-mirror-active.state").is_file())

            global_profile.unlink()
            _run(entry, adb_root, "apply")

            generations = sorted(
                (adb_root / "otast/retired/pif-mirror-source-v2/pif-mirror-active").glob("g*/state")
            )
            self.assertEqual(len(generations), 2)
            backup_paths: list[Path] = []
            for state in generations:
                backup = Path(_state_value(state, "backup"))
                backup_paths.append(backup)
                self.assertTrue(backup.is_file())
                self.assertFalse(backup.is_symlink())
                self.assertEqual(_sha256(backup), _state_value(state, "original_hash"))
            self.assertNotEqual(backup_paths[0], backup_paths[1])
            self.assertFalse((adb_root / "otast/backups/pif-mirror-active.original").exists())

    def test_disabled_active_module_cannot_become_canonical(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-disabled-active-") as raw:
            work = Path(raw)
            module_zip = build_module(ROOT, work / "dist")
            adb_root, entry, _ = _new_root(work / "fake", module_zip, staged_pif=True)

            (adb_root / "pif.prop").unlink()
            active = adb_root / "modules/playintegrityfix/pif.prop"
            staged = adb_root / "modules_update/playintegrityfix/pif.prop"
            active_text = _profile(
                "google/panther_beta/panther:CANARY/TEST/1:user/release-keys",
                "Disabled Pixel 7",
            )
            active.write_text(active_text, encoding="utf-8")
            active.chmod(0o644)
            (active.parent / "disable").write_text("1\n", encoding="utf-8")
            staged_before = staged.read_bytes()

            report = _run(entry, adb_root, "report")
            self.assertIn("pif_canonical_profile_role=STAGED_FALLBACK", report.stdout)
            _run(entry, adb_root, "apply")
            self.assertEqual(active.read_text(encoding="utf-8"), active_text)
            self.assertEqual(staged.read_bytes(), staged_before)

    def test_magisk_staged_promotion_rebases_active_restore_baseline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-promotion-") as raw:
            work = Path(raw)
            module_zip = build_module(ROOT, work / "dist")
            adb_root, entry, _ = _new_root(work / "fake", module_zip, staged_pif=True)

            active_dir = adb_root / "modules/playintegrityfix"
            staged_dir = adb_root / "modules_update/playintegrityfix"
            staged_profile_original = _profile(
                "google/shiba_beta/shiba:CANARY/STAGED/1:user/release-keys",
                "Staged Pixel 8",
            ).encode()
            (staged_dir / "pif.prop").write_bytes(staged_profile_original)
            (staged_dir / "pif.prop").chmod(0o644)
            staged_writer_fixture = FIXTURES / "pif-security-patch-73552eec.sh"
            staged_writer_original = staged_writer_fixture.read_bytes()
            (staged_dir / "security_patch.sh").write_bytes(staged_writer_original)
            (staged_dir / "security_patch.sh").chmod(0o755)

            _run(entry, adb_root, "apply")
            _simulate_managed_boot(adb_root)

            shutil.rmtree(active_dir)
            shutil.copytree(staged_dir, active_dir, copy_function=shutil.copy2)
            shutil.rmtree(staged_dir)

            pending = _run(entry, adb_root, "verify", expect=1)
            self.assertIn("ownership/topology state is pending reconciliation", pending.stdout)
            promoted = _run(entry, adb_root, "apply")
            self.assertIn("STATE_MIGRATION_COMPLETE", promoted.stdout)

            mirror_state = adb_root / "otast/records/pif-mirror-active.state"
            writer_state = adb_root / "otast/records/pif-security-patch-active.state"
            self.assertTrue(mirror_state.is_file())
            self.assertTrue(writer_state.is_file())
            self.assertFalse((adb_root / "otast/records/pif-mirror-staged.state").exists())
            self.assertFalse((adb_root / "otast/records/pif-security-patch-staged.state").exists())
            self.assertEqual(
                (adb_root / "otast/backups/pif-mirror-active.original").read_bytes(),
                staged_profile_original,
            )
            self.assertEqual(
                (adb_root / "otast/backups/pif-security-patch-active.original").read_bytes(),
                staged_writer_original,
            )

            _run(entry, adb_root, "restore")
            self.assertEqual((active_dir / "pif.prop").read_bytes(), staged_profile_original)
            self.assertEqual((active_dir / "security_patch.sh").read_bytes(), staged_writer_original)

    def test_failed_provisional_plan_does_not_seed_legacy_mirror_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-provisional-migration-") as raw:
            work = Path(raw)
            module_zip = build_module(ROOT, work / "dist")
            adb_root, entry, _ = _new_root(work / "fake", module_zip, staged_pif=False)

            active = adb_root / "modules/playintegrityfix/pif.prop"
            state_root = adb_root / "otast"
            records = state_root / "records"
            backups = state_root / "backups"
            records.mkdir(parents=True)
            backups.mkdir(parents=True)
            legacy_backup = backups / "pif-prop-active.original"
            legacy_backup.write_text(
                _profile(
                    "google/oriole_beta/oriole:CANARY/ORIGINAL/1:user/release-keys",
                    "Legacy original",
                ),
                encoding="utf-8",
            )
            legacy_backup.chmod(0o600)
            authority_hash = _sha256(adb_root / "ota.prop")
            legacy_state = records / "pif-prop-active.state"
            legacy_state.write_text(
                "\n".join(
                    (
                        "version=1",
                        "id=pif-prop-active",
                        "target=playintegrityfix",
                        f"path={active}",
                        "strategy=external",
                        "original_exists=1",
                        "original_mode=0644",
                        f"original_hash={_sha256(legacy_backup)}",
                        f"backup={legacy_backup}",
                        f"managed_hash={_sha256(active)}",
                        "managed_mode=0644",
                        f"authority_sha256={authority_hash}",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            legacy_state.chmod(0o600)

            (active.parent / "security_patch.sh").unlink()
            failed = _run(entry, adb_root, "apply", expect=1)
            self.assertIn("required reviewed target path is missing", failed.stdout)
            self.assertTrue(legacy_state.is_file())
            self.assertFalse((records / "pif-mirror-active.state").exists())
            self.assertFalse((backups / "pif-mirror-active.original").exists())

    def test_deprecated_writer_retirement_rejects_symlinked_module_ancestor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-retire-symlink-") as raw:
            base = Path(raw)
            adb_root = base / "data/adb"
            outside = base / "outside"
            state_root = adb_root / "otast"
            records = state_root / "records"
            backups = state_root / "backups"
            (adb_root / "modules").mkdir(parents=True)
            outside.mkdir()
            records.mkdir(parents=True)
            backups.mkdir(parents=True)

            outside_writer = outside / "autopif.sh"
            outside_writer.write_text("managed-writer\n", encoding="utf-8")
            outside_writer.chmod(0o755)
            (adb_root / "modules/playintegrityfix").symlink_to(outside, target_is_directory=True)
            backup = backups / "pif-autopif-active.original"
            backup.write_text("original-writer\n", encoding="utf-8")
            backup.chmod(0o600)
            authority_hash = "a" * 64
            state = records / "pif-autopif-active.state"
            state.write_text(
                "\n".join(
                    (
                        "version=1",
                        "id=pif-autopif-active",
                        "target=playintegrityfix",
                        f"path={adb_root / 'modules/playintegrityfix/autopif.sh'}",
                        "strategy=external",
                        "original_exists=1",
                        "original_mode=0755",
                        f"original_hash={_sha256(backup)}",
                        f"backup={backup}",
                        f"managed_hash={_sha256(outside_writer)}",
                        "managed_mode=0755",
                        f"authority_sha256={authority_hash}",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            state.chmod(0o600)

            runtime = ROOT / "module/runtime"
            busybox = shutil.which("busybox")
            shell = [busybox, "sh"] if busybox else ["sh"]
            command = f'''
                ADB_ROOT="{adb_root}"
                OTAST_STATE_ROOT="{state_root}"
                OTAST_TMP_ROOT="$OTAST_STATE_ROOT/tmp"
                OTAST_AUTHORITY_SHA256="{authority_hash}"
                . "{runtime / 'common.sh'}" || exit 10
                . "{runtime / 'transaction.sh'}" || exit 11
                . "{runtime / 'pif.sh'}" || exit 12
                . "{runtime / 'policy.sh'}" || exit 13
                . "{runtime / 'profiles.sh'}" || exit 14
                . "{runtime / 'architecture-v2.sh'}" || exit 15
                . "{runtime / 'pif-migration-v2.sh'}" || exit 16
                if _otast_pif_restore_deprecated_writer pif-autopif-active; then
                    exit 90
                fi
            '''
            result = subprocess.run(
                [*shell, "-c", command],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("symlink parent rejected", result.stdout)
            self.assertEqual(outside_writer.read_text(encoding="utf-8"), "managed-writer\n")

    def test_installer_validates_v2_architecture_and_migration_files(self) -> None:
        customize = (ROOT / "module/customize.sh").read_text(encoding="utf-8")
        self.assertIn("runtime/architecture-v2.sh", customize)
        self.assertIn("runtime/pif-migration-v2.sh", customize)


if __name__ == "__main__":
    unittest.main()
