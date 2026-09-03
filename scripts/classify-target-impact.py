#!/usr/bin/env python3
"""Classify an upstream source delta without modifying OTAST or target modules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.otastctl.compatibility import classify_target_paths  # noqa: E402
from tools.otastctl.util import OtastError, stable_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="managed target ID from compatibility/supported-targets.json")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--path", action="append", dest="paths", help="changed source path; repeat as needed")
    source.add_argument("--paths-json", type=Path, help="JSON file containing changed_paths or a string list")
    args = parser.parse_args()

    paths = args.paths or []
    if args.paths_json is not None:
        try:
            value = json.loads(args.paths_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"STOP: cannot read changed-path evidence: {exc}", file=sys.stderr)
            return 20
        if isinstance(value, dict):
            value = value.get("changed_paths")
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            print("STOP: changed-path evidence must be a string list or object with changed_paths", file=sys.stderr)
            return 20
        paths = value

    try:
        result = classify_target_paths(ROOT, args.target, paths)
    except OtastError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 20
    print(stable_json(result), end="")
    return 10 if result["requires_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
