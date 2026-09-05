from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from .authority import parse_authority
from .compatibility import QUALIFICATION_TIERS, load_registry
from .runtime_digest import RUNTIME_DIGEST_ALGORITHM, validate_runtime_digest
from .util import OtastError, sha256_file

QUALIFICATION_SCHEMA_VERSION = 1
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PAGE_SIZE_STATES = {"UNQUALIFIED", "DEVICE_VALIDATED", "RELEASE_QUALIFIED"}
RECORD_STATES = {
    "CURRENT",
    "STALE_RUNTIME_DIGEST_UNBOUND",
    "STALE_RUNTIME_CHANGED",
    "PARTIAL",
}
ROOT_ATTRIBUTION_RESULTS = {"PASS", "PASS_WITH_ATTRIBUTION", "FAIL", "INCONCLUSIVE"}
ROOT_REPORT_ACCEPTED_RESULTS = {"PASS", "PASS_WITH_WARNINGS"}
ROOT_FINDING_CATEGORIES = {
    "OTAST-owned semantic inconsistency",
    "detector/report inconsistency",
    "unknown/needs investigation",
    "diagnostic coverage limitation",
    "another reviewed module's exposure",
}


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtastError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OtastError(f"{label} must be a JSON object")
    return value


def qualification_registry_path(root: Path) -> Path:
    return root / "compatibility/qualification-registry.json"


def load_qualification_registry(root: Path) -> dict[str, Any]:
    return _load_json(qualification_registry_path(root), "qualification registry")


