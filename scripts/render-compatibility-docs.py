#!/usr/bin/env python3
"""Render or verify the generated compatibility status document."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
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

    try:
        if args.check:
            validate_registry(ROOT)
            print("PASS: compatibility registry and generated status are current")
            return 0
        expected = render_compatibility_status(ROOT)
    except OtastError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 20

    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        print(f"STOP: generated compatibility status destination is unsafe: {destination}", file=sys.stderr)
        return 20

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        temporary = None
    except OSError as exc:
        print(f"STOP: cannot write generated compatibility status: {exc}", file=sys.stderr)
        return 20
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    print(f"WROTE: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
