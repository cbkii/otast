from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path, PurePosixPath
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
DISTRIBUTION_TYPES = {
    "BRANCH_BUILD",
    "BRANCH_SOURCE",
    "BRANCH_SOURCE_WITH_VERSION_RANGE",
    "RELEASE_ASSET",
    "RELEASE_AND_WORKFLOW_ARTIFACT",
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
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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
    root = root.resolve()
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
    candidate = root / relative
    platform_root = (root / "compatibility/platforms").resolve()
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(platform_root)
    except (OSError, ValueError) as exc:
        raise OtastError(f"platform profile path escapes compatibility/platforms: {profile_id}") from exc
    if candidate.is_symlink() or resolved.is_symlink() or not resolved.is_file():
        raise OtastError(f"platform profile path is unsafe: {profile_id}")
    profile = _read_json(resolved, f"platform profile {profile_id}")
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


def _require_distribution_string(distribution: dict[str, Any], key: str, target_id: str) -> str:
    value = distribution.get(key)
    if not isinstance(value, str) or not value or any(ch in value for ch in "\r\n\0"):
        raise OtastError(f"target distribution field is missing or invalid: {target_id}.{key}")
    return value


def _validate_distribution(target_id: str, record: dict[str, Any], monitor: dict[str, Any]) -> None:
    distribution = record.get("distribution_identity")
    if not isinstance(distribution, dict):
        raise OtastError(f"target distribution identity is incomplete: {target_id}")
    source_type = distribution.get("source_type")
    repository = distribution.get("repository")
    if source_type not in DISTRIBUTION_TYPES:
        raise OtastError(f"target distribution type is unsupported: {target_id}")
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise OtastError(f"target distribution repository is invalid: {target_id}")
    if repository != monitor.get("repository"):
        raise OtastError(f"target distribution repository disagrees with monitor: {target_id}")

    module_ids = set(_require_string_list(record.get("module_ids"), f"target {target_id} module_ids"))
    declared_distribution_ids: set[str] = set()
    module_id = distribution.get("module_id")
    if isinstance(module_id, str) and module_id:
        declared_distribution_ids.add(module_id)
    raw_module_ids = distribution.get("module_ids")
    if raw_module_ids is not None:
        declared_distribution_ids.update(
            _require_string_list(raw_module_ids, f"target {target_id} distribution module_ids")
        )
    if declared_distribution_ids and not declared_distribution_ids.issubset(module_ids):
        raise OtastError(f"target distribution module identity is outside explicit module_ids: {target_id}")

    for key, value in distribution.items():
        if key.endswith("commit") and value is not None:
            if not isinstance(value, str) or not SHA1_RE.fullmatch(value):
                raise OtastError(f"target distribution commit is invalid: {target_id}.{key}")
        if key.endswith("sha256") and value is not None:
            if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                raise OtastError(f"target distribution SHA-256 is invalid: {target_id}.{key}")

    if source_type == "RELEASE_ASSET":
        for key in ("release", "asset_name", "asset_sha256", "module_id", "version", "version_code", "author"):
            if key not in distribution or distribution[key] in (None, ""):
                raise OtastError(f"release-asset identity is missing {key}: {target_id}")
        if not isinstance(distribution["version_code"], int) or isinstance(distribution["version_code"], bool):
            raise OtastError(f"release-asset version_code is invalid: {target_id}")
    elif source_type == "BRANCH_SOURCE_WITH_VERSION_RANGE":
        prefixes = _require_string_list(distribution.get("version_prefixes"), f"target {target_id} version prefixes")
        code_range = distribution.get("version_code_range")
        if not prefixes or not isinstance(code_range, list) or len(code_range) != 2:
            raise OtastError(f"version-range distribution identity is incomplete: {target_id}")
        if not all(isinstance(item, int) and not isinstance(item, bool) for item in code_range):
            raise OtastError(f"version-range distribution codes are invalid: {target_id}")
        if code_range[0] > code_range[1]:
            raise OtastError(f"version-range distribution codes are reversed: {target_id}")
    elif source_type in {"BRANCH_BUILD", "BRANCH_SOURCE"}:
        ref = distribution.get("ref")
        if not isinstance(ref, str) or not ref:
            raise OtastError(f"branch distribution ref is missing: {target_id}")
    elif source_type == "RELEASE_AND_WORKFLOW_ARTIFACT":
        _require_distribution_string(distribution, "release_ref", target_id)
        for key in ("reviewed_source_commit", "reviewed_generated_commit"):
            value = _require_distribution_string(distribution, key, target_id)
            if SHA1_RE.fullmatch(value) is None:
                raise OtastError(f"release/workflow distribution commit is invalid: {target_id}.{key}")
        asset_name = _require_distribution_string(distribution, "release_asset_name", target_id)
        if PurePosixPath(asset_name).name != asset_name or "/" in asset_name or "\\" in asset_name:
            raise OtastError(f"release/workflow asset name is unsafe: {target_id}")
        asset_sha = _require_distribution_string(distribution, "release_asset_sha256", target_id)
        if SHA256_RE.fullmatch(asset_sha) is None:
            raise OtastError(f"release/workflow asset SHA-256 is invalid: {target_id}")


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
    architecture = support.get("family_architecture")
    if not isinstance(architecture, dict) or architecture.get("tier") != "DESIGN_COMPATIBLE":
        raise OtastError("family_architecture must explicitly declare DESIGN_COMPATIBLE")
    if support.get("undeclared_device_tier") != "UNQUALIFIED":
        raise OtastError("undeclared Pixel devices must remain UNQUALIFIED")

    profile_ids = _require_string_list(support.get("supported_platform_profiles"), "supported platform profiles")
    architecture_profiles = _require_string_list(
        architecture.get("platform_profiles"), "family architecture platform profiles"
    )
    if set(architecture_profiles) != set(profile_ids):
        raise OtastError("family architecture platform profiles disagree with supported profiles")

    platform_summaries: dict[str, dict[str, object]] = {}
    runtime_platform = root / "module/runtime/platform.sh"
    if runtime_platform.is_symlink() or not runtime_platform.is_file():
        raise OtastError("runtime platform mirror is missing or unsafe")
    runtime_text = runtime_platform.read_text(encoding="utf-8")

    for profile_id in profile_ids:
        profile = load_platform(root, profile_id)
        android_release = profile.get("android_release")
        sdk = profile.get("sdk")
        if not isinstance(android_release, str) or not android_release.isdigit():
            raise OtastError(f"platform android_release is invalid: {profile_id}")
        if not isinstance(sdk, int) or isinstance(sdk, bool) or sdk <= 0:
            raise OtastError(f"platform SDK is invalid: {profile_id}")
        authority = profile.get("authority")
        if not isinstance(authority, dict):
            raise OtastError(f"platform profile has no authority contract: {profile_id}")
        required = set(_require_string_list(authority.get("required_keys"), f"{profile_id} required authority keys"))
        for key in ("ro.build.version.security_patch", "ro.vendor.build.security_patch"):
            if key not in required:
                raise OtastError(f"platform profile must require independent system/vendor SPL: missing {key}")
        static_sources = profile.get("static_property_sources")
        if not isinstance(static_sources, dict):
            raise OtastError(f"platform static property sources are missing: {profile_id}")
        for key in ("ro.build.version.security_patch", "ro.vendor.build.security_patch"):
            _require_string_list(static_sources.get(key), f"{profile_id} static sources for {key}")
        bootconfig = profile.get("bootconfig_evidence")
        if not isinstance(bootconfig, dict) or not bootconfig:
            raise OtastError(f"platform bootconfig evidence is missing: {profile_id}")
        native = profile.get("native_environment_evidence")
        if not isinstance(native, dict):
            raise OtastError(f"platform native environment evidence is missing: {profile_id}")
        for key in (
            "runtime_page_size",
            "primary_abi",
            "abi_list",
            "native_library_inventory",
            "elf_load_alignment",
            "zygisk_identity",
        ):
            if not isinstance(native.get(key), str) or not native[key]:
                raise OtastError(f"platform native evidence field is missing: {profile_id}.{key}")

        contract = profile.get("device_family")
        if not isinstance(contract, dict):
            raise OtastError(f"platform device-family contract is invalid: {profile_id}")
        expected_runtime = {
            "OTAST_PLATFORM_ID": profile_id,
            "OTAST_PLATFORM_ANDROID_RELEASE": android_release,
            "OTAST_PLATFORM_SDK": str(sdk),
            "OTAST_PLATFORM_MANUFACTURER": str(contract.get("manufacturer", "")),
            "OTAST_PLATFORM_MODEL_PREFIX": str(contract.get("model_prefix", "")),
            "OTAST_PLATFORM_FINGERPRINT_VENDOR": str(contract.get("fingerprint_vendor", "")),
            "OTAST_PLATFORM_FINGERPRINT_SUFFIX": str(contract.get("fingerprint_suffix", "")),
        }
        for name, expected in expected_runtime.items():
            assignment = f"{name}='{expected}'"
            if assignment not in runtime_text:
                raise OtastError(f"runtime platform mirror disagrees with {profile_id}: {name}")
        platform_summaries[profile_id] = {"android_release": android_release, "sdk": sdk}

    devices = support.get("devices")
    if not isinstance(devices, dict) or not devices:
        raise OtastError("support_model.devices must be a non-empty object")
    for device, record in devices.items():
        if not isinstance(device, str) or not re.fullmatch(r"[a-z0-9_]+", device) or not isinstance(record, dict):
            raise OtastError("device qualification record is malformed")
        tier = record.get("tier")
        if tier not in QUALIFICATION_TIERS:
            raise OtastError(f"device qualification tier is invalid: {device}")
        if record.get("platform_profile") not in profile_ids:
            raise OtastError(f"device references unsupported platform profile: {device}")
        builds = record.get("qualified_builds")
        if not isinstance(builds, list) or not all(isinstance(item, str) and item for item in builds):
            raise OtastError(f"device qualified_builds must be a string list: {device}")
        if len(builds) != len(set(builds)):
            raise OtastError(f"device qualified_builds contains duplicates: {device}")
        if tier in {"FIXTURE_QUALIFIED", "DEVICE_VALIDATED", "RELEASE_QUALIFIED"} and not builds:
            raise OtastError(f"qualified device tier requires an exact build: {device}")
        if tier in {"UNQUALIFIED", "DESIGN_COMPATIBLE"} and builds:
            raise OtastError(f"unproven device tier may not claim qualified builds: {device}")
        fixture = record.get("authority_fixture")
        if tier in {"FIXTURE_QUALIFIED", "DEVICE_VALIDATED", "RELEASE_QUALIFIED"}:
            if not isinstance(fixture, str) or not (root / fixture).is_file():
                raise OtastError(f"qualified device authority fixture is missing: {device}")

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
    if reference.get("platform_profile") != reference_record.get("platform_profile"):
        raise OtastError("release_reference platform disagrees with device qualification")
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
        for module_id in _require_string_list(
            record.get("module_ids", []), f"observed dependency {dep_id} module_ids", allow_empty=True
        ):
            if module_id in observed_module_ids:
                raise OtastError(f"observed module ID declared twice: {module_id}")
            if module_id in conflict_ids:
                raise OtastError(f"observed dependency overlaps explicit conflict: {module_id}")
            observed_module_ids.add(module_id)

    targets = registry.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise OtastError("managed targets object is missing or empty")
    managed_module_ids: set[str] = set()
    for target_id, record in targets.items():
        if not isinstance(record, dict) or record.get("target_role") != "MANAGED":
            raise OtastError(f"target must explicitly declare MANAGED ownership: {target_id}")
        basis = record.get("compatibility_basis")
        if basis not in COMPATIBILITY_BASES:
            raise OtastError(f"target compatibility basis is invalid: {target_id}")
        target_module_ids = _require_string_list(record.get("module_ids"), f"target {target_id} module_ids")
        for module_id in target_module_ids:
            if module_id in managed_module_ids:
                raise OtastError(f"managed module ID declared by multiple targets: {module_id}")
            if module_id in conflict_ids:
                raise OtastError(f"managed target overlaps explicit conflict: {module_id}")
            if module_id in observed_module_ids:
                raise OtastError(f"managed target is also declared as an observed module: {module_id}")
            managed_module_ids.add(module_id)

        monitor = record.get("monitor")
        if not isinstance(monitor, dict):
            raise OtastError(f"target monitor is invalid: {target_id}")
        repository = monitor.get("repository")
        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
            raise OtastError(f"target monitor repository is invalid: {target_id}")
        if not SHA1_RE.fullmatch(str(monitor.get("expected_head", ""))):
            raise OtastError(f"target monitor expected_head is invalid: {target_id}")
        _validate_distribution(target_id, record, monitor)

        policy = record.get("impact_policy")
        if not isinstance(policy, dict):
            raise OtastError(f"target impact policy is missing: {target_id}")
        unknown_policy = set(policy) - set(IMPACT_POLICY_KEYS)
        if unknown_policy:
            raise OtastError(f"target impact policy has unknown categories: {target_id}: {sorted(unknown_policy)}")
        for category in IMPACT_POLICY_KEYS:
            _require_string_list(policy.get(category, []), f"{target_id} impact_policy.{category}", allow_empty=True)

        if basis == "WHOLE_FILE_VERSION_RANGE":
            supported = record.get("supported_version")
            if not isinstance(supported, dict):
                raise OtastError(f"whole-file version-range target lacks supported_version: {target_id}")
            _require_string_list(supported.get("prefixes"), f"{target_id} supported version prefixes")
            minimum = supported.get("min_version_code")
            maximum = supported.get("max_version_code")
            if not all(isinstance(item, int) and not isinstance(item, bool) for item in (minimum, maximum)):
                raise OtastError(f"whole-file version codes are invalid: {target_id}")
            if minimum > maximum:
                raise OtastError(f"whole-file version-code range is reversed: {target_id}")
        elif basis == "STRUCTURE_SENSITIVE_TRANSFORM":
            hashes = record.get("accepted_hashes")
            if not isinstance(hashes, dict) or not hashes:
                raise OtastError(f"structure-sensitive target lacks accepted hashes: {target_id}")
            for path, values in hashes.items():
                for digest in _require_string_list(values, f"{target_id} accepted hashes for {path}"):
                    if not SHA256_RE.fullmatch(digest):
                        raise OtastError(f"structure-sensitive accepted hash is invalid: {target_id}:{path}")
        elif basis == "EXACT_REVIEWED_ARTIFACT":
            distribution = record["distribution_identity"]
            commit = distribution.get("reviewed_commit") or record.get("reviewed_commit")
            if commit is not None and (not isinstance(commit, str) or not SHA1_RE.fullmatch(commit)):
                raise OtastError(f"exact reviewed artefact commit is invalid: {target_id}")

    for dep_id, record in dependencies.items():
        managed_target = record.get("managed_target") if isinstance(record, dict) else None
        if managed_target is not None and managed_target not in targets:
            raise OtastError(f"observed dependency references unknown managed target: {dep_id}")

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
    per_path: list[dict[str, object]] = []
    for path in paths:
        if not path or path.startswith("/") or ".." in Path(path).parts or any(ch in path for ch in "\r\n\0"):
            raise OtastError(f"unsafe changed path: {path!r}")
        matches: set[str] = set()
        for policy_key, candidate in IMPACT_POLICY_KEYS.items():
            patterns = policy.get(policy_key, [])
            if isinstance(patterns, list) and _matches(path, (str(item) for item in patterns)):
                matches.add(candidate)
        impact = max(matches, key=lambda item: IMPACT_PRIORITY[item]) if matches else "UNKNOWN_PACKAGE_CHANGE"
        per_path.append({"path": path, "impact": impact, "matched_impacts": sorted(matches)})
    primary = max((str(item["impact"]) for item in per_path), key=lambda item: IMPACT_PRIORITY[item])
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
    architecture = support.get("family_architecture", {}) if isinstance(support, dict) else {}
    reference = support.get("release_reference", {}) if isinstance(support, dict) else {}
    targets = registry.get("targets", {})
    dependencies = registry.get("observed_dependencies", {})
    platforms = registry.get("platforms", {})
    lines = [
        "<!-- GENERATED by tools.otastctl.compatibility.render_compatibility_status; do not hand-edit. -->",
        "# Compatibility status",
        "",
        "The machine-readable sources of truth are `compatibility/supported-targets.json` and the referenced platform profiles under `compatibility/platforms/`.",
        "",
        "## Family/platform contract",
        "",
        f"- Device family: `{support.get('device_family', '')}`.",
        f"- Family architecture tier: `{architecture.get('tier', '')}`.",
        f"- Undeclared device/build tier: `{support.get('undeclared_device_tier', '')}`.",
        "- Family architectural compatibility does not make an undeclared Pixel physically qualified.",
        "",
        "| Platform profile | Status | Android | SDK |",
        "|---|---|---|---|",
    ]
    if isinstance(platforms, dict):
        for profile_id, record in sorted(platforms.items()):
            if not isinstance(record, dict):
                continue
            try:
                profile = load_platform(root, profile_id)
                release = profile.get("android_release", "")
                sdk = profile.get("sdk", "")
            except OtastError:
                release = "invalid"
                sdk = "invalid"
            lines.append(f"| `{profile_id}` | `{record.get('status', '')}` | `{release}` | `{sdk}` |")
    lines.extend([
        "",
        "## Device/build qualification",
        "",
        "| Device | Model | Platform | Tier | Exact qualified builds |",
        "|---|---|---|---|---|",
    ])
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