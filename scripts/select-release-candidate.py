#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.otastctl.release import VERSION_RE, expected_asset_name, is_prerelease


class SelectionError(RuntimeError):
    pass


def _flatten_releases(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise SelectionError("GitHub release data must be a JSON array")
    if value and all(isinstance(page, list) for page in value):
        value = [item for page in value for item in page]
    if not all(isinstance(item, dict) for item in value):
        raise SelectionError("GitHub release data must contain release objects")
    return list(value)  # type: ignore[arg-type]


def _asset_names(release: dict[str, object]) -> set[str]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return set()
    return {
        str(asset["name"])
        for asset in assets
        if isinstance(asset, dict) and isinstance(asset.get("name"), str)
    }


def select_candidate(
    releases: object,
    *,
    requested_version: str = "",
    require_proof: bool = True,
) -> dict[str, object]:
    requested = requested_version.strip()
    if requested and not VERSION_RE.fullmatch(requested):
        raise SelectionError(f"invalid release version: {requested}")

    eligible: list[dict[str, object]] = []
    complete_unproven: list[str] = []
    for release in _flatten_releases(releases):
        version = release.get("tag_name")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            continue
        if requested:
            if version != requested:
                continue
            if release.get("draft") not in (True, False):
                continue
        elif release.get("draft") is not True:
            continue

        zip_name = expected_asset_name(version)
        base_assets = {zip_name, f"{zip_name}.sha256", "release-manifest.json"}
        names = _asset_names(release)
        if not base_assets.issubset(names):
            continue

        proof_name = f"otast-{version}-device-proof.json"
        proof_present = proof_name in names
        if require_proof and not proof_present:
            complete_unproven.append(version)
            continue

        selected = dict(release)
        selected["proof_present"] = proof_present
        eligible.append(selected)

    if requested:
        if len(eligible) != 1:
            if require_proof and requested in complete_unproven:
                raise SelectionError(
                    f"release {requested} is prepared but has no physical proof; "
                    "run `otast release` or uncheck Require physical device proof"
                )
            raise SelectionError(
                f"no complete OTAST release candidate exists for {requested}; run prepare-release first"
            )
        chosen = eligible[0]
    else:
        if not eligible:
            if require_proof and complete_unproven:
                versions = ", ".join(sorted(complete_unproven))
                raise SelectionError(
                    "prepared release draft(s) lack physical proof: "
                    f"{versions}; run `otast release` or uncheck Require physical device proof"
                )
            raise SelectionError("no complete OTAST release draft exists; run prepare-release first")
        if len(eligible) != 1:
            versions = ", ".join(sorted(str(item.get("tag_name")) for item in eligible))
            raise SelectionError(
                f"multiple eligible OTAST release drafts exist: {versions}; specify Version explicitly"
            )
        chosen = eligible[0]

    version = str(chosen["tag_name"])
    return {
        "version": version,
        "prerelease": is_prerelease(version),
        "proof_present": bool(chosen.get("proof_present", False)),
        "draft": bool(chosen.get("draft", False)),
        "target_commitish": str(chosen.get("target_commitish") or ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select one complete OTAST GitHub release candidate")
    parser.add_argument("--releases-json", required=True)
    parser.add_argument("--requested", default="")
    parser.add_argument("--require-proof", action="store_true")
    args = parser.parse_args(argv)

    try:
        with open(args.releases_json, encoding="utf-8") as handle:
            releases = json.load(handle)
        result = select_candidate(
            releases,
            requested_version=args.requested,
            require_proof=args.require_proof,
        )
    except (OSError, json.JSONDecodeError, SelectionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
