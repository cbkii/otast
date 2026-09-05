from __future__ import annotations

import json
import re
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


def registry_provenance(root: Path) -> dict[str, object]:
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
        if build_id not in device_record.get("qualified_builds", []):
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
            authority_path.relative_to(root.resolve())
        except ValueError as exc:
            raise OtastError(f"qualification authority fixture escapes repository: {record_id}") from exc
        if sha256_file(authority_path) != record["authority_sha256"]:
            raise OtastError(f"qualification authority SHA-256 mismatch: {record_id}")
        authority = parse_authority(authority_path, platform_profile=str(record["platform_profile"]))
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
    if report.get("fatal_reason") or report.get("result") == "PARTIAL":
        return {"result": "INCONCLUSIVE", "reason": "root-exposure evidence is incomplete"}

    findings = report.get("findings")
    if not isinstance(findings, list):
        return {"result": "INCONCLUSIVE", "reason": "root-exposure findings are missing"}
    categories = {str(item.get("category", "")) for item in findings if isinstance(item, dict)}
    if "OTAST-owned semantic inconsistency" in categories:
        return {"result": "FAIL", "reason": "OTAST-owned exposure or semantic inconsistency detected"}
    if categories & {"detector/report inconsistency", "unknown/needs investigation", "diagnostic coverage limitation"}:
        return {"result": "INCONCLUSIVE", "reason": "detector evidence requires further attribution"}
    external = categories & {"another reviewed module's exposure"}
    if external:
        return {
            "result": "PASS_WITH_ATTRIBUTION",
            "reason": "findings are attributed to declared external root-stack dependencies; no OTAST mutation is authorized",
        }
    if not categories:
        return {"result": "PASS", "reason": "no relevant exposure findings"}
    return {"result": "INCONCLUSIVE", "reason": "unrecognized root-exposure finding category"}
