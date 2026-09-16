from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .util import OtastError

PIF_PROVIDER_SCHEMA_VERSION = 1
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
PROVIDER_STATUSES = {
    "SUPPORTED_PREFERRED",
    "SUPPORTED_CANDIDATE_PHYSICAL_QUALIFICATION_REQUIRED",
}
POLICY_TO_IMPACT = {
    "docs_ci": "DOCS_OR_CI_ONLY",
    "preserved_surface": "PRESERVED_NON_WRITER_SURFACE",
    "module_identity": "MODULE_IDENTITY",
    "native_dependency": "NATIVE_DEPENDENCY",
    "target_writer": "TARGET_WRITER",
    "new_writer_capability": "NEW_WRITER_CAPABILITY",
}
IMPACT_PRIORITY = {
    "DOCS_OR_CI_ONLY": 0,
    "PRESERVED_NON_WRITER_SURFACE": 1,
    "MODULE_IDENTITY": 2,
    "NATIVE_DEPENDENCY": 3,
    "TARGET_WRITER": 4,
    "REMOVED_WRITER_CAPABILITY": 5,
    "NEW_WRITER_CAPABILITY": 6,
    "AMBIGUOUS_UNKNOWN_WRITER_BEHAVIOR": 7,
}


def load_pif_providers(root: Path) -> dict[str, Any]:
    """Load the reviewed PIF provider registry without executing provider code."""
    path = root / "compatibility/pif-providers.json"
    if path.is_symlink() or not path.is_file():
        raise OtastError("PIF provider registry is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtastError(f"cannot read PIF provider registry: {exc}") from exc
    if not isinstance(value, dict):
        raise OtastError("PIF provider registry must be an object")
    return value


def _string_list(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise OtastError(f"{label} must be a{' non-empty' if not allow_empty else ''} string list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or any(ch in item for ch in "\r\n\0"):
            raise OtastError(f"{label} contains an invalid value")
        result.append(item)
    if len(result) != len(set(result)):
        raise OtastError(f"{label} contains duplicates")
    return result


def validate_pif_providers(root: Path) -> dict[str, object]:
    """Validate provider identity, profile, writer and provenance contracts."""
    root = root.resolve()
    document = load_pif_providers(root)
    if document.get("schema_version") != PIF_PROVIDER_SCHEMA_VERSION:
        raise OtastError(f"PIF provider registry schema must be {PIF_PROVIDER_SCHEMA_VERSION}")
    if document.get("module_id") != "playintegrityfix":
        raise OtastError("PIF provider registry must bind the shared playintegrityfix module ID")
    if document.get("selection_policy") != "exact-reviewed-provider-evidence":
        raise OtastError("PIF provider selection policy must remain exact-reviewed-provider-evidence")
    providers = document.get("providers")
    if not isinstance(providers, dict) or set(providers) != {"kowx-inject-s", "osm0sis-fork-v18"}:
        raise OtastError("initial PIF provider set is incomplete or unexpected")
    preferred = document.get("preferred_provider")
    if preferred not in providers:
        raise OtastError("preferred PIF provider is undeclared")
    if not isinstance(document.get("preference_gate"), str) or not document["preference_gate"]:
        raise OtastError("PIF provider preference gate is missing")

    reviewed: dict[str, dict[str, object]] = {}
    for provider_id, record in providers.items():
        if not isinstance(record, dict):
            raise OtastError(f"PIF provider record is malformed: {provider_id}")
        if record.get("status") not in PROVIDER_STATUSES:
            raise OtastError(f"PIF provider status is invalid: {provider_id}")
        commit = record.get("reviewed_commit")
        module_sha = record.get("module_prop_sha256")
        blob = record.get("module_prop_git_blob")
        if not isinstance(commit, str) or SHA40_RE.fullmatch(commit) is None:
            raise OtastError(f"PIF provider reviewed commit is invalid: {provider_id}")
        if not isinstance(blob, str) or SHA40_RE.fullmatch(blob) is None:
            raise OtastError(f"PIF provider module.prop blob is invalid: {provider_id}")
        if not isinstance(module_sha, str) or SHA64_RE.fullmatch(module_sha) is None:
            raise OtastError(f"PIF provider module.prop SHA-256 is invalid: {provider_id}")
        identity = record.get("module_identity")
        if not isinstance(identity, dict) or identity.get("id") != document["module_id"]:
            raise OtastError(f"PIF provider module identity is invalid: {provider_id}")
        if not isinstance(identity.get("name"), str) or not identity["name"]:
            raise OtastError(f"PIF provider module name is missing: {provider_id}")
        if not isinstance(identity.get("version"), str) or not identity["version"]:
            raise OtastError(f"PIF provider version is missing: {provider_id}")
        if not isinstance(identity.get("version_code"), int) or isinstance(identity.get("version_code"), bool):
            raise OtastError(f"PIF provider versionCode is invalid: {provider_id}")
        profile = record.get("profile")
        if not isinstance(profile, dict):
            raise OtastError(f"PIF provider profile contract is missing: {provider_id}")
        precedence = _string_list(profile.get("canonical_precedence"), f"{provider_id} canonical precedence")
        if not all(path.startswith("/data/adb/") for path in precedence):
            raise OtastError(f"PIF provider canonical precedence escapes /data/adb: {provider_id}")
        writers = _string_list(record.get("sensitive_property_writers"), f"{provider_id} sensitive writers")
        patch = record.get("security_patch_behavior")
        if not isinstance(patch, dict) or patch.get("mode") != "SURGICAL_REVIEWED_BOUNDARY":
            raise OtastError(f"PIF provider security-patch ownership contract is incomplete: {provider_id}")
        writer = patch.get("writer")
        if not isinstance(writer, str) or not writer.startswith("module/"):
            raise OtastError(f"PIF provider security-patch writer is invalid: {provider_id}")
        impact = record.get("impact_policy")
        if not isinstance(impact, dict):
            raise OtastError(f"PIF provider impact policy is missing: {provider_id}")
        unknown = set(impact) - set(POLICY_TO_IMPACT)
        if unknown:
            raise OtastError(f"PIF provider impact policy contains unknown categories: {provider_id}: {sorted(unknown)}")
        for policy_key in POLICY_TO_IMPACT:
            _string_list(impact.get(policy_key, []), f"{provider_id} impact {policy_key}", allow_empty=True)
        reviewed[provider_id] = {
            "status": record["status"],
            "reviewed_commit": commit,
            "module_prop_sha256": module_sha,
            "canonical_precedence": precedence,
            "sensitive_property_writers": writers,
            "security_patch_writer": writer,
        }

    fork = providers["osm0sis-fork-v18"]
    release_sha = fork.get("release_asset_sha256") if isinstance(fork, dict) else None
    if not isinstance(release_sha, str) or SHA64_RE.fullmatch(release_sha) is None:
        raise OtastError("Play Integrity Fork release-asset provenance is missing")
    fork_profile = fork.get("profile") if isinstance(fork, dict) else None
    if not isinstance(fork_profile, dict):
        raise OtastError("Play Integrity Fork profile contract is missing")
    runtime_precedence = _string_list(
        fork_profile.get("upstream_runtime_precedence"), "Play Integrity Fork upstream runtime precedence"
    )
    if runtime_precedence != ["custom.pif.prop", "custom.pif.json", "pif.prop", "pif.json"]:
        raise OtastError("Play Integrity Fork runtime profile precedence changed from the reviewed v18 loader")
    patch = fork.get("security_patch_behavior") if isinstance(fork, dict) else None
    if not isinstance(patch, dict) or not isinstance(patch.get("writer_git_blob"), str):
        raise OtastError("Play Integrity Fork autopif4 writer provenance is missing")
    if SHA40_RE.fullmatch(str(patch["writer_git_blob"])) is None:
        raise OtastError("Play Integrity Fork autopif4 writer Git blob is invalid")
    if providers[preferred].get("status") != "SUPPORTED_PREFERRED":
        raise OtastError("preferred PIF provider is not marked preferred")
    if fork.get("preference_qualification") != "UNQUALIFIED_ON_TEGU_EXACT_STACK":
        raise OtastError("Fork preference must remain gated by exact-stack physical qualification")

    generated = root / "docs/PIF-PROVIDERS.md"
    if generated.is_symlink() or not generated.is_file():
        raise OtastError("generated PIF provider document is missing")
    if generated.read_text(encoding="utf-8") != render_pif_providers(root):
        raise OtastError("docs/PIF-PROVIDERS.md is stale; regenerate it from compatibility/pif-providers.json")
    return {
        "schema_version": PIF_PROVIDER_SCHEMA_VERSION,
        "preferred_provider": preferred,
        "providers": reviewed,
    }


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify_provider_changed_paths(
    provider_record: dict[str, Any],
    changed_paths: Iterable[str],
    *,
    removed_paths: Iterable[str] = (),
) -> dict[str, object]:
    """Classify upstream path movement without executing unreviewed provider code."""
    policy = provider_record.get("impact_policy")
    if not isinstance(policy, dict):
        raise OtastError("PIF provider has no impact policy")
    removed = set(removed_paths)
    paths = sorted(set(changed_paths))
    if not paths:
        raise OtastError("PIF provider changed path set is empty")
    per_path: list[dict[str, str]] = []
    for path in paths:
        if not path or path.startswith("/") or ".." in Path(path).parts or any(ch in path for ch in "\r\n\0"):
            raise OtastError(f"unsafe PIF provider changed path: {path!r}")
        matched: list[str] = []
        for key, impact in POLICY_TO_IMPACT.items():
            if _matches(path, (str(item) for item in policy.get(key, []))):
                matched.append(impact)
        if path in removed and ("TARGET_WRITER" in matched or "NEW_WRITER_CAPABILITY" in matched):
            impact_name = "REMOVED_WRITER_CAPABILITY"
        elif not matched:
            impact_name = "AMBIGUOUS_UNKNOWN_WRITER_BEHAVIOR"
        else:
            impact_name = max(matched, key=lambda value: IMPACT_PRIORITY[value])
        per_path.append({"path": path, "impact": impact_name})
    primary = max((item["impact"] for item in per_path), key=lambda value: IMPACT_PRIORITY[value])
    return {
        "impact": primary,
        "requires_review": primary != "DOCS_OR_CI_ONLY",
        "automatic_promotion_allowed": primary == "DOCS_OR_CI_ONLY",
        "paths": per_path,
    }


def render_pif_providers(root: Path) -> str:
    """Render the provider document from the canonical JSON registry."""
    document = load_pif_providers(root)
    providers = document.get("providers", {})
    lines = [
        "<!-- GENERATED from compatibility/pif-providers.json; do not hand-edit. -->",
        "# PIF provider contracts",
        "",
        "Both reviewed implementations use module ID `playintegrityfix`; they are mutually exclusive providers, not co-installable targets.",
        "",
        f"Preferred provider: `{document.get('preferred_provider', '')}`.",
        "",
        str(document.get("preference_gate", "")),
        "",
        "| Provider | Status | Reviewed source | Profile precedence | Security-patch writer boundary |",
        "|---|---|---|---|---|",
    ]
    if isinstance(providers, dict):
        for provider_id, record in providers.items():
            if not isinstance(record, dict):
                continue
            profile = record.get("profile", {}) if isinstance(record.get("profile"), dict) else {}
            patch = record.get("security_patch_behavior", {}) if isinstance(record.get("security_patch_behavior"), dict) else {}
            precedence = " → ".join(f"`{item}`" for item in profile.get("canonical_precedence", []))
            lines.append(
                f"| `{provider_id}` | `{record.get('status', '')}` | `{record.get('repository', '')}@{record.get('reviewed_commit', '')}` | "
                f"{precedence} | `{patch.get('writer', '')}` / `{patch.get('mode', '')}` |"
            )
    lines.extend([
        "",
        "## Runtime policy",
        "",
        "- Inject-S retains PR #41's canonical global/active/staged profile and immutable mirror-generation state machine.",
        "- Fork v18 uses provider-owned `custom.pif.prop`; OTAST never mirrors or rewrites it.",
        "- Fork's reviewed native loader uses `custom.pif.prop > custom.pif.json > pif.prop > pif.json`; a present custom prop is therefore authoritative even when a JSON file also exists.",
        "- JSON-only Fork configuration fails closed in the OTAST runtime. Upstream supports JSON, but OTAST deliberately avoids an ad-hoc shell JSON parser; migrate to `custom.pif.prop` before Apply.",
        "- Fork `autopif4.sh` remains the profile generator, but its direct TrickyStore `security_patch.txt` mutation is suppressed because that external contract belongs to OTAST. TEESimulator/OhMyKeyMint warning flow and the remaining profile/killpi lifecycle are preserved.",
        "- Active/staged trees must resolve to the same reviewed provider implementation. A cross-provider staged transition fails closed; OTAST never switches providers automatically.",
        "",
        "## Maintenance impact classes",
        "",
        "Provider source movement is classified as docs/CI only, preserved non-writer surface, module identity, native dependency, target writer, new writer capability, removed writer capability, or ambiguous/unknown writer behavior. New, removed, or ambiguous writer behavior always requires explicit review and cannot advance compatibility automatically.",
    ])
    return "\n".join(lines).rstrip() + "\n"
