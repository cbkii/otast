from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .util import OtastError

REGISTRY_SCHEMA_VERSION = 5
PLATFORM_SCHEMA_VERSION = 1
QUALIFICATION_TIERS = {
    "DESIGN_COMPATIBLE",
    "FIXTURE_QUALIFIED",
    "DEVICE_VALIDATED",
    "RELEASE_QUALIFIED",
    "UNQUALIFIED",
}
COMPATIBILITY_BASES = {
    "WHOLE_FILE_VERSION_RANGE",
    "STRUCTURE_SENSITIVE_TRANSFORM",
    "EXACT_REVIEWED_ARTIFACT",
    "PRESERVED_OBSERVED_SURFACE",
    "UNSUPPORTED_UNKNOWN",
}
IMPACT_CLASSES = (
    "DOCS_OR_CI_ONLY",
    "PRESERVED_SURFACE_CHANGED",
    "NATIVE_DEPENDENCY_CHANGED",
    "MANAGED_WHOLE_FILE_CHANGED",
    "STRUCTURE_SENSITIVE_CHANGED",
    "MODULE_IDENTITY_CHANGED",
    "UNKNOWN_PACKAGE_CHANGE",
)
IMPACT_POLICY_KEYS = {
    "docs_ci": "DOCS_OR_CI_ONLY",
    "preserved_surface": "PRESERVED_SURFACE_CHANGED",
    "native_dependency": "NATIVE_DEPENDENCY_CHANGED",
    "managed_whole_file": "MANAGED_WHOLE_FILE_CHANGED",
    "structure_sensitive": "STRUCTURE_SENSITIVE_CHANGED",
    "module_identity": "MODULE_IDENTITY_CHANGED",
}
IMPACT_PRIORITY = {
    "DOCS_OR_CI_ONLY": 10,
    "PRESERVED_SURFACE_CHANGED": 30,
    "NATIVE_DEPENDENCY_CHANGED": 50,
    "MANAGED_WHOLE_FILE_CHANGED": 60,
    "STRUCTURE_SENSITIVE_CHANGED": 70,
    "UNKNOWN_PACKAGE_CHANGE": 75,
    "MODULE_IDENTITY_CHANGED": 80,
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtastError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OtastError(f"{label} must be a JSON object: {path}")
    return value


def load_registry(root: Path) -> dict[str, Any]:
    return _read_json(root / "compatibility/supported-targets.json", "compatibility registry")


def load_platform(root: Path, profile_id: str) -> dict[str, Any]:
    registry = load_registry(root)
    platforms = registry.get("platforms")
    if not isinstance(platforms, dict) or profile_id not in platforms:
        raise OtastError(f"unknown or unsupported platform profile: {profile_id}")
    record = platforms[profile_id]
    if not isinstance(record, dict) or record.get("status") != "SUPPORTED":
        raise OtastError(f"platform profile is not supported: {profile_id}")
    relative = record.get("profile")
    if not isinstance(relative, str) or not relative.startswith("compatibility/platforms/"):
        raise OtastError(f"platform profile path is invalid: {profile_id}")
    profile = _read_json(root / relative, f"platform profile {profile_id}")
    if profile.get("schema_version") != PLATFORM_SCHEMA_VERSION or profile.get("id") != profile_id:
        raise OtastError(f"platform profile metadata mismatch: {profile_id}")
    if profile.get("status") != "SUPPORTED":
        raise OtastError(f"platform profile declares unsupported status: {profile_id}")
    return profile


def _require_string_list(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise OtastError(f"{label} must be a{' non-empty' if not allow_empty else ''} string list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or any(ch in item for ch in "\r\n\0"):
            raise OtastError(f"{label} contains an invalid value")
        result.append(item)
    if len(result) != len(set(result)):
        raise OtastError(f"{label} contains duplicates")
    return result


def validate_registry(root: Path) -> dict[str, object]:
    registry = load_registry(root)
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise OtastError(f"compatibility registry schema must be {REGISTRY_SCHEMA_VERSION}")

    support = registry.get("support_model")
    if not isinstance(support, dict) or support.get("device_family") != "Google Pixel":
        raise OtastError("support_model must describe the Google Pixel family")
    tiers = support.get("qualification_tiers")
    if not isinstance(tiers, dict) or set(tiers) != QUALIFICATION_TIERS:
        raise OtastError("qualification tier set is incomplete or ambiguous")
    default_tier = support.get("family_default_tier")
    if default_tier not in QUALIFICATION_TIERS:
        raise OtastError("family_default_tier is invalid")

    profile_ids = _require_string_list(support.get("supported_platform_profiles"), "supported platform profiles")
    platform_summaries: dict[str, dict[str, object]] = {}
    for profile_id in profile_ids:
        profile = load_platform(root, profile_id)
        if profile.get("android_release") != "16" or profile.get("sdk") != 36:
            raise OtastError("only the reviewed Android 16 / SDK 36 profile is supported")
        authority = profile.get("authority")
        if not isinstance(authority, dict):
            raise OtastError(f"platform profile has no authority contract: {profile_id}")
        required = set(_require_string_list(authority.get("required_keys"), f"{profile_id} required authority keys"))
        for key in ("ro.build.version.security_patch", "ro.vendor.build.security_patch"):
            if key not in required:
                raise OtastError(f"platform profile must require independent system/vendor SPL: missing {key}")
        platform_summaries[profile_id] = {
            "android_release": profile["android_release"],
            "sdk": profile["sdk"],
        }

        runtime_platform = root / "module/runtime/platform.sh"
        if runtime_platform.is_symlink() or not runtime_platform.is_file():
            raise OtastError("runtime platform mirror is missing or unsafe")
        runtime_text = runtime_platform.read_text(encoding="utf-8")
        contract = profile.get("device_family")
        if not isinstance(contract, dict):
            raise OtastError(f"platform device-family contract is invalid: {profile_id}")
        expected_runtime = {
            "OTAST_PLATFORM_ID": profile_id,
            "OTAST_PLATFORM_ANDROID_RELEASE": str(profile["android_release"]),
            "OTAST_PLATFORM_SDK": str(profile["sdk"]),
            "OTAST_PLATFORM_MANUFACTURER": str(contract.get("manufacturer", "")),
            "OTAST_PLATFORM_MODEL_PREFIX": str(contract.get("model_prefix", "")),
            "OTAST_PLATFORM_FINGERPRINT_VENDOR": str(contract.get("fingerprint_vendor", "")),
            "OTAST_PLATFORM_FINGERPRINT_SUFFIX": str(contract.get("fingerprint_suffix", "")),
        }
        for name, expected in expected_runtime.items():
            assignment = f"{name}='{expected}'"
            if assignment not in runtime_text:
                raise OtastError(f"runtime platform mirror disagrees with {profile_id}: {name}")

    devices = support.get("devices")
    if not isinstance(devices, dict) or not devices:
        raise OtastError("support_model.devices must be a non-empty object")
    for device, record in devices.items():
        if not isinstance(device, str) or not isinstance(record, dict):
            raise OtastError("device qualification record is malformed")
        if record.get("tier") not in QUALIFICATION_TIERS:
            raise OtastError(f"device qualification tier is invalid: {device}")
        if record.get("platform_profile") not in profile_ids:
            raise OtastError(f"device references unsupported platform profile: {device}")
        builds = record.get("qualified_builds")
        if not isinstance(builds, list):
            raise OtastError(f"device qualified_builds must be a list: {device}")
        if record.get("tier") in {"FIXTURE_QUALIFIED", "DEVICE_VALIDATED", "RELEASE_QUALIFIED"} and not builds:
            raise OtastError(f"qualified device tier requires an exact build: {device}")

    reference = support.get("release_reference")
    if not isinstance(reference, dict):
        raise OtastError("release_reference is missing")
    reference_device = str(reference.get("device", ""))
    reference_record = devices.get(reference_device)
    if not isinstance(reference_record, dict):
        raise OtastError("release_reference device is not declared")
    if reference.get("tier") != reference_record.get("tier"):
        raise OtastError("release_reference tier disagrees with device qualification")
    if reference.get("build") not in reference_record.get("qualified_builds", []):
        raise OtastError("release_reference build is not an exact qualified build")
    fixture = reference.get("authority_fixture")
    if not isinstance(fixture, str) or not (root / fixture).is_file():
        raise OtastError("release_reference authority fixture is missing")

    conflicts = registry.get("conflicts")
    if not isinstance(conflicts, dict) or not conflicts:
        raise OtastError("conflicts must be explicit and non-empty")
    conflict_ids: set[str] = set()
    for conflict_id, record in conflicts.items():
        if not isinstance(record, dict) or record.get("severity") not in {"HARD_STOP", "REVIEW_REQUIRED"}:
            raise OtastError(f"conflict has invalid severity: {conflict_id}")
        if not isinstance(record.get("reason"), str) or not record["reason"].strip():
            raise OtastError(f"conflict has no reason: {conflict_id}")
        for module_id in _require_string_list(record.get("module_ids"), f"conflict {conflict_id} module_ids"):
            if module_id in conflict_ids:
                raise OtastError(f"conflicting module ID declared twice: {module_id}")
            conflict_ids.add(module_id)
    strict_exclusions = set(_require_string_list(registry.get("strict_exclusions"), "strict_exclusions"))
    if strict_exclusions != conflict_ids:
        raise OtastError("strict_exclusions must exactly mirror conflict module IDs")

    dependencies = registry.get("observed_dependencies")
    if not isinstance(dependencies, dict) or not dependencies:
        raise OtastError("observed_dependencies must be explicit and non-empty")
    observed_module_ids: set[str] = set()
    for dep_id, record in dependencies.items():
        if not isinstance(record, dict) or record.get("mode") != "READ_ONLY":
            raise OtastError(f"observed dependency must be READ_ONLY: {dep_id}")
        if "managed_paths" in record:
            raise OtastError(f"observed dependency may not declare managed_paths: {dep_id}")
        for module_id in _require_string_list(record.get("module_ids", []), f"observed dependency {dep_id} module_ids", allow_empty=True):
            if module_id in observed_module_ids:
                raise OtastError(f"observed module ID declared twice: {module_id}")
            observed_module_ids.add(module_id)

    targets = registry.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise OtastError("managed targets object is missing or empty")
    managed_module_ids: set[str] = set()
    for target_id, record in targets.items():
        if not isinstance(record, dict) or record.get("target_role") != "MANAGED":
            raise OtastError(f"target must explicitly declare MANAGED ownership: {target_id}")
        if record.get("compatibility_basis") not in COMPATIBILITY_BASES:
            raise OtastError(f"target compatibility basis is invalid: {target_id}")
        for module_id in _require_string_list(record.get("module_ids"), f"target {target_id} module_ids"):
            if module_id in managed_module_ids:
                raise OtastError(f"managed module ID declared by multiple targets: {module_id}")
            if module_id in conflict_ids:
                raise OtastError(f"managed target overlaps explicit conflict: {module_id}")
            managed_module_ids.add(module_id)
        monitor = record.get("monitor")
        if not isinstance(monitor, dict) or not isinstance(monitor.get("repository"), str):
            raise OtastError(f"target monitor is invalid: {target_id}")
        if not SHA_RE.fullmatch(str(monitor.get("expected_head", ""))):
            raise OtastError(f"target monitor expected_head is invalid: {target_id}")
        distribution = record.get("distribution_identity")
        if not isinstance(distribution, dict) or not distribution.get("source_type") or not distribution.get("repository"):
            raise OtastError(f"target distribution identity is incomplete: {target_id}")
        policy = record.get("impact_policy")
        if not isinstance(policy, dict):
            raise OtastError(f"target impact policy is missing: {target_id}")
        unknown_policy = set(policy) - set(IMPACT_POLICY_KEYS)
        if unknown_policy:
            raise OtastError(f"target impact policy has unknown categories: {target_id}: {sorted(unknown_policy)}")
        for category in IMPACT_POLICY_KEYS:
            _require_string_list(policy.get(category, []), f"{target_id} impact_policy.{category}", allow_empty=True)

    generated_status = root / "docs/COMPATIBILITY-STATUS.md"
    if generated_status.is_symlink() or not generated_status.is_file():
        raise OtastError("generated compatibility status document is missing")
    if generated_status.read_text(encoding="utf-8") != render_compatibility_status(root):
        raise OtastError("docs/COMPATIBILITY-STATUS.md is stale; regenerate from the compatibility registry")

    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "device_family": support["device_family"],
        "platforms": platform_summaries,
        "release_reference": reference,
        "managed_targets": sorted(targets),
        "observed_dependencies": sorted(dependencies),
        "conflicts": sorted(conflicts),
    }


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify_changed_paths(target_record: dict[str, Any], changed_paths: Iterable[str]) -> dict[str, object]:
    policy = target_record.get("impact_policy")
    if not isinstance(policy, dict):
        raise OtastError("target has no impact_policy")
    paths = sorted(set(changed_paths))
    if not paths:
        raise OtastError("changed path set is empty")
    per_path: list[dict[str, str]] = []
    for path in paths:
        if not path or path.startswith("/") or ".." in Path(path).parts or any(ch in path for ch in "\r\n\0"):
            raise OtastError(f"unsafe changed path: {path!r}")
        impact = "UNKNOWN_PACKAGE_CHANGE"
        for policy_key, candidate in IMPACT_POLICY_KEYS.items():
            patterns = policy.get(policy_key, [])
            if isinstance(patterns, list) and _matches(path, (str(item) for item in patterns)):
                impact = candidate
                break
        per_path.append({"path": path, "impact": impact})
    primary = max((item["impact"] for item in per_path), key=lambda item: IMPACT_PRIORITY[item])
    return {
        "impact": primary,
        "requires_review": primary != "DOCS_OR_CI_ONLY",
        "paths": per_path,
    }


def classify_target_paths(root: Path, target_id: str, changed_paths: Iterable[str]) -> dict[str, object]:
    registry = load_registry(root)
    targets = registry.get("targets")
    if not isinstance(targets, dict) or target_id not in targets or not isinstance(targets[target_id], dict):
        raise OtastError(f"unknown managed target: {target_id}")
    result = classify_changed_paths(targets[target_id], changed_paths)
    result.update({"target": target_id, "schema_version": 1})
    return result


def render_compatibility_status(root: Path) -> str:
    registry = load_registry(root)
    support = registry.get("support_model", {})
    devices = support.get("devices", {}) if isinstance(support, dict) else {}
    reference = support.get("release_reference", {}) if isinstance(support, dict) else {}
    targets = registry.get("targets", {})
    dependencies = registry.get("observed_dependencies", {})
    lines = [
        "<!-- GENERATED by tools.otastctl.compatibility.render_compatibility_status; do not hand-edit. -->",
        "# Compatibility status",
        "",
        "The machine-readable sources of truth are `compatibility/supported-targets.json` and the referenced platform profiles under `compatibility/platforms/`.",
        "",
        "## Device/build qualification",
        "",
        "| Device | Model | Platform | Tier | Exact qualified builds |",
        "|---|---|---|---|---|",
    ]
    if isinstance(devices, dict):
        for device, record in sorted(devices.items()):
            if not isinstance(record, dict):
                continue
            builds = record.get("qualified_builds", [])
            build_text = ", ".join(f"`{item}`" for item in builds) if isinstance(builds, list) and builds else "none"
            lines.append(
                f"| `{device}` | {record.get('model', '')} | `{record.get('platform_profile', '')}` | "
                f"`{record.get('tier', '')}` | {build_text} |"
            )
    lines.extend([
        "",
        "Release reference: "
        f"`{reference.get('device', '')}` / `{reference.get('build', '')}` / `{reference.get('tier', '')}`.",
        "",
        "## Managed targets",
        "",
        "| Target | Compatibility basis | Distribution type |",
        "|---|---|---|",
    ])
    if isinstance(targets, dict):
        for target, record in sorted(targets.items()):
            if not isinstance(record, dict):
                continue
            distribution = record.get("distribution_identity", {})
            source_type = distribution.get("source_type", "") if isinstance(distribution, dict) else ""
            lines.append(f"| `{target}` | `{record.get('compatibility_basis', '')}` | `{source_type}` |")
    lines.extend([
        "",
        "## Observed dependencies",
        "",
        "These surfaces are evidence-only and are not mutated by OTAST.",
        "",
    ])
    if isinstance(dependencies, dict):
        for dep, record in sorted(dependencies.items()):
            kind = record.get("kind", "") if isinstance(record, dict) else ""
            lines.append(f"- `{dep}` — `{kind}` (`READ_ONLY`)")
    return "\n".join(lines).rstrip() + "\n"
