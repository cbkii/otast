#!/usr/bin/env python3
"""Reliable Termux/GitHub maintenance workflow for OTAST.

This is orchestration only. It never installs OTAST on the live device, executes
upstream installer code, commits, pushes, tags, releases, or edits GitHub code.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import selectors
import shutil
import time
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

EXIT_OK = 0
EXIT_REVIEW = 10
EXIT_ERROR = 20
SCHEMA_VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ControlledError(RuntimeError):
    """Expected failure with a user-actionable message."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def stable_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    atomic_write(path, stable_json(value), mode)


def repo_root() -> Path:
    override = os.environ.get("OTAST_REPO_ROOT")
    candidate = Path(override).expanduser() if override else Path(__file__).resolve().parent.parent
    candidate = candidate.resolve()
    required = [
        candidate / "pyproject.toml",
        candidate / "compatibility/supported-targets.json",
        candidate / "scripts/test.sh",
        candidate / "tools/otastctl",
    ]
    if not all(path.exists() for path in required):
        raise ControlledError(f"path is not a complete OTAST repository: {candidate}")
    return candidate


def require_non_root(operation: str) -> None:
    if os.geteuid() == 0:
        raise ControlledError(f"{operation} must run as the ordinary Termux user, not through su")


def load_registry(root: Path) -> dict[str, Any]:
    path = root / "compatibility/supported-targets.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlledError(f"cannot read supported target registry: {path}: {exc}") from exc
    targets = value.get("targets") if isinstance(value, dict) else None
    if not isinstance(targets, dict) or not targets:
        raise ControlledError("supported-targets.json has no non-empty targets object")
    return value


def canonical_target(registry: dict[str, Any], supplied: str) -> tuple[str, dict[str, Any]]:
    targets = registry["targets"]
    aliases: dict[str, str] = {}
    for key, record in targets.items():
        aliases[str(key).lower()] = str(key)
        if isinstance(record, dict):
            for module_id in record.get("module_ids", []):
                aliases[str(module_id).lower()] = str(key)
    canonical = aliases.get(supplied.lower())
    if canonical is None:
        raise ControlledError(
            f"unknown target {supplied!r}; available: {', '.join(sorted(targets))}"
        )
    record = targets[canonical]
    if not isinstance(record, dict):
        raise ControlledError(f"target record is invalid: {canonical}")
    return canonical, record


def monitor_metadata(target: str, record: dict[str, Any]) -> tuple[str, str, str]:
    monitor = record.get("monitor")
    if not isinstance(monitor, dict):
        raise ControlledError(f"target has no monitor object: {target}")
    repository = monitor.get("repository")
    ref = monitor.get("branch") or monitor.get("ref") or "main"
    expected = monitor.get("expected_head")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ControlledError(f"target has invalid monitor.repository: {target}")
    if not isinstance(ref, str) or not ref or any(ch in ref for ch in "\r\n\0"):
        raise ControlledError(f"target has invalid monitor branch/ref: {target}")
    if not isinstance(expected, str) or SHA_RE.fullmatch(expected) is None:
        raise ControlledError(f"target has invalid monitor.expected_head: {target}")
    return repository, ref, expected


def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    stream: bool = False,
    log_path: Path | None = None,
) -> CommandResult:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    if stream:
        process = subprocess.Popen(
            list(args),
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
        )
        output_parts: list[str] = []
        log_handle = None
        selector = selectors.DefaultSelector()
        deadline = time.monotonic() + timeout
        try:
            if log_path:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_handle = log_path.open("a", encoding="utf-8", newline="\n")
            assert process.stdout is not None
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    raise ControlledError(f"command timed out after {timeout}s: {' '.join(args)}")
                events = selector.select(timeout=min(1.0, remaining))
                if not events:
                    if process.poll() is not None:
                        break
                    continue
                for key, _ in events:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    text = chunk.decode("utf-8", errors="replace")
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    output_parts.append(text)
                    if log_handle:
                        log_handle.write(text)
                        log_handle.flush()
                if process.poll() is not None and not selector.get_map():
                    break
            returncode = process.wait(timeout=max(1.0, deadline - time.monotonic()))
        finally:
            selector.close()
            if log_handle:
                log_handle.close()
        return CommandResult(tuple(args), returncode, "".join(output_parts), "")

    try:
        completed = subprocess.run(
            list(args),
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ControlledError(f"command timed out after {timeout}s: {' '.join(args)}") from exc
    return CommandResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)


def require_program(name: str) -> str:
    value = shutil.which(name)
    if value is None:
        raise ControlledError(f"required command is missing: {name}")
    return value


def gh_environment() -> dict[str, str]:
    """Return a child environment with a GitHub token without printing it."""
    require_program("gh")
    existing = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if existing:
        return {"GH_TOKEN": existing}
    status = run_command(["gh", "auth", "status", "--hostname", "github.com"], timeout=30)
    if status.returncode != 0:
        message = (status.stderr or status.stdout).strip()
        raise ControlledError(
            "GitHub CLI is not authenticated. Run: gh auth login --hostname github.com"
            + (f"\n{message}" if message else "")
        )
    token = run_command(["gh", "auth", "token", "--hostname", "github.com"], timeout=30)
    if token.returncode != 0 or not token.stdout.strip():
        raise ControlledError("gh is authenticated but its active token could not be retrieved")
    return {"GH_TOKEN": token.stdout.strip()}