def _candidate_zip_registry_provenance(path: Path, expected_source: str) -> dict[str, object]:
    """Read registry provenance from the exact candidate ZIP used by physical proof.

    `release-device-lifecycle.sh` supplies ZIP_PATH_VALUE and SOURCE_VALUE only to
    its proof-generation Python process. In that bounded context the candidate ZIP,
    not a possibly stale/dirty local checkout, is the provenance authority.
    """
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"candidate ZIP is missing or unsafe: {path}")
    if SHA40_RE.fullmatch(expected_source) is None:
        raise OtastError("candidate source commit must be a full Git SHA")
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("release.properties").decode("utf-8")
    except (OSError, KeyError, UnicodeDecodeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise OtastError(f"cannot read candidate release provenance: {path}") from exc
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or "=" not in line:
            raise OtastError("candidate release.properties contains a malformed line")
        key, value = line.split("=", 1)
        if not key or not value or key in values:
            raise OtastError("candidate release.properties contains duplicate or empty metadata")
        values[key] = value
    if values.get("schema_version") != "2":
        raise OtastError("candidate release.properties schema mismatch")
    if values.get("commit_sha") != expected_source:
        raise OtastError("candidate ZIP source commit disagrees with physical-proof source")
    try:
        compatibility_schema = int(values["compatibility_registry_schema"])
        qualification_schema = int(values["qualification_registry_schema"])
    except (KeyError, ValueError) as exc:
        raise OtastError("candidate registry schema provenance is invalid") from exc
    if compatibility_schema <= 0 or qualification_schema <= 0:
        raise OtastError("candidate registry schema provenance must be positive")
    compatibility_sha = values.get("compatibility_registry_sha256", "")
    qualification_sha = values.get("qualification_registry_sha256", "")
    if SHA64_RE.fullmatch(compatibility_sha) is None or SHA64_RE.fullmatch(qualification_sha) is None:
        raise OtastError("candidate registry SHA-256 provenance is invalid")
    return {
        "compatibility_registry_schema": compatibility_schema,
        "compatibility_registry_sha256": compatibility_sha,
        "qualification_registry_schema": qualification_schema,
        "qualification_registry_sha256": qualification_sha,
    }


def registry_provenance(root: Path) -> dict[str, object]:
    # Physical proof generation deliberately exports these two values only for
    # the inline proof writer. Binding here prevents a dirty/stale checkout from
    # stamping local registry hashes onto a ZIP built by authoritative GitHub main.
    candidate_zip = os.environ.get("ZIP_PATH_VALUE")
    candidate_source = os.environ.get("SOURCE_VALUE")
    if candidate_zip or candidate_source:
        if not candidate_zip or not candidate_source:
            raise OtastError("physical-proof candidate provenance environment is incomplete")
        return _candidate_zip_registry_provenance(Path(candidate_zip), candidate_source)

    compatibility_path = root / "compatibility/supported-targets.json"
    qualification_path = qualification_registry_path(root)
    compatibility = _load_json(compatibility_path, "compatibility registry")
    qualification = _load_json(qualification_path, "qualification registry")
    return {
        "compatibility_registry_schema": int(compatibility.get("schema_version", 0)),
        "compatibility_registry_sha256": sha256_file(compatibility_path),
        "qualification_registry_schema": int(qualification.get("schema_version", 0)),
        "qualification_registry_sha256": sha256_file(qualification_path),
    }


def validate_qualification_registry(root: Path) -> dict[str, object]:
    root = root.resolve()
    compatibility = load_registry(root)
    qualification = load_qualification_registry(root)
    if qualification.get("schema_version") != QUALIFICATION_SCHEMA_VERSION:
        raise OtastError(f"qualification registry schema must be {QUALIFICATION_SCHEMA_VERSION}")
    if qualification.get("runtime_digest_algorithm") != RUNTIME_DIGEST_ALGORITHM:
        raise OtastError("qualification registry runtime digest algorithm mismatch")

    support = compatibility.get("support_model")
    if not isinstance(support, dict):
        raise OtastError("compatibility support model is missing")
    release_reference = support.get("release_reference")
    devices = support.get("devices")
    if not isinstance(release_reference, dict) or not isinstance(devices, dict):
        raise OtastError("compatibility release-reference contract is incomplete")

    registry_reference = qualification.get("release_reference")
    if not isinstance(registry_reference, dict):
        raise OtastError("qualification release reference is missing")
    expected_reference = {
        "device": release_reference.get("device"),
        "build_id": release_reference.get("build"),
        "platform_profile": release_reference.get("platform_profile"),
    }
    if registry_reference != expected_reference:
        raise OtastError("qualification release reference disagrees with compatibility registry")

    records = qualification.get("records")
    if not isinstance(records, dict):
        raise OtastError("qualification records must be an object")

    current_records = 0
    authority_root = (root / "authority").resolve()
    for record_id, record in records.items():
        if not isinstance(record_id, str) or not record_id or not isinstance(record, dict):
            raise OtastError("qualification record is malformed")
        device = record.get("device")
        if not isinstance(device, str) or device not in devices:
            raise OtastError(f"qualification record uses undeclared device: {record_id}")
        device_record = devices[device]
        if not isinstance(device_record, dict):
            raise OtastError(f"compatibility device record is malformed: {device}")
        if record.get("model") != device_record.get("model"):
            raise OtastError(f"qualification model disagrees with compatibility device: {record_id}")
        if record.get("platform_profile") != device_record.get("platform_profile"):
            raise OtastError(f"qualification platform disagrees with compatibility device: {record_id}")
        tier = record.get("qualification_tier")
        if tier not in QUALIFICATION_TIERS or tier in {"DESIGN_COMPATIBLE", "UNQUALIFIED"}:
            raise OtastError(f"physical qualification record has invalid tier: {record_id}")
        build_id = record.get("build_id")
        if not isinstance(build_id, str) or not build_id:
            raise OtastError(f"qualification build ID is missing: {record_id}")
        qualified_builds = device_record.get("qualified_builds")
        if not isinstance(qualified_builds, list) or not all(
            isinstance(item, str) and item for item in qualified_builds
        ):
            raise OtastError(f"compatibility qualified_builds is malformed: {device}")
        if build_id not in qualified_builds:
            raise OtastError(f"qualification build is not declared for device: {record_id}")
        source = record.get("qualified_source_commit")
        if not isinstance(source, str) or SHA40_RE.fullmatch(source) is None:
            raise OtastError(f"qualified source commit is invalid: {record_id}")
        for field in ("authority_sha256", "zip_sha256", "proof_sha256"):
            value = record.get(field)
            if not isinstance(value, str) or SHA64_RE.fullmatch(value) is None:
                raise OtastError(f"qualification {field} is invalid: {record_id}")
        if not isinstance(record.get("version_code"), int) or isinstance(record.get("version_code"), bool):
            raise OtastError(f"qualification versionCode is invalid: {record_id}")
        if not isinstance(record.get("otast_version"), str) or not record["otast_version"]:
            raise OtastError(f"qualification version is invalid: {record_id}")
        if not isinstance(record.get("qualification_date"), str) or DATE_RE.fullmatch(record["qualification_date"]) is None:
            raise OtastError(f"qualification date is invalid: {record_id}")

        authority_relative = record.get("authority_fixture")
        if not isinstance(authority_relative, str) or not authority_relative.startswith("authority/"):
            raise OtastError(f"qualification authority fixture path is invalid: {record_id}")
        authority_path = (root / authority_relative).resolve()
        try:
            authority_path.relative_to(authority_root)
        except ValueError as exc:
            raise OtastError(f"qualification authority fixture escapes authority directory: {record_id}") from exc
        if authority_path == authority_root or authority_path.is_symlink() or not authority_path.is_file():
            raise OtastError(f"qualification authority fixture is missing or unsafe: {record_id}")
        if sha256_file(authority_path) != record["authority_sha256"]:
            raise OtastError(f"qualification authority SHA-256 mismatch: {record_id}")
        authority = parse_authority(
            authority_path,
            platform_profile=str(record["platform_profile"]),
            root=root,
        )
        expected_identity = {
            "ro.product.device": record["device"],
            "ro.product.model": record["model"],
            "ro.product.manufacturer": record["manufacturer"],
            "ro.build.id": record["build_id"],
            "ro.build.fingerprint": record["fingerprint"],
        }
        for key, expected in expected_identity.items():
            if authority.values.get(key) != expected:
                raise OtastError(f"qualification authority identity mismatch for {key}: {record_id}")

        state = record.get("current_state")
        if state not in RECORD_STATES:
            raise OtastError(f"qualification current_state is invalid: {record_id}")
        runtime_digest = record.get("runtime_digest")
        if state == "CURRENT":
            validate_runtime_digest(runtime_digest)
            current_records += 1
        elif runtime_digest is not None:
            validate_runtime_digest(runtime_digest)
        if state.startswith("STALE_") and not isinstance(record.get("stale_reason"), str):
            raise OtastError(f"stale qualification has no reason: {record_id}")

        page_sizes = record.get("page_size_qualification")
        if not isinstance(page_sizes, dict) or not page_sizes:
            raise OtastError(f"page-size qualification is missing: {record_id}")
        for page_size, status in page_sizes.items():
            if not isinstance(page_size, str) or not page_size.isdigit() or int(page_size) <= 0:
                raise OtastError(f"page-size key is invalid: {record_id}")
            if status not in PAGE_SIZE_STATES:
                raise OtastError(f"page-size qualification status is invalid: {record_id}")

    return {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "records": len(records),
        "current_records": current_records,
        "release_reference": expected_reference,
        **registry_provenance(root),
    }


def find_current_qualification(
    root: Path,
    *,
    device: str,
    build_id: str,
    runtime_digest: str,
) -> tuple[str, dict[str, Any]] | None:
    validate_runtime_digest(runtime_digest)
    registry = load_qualification_registry(root)
    records = registry.get("records", {})
    if not isinstance(records, dict):
        return None
    matches: list[tuple[str, dict[str, Any]]] = []
    for record_id, record in records.items():
        if not isinstance(record, dict) or record.get("current_state") != "CURRENT":
            continue
        if record.get("device") == device and record.get("build_id") == build_id and record.get("runtime_digest") == runtime_digest:
            matches.append((str(record_id), record))
    if len(matches) > 1:
        raise OtastError("multiple CURRENT qualification records match the same device/build/runtime digest")
    return matches[0] if matches else None


def proof_reuse_decision(
    record: dict[str, Any],
    *,
    current_runtime_digest: str,
    current_source_commit: str,
) -> dict[str, object]:
    validate_runtime_digest(current_runtime_digest)
    if SHA40_RE.fullmatch(current_source_commit) is None:
        raise OtastError("current source commit must be a full Git SHA")
    qualified_digest = record.get("runtime_digest")
    if record.get("current_state") != "CURRENT" or not isinstance(qualified_digest, str):
        return {"reusable": False, "reason": "qualification record is not CURRENT/runtime-bound"}
    if qualified_digest != current_runtime_digest:
        return {"reusable": False, "reason": "runtime payload digest changed"}
    qualified_source = record.get("qualified_source_commit")
    if not isinstance(qualified_source, str) or SHA40_RE.fullmatch(qualified_source) is None:
        return {"reusable": False, "reason": "qualified source provenance is invalid"}
    return {
        "reusable": True,
        "reason": "runtime payload digest is identical",
        "qualified_source_commit": qualified_source,
        "current_source_commit": current_source_commit,
        "runtime_digest": current_runtime_digest,
    }


def classify_root_exposure_report(report: object) -> dict[str, object]:
    if not isinstance(report, dict):
        return {"result": "INCONCLUSIVE", "reason": "root-exposure report is not an object"}
    if report.get("read_only") is not True:
        return {"result": "FAIL", "reason": "root-exposure evidence is not declared read-only"}
    report_result = report.get("result")
    if report.get("fatal_reason") or report_result == "PARTIAL":
        return {"result": "INCONCLUSIVE", "reason": "root-exposure evidence is incomplete"}
    if report_result == "FAIL":
        return {"result": "FAIL", "reason": "root-exposure report declares failure"}
    if report_result not in ROOT_REPORT_ACCEPTED_RESULTS:
        return {"result": "INCONCLUSIVE", "reason": "root-exposure report result is not accepted"}

    findings = report.get("findings")
    if not isinstance(findings, list):
        return {"result": "INCONCLUSIVE", "reason": "root-exposure findings are missing"}
    categories: set[str] = set()
    for item in findings:
        if not isinstance(item, dict):
            return {"result": "INCONCLUSIVE", "reason": "root-exposure finding is malformed"}
        category = item.get("category")
        if not isinstance(category, str) or not category or category not in ROOT_FINDING_CATEGORIES:
            return {"result": "INCONCLUSIVE", "reason": "unrecognized root-exposure finding category"}
        categories.add(category)

    if "OTAST-owned semantic inconsistency" in categories:
        return {"result": "FAIL", "reason": "OTAST-owned exposure or semantic inconsistency detected"}
    if categories & {"detector/report inconsistency", "unknown/needs investigation", "diagnostic coverage limitation"}:
        return {"result": "INCONCLUSIVE", "reason": "detector evidence requires further attribution"}
    if "another reviewed module's exposure" in categories:
        return {
            "result": "PASS_WITH_ATTRIBUTION",
            "reason": "findings are attributed to declared external root-stack dependencies; no OTAST mutation is authorized",
        }
    if not categories:
        return {"result": "PASS", "reason": "no relevant exposure findings"}
    return {"result": "INCONCLUSIVE", "reason": "unrecognized root-exposure finding category"}
