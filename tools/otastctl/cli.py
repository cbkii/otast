from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .authority import parse_authority
from .build import build_module, validate_module_zip
from .capture import safe_extract_capture
from .fake_root import clone_fixture_root, qualify_fake_root
from .fixture import reset_fixture, sanitize_fixture
from .monitor import monitor_targets
from .privacy import require_public_safe, scan_repository
from .release import (
    build_release_bundle,
    load_release_list,
    load_update_metadata,
    resolve_release_identity_from_repo,
    select_proven_draft,
    stamp_release_metadata,
    verify_release_bundle,
    write_update_metadata,
)
from .repository import build_source_zip, validate_source_zip
from .util import OtastError, stable_json
from .verify import verify_repository


def _root(value: str) -> Path:
    return Path(value).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="otastctl", description="OTAST local validation and packaging tools")
    parser.add_argument("--repo-root", default=".", help="repository root (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="verify repository policy, syntax, tests and deterministic packaging")
    verify.add_argument("--full", action="store_true", help="run the complete unit and fake-root suite")

    build = sub.add_parser("build", help="build and validate the deterministic Magisk module ZIP")
    build.add_argument("--output", default="dist")
    build.add_argument("--commit-sha", default="unknown")

    build_release = sub.add_parser("build-release", help="build and verify the canonical OTAST release bundle")
    build_release.add_argument("--output", default="dist")
    build_release.add_argument("--commit-sha", default="unknown")

    verify_release = sub.add_parser("verify-release", help="verify a canonical OTAST release bundle")
    verify_release.add_argument("--zip", required=True)
    verify_release.add_argument("--checksum", required=True)
    verify_release.add_argument("--manifest", required=True)

    resolve_release = sub.add_parser("resolve-release-version", help="resolve the next or explicitly requested release identity")
    resolve_release.add_argument("--requested", default="", help="explicit vMAJOR.MINOR.PATCH[-prerelease], otherwise automatic")

    stamp_release = sub.add_parser("stamp-release", help="stamp candidate version metadata without changing stable update.json")
    stamp_release.add_argument("--version", required=True)
    stamp_release.add_argument("--version-code", required=True, type=int)
    stamp_release.add_argument("--notes-file", help="optional release notes to insert/replace in CHANGELOG.md")

    select_release = sub.add_parser("select-proven-release", help="select exactly one physically proven draft from GitHub release JSON")
    select_release.add_argument("--releases-json", required=True)
    select_release.add_argument("--requested", default="")

    generate_update = sub.add_parser("generate-update-json", help="generate stable Magisk updater metadata from a final release manifest")
    generate_update.add_argument("--manifest", required=True)
    generate_update.add_argument("--output", required=True)

    validate_update = sub.add_parser("validate-update-json", help="validate stable Magisk updater metadata")
    validate_update.add_argument("path")

    validate_zip = sub.add_parser("validate-zip", help="validate an existing module ZIP")
    validate_zip.add_argument("zip")

    package_source = sub.add_parser("package-source", help="build a deterministic public repository ZIP")
    package_source.add_argument("--output", default="dist/otast-public-ready.zip")

    validate_source = sub.add_parser("validate-source", help="validate a public repository ZIP")
    validate_source.add_argument("zip")

    authority = sub.add_parser("authority-validate", help="validate an ota.prop authority file")
    authority.add_argument("path")

    fake = sub.add_parser("fake-root", help="run the module lifecycle against a disposable fake Magisk root")
    fake.add_argument("--output", default="reports/fake-magisk-root")

    monitor = sub.add_parser("monitor", help="compare upstream branch heads with reviewed compatibility baselines")
    monitor.add_argument("--output", default="reports/target-monitor")

    privacy = sub.add_parser("privacy-scan", help="scan the repository for public-release privacy hazards")
    privacy.add_argument("--json", action="store_true")

    extract = sub.add_parser("capture-extract", help="safely extract a bounded device-capture tar")
    extract.add_argument("archive")
    extract.add_argument("destination")

    sanitize = sub.add_parser("fixture-sanitize", help="sanitize a private captured fake-root fixture")
    sanitize.add_argument("source")
    sanitize.add_argument("destination")

    reset = sub.add_parser("fixture-reset", help="copy a sanitized fixture into a disposable working root")
    reset.add_argument("source")
    reset.add_argument("destination")
    reset.add_argument("--allowed-root", required=True)

    clone = sub.add_parser("fixture-clone", help="reset a fixture and install the exact candidate module ZIP")
    clone.add_argument("source")
    clone.add_argument("destination")
    clone.add_argument("--allowed-root", required=True)
    clone.add_argument("--module-zip", help="install this exact validated candidate ZIP")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo = _root(args.repo_root)
    try:
        if args.command == "verify":
            print(stable_json(verify_repository(repo, full=args.full)), end="")
        elif args.command == "build":
            output = _root(args.output) if Path(args.output).is_absolute() else (repo / args.output).resolve()
            print(build_module(repo, output, commit_sha=args.commit_sha))
        elif args.command == "build-release":
            output = _root(args.output) if Path(args.output).is_absolute() else (repo / args.output).resolve()
            print(stable_json(build_release_bundle(repo, output, commit_sha=args.commit_sha)), end="")
        elif args.command == "verify-release":
            report = verify_release_bundle(_root(args.zip), _root(args.checksum), _root(args.manifest))
            print(stable_json(report), end="")
        elif args.command == "resolve-release-version":
            print(stable_json(resolve_release_identity_from_repo(repo, requested_version=args.requested)), end="")
        elif args.command == "stamp-release":
            notes = _root(args.notes_file).read_text(encoding="utf-8") if args.notes_file else None
            report = stamp_release_metadata(repo, version=args.version, version_code=args.version_code, notes=notes)
            print(stable_json(report), end="")
        elif args.command == "select-proven-release":
            releases = load_release_list(_root(args.releases_json))
            print(stable_json(select_proven_draft(releases, requested_version=args.requested)), end="")
        elif args.command == "generate-update-json":
            output = _root(args.output) if Path(args.output).is_absolute() else (repo / args.output).resolve()
            data = write_update_metadata(_root(args.manifest), output)
            print(stable_json({"output": str(output), "metadata": data}), end="")
        elif args.command == "validate-update-json":
            print(stable_json(load_update_metadata(_root(args.path))), end="")
        elif args.command == "validate-zip":
            validate_module_zip(_root(args.zip))
            print("module ZIP validation passed")
        elif args.command == "package-source":
            output = _root(args.output) if Path(args.output).is_absolute() else (repo / args.output).resolve()
            print(build_source_zip(repo, output))
        elif args.command == "validate-source":
            validate_source_zip(_root(args.zip))
            print("source ZIP validation passed")
        elif args.command == "authority-validate":
            authority = parse_authority(_root(args.path))
            print(stable_json({"result": "PASS", "sha256": authority.sha256, "values": authority.values}), end="")
        elif args.command == "fake-root":
            output = _root(args.output) if Path(args.output).is_absolute() else (repo / args.output).resolve()
            print(stable_json(qualify_fake_root(repo, output)), end="")
        elif args.command == "monitor":
            output = _root(args.output) if Path(args.output).is_absolute() else (repo / args.output).resolve()
            report = monitor_targets(repo, output)
            print(stable_json(report), end="")
            return 0 if report["result"] == "PASS" else (2 if report["result"] == "REVIEW_REQUIRED" else 1)
        elif args.command == "privacy-scan":
            findings = scan_repository(repo)
            if args.json:
                print(json.dumps({"result": "PASS" if not findings else "FAIL", "findings": findings}, indent=2) + "\n")
            else:
                require_public_safe(repo)
                print("public privacy scan passed")
            return 1 if findings else 0
        elif args.command == "capture-extract":
            safe_extract_capture(_root(args.archive), _root(args.destination))
            print(_root(args.destination))
        elif args.command == "fixture-sanitize":
            manifest = sanitize_fixture(_root(args.source), _root(args.destination))
            print(stable_json(manifest), end="")
        elif args.command == "fixture-reset":
            reset_fixture(_root(args.source), _root(args.destination), _root(args.allowed_root))
            print(_root(args.destination))
        elif args.command == "fixture-clone":
            module_zip = _root(args.module_zip) if args.module_zip else None
            report = clone_fixture_root(
                repo,
                _root(args.source),
                _root(args.destination),
                _root(args.allowed_root),
                module_zip=module_zip,
            )
            print(stable_json(report), end="")
        else:  # pragma: no cover
            parser.error("unknown command")
        return 0
    except (OtastError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
