#!/usr/bin/env python3
"""Render or verify the generated compatibility status document."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.otastctl.compatibility import render_compatibility_status, validate_registry  # noqa: E402
from tools.otastctl.util import OtastError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated status is stale")
    args = parser.parse_args()
    destination = ROOT / "docs/COMPATIBILITY-STATUS.md"
    expected = render_compatibility_status(ROOT)
    if args.check:
        try:
            validate_registry(ROOT)
        except OtastError as exc:
            print(f"STOP: {exc}", file=sys.stderr)
            return 20
        print("PASS: compatibility registry and generated status are current")
        return 0
    destination.write_text(expected, encoding="utf-8")
    print(f"WROTE: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
