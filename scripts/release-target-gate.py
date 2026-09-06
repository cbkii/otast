#!/usr/bin/env python3
"""Release-specific compatibility gate layered on the strict upstream monitor.

Normal maintenance continues to flag any monitored branch movement. During an
OTAST release, a review-required branch movement may be non-blocking only when the
target's supported distribution is an exact pinned release artifact and that tag
and GitHub asset digest still match the reviewed registry identity.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

EXIT_OK = 0
EXIT_REVIEW = 10
EXIT_ERROR = 20


class GateError(RuntimeError):
    pass


def github_json(url: str, *, attempts: int = 3, timeout: int = 20) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "otast-release-target-gate/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
                if response.status != 200 or len(payload) > 2 * 1024 * 1024:
                    raise GateError(f"invalid GitHub response for {url}")
                value = json.loads(payload.decode("utf-8"))
                if not isinstance(value, dict):
                    raise GateError(f"GitHub response is not an object: {url}")
                return value
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, GateError) as exc:
            last = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise GateError(f"GitHub lookup failed after {attempts} attempts: {url}: {last}")


def load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise GateError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{label} must be a JSON object")
    return value


def verify_release_asset(
    target: str,
    distribution: dict[str, Any],
    fetch: Callable[[str], dict[str, Any]],
) -> dict[str, str]:
    repository = distribution.get("repository")
    release = distribution.get("release") or distribution.get("release_ref")
    asset_name = distribution.get("asset_name") or distribution.get("release_asset_name")
    asset_sha = distribution.get("asset_sha256") or distribution.get("release_asset_sha256")
    expected_commit = distribution.get("reviewed_commit") or distribution.get("reviewed_source_commit")
    if not all(isinstance(item, str) and item for item in (repository, release, asset_name, asset_sha, expected_commit)):
        raise GateError(f"{target}: pinned release distribution identity is incomplete")

    encoded_release = urllib.parse.quote(str(release), safe="")
    commit = fetch(f"https://api.github.com/repos/{repository}/commits/{encoded_release}")
    observed_commit = commit.get("sha")
    if observed_commit != expected_commit:
        raise GateError(
            f"{target}: reviewed release ref moved: expected={expected_commit} observed={observed_commit}"
        )

    metadata = fetch(f"https://api.github.com/repos/{repository}/releases/tags/{encoded_release}")
    if metadata.get("draft") is True or metadata.get("tag_name") != release:
        raise GateError(f"{target}: reviewed release metadata is no longer valid")
    assets = metadata.get("assets")
    if not isinstance(assets, list):
        raise GateError(f"{target}: reviewed release has no asset inventory")
    matches = [item for item in assets if isinstance(item, dict) and item.get("name") == asset_name]
    if len(matches) != 1:
        raise GateError(f"{target}: reviewed release asset is missing or ambiguous: {asset_name}")
    digest = matches[0].get("digest")
    expected_digest = f"sha256:{asset_sha}"
    if digest != expected_digest:
        raise GateError(
            f"{target}: reviewed release asset digest changed: expected={expected_digest} observed={digest}"
        )
    return {
        "release": str(release),
        "commit": str(expected_commit),
        "asset": str(asset_name),
        "sha256": str(asset_sha),
    }


def evaluate(
    root: Path,
    monitor: dict[str, Any],
    *,
    fetch: Callable[[str], dict[str, Any]] = github_json,
) -> tuple[int, dict[str, Any]]:
    registry = load_object(root / "compatibility/supported-targets.json", "compatibility registry")
    targets = registry.get("targets")
    rows = monitor.get("targets")
    if not isinstance(targets, dict) or not isinstance(rows, list):
        raise GateError("monitor/registry target data is malformed")

    result_rows: list[dict[str, Any]] = []
    blockers = False
    for row in rows:
        if not isinstance(row, dict):
            raise GateError("monitor contains a malformed target row")
        target = row.get("target")
        status = row.get("status")
        if not isinstance(target, str) or target not in targets:
            raise GateError(f"monitor references unknown target: {target!r}")
        record = targets[target]
        if not isinstance(record, dict):
            raise GateError(f"target registry record is malformed: {target}")
        distribution = record.get("distribution_identity")
        if not isinstance(distribution, dict):
            raise GateError(f"target distribution identity is missing: {target}")
        source_type = distribution.get("source_type")

        if source_type in {"RELEASE_ASSET", "RELEASE_AND_WORKFLOW_ARTIFACT"}:
            proof = verify_release_asset(target, distribution, fetch)
            release_status = "pinned-artifact-supported"
            advisory = status == "review-required"
            result_rows.append(
                {
                    "target": target,
                    "monitor_status": status,
                    "release_status": release_status,
                    "advisory_branch_drift": advisory,
                    "pinned_artifact": proof,
                }
            )
            continue

        if status != "supported":
            blockers = True
            release_status = "review-required"
        else:
            release_status = "supported"
        result_rows.append(
            {
                "target": target,
                "monitor_status": status,
                "release_status": release_status,
                "advisory_branch_drift": False,
            }
        )

    result = "REVIEW_REQUIRED" if blockers else "PASS"
    return (EXIT_REVIEW if blockers else EXIT_OK), {
        "schema_version": 1,
        "result": result,
        "targets": result_rows,
    }


def render_markdown(value: dict[str, Any]) -> str:
    lines = [
        "# OTAST release target gate",
        "",
        f"Result: **{value['result']}**",
        "",
        "| Target | Monitor | Release gate | Note |",
        "|---|---|---|---|",
    ]
    for row in value["targets"]:
        note = ""
        if row.get("advisory_branch_drift"):
            proof = row.get("pinned_artifact") or {}
            note = f"upstream branch moved; pinned `{proof.get('release')}` artifact remains exact"
        lines.append(
            f"| `{row['target']}` | `{row['monitor_status']}` | `{row['release_status']}` | {note} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate strict monitor output for release-safe pinned artifacts.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--monitor-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve()
        monitor = load_object(args.monitor_json, "target monitor")
        args.output.mkdir(parents=True, exist_ok=True)
        rc, value = evaluate(root, monitor)
        (args.output / "release-target-gate.json").write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (args.output / "release-target-gate.md").write_text(render_markdown(value), encoding="utf-8")
        print(json.dumps(value, indent=2, sort_keys=True))
        return rc
    except GateError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