def gh_api(endpoint: str, *, env: dict[str, str], timeout: int = 45) -> Any:
    result = run_command(["gh", "api", endpoint], env=env, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ControlledError(f"GitHub API request failed: {endpoint}\n{detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ControlledError(f"GitHub API returned malformed JSON: {endpoint}") from exc


def rate_limit(env: dict[str, str]) -> dict[str, Any]:
    value = gh_api("rate_limit", env=env)
    core = value.get("resources", {}).get("core") if isinstance(value, dict) else None
    if not isinstance(core, dict):
        raise ControlledError("GitHub rate-limit response has no core resource")
    result = {
        "limit": int(core.get("limit", 0)),
        "remaining": int(core.get("remaining", 0)),
        "used": int(core.get("used", 0)),
        "reset": int(core.get("reset", 0)),
    }
    return result


def local_time_from_epoch(epoch: int) -> str:
    if epoch <= 0:
        return "unknown"
    return dt.datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def ensure_rate_budget(env: dict[str, str], required: int) -> dict[str, Any]:
    current = rate_limit(env)
    if current["remaining"] < required:
        raise ControlledError(
            "GitHub API allowance is too low for a reliable run: "
            f"{current['remaining']}/{current['limit']} remaining; "
            f"need at least {required}; resets {local_time_from_epoch(current['reset'])}"
        )
    return current


def resolve_commit(repository: str, ref: str, env: dict[str, str]) -> str:
    endpoint = f"repos/{repository}/commits/{quote(ref, safe='')}"
    value = gh_api(endpoint, env=env)
    sha = value.get("sha") if isinstance(value, dict) else None
    if not isinstance(sha, str) or SHA_RE.fullmatch(sha) is None:
        raise ControlledError(f"GitHub returned no valid commit SHA for {repository}@{ref}")
    return sha


def report_dir(root: Path, prefix: str, explicit: str | None = None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
    else:
        candidate = root / "reports" / f"{prefix}-{utc_stamp()}"
    candidate = candidate.resolve(strict=False)
    reports_root = (root / "reports").resolve(strict=False)
    try:
        candidate.relative_to(reports_root)
    except ValueError as exc:
        raise ControlledError(f"report output must remain below {reports_root}: {candidate}") from exc
    if candidate.exists() and any(candidate.iterdir()):
        raise ControlledError(f"report output already exists and is not empty: {candidate}")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def monitor_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# OTAST target monitor",
        "",
        f"Result: **{result['result']}**",
        "",
        "| Target | Upstream | Expected | Observed | Status |",
        "|---|---|---|---|---|",
    ]
    for item in result["targets"]:
        observed = item.get("observed_head") or "unavailable"
        lines.append(
            f"| `{item['target']}` | `{item['repository']}@{item['ref']}` | "
            f"`{item['expected_head'][:12]}` | `{observed[:12] if observed != 'unavailable' else observed}` | "
            f"`{item['status']}` |"
        )
        if item.get("error"):
            lines.extend(["", f"> {item['target']}: {item['error']}", ""])
    rate = result.get("rate_limit_before") or {}
    if rate:
        lines.extend(
            [
                "",
                "## GitHub API",
                "",
                f"- Authenticated allowance before run: {rate.get('remaining')}/{rate.get('limit')}",
                f"- Reset: {local_time_from_epoch(int(rate.get('reset', 0)))}",
            ]
        )
    if result["result"] == "REVIEW_REQUIRED":
        lines.extend(["", "## Next commands", ""])
        for item in result["targets"]:
            if item["status"] == "review-required":
                lines.append(f"```bash\notast review {item['target']}\n```")
    return "\n".join(lines).rstrip() + "\n"


def run_monitor(root: Path, *, output: Path, cleanup: bool, keep: int) -> tuple[int, dict[str, Any]]:
    registry = load_registry(root)
    targets = registry["targets"]
    rows: list[dict[str, Any]] = []
    try:
        env = gh_environment()
        before = ensure_rate_budget(env, len(targets) + 3)
    except ControlledError as exc:
        message = str(exc)
        for target in sorted(targets):
            record = targets[target]
            monitor = record.get("monitor") if isinstance(record, dict) else {}
            rows.append(
                {
                    "target": target,
                    "repository": monitor.get("repository", "") if isinstance(monitor, dict) else "",
                    "ref": (monitor.get("branch") or monitor.get("ref") or "") if isinstance(monitor, dict) else "",
                    "expected_head": monitor.get("expected_head", "") if isinstance(monitor, dict) else "",
                    "observed_head": "",
                    "status": "monitor-failure",
                    "error": message,
                }
            )
        result = {
            "schema_version": 2,
            "generated_utc": utc_now(),
            "result": "ERROR",
            "rate_limit_before": {},
            "targets": rows,
        }
        write_json(output / "target-monitor.json", result)
        atomic_write(output / "target-monitor.md", monitor_markdown(result), 0o600)
        print(stable_json(result), end="")
        print(f"Report: {output / 'target-monitor.md'}")
        print(f"STOP: {message}", file=sys.stderr)
        return EXIT_ERROR, result

    had_error = False
    had_review = False
    fatal_message = ""
    ordered_targets = sorted(targets)
    for index, target in enumerate(ordered_targets):
        record = targets[target]
        try:
            repository, ref, expected = monitor_metadata(target, record)
            observed = resolve_commit(repository, ref, env)
            status = "supported" if observed == expected else "review-required"
            had_review = had_review or status == "review-required"
            rows.append(
                {
                    "target": target,
                    "repository": repository,
                    "ref": ref,
                    "expected_head": expected,
                    "observed_head": observed,
                    "status": status,
                    "error": "",
                }
            )
        except ControlledError as exc:
            had_error = True
            fatal_message = str(exc)
            monitor = record.get("monitor") if isinstance(record, dict) else {}
            rows.append(
                {
                    "target": target,
                    "repository": monitor.get("repository", "") if isinstance(monitor, dict) else "",
                    "ref": (monitor.get("branch") or monitor.get("ref") or "") if isinstance(monitor, dict) else "",
                    "expected_head": monitor.get("expected_head", "") if isinstance(monitor, dict) else "",
                    "observed_head": "",
                    "status": "monitor-failure",
                    "error": fatal_message,
                }
            )
            if any(token in fatal_message.lower() for token in ("rate", "auth", "403", "401")):
                for skipped in ordered_targets[index + 1 :]:
                    skipped_record = targets[skipped]
                    skipped_monitor = skipped_record.get("monitor") if isinstance(skipped_record, dict) else {}
                    rows.append(
                        {
                            "target": skipped,
                            "repository": skipped_monitor.get("repository", "") if isinstance(skipped_monitor, dict) else "",
                            "ref": (skipped_monitor.get("branch") or skipped_monitor.get("ref") or "") if isinstance(skipped_monitor, dict) else "",
                            "expected_head": skipped_monitor.get("expected_head", "") if isinstance(skipped_monitor, dict) else "",
                            "observed_head": "",
                            "status": "monitor-failure",
                            "error": "not attempted after fatal GitHub authentication/rate failure",
                        }
                    )
                break
    if had_error:
        outcome = "ERROR"
        rc = EXIT_ERROR
    elif had_review:
        outcome = "REVIEW_REQUIRED"
        rc = EXIT_REVIEW
    else:
        outcome = "SUPPORTED"
        rc = EXIT_OK
    result = {
        "schema_version": 2,
        "generated_utc": utc_now(),
        "result": outcome,
        "rate_limit_before": before,
        "targets": rows,
    }
    write_json(output / "target-monitor.json", result)
    atomic_write(output / "target-monitor.md", monitor_markdown(result), 0o600)
    print(stable_json(result), end="")
    print(f"Report: {output / 'target-monitor.md'}")
    if fatal_message:
        print(f"STOP: {fatal_message}", file=sys.stderr)
    if rc == EXIT_OK and cleanup:
        cleanup_reports(root, category="target-monitor", current=output, keep=keep, dry_run=False)
    return rc, result


def report_classification(path: Path) -> tuple[str, bool]:
    candidates = [
        (path / "target-monitor.json", {"SUPPORTED"}),
        (path / "review.json", {"NO_PACKAGE_IMPACT", "PACKAGE_CHANGED"}),
        (path / "maintenance.json", {"PASS"}),
    ]
    for file_path, success_values in candidates:
        if not file_path.is_file():
            continue
        try:
            value = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "unknown", False
        outcome = str(value.get("result", "unknown"))
        return outcome, outcome in success_values
    return "unknown", False


def cleanup_reports(
    root: Path,
    *,
    category: str = "all",
    current: Path | None = None,
    keep: int = 3,
    dry_run: bool = False,
) -> list[Path]:
    reports = (root / "reports").resolve()
    reports.mkdir(parents=True, exist_ok=True)
    patterns = {
        "target-monitor": ["target-monitor-*"],
        "target-review": ["target-review-*"],
        "maintenance": ["maintenance-*"],
    }
    selected = patterns if category == "all" else {category: patterns.get(category, [])}
    if not selected or any(not value for value in selected.values()):
        raise ControlledError(f"unknown report cleanup category: {category}")

    grouped: dict[tuple[str, str], list[Path]] = {}
    for category_name, globs in selected.items():
        matches: dict[Path, None] = {}
        for pattern in globs:
            for candidate in reports.glob(pattern):
                if candidate.is_dir() and not candidate.is_symlink():
                    matches[candidate.resolve()] = None
        for candidate in matches:
            group = "all"
            if category_name == "target-review":
                review_path = candidate / "review.json"
                try:
                    value = json.loads(review_path.read_text(encoding="utf-8"))
                    group = str(value.get("target") or "unknown")
                except (OSError, json.JSONDecodeError):
                    group = "unknown"
            grouped.setdefault((category_name, group), []).append(candidate)

    removed: list[Path] = []
    current_resolved = current.resolve() if current else None
    for _, candidates in sorted(grouped.items()):
        ordered = sorted(candidates, key=lambda item: item.stat().st_mtime_ns, reverse=True)
        successful = [item for item in ordered if report_classification(item)[1]]
        unsuccessful = [item for item in ordered if not report_classification(item)[1]]
        # Keep the requested successful history plus the newest failed/unknown run for diagnosis.
        keep_set = set(successful[: max(keep, 0)]) | set(unsuccessful[:1])
        if current_resolved:
            keep_set.add(current_resolved)
        for candidate in ordered:
            if candidate in keep_set or (candidate / ".otast-keep").exists():
                continue
            removed.append(candidate)
            if dry_run:
                print(f"WOULD_REMOVE {candidate}")
            else:
                shutil.rmtree(candidate)
                print(f"REMOVED      {candidate}")
    if not removed:
        print("CLEANUP      nothing to remove")
    return removed


def latest_fixture() -> Path:
    root = Path.home() / ".local/share/otast/device-fixtures"
    candidates = [path for path in root.glob("*") if path.is_dir() and not path.is_symlink()]
    if not candidates:
        raise ControlledError(f"no captured fixture exists under {root}")
    return max(candidates, key=lambda item: item.stat().st_mtime_ns).resolve()


def fake_root_path(name: str) -> Path:
    if SAFE_NAME_RE.fullmatch(name) is None:
        raise ControlledError(f"unsafe fake-root name: {name!r}")
    return (Path.home() / ".cache/otast/fake-roots" / name).resolve(strict=False)


def child_token_env() -> dict[str, str]:
    return gh_environment()


def parse_json_output(result: CommandResult, label: str) -> dict[str, Any]:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ControlledError(f"{label} failed with status {result.returncode}\n{detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ControlledError(f"{label} returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise ControlledError(f"{label} returned a non-object JSON result")
    return value


def fetch_ref_evidence(root: Path, target: str, sha: str, env: dict[str, str]) -> dict[str, Any]:
    helper = root / "scripts/upstream-target-package.py"
    result = run_command(
        [sys.executable, str(helper), "fetch-ref", target, "--ref", sha],
        cwd=root,
        env=env,
        timeout=180,
    )
    return parse_json_output(result, f"fetch-ref {target}@{sha[:12]}")


def tree_file_map(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_dir() or path.is_symlink():
        raise ControlledError(f"module tree is missing or unsafe: {path}")
    result: dict[str, dict[str, Any]] = {}
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ControlledError(f"module tree contains a symlink: {item}")
        if not item.is_file():
            continue
        digest = hashlib.sha256()
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result[item.relative_to(path).as_posix()] = {
            "sha256": digest.hexdigest(),
            "size": item.stat().st_size,
            "mode": f"{stat.S_IMODE(item.stat().st_mode):04o}",
        }
    return result


def evidence_module_path(metadata: dict[str, Any]) -> Path:
    source = Path(str(metadata.get("source_tree", ""))).resolve()
    module_root = Path(str(metadata.get("module_root", "")))
    path = (source / module_root).resolve()
    try:
        path.relative_to(source)
    except ValueError as exc:
        raise ControlledError("candidate module root escapes retained source tree") from exc
    return path


def compare_maps(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> dict[str, Any]:
    added: list[str] = []
    removed: list[str] = []
    changed: list[dict[str, Any]] = []
    same = 0
    for relative in sorted(set(old) | set(new)):
        left = old.get(relative)
        right = new.get(relative)
        if left is None:
            added.append(relative)
        elif right is None:
            removed.append(relative)
        elif left == right:
            same += 1
        else:
            changed.append({"path": relative, "old": left, "new": right})
    return {"identical": not added and not removed and not changed, "same": same, "added": added, "removed": removed, "changed": changed}


def review_markdown(value: dict[str, Any]) -> str:
    lines = [
        f"# OTAST target review: {value['target']}",
        "",
        f"Result: **{value['result']}**",
        "",
        f"- Upstream: `{value['repository']}@{value['ref']}`",
        f"- Previously reviewed head: `{value['expected_head']}`",
        f"- Observed head: `{value['observed_head']}`",
        f"- Fake root: `{value['fake_root']}`",
        f"- Installer execution: `NEVER_EXECUTED`",
        f"- Module trees identical: `{str(value['module_comparison']['identical']).lower()}`",
        f"- Active/candidate comparison status: `{value['active_candidate_compare_rc']}`",
        f"- Report status: `{value['report_rc']}`",
        f"- Preflight status: `{value['preflight_rc']}`",
        "",
        "## Module comparison",
        "",
        f"- Same files: {value['module_comparison']['same']}",
        f"- Added: {len(value['module_comparison']['added'])}",
        f"- Removed: {len(value['module_comparison']['removed'])}",
        f"- Changed: {len(value['module_comparison']['changed'])}",
    ]
    if value["acceptance_ready"]:
        lines.extend(["", "## Next", "", f"```bash\notast accept {value['target']}\n```"])
    else:
        lines.extend(["", "## Next", "", "Do not advance the monitor baseline. Update and validate the compatibility profile/runtime first."])
    return "\n".join(lines) + "\n"


def run_review(root: Path, target_arg: str, observed_arg: str | None, fixture_arg: str | None, name_arg: str | None, keep: int) -> tuple[int, dict[str, Any], Path]:
    registry = load_registry(root)
    target, record = canonical_target(registry, target_arg)
    repository, ref, expected = monitor_metadata(target, record)
    env = child_token_env()
    ensure_rate_budget(env, 8)
    observed = observed_arg or resolve_commit(repository, ref, env)
    if SHA_RE.fullmatch(observed) is None:
        raise ControlledError(f"observed SHA is invalid: {observed!r}")
    if observed == expected:
        raise ControlledError(f"{target} is already current at {observed[:12]}; no review is required")
    output = report_dir(root, f"target-review-{target}-{observed[:12]}")
    log = output / "review.log"
    print(f"Review output: {output}")
    print(f"Target:        {target}")
    print(f"Expected:      {expected}")
    print(f"Observed:      {observed}")

    old_evidence = fetch_ref_evidence(root, target, expected, env)
    new_evidence = fetch_ref_evidence(root, target, observed, env)
    old_map = tree_file_map(evidence_module_path(old_evidence))
    new_map = tree_file_map(evidence_module_path(new_evidence))
    comparison = compare_maps(old_map, new_map)
    write_json(output / "module-comparison.json", comparison)

    fixture = Path(fixture_arg).expanduser().resolve() if fixture_arg else latest_fixture()
    name = name_arg or f"review-{target}-{observed[:12]}"
    fake_root = fake_root_path(name)
    reset = run_command(
        ["bash", str(root / "scripts/reset-fake-magisk-root.sh"), str(fixture), name],
        cwd=root,
        timeout=300,
        stream=True,
        log_path=log,
    )
    if reset.returncode != 0:
        raise ControlledError(f"fake-root reset failed with status {reset.returncode}; log: {log}")
    package = str(new_evidence.get("package", ""))
    materialize = run_command(
        [sys.executable, str(root / "scripts/upstream-target-package.py"), "materialize", target, package, str(fake_root), "--tree", "modules_update"],
        cwd=root,
        env=env,
        timeout=300,
        stream=True,
        log_path=log,
    )
    if materialize.returncode != 0:
        raise ControlledError(f"candidate materialization failed with status {materialize.returncode}; log: {log}")

    active_compare = run_command(
        [sys.executable, str(root / "scripts/upstream-target-package.py"), "compare", target, str(fake_root)],
        cwd=root,
        env=env,
        timeout=300,
        stream=True,
        log_path=log,
    )

    report = run_command(
        ["bash", str(root / "scripts/validate-fake-magisk-root.sh"), str(fake_root), "report"],
        cwd=root,
        timeout=300,
        stream=True,
        log_path=log,
    )
    preflight = run_command(
        ["bash", str(root / "scripts/validate-fake-magisk-root.sh"), str(fake_root), "preflight"],
        cwd=root,
        timeout=300,
        stream=True,
        log_path=log,
    )

    acceptance_ready = (
        comparison["identical"]
        and active_compare.returncode == 0
        and report.returncode == 0
        and preflight.returncode == 0
    )
    if acceptance_ready:
        result_name = "NO_PACKAGE_IMPACT"
        rc = EXIT_OK
    elif not comparison["identical"]:
        result_name = "PACKAGE_CHANGED"
        rc = EXIT_REVIEW
    else:
        result_name = "VALIDATION_FAILED"
        rc = EXIT_ERROR
    result = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "result": result_name,
        "acceptance_ready": acceptance_ready,
        "target": target,
        "repository": repository,
        "ref": ref,
        "expected_head": expected,
        "observed_head": observed,
        "fixture": str(fixture),
        "fake_root": str(fake_root),
        "old_evidence": str(old_evidence.get("evidence_dir", "")),
        "new_evidence": str(new_evidence.get("evidence_dir", "")),
        "module_comparison": comparison,
        "active_candidate_compare_rc": active_compare.returncode,
        "report_rc": report.returncode,
        "preflight_rc": preflight.returncode,
        "installer_execution": "NEVER_EXECUTED",
        "log": str(log),
    }
    write_json(output / "review.json", result)
    atomic_write(output / "review.md", review_markdown(result), 0o600)
    print(stable_json(result), end="")
    print(f"Review: {output / 'review.md'}")
    if rc in (EXIT_OK, EXIT_REVIEW):
        cleanup_reports(root, category="target-review", current=output, keep=keep, dry_run=False)
    return rc, result, output


def find_latest_review(root: Path, target: str) -> Path:
    candidates = []
    for directory in (root / "reports").glob(f"target-review-{target}-*"):
        review = directory / "review.json"
        if directory.is_dir() and review.is_file():
            try:
                value = json.loads(review.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("target") == target:
                candidates.append(directory)
    if not candidates:
        raise ControlledError(f"no completed review exists for target: {target}")
    return max(candidates, key=lambda item: item.stat().st_mtime_ns)


def find_object_for_key(text: str, key: str, *, start: int = 0, end: int | None = None) -> tuple[int, int]:
    if end is None:
        end = len(text)
    pattern = re.compile(r'"' + re.escape(key) + r'"\s*:')
    match = pattern.search(text, start, end)
    if match is None:
        raise ControlledError(f"JSON key not found while preparing structured update: {key}")
    cursor = match.end()
    while cursor < end and text[cursor].isspace():
        cursor += 1
    if cursor >= end or text[cursor] != "{":
        raise ControlledError(f"JSON key is not an object: {key}")
    object_start = cursor
    depth = 0
    in_string = False
    escaped = False
    while cursor < end:
        character = text[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        else:
            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return object_start, cursor + 1
        cursor += 1
    raise ControlledError(f"unterminated JSON object: {key}")


def update_expected_head_text(text: str, target: str, old: str, new: str) -> str:
    targets_start, targets_end = find_object_for_key(text, "targets")
    target_start, target_end = find_object_for_key(text, target, start=targets_start, end=targets_end)
    monitor_start, monitor_end = find_object_for_key(text, "monitor", start=target_start, end=target_end)
    monitor_text = text[monitor_start:monitor_end]
    pattern = re.compile(r'("expected_head"\s*:\s*")' + re.escape(old) + r'(")')
    updated_monitor, count = pattern.subn(r"\g<1>" + new + r"\g<2>", monitor_text, count=1)
    if count != 1:
        raise ControlledError("expected monitor.expected_head transition was not found exactly once")
    updated = text[:monitor_start] + updated_monitor + text[monitor_end:]
    before = json.loads(text)
    after = json.loads(updated)
    if before["targets"][target]["monitor"]["expected_head"] != old:
        raise ControlledError("registry changed since review: old expected head no longer matches")
    if after["targets"][target]["monitor"]["expected_head"] != new:
        raise ControlledError("structured monitor update did not produce the expected value")
    before_copy = json.loads(text)
    before_copy["targets"][target]["monitor"]["expected_head"] = new
    if before_copy != after:
        raise ControlledError("structured update would alter more than monitor.expected_head")
    return updated


def run_accept(root: Path, target_arg: str, review_arg: str | None, keep: int) -> tuple[int, dict[str, Any]]:
    registry = load_registry(root)
    target, record = canonical_target(registry, target_arg)
    _, _, expected = monitor_metadata(target, record)
    review_dir = Path(review_arg).expanduser().resolve() if review_arg else find_latest_review(root, target)
    review_path = review_dir / "review.json" if review_dir.is_dir() else review_dir
    if review_path.name == "review.json":
        review_dir = review_path.parent
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlledError(f"cannot read target review: {review_path}: {exc}") from exc
    if review.get("target") != target:
        raise ControlledError("review target does not match requested target")
    if review.get("acceptance_ready") is not True or review.get("result") != "NO_PACKAGE_IMPACT":
        raise ControlledError("review is not acceptance-ready; do not advance the baseline")
    if review.get("expected_head") != expected:
        raise ControlledError("registry baseline changed after this review; run a new review")
    observed = review.get("observed_head")
    if not isinstance(observed, str) or SHA_RE.fullmatch(observed) is None:
        raise ControlledError("review has no valid observed commit")

    registry_path = root / "compatibility/supported-targets.json"
    original = registry_path.read_text(encoding="utf-8")
    updated = update_expected_head_text(original, target, expected, observed)
    atomic_write(registry_path, updated, stat.S_IMODE(registry_path.stat().st_mode))

    monitor_output = report_dir(root, "target-monitor-accept")
    try:
        monitor_rc, monitor_result = run_monitor(root, output=monitor_output, cleanup=False, keep=keep)
    except Exception:
        atomic_write(registry_path, original, stat.S_IMODE(registry_path.stat().st_mode))
        raise
    target_result = next((item for item in monitor_result["targets"] if item["target"] == target), None)
    if not target_result or target_result.get("status") != "supported" or target_result.get("observed_head") != observed:
        atomic_write(registry_path, original, stat.S_IMODE(registry_path.stat().st_mode))
        raise ControlledError("post-update monitor did not confirm the accepted target; registry was restored")

    diff_check = run_command(["git", "diff", "--check"], cwd=root, timeout=30)
    if diff_check.returncode != 0:
        atomic_write(registry_path, original, stat.S_IMODE(registry_path.stat().st_mode))
        raise ControlledError("git diff --check failed after acceptance; registry was restored")

    acceptance = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "result": "ACCEPTED",
        "target": target,
        "from": expected,
        "to": observed,
        "review": str(review_path),
        "changed_path": f"targets.{target}.monitor.expected_head",
        "post_monitor_result": monitor_result["result"],
        "post_monitor_report": str(monitor_output / "target-monitor.md"),
    }
    write_json(review_dir / "acceptance.json", acceptance)
    print(stable_json(acceptance), end="")
    if monitor_rc == EXIT_OK:
        cleanup_reports(root, category="target-monitor", current=monitor_output, keep=keep, dry_run=False)
        return EXIT_OK, acceptance
    if monitor_rc == EXIT_REVIEW:
        # Another target may have moved concurrently. The accepted target remains proven.
        print("REVIEW_REQUIRED: accepted target is current, but another target requires review.", file=sys.stderr)
        return EXIT_REVIEW, acceptance
    print(
        "STOP: accepted target is current, but another monitor lookup failed; "
        "inspect the post-monitor report.",
        file=sys.stderr,
    )
    return EXIT_ERROR, acceptance


def run_doctor(root: Path) -> int:
    require_non_root("OTAST maintenance")
    for command in ("bash", "git", "gh", "python3"):
        path = require_program(command)
        print(f"PASS command {command}: {path}")
    env = gh_environment()
    current = ensure_rate_budget(env, 10)
    print(f"PASS GitHub authentication: {current['remaining']}/{current['limit']} API requests remaining")
    print(f"INFO API reset: {local_time_from_epoch(current['reset'])}")
    registry = load_registry(root)
    for target, record in sorted(registry["targets"].items()):
        repository, ref, expected = monitor_metadata(target, record)
        print(f"PASS target {target}: {repository}@{ref} expected {expected[:12]}")
    result = run_command(["bash", str(root / "scripts/check-dev-environment.sh")], cwd=root, timeout=180, stream=True)
    if result.returncode != 0:
        raise ControlledError(f"repository environment check failed with status {result.returncode}")
    return EXIT_OK


def maintenance_markdown(value: dict[str, Any]) -> str:
    lines = [
        "# OTAST maintenance run",
        "",
        f"Result: **{value['result']}**",
        "",
        f"- Started: `{value['started_utc']}`",
        f"- Finished: `{value['finished_utc']}`",
        f"- Monitor: `{value['monitor_result']}`",
        f"- Test mode: `{value['test_mode']}`",
        f"- Test status: `{value['test_rc']}`",
        f"- Audit status: `{value['audit_rc']}`",
        f"- Device proof status: `{value['proof_rc']}`",
        "",
        f"Log: `{value['log']}`",
    ]
    return "\n".join(lines) + "\n"


def run_maintenance(root: Path, *, mode: str, audit: bool, device_proof: bool, keep: int) -> int:
    output = report_dir(root, "maintenance")
    log = output / "maintenance.log"
    started = utc_now()
    print(f"Maintenance output: {output}")
    try:
        run_doctor(root)
    except ControlledError as exc:
        result = {
            "schema_version": 1,
            "result": "ERROR",
            "started_utc": started,
            "finished_utc": utc_now(),
            "monitor_result": "NOT_RUN",
            "test_mode": mode,
            "test_rc": None,
            "audit_rc": None,
            "proof_rc": None,
            "log": str(log),
            "error": str(exc),
        }
        write_json(output / "maintenance.json", result)
        atomic_write(output / "maintenance.md", maintenance_markdown(result), 0o600)
        raise

    monitor_output = report_dir(root, "target-monitor-maintenance")
    monitor_rc, monitor_result = run_monitor(root, output=monitor_output, cleanup=False, keep=keep)
    if monitor_rc != EXIT_OK:
        result = {
            "schema_version": 1,
            "result": "REVIEW_REQUIRED" if monitor_rc == EXIT_REVIEW else "ERROR",
            "started_utc": started,
            "finished_utc": utc_now(),
            "monitor_result": monitor_result["result"],
            "monitor_report": str(monitor_output / "target-monitor.md"),
            "test_mode": mode,
            "test_rc": None,
            "audit_rc": None,
            "proof_rc": None,
            "log": str(log),
        }
        write_json(output / "maintenance.json", result)
        atomic_write(output / "maintenance.md", maintenance_markdown(result), 0o600)
        if monitor_rc == EXIT_REVIEW:
            print("Target review required. Run the command(s) listed in the monitor report.")
        return monitor_rc

    audit_rc: int | None = None
    if audit:
        audit_output = root / "reports" / f"public-init-maintenance-{utc_stamp()}"
        audit_result = run_command(
            ["bash", str(root / "scripts/public-init-audit.sh"), str(audit_output)],
            cwd=root,
            timeout=1200,
            stream=True,
            log_path=log,
        )
        audit_rc = audit_result.returncode
        # The public-boundary audit already includes the complete repository test suite.
        test = CommandResult(("public-init-audit",), 0 if audit_rc == 0 else audit_rc, "", "")
        mode = "audit(full)"
    else:
        test = run_command(
            ["bash", str(root / "scripts/test.sh"), f"--{mode}"],
            cwd=root,
            timeout=1200,
            stream=True,
            log_path=log,
        )
    proof_rc: int | None = None
    if test.returncode == 0 and (audit_rc in (None, 0)) and device_proof:
        proof = run_command(
            ["bash", str(root / "scripts/prove-device-fake-root.sh"), "--fixture", str(latest_fixture()), "--restore-clone"],
            cwd=root,
            timeout=1200,
            stream=True,
            log_path=log,
        )
        proof_rc = proof.returncode
    success = test.returncode == 0 and audit_rc in (None, 0) and proof_rc in (None, 0)
    result = {
        "schema_version": 1,
        "result": "PASS" if success else "ERROR",
        "started_utc": started,
        "finished_utc": utc_now(),
        "monitor_result": monitor_result["result"],
        "monitor_report": str(monitor_output / "target-monitor.md"),
        "test_mode": mode,
        "test_rc": test.returncode,
        "audit_rc": audit_rc,
        "proof_rc": proof_rc,
        "log": str(log),
    }
    write_json(output / "maintenance.json", result)
    atomic_write(output / "maintenance.md", maintenance_markdown(result), 0o600)
    print(stable_json(result), end="")
    if success:
        cleanup_reports(root, category="target-monitor", current=monitor_output, keep=keep, dry_run=False)
        cleanup_reports(root, category="maintenance", current=output, keep=keep, dry_run=False)
        return EXIT_OK
    return EXIT_ERROR


def ensure_label(repo: str, name: str, color: str, description: str, env: dict[str, str]) -> None:
    result = run_command(
        ["gh", "label", "create", name, "--repo", repo, "--color", color, "--description", description, "--force"],
        env=env,
        timeout=45,
    )
    if result.returncode != 0:
        raise ControlledError(f"cannot ensure issue label {name}: {(result.stderr or result.stdout).strip()}")


def issue_body(item: dict[str, Any], issue_number: int | None = None) -> str:
    target = item["target"]
    marker = f"<!-- otast-target-monitor:{target} -->"
    observed = item.get("observed_head") or "unavailable"
    status = item["status"]
    lines = [
        marker,
        f"# OTAST target monitor: `{target}`",
        "",
        f"Status: **{status}**",
        "",
        "## Upstream state",
        "",
        f"- Repository/ref: `{item.get('repository')}@{item.get('ref')}`",
        f"- Reviewed baseline: `{item.get('expected_head')}`",
        f"- Observed head: `{observed}`",
    ]
    if item.get("error"):
        lines.extend([f"- Monitor error: `{item['error']}`"])
    lines.extend(
        [
            "",
            "## Termux reproduction",
            "",
            "```bash",
            "cd \"$HOME/repos/otast\"",
            "otast doctor",
            f"otast review {target}" if status == "review-required" else "otast monitor",
            "```",
            "",
            "## Required resolution",
            "",
            "1. Retain and inspect the exact immutable upstream source/release evidence.",
            "2. Compare the previously reviewed and observed module trees, including hashes and modes.",
            "3. Run fake-root Report and Preflight without executing upstream installers.",
            "4. Update compatibility/runtime support when the package changed; otherwise use the structured baseline-accept command.",
            "5. Run `otast maintain --full` and keep all private fixture/evidence paths outside Git.",
            "6. Open a focused PR containing the evidence summary and tests.",
            "",
            "## Acceptance criteria",
            "",
            "- Monitor on the PR head reports the target as `supported`.",
            "- Full tests and public-boundary audit pass.",
            "- Device proof is included when installer-generated or runtime behaviour changed.",
            "- The PR body includes `Closes #" + (str(issue_number) if issue_number else "<issue-number>") + "`.",
            "",
            "This issue is reconciled automatically. It closes only after the default branch contains a reviewed matching baseline.",
        ]
    )
    return "\n".join(lines) + "\n"


def sync_issues(report_path: Path, repository: str) -> int:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlledError(f"cannot read monitor report: {report_path}: {exc}") from exc
    env = gh_environment()
    ensure_label(repository, "monitor", "0E8A16", "Automated upstream target monitoring", env)
    ensure_label(repository, "compatibility", "5319E7", "Target compatibility maintenance", env)
    ensure_label(repository, "needs-review", "D93F0B", "Human or agent review required", env)

    listed = run_command(
        ["gh", "issue", "list", "--repo", repository, "--state", "all", "--limit", "200", "--json", "number,state,title,body"],
        env=env,
        timeout=60,
    )
    if listed.returncode != 0:
        raise ControlledError(f"cannot list monitor issues: {(listed.stderr or listed.stdout).strip()}")
    try:
        issues = json.loads(listed.stdout)
    except json.JSONDecodeError as exc:
        raise ControlledError("gh issue list returned malformed JSON") from exc
    by_marker: dict[str, dict[str, Any]] = {}
    for issue in issues:
        body = str(issue.get("body") or "")
        for match in re.finditer(r"<!-- otast-target-monitor:([A-Za-z0-9._-]+) -->", body):
            by_marker[match.group(1)] = issue

    for item in report.get("targets", []):
        target = item["target"]
        label = f"target:{target}"
        ensure_label(repository, label, "BFDADC", f"OTAST target {target}", env)
        existing = by_marker.get(target)
        if item["status"] == "supported":
            if existing and existing.get("state") == "OPEN":
                close = run_command(
                    ["gh", "issue", "close", str(existing["number"]), "--repo", repository, "--comment", "The default branch monitor now reports this target as supported."],
                    env=env,
                    timeout=45,
                )
                if close.returncode != 0:
                    raise ControlledError(f"cannot close issue #{existing['number']}: {(close.stderr or close.stdout).strip()}")
            continue
        title = f"[OTAST target] {target} upstream review required" if item["status"] == "review-required" else f"[OTAST monitor] {target} lookup failed"
        if existing:
            number = int(existing["number"])
            body = issue_body(item, number)
            # Use a temporary body file so the issue body is passed without shell interpolation.
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                handle.write(body)
                body_path = Path(handle.name)
            try:
                edit = run_command(
                    ["gh", "issue", "edit", str(number), "--repo", repository, "--title", title, "--body-file", str(body_path), "--add-label", "monitor,compatibility,needs-review," + label],
                    env=env,
                    timeout=60,
                )
                if edit.returncode != 0:
                    raise ControlledError(f"cannot update issue #{number}: {(edit.stderr or edit.stdout).strip()}")
                if existing.get("state") == "CLOSED":
                    reopen = run_command(["gh", "issue", "reopen", str(number), "--repo", repository], env=env, timeout=45)
                    if reopen.returncode != 0:
                        raise ControlledError(f"cannot reopen issue #{number}: {(reopen.stderr or reopen.stdout).strip()}")
            finally:
                body_path.unlink(missing_ok=True)
        else:
            provisional = issue_body(item)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                handle.write(provisional)
                body_path = Path(handle.name)
            try:
                create = run_command(
                    ["gh", "issue", "create", "--repo", repository, "--title", title, "--body-file", str(body_path), "--label", "monitor,compatibility,needs-review," + label],
                    env=env,
                    timeout=60,
                )
                if create.returncode != 0:
                    raise ControlledError(f"cannot create issue for {target}: {(create.stderr or create.stdout).strip()}")
                match = re.search(r"/issues/(\d+)(?:\s*)$", create.stdout.strip())
                if match is None:
                    raise ControlledError(
                        f"created issue for {target}, but could not determine its number from gh output: "
                        f"{create.stdout.strip()!r}"
                    )
                number = int(match.group(1))
                body_path.write_text(issue_body(item, number), encoding="utf-8")
                edit = run_command(
                    ["gh", "issue", "edit", str(number), "--repo", repository, "--body-file", str(body_path)],
                    env=env,
                    timeout=60,
                )
                if edit.returncode != 0:
                    raise ControlledError(
                        f"created issue #{number}, but could not bind its closure instruction: "
                        f"{(edit.stderr or edit.stdout).strip()}"
                    )
            finally:
                body_path.unlink(missing_ok=True)
    return EXIT_OK


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Authenticated, structured OTAST maintenance for Termux and GitHub Actions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0=complete/supported, 10=review required, 20=error.",
    )
    sub = result.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check Termux, repository, gh authentication and API budget.")

    monitor = sub.add_parser("monitor", help="Run the authenticated upstream target monitor.")
    monitor.add_argument("--output")
    monitor.add_argument("--no-cleanup", action="store_true")
    monitor.add_argument("--keep", type=int, default=3)

    review = sub.add_parser("review", help="Review one observed upstream target change end-to-end.")
    review.add_argument("target")
    review.add_argument("--observed")
    review.add_argument("--fixture")
    review.add_argument("--name")
    review.add_argument("--keep", type=int, default=3)

    accept = sub.add_parser("accept", help="Advance only monitor.expected_head from a passing no-impact review.")
    accept.add_argument("target")
    accept.add_argument("--review")
    accept.add_argument("--keep", type=int, default=3)

    maintain = sub.add_parser("maintain", help="Doctor, monitor and test in one memorable command.")
    modes = maintain.add_mutually_exclusive_group()
    modes.add_argument("--quick", action="store_true")
    modes.add_argument("--full", action="store_true")
    maintain.add_argument("--audit", action="store_true")
    maintain.add_argument("--device-proof", action="store_true")
    maintain.add_argument("--keep", type=int, default=3)

    cleanup = sub.add_parser("cleanup", help="Prune old transient report histories safely.")
    cleanup.add_argument("--category", choices=("all", "target-monitor", "target-review", "maintenance"), default="all")
    cleanup.add_argument("--keep", type=int, default=3)
    cleanup.add_argument("--dry-run", action="store_true")

    issues = sub.add_parser("issues-sync", help="Reconcile deterministic GitHub issues from a monitor report.")
    issues.add_argument("--report", required=True)
    issues.add_argument("--repo", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        require_non_root(f"otast maintenance {args.command}")
        root = repo_root()
        if args.command == "doctor":
            return run_doctor(root)
        if args.command == "monitor":
            output = report_dir(root, "target-monitor", args.output)
            rc, _ = run_monitor(root, output=output, cleanup=not args.no_cleanup, keep=args.keep)
            return rc
        if args.command == "review":
            rc, _, _ = run_review(root, args.target, args.observed, args.fixture, args.name, args.keep)
            return rc
        if args.command == "accept":
            rc, _ = run_accept(root, args.target, args.review, args.keep)
            return rc
        if args.command == "maintain":
            mode = "full" if args.full else "quick" if args.quick else "standard"
            return run_maintenance(root, mode=mode, audit=args.audit, device_proof=args.device_proof, keep=args.keep)
        if args.command == "cleanup":
            cleanup_reports(root, category=args.category, keep=args.keep, dry_run=args.dry_run)
            return EXIT_OK
        if args.command == "issues-sync":
            return sync_issues(Path(args.report).expanduser().resolve(), args.repo)
        raise ControlledError(f"unsupported command: {args.command}")
    except ControlledError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("STOP: interrupted by user", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
