from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = SOURCE_ROOT / "scripts/otast-maintenance.py"
PLAYBOOK = SOURCE_ROOT / "scripts/otast-playbook.sh"
SAFETY = SOURCE_ROOT / "scripts/otast_safety_guard.py"

OLD = "628d9d8ee9810b97516574475c0e28cdd6d4c026"
NEW = "5330b77c0b797e580c582d43e91ceae5b450dce6"


class MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.home = self.base / "home"
        self.bin = self.base / "bin"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "tools/otastctl").mkdir(parents=True)
        (self.repo / "compatibility").mkdir(parents=True)
        (self.repo / "reports").mkdir(parents=True)
        (self.repo / "module").mkdir(parents=True)
        self.home.mkdir()
        self.bin.mkdir()
        (self.repo / "pyproject.toml").write_text("[project]\nname='otast-test'\n", encoding="utf-8")
        (self.repo / "module/module.prop").write_text("version=v1.0.0-rc.3\nversionCode=100003\n", encoding="utf-8")
        shutil.copy2(MAINTENANCE, self.repo / "scripts/otast-maintenance.py")
        shutil.copy2(PLAYBOOK, self.repo / "scripts/otast-playbook.sh")
        shutil.copy2(SAFETY, self.repo / "scripts/otast_safety_guard.py")
        for name in ("test.sh", "check-dev-environment.sh", "public-init-audit.sh"):
            path = self.repo / "scripts" / name
            path.write_text("#!/usr/bin/env bash\nprintf 'PASS %s\\n' \"$0\"\n", encoding="utf-8")
            path.chmod(0o755)
        self.write_registry(OLD)
        self.write_fake_gh()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_registry(self, expected: str) -> None:
        value = {
            "schema_version": 1,
            "targets": {
                "yurikey": {
                    "module_ids": ["Yurikey"],
                    "monitor": {
                        "repository": "Yurii0307/yurikey",
                        "branch": "main",
                        "expected_head": expected,
                    },
                    "reviewed_sources": [{"commit": OLD}],
                }
            },
        }
        (self.repo / "compatibility/supported-targets.json").write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )

    def write_fake_gh(self) -> None:
        script = self.bin / "gh"
        script.write_text(
            textwrap.dedent(
                r'''#!/usr/bin/env bash
                log=${FAKE_GH_LOG:-}
                [[ -n $log ]] && printf '%q ' "$@" >>"$log" && printf '\n' >>"$log"
                body_log=${FAKE_GH_BODY_LOG:-}
                if [[ -n $body_log ]]; then
                  args=("$@")
                  for ((i=0; i<${#args[@]}; i++)); do
                    if [[ ${args[i]} == --body-file && $((i + 1)) -lt ${#args[@]} ]]; then
                      cat -- "${args[i + 1]}" >"$body_log"
                    fi
                  done
                fi
                case "${1:-} ${2:-}" in
                  'auth status')
                    [[ ${FAKE_GH_AUTH:-ok} == ok ]] && exit 0
                    printf 'not logged in\n' >&2
                    exit 1
                    ;;
                  'auth token')
                    printf 'test-token\n'
                    exit 0
                    ;;
                  'api rate_limit')
                    remaining=${FAKE_GH_REMAINING:-5000}
                    printf '{"resources":{"core":{"limit":5000,"remaining":%s,"used":0,"reset":4102444800}}}\n' "$remaining"
                    exit 0
                    ;;
                  'api '*)
                    endpoint=$2
                    if [[ $endpoint == repos/Yurii0307/yurikey/commits/main ]]; then
                      printf '{"sha":"%s"}\n' "${FAKE_GH_HEAD:-628d9d8ee9810b97516574475c0e28cdd6d4c026}"
                      exit 0
                    fi
                    printf 'unknown endpoint: %s\n' "$endpoint" >&2
                    exit 1
                    ;;
                  'label create') exit 0 ;;
                  'issue list') printf '[]\n'; exit 0 ;;
                  'issue create') printf 'https://github.com/example/repo/issues/1\n'; exit 0 ;;
                  'issue edit'|'issue close'|'issue reopen') exit 0 ;;
                esac
                printf 'unsupported fake gh call: %s\n' "$*" >&2
                exit 1
                '''
            ).lstrip(),
            encoding="utf-8",
        )
        script.chmod(0o755)

    def env(self, **extra: str) -> dict[str, str]:
        value = os.environ.copy()
        value.pop("GH_TOKEN", None)
        value.pop("GITHUB_TOKEN", None)
        value.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin}:{value.get('PATH', '')}",
                "OTAST_REPO_ROOT": str(self.repo),
            }
        )
        value.update(extra)
        return value

    def run_tool(self, *args: str, **env: str):
        module_path = self.repo / "scripts/otast-maintenance.py"
        spec = importlib.util.spec_from_file_location(f"otast_maintenance_test_{id(self)}", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        stdout = io.StringIO()
        stderr = io.StringIO()
        original = os.environ.copy()
        test_env = self.env(**env)
        os.environ.clear()
        os.environ.update(test_env)
        # Use the real unprivileged test-process UID. ``module.os`` is the
        # interpreter-wide ``os`` module, so assigning module.os.geteuid here
        # would leak into subsequently imported test modules.
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = module.main(list(args))
        finally:
            os.environ.clear()
            os.environ.update(original)
        return type("Result", (), {"returncode": rc, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()})()


    def test_run_tool_preserves_process_geteuid(self) -> None:
        original_geteuid = os.geteuid
        output = self.repo / "reports/target-monitor-uid-contract"
        result = self.run_tool("monitor", "--output", str(output), "--no-cleanup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(os.geteuid, original_geteuid)

    def test_authenticated_monitor_supported(self) -> None:
        output = self.repo / "reports/target-monitor-test"
        result = self.run_tool("monitor", "--output", str(output), "--no-cleanup")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((output / "target-monitor.json").read_text())
        self.assertEqual(report["result"], "SUPPORTED")
        self.assertEqual(report["targets"][0]["status"], "supported")

    def test_monitor_review_required_has_distinct_exit_and_next_command(self) -> None:
        output = self.repo / "reports/target-monitor-change"
        result = self.run_tool(
            "monitor", "--output", str(output), "--no-cleanup", FAKE_GH_HEAD=NEW
        )
        self.assertEqual(result.returncode, 10, result.stderr)
        report = json.loads((output / "target-monitor.json").read_text())
        self.assertEqual(report["result"], "REVIEW_REQUIRED")
        self.assertIn("otast review yurikey", (output / "target-monitor.md").read_text())

    def test_monitor_stops_before_lookup_when_rate_budget_is_low(self) -> None:
        output = self.repo / "reports/target-monitor-low-rate"
        log = self.base / "gh.log"
        result = self.run_tool(
            "monitor",
            "--output",
            str(output),
            "--no-cleanup",
            FAKE_GH_REMAINING="1",
            FAKE_GH_LOG=str(log),
        )
        self.assertEqual(result.returncode, 20)
        self.assertIn("allowance is too low", result.stderr)
        calls = log.read_text()
        self.assertNotIn("commits/main", calls)

    def test_accept_updates_only_monitor_expected_head(self) -> None:
        review_dir = self.repo / f"reports/target-review-yurikey-{NEW[:12]}-fixture"
        review_dir.mkdir()
        review = {
            "result": "NO_PACKAGE_IMPACT",
            "acceptance_ready": True,
            "target": "yurikey",
            "expected_head": OLD,
            "observed_head": NEW,
        }
        (review_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")
        result = self.run_tool(
            "accept", "yurikey", "--review", str(review_dir), FAKE_GH_HEAD=NEW
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        registry = json.loads((self.repo / "compatibility/supported-targets.json").read_text())
        record = registry["targets"]["yurikey"]
        self.assertEqual(record["monitor"]["expected_head"], NEW)
        self.assertEqual(record["reviewed_sources"][0]["commit"], OLD)
        self.assertTrue((review_dir / "acceptance.json").is_file())

    def test_bare_fake_root_name_is_resolved_under_private_root(self) -> None:
        module_path = self.repo / "scripts/otast-maintenance.py"
        spec = importlib.util.spec_from_file_location("otast_maintenance_path_test", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        original_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        try:
            self.assertEqual(
                module.fake_root_path("candidate"),
                (self.home / ".cache/otast/fake-roots/candidate").resolve(strict=False),
            )
        finally:
            if original_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = original_home
        playbook = (self.repo / "scripts/otast-playbook.sh").read_text(encoding="utf-8")
        self.assertIn('candidate=$root_base/$input', playbook)

    def test_issue_sync_creates_agent_ready_target_issue(self) -> None:
        report = self.repo / "reports/issue-report.json"
        report.write_text(
            json.dumps(
                {
                    "result": "REVIEW_REQUIRED",
                    "targets": [
                        {
                            "target": "yurikey",
                            "repository": "Yurii0307/yurikey",
                            "ref": "main",
                            "expected_head": OLD,
                            "observed_head": NEW,
                            "status": "review-required",
                            "error": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        log = self.base / "gh-issues.log"
        body_log = self.base / "gh-issue-body.md"
        result = self.run_tool(
            "issues-sync",
            "--report",
            str(report),
            "--repo",
            "cbkii/otast",
            FAKE_GH_LOG=str(log),
            FAKE_GH_BODY_LOG=str(body_log),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = log.read_text(encoding="utf-8")
        self.assertIn("issue create", calls)
        self.assertIn("issue edit 1", calls)
        self.assertIn("target:yurikey", calls)
        body = body_log.read_text(encoding="utf-8")
        self.assertIn("Closes #1", body)
        self.assertNotIn("<issue-number>", body)

    def test_successful_monitor_prunes_old_failed_reports_only_after_success(self) -> None:
        oldest_failed = self.repo / "reports/target-monitor-001-failed"
        newest_failed = self.repo / "reports/target-monitor-002-failed"
        old_success = self.repo / "reports/target-monitor-003-success"
        oldest_failed.mkdir()
        newest_failed.mkdir()
        old_success.mkdir()
        (oldest_failed / "target-monitor.json").write_text('{"result":"ERROR"}\n')
        (newest_failed / "target-monitor.json").write_text('{"result":"ERROR"}\n')
        (old_success / "target-monitor.json").write_text('{"result":"SUPPORTED"}\n')
        os.utime(oldest_failed, (1, 1))
        os.utime(newest_failed, (2, 2))
        os.utime(old_success, (3, 3))
        output = self.repo / "reports/target-monitor-current"
        result = self.run_tool("monitor", "--output", str(output), "--keep", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(oldest_failed.exists())
        self.assertTrue(newest_failed.exists())
        self.assertFalse(old_success.exists())
        self.assertTrue(output.exists())

    def test_review_classifier_treats_identical_package_preflight_as_diagnostic(self) -> None:
        spec = importlib.util.spec_from_file_location("otast_maintenance_classifier", MAINTENANCE)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        identical = {"identical": True}
        changed = {"identical": False}

        ready, result, rc, policy = module.classify_review_result(
            identical,
            active_candidate_compare_rc=0,
            report_rc=0,
            preflight_rc=1,
        )
        self.assertTrue(ready)
        self.assertEqual(result, "NO_PACKAGE_IMPACT")
        self.assertEqual(rc, module.EXIT_OK)
        self.assertEqual(policy, "DIAGNOSTIC_ONLY_FOR_IDENTICAL_PACKAGE")

        ready, result, rc, _ = module.classify_review_result(
            identical,
            active_candidate_compare_rc=1,
            report_rc=0,
            preflight_rc=1,
        )
        self.assertFalse(ready)
        self.assertEqual(result, "VALIDATION_FAILED")
        self.assertEqual(rc, module.EXIT_ERROR)

        ready, result, rc, policy = module.classify_review_result(
            changed,
            active_candidate_compare_rc=0,
            report_rc=0,
            preflight_rc=0,
        )
        self.assertFalse(ready)
        self.assertEqual(result, "PACKAGE_CHANGED")
        self.assertEqual(rc, module.EXIT_REVIEW)
        self.assertEqual(policy, "REQUIRED_FOR_CHANGED_PACKAGE")



if __name__ == "__main__":
    unittest.main()
