from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .util import OtastError, atomic_write, stable_json


def _github_json(url: str, *, timeout: int = 20, attempts: int = 3) -> dict[str, object]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "otast-target-monitor/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise OtastError(f"GitHub returned HTTP {response.status}: {url}")
                payload = response.read(2 * 1024 * 1024 + 1)
                if len(payload) > 2 * 1024 * 1024:
                    raise OtastError(f"GitHub response exceeded size limit: {url}")
                parsed = json.loads(payload.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise OtastError(f"GitHub response is not an object: {url}")
                return parsed
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, OtastError) as exc:
            last = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise OtastError(f"GitHub lookup failed after {attempts} attempts: {url}: {last}")


def monitor_targets(repo_root: Path, output_dir: Path) -> dict[str, object]:
    manifest_path = repo_root / "compatibility/supported-targets.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    targets = data.get("targets")
    if not isinstance(targets, dict):
        raise OtastError("compatibility manifest has no targets object")

    results: list[dict[str, object]] = []
    for target_id in sorted(targets):
        target = targets[target_id]
        if not isinstance(target, dict) or not isinstance(target.get("monitor"), dict):
            continue
        monitor = target["monitor"]
        repository = str(monitor.get("repository", ""))
        branch = str(monitor.get("branch", ""))
        expected = str(monitor.get("expected_head", ""))
        if not repository or not branch or len(expected) != 40:
            raise OtastError(f"invalid monitor configuration for {target_id}")
        url = f"https://api.github.com/repos/{repository}/commits/{branch}"
        try:
            payload = _github_json(url)
            observed = str(payload.get("sha", ""))
            status = "supported" if observed == expected else "review-required"
            error = ""
        except OtastError as exc:
            observed = ""
            status = "monitor-failure"
            error = str(exc)
        results.append(
            {
                "target": target_id,
                "repository": repository,
                "branch": branch,
                "expected_head": expected,
                "observed_head": observed,
                "status": status,
                "error": error,
            }
        )

    overall = "PASS"
    if any(item["status"] == "monitor-failure" for item in results):
        overall = "ERROR"
    elif any(item["status"] == "review-required" for item in results):
        overall = "REVIEW_REQUIRED"
    report = {"schema_version": 1, "result": overall, "targets": results}
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(output_dir / "target-monitor.json", stable_json(report).encode())
    lines = ["# OTAST target monitor", "", f"Result: **{overall}**", "", "| Target | Branch | Expected | Observed | Status |", "|---|---|---|---|---|"]
    for item in results:
        lines.append(
            f"| `{item['target']}` | `{item['repository']}@{item['branch']}` | `{item['expected_head'][:12]}` | "
            f"`{str(item['observed_head'])[:12] or 'unavailable'}` | `{item['status']}` |"
        )
        if item["error"]:
            lines.append(f"\n> {item['target']}: {item['error']}\n")
    atomic_write(output_dir / "target-monitor.md", ("\n".join(lines) + "\n").encode())
    return report
