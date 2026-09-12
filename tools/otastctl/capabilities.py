from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import OtastError

CAPABILITY_SCHEMA_VERSION = 1
REQUIRED_CAPABILITIES = {
    "installed_ota_static_identity",
    "raw_boot_avb_evidence",
    "global_sensitive_props",
    "pif_profile",
    "platform_system_spl",
    "platform_vendor_spl",
    "trickystore_patch",
    "key_attestation",
    "vbmeta_digest",
    "target_list",
    "package_provenance",
    "zygisk_provider",
    "root_concealment",
    "lsposed_environment",
}
WRITE_ROLES = {"AUTHORITY_COORDINATOR", "PROVIDER", "NON_TARGET_PROVIDER", "NON_TARGET_FRAMEWORK"}
ADAPTER_ROLES = {"COMPATIBILITY_ADAPTER", "LEGACY_COMPATIBILITY_ADAPTER"}
NON_TARGET_IDS = {"AshLooper", "AshReXcue", "BetterKnownInstalled", "BKI"}


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtastError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OtastError(f"{label} must be a JSON object")
    return value


def load_capabilities(root: Path) -> dict[str, Any]:
    return _read_object(root / "compatibility/capabilities.json", "capability registry")


def _string_list(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
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


def validate_capabilities(root: Path) -> dict[str, object]:
    root = root.resolve()
    document = load_capabilities(root)
    if document.get("schema_version") != CAPABILITY_SCHEMA_VERSION:
        raise OtastError(f"capability registry schema must be {CAPABILITY_SCHEMA_VERSION}")
    invariant = document.get("governing_invariant")
    if not isinstance(invariant, str) or "One authoritative writer" not in invariant:
        raise OtastError("capability registry must state the one-writer invariant")

    capabilities = document.get("capabilities")
    if not isinstance(capabilities, dict) or set(capabilities) != REQUIRED_CAPABILITIES:
        raise OtastError("capability registry is incomplete or contains undeclared capabilities")
    for capability_id, record in capabilities.items():
        if not isinstance(record, dict):
            raise OtastError(f"capability record is malformed: {capability_id}")
        if not isinstance(record.get("exclusive"), bool):
            raise OtastError(f"capability exclusivity is missing: {capability_id}")
        if not isinstance(record.get("mutable"), bool):
            raise OtastError(f"capability mutability is missing: {capability_id}")
        for key in ("authoritative_owner", "transaction", "reboot_boundary"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                raise OtastError(f"capability {key} is missing: {capability_id}")
        _string_list(record.get("validation"), f"capability {capability_id} validation")

    integrations = document.get("integrations")
    if not isinstance(integrations, dict) or not integrations:
        raise OtastError("capability integrations are missing")
    direct_writers: dict[str, list[str]] = {capability: [] for capability in capabilities}
    module_ids: dict[str, str] = {}
    for integration_id, record in integrations.items():
        if not isinstance(record, dict) or not isinstance(record.get("role"), str):
            raise OtastError(f"integration role is missing: {integration_id}")
        role = record["role"]
        writes = _string_list(record.get("writes", []), f"integration {integration_id} writes", allow_empty=True)
        neutralized = _string_list(
            record.get("neutralized_writers", []), f"integration {integration_id} neutralized_writers", allow_empty=True
        )
        allowed = _string_list(record.get("allowed", []), f"integration {integration_id} allowed", allow_empty=True)
        observes = _string_list(record.get("observes", []), f"integration {integration_id} observes", allow_empty=True)
        for capability in writes + neutralized + allowed + observes:
            if capability not in capabilities:
                raise OtastError(f"integration {integration_id} references unknown capability: {capability}")
        if role in ADAPTER_ROLES and writes:
            raise OtastError(f"compatibility adapter may not remain an authoritative writer: {integration_id}")
        if role not in WRITE_ROLES | ADAPTER_ROLES | {"NON_TARGET_OPERATIONAL_DEPENDENCY"}:
            raise OtastError(f"unsupported integration role: {integration_id}: {role}")
        if role in WRITE_ROLES:
            for capability in writes:
                direct_writers[capability].append(integration_id)
        for module_id in _string_list(record.get("module_ids", []), f"integration {integration_id} module_ids", allow_empty=True):
            if module_id in module_ids:
                raise OtastError(f"module ID belongs to multiple capability integrations: {module_id}")
            module_ids[module_id] = integration_id

    # Static claims may name conditional owners (for example OTAST vs a provider),
    # but no preferred stack may select multiple direct implementations for an
    # exclusive capability. Runtime enforces the effective-device instance.
    preferred = document.get("preferred_stack")
    if not isinstance(preferred, dict):
        raise OtastError("preferred_stack is missing")
    for key in ("required_or_primary", "optional", "not_preferred"):
        _string_list(preferred.get(key), f"preferred_stack.{key}")

    supported = _read_object(root / "compatibility/supported-targets.json", "compatibility registry")
    strict = set(_string_list(supported.get("strict_exclusions"), "strict_exclusions"))
    if not NON_TARGET_IDS.issubset(strict):
        raise OtastError("Ash/BKI non-target module trees must remain write-path protected")
    conflicts = supported.get("conflicts")
    if not isinstance(conflicts, dict):
        raise OtastError("compatibility conflicts are missing")
    for conflict_id, record in conflicts.items():
        if not isinstance(record, dict):
            raise OtastError(f"conflict is malformed: {conflict_id}")
        ids = set(_string_list(record.get("module_ids"), f"conflict {conflict_id} module_ids"))
        if ids & NON_TARGET_IDS:
            if record.get("severity") == "HARD_STOP" or "identity-governor" in conflict_id:
                raise OtastError("Ash/BKI must not be classified as hard-stop identity governors")

    generated = root / "docs/CAPABILITY-OWNERSHIP.md"
    if generated.is_symlink() or not generated.is_file():
        raise OtastError("generated capability ownership document is missing")
    if generated.read_text(encoding="utf-8") != render_capability_ownership(root):
        raise OtastError("docs/CAPABILITY-OWNERSHIP.md is stale; regenerate it from compatibility/capabilities.json")

    return {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "capabilities": sorted(capabilities),
        "integrations": sorted(integrations),
        "exclusive_capabilities": sorted(
            capability for capability, record in capabilities.items() if isinstance(record, dict) and record.get("exclusive")
        ),
    }


def render_capability_ownership(root: Path) -> str:
    document = load_capabilities(root)
    capabilities = document.get("capabilities", {})
    integrations = document.get("integrations", {})
    preferred = document.get("preferred_stack", {})
    lines = [
        "<!-- GENERATED by tools.otastctl.capabilities.render_capability_ownership; do not hand-edit. -->",
        "# Capability ownership",
        "",
        str(document.get("governing_invariant", "")),
        "",
        "A process-scoped PIF/DroidGuard identity is a separate domain from installed OTA identity and is not required to match it.",
        "",
        "## Capability matrix",
        "",
        "| Capability | Exclusive | Authority | Mutable | Transaction / Restore boundary | Reboot boundary |",
        "|---|---|---|---|---|---|",
    ]
    if isinstance(capabilities, dict):
        for capability_id, record in capabilities.items():
            if not isinstance(record, dict):
                continue
            lines.append(
                f"| `{capability_id}` | `{str(bool(record.get('exclusive'))).lower()}` | "
                f"`{record.get('authoritative_owner', '')}` | `{str(bool(record.get('mutable'))).lower()}` | "
                f"{record.get('transaction', '')} | {record.get('reboot_boundary', '')} |"
            )
    lines.extend(["", "## Integration roles", "", "| Integration | Role | Writes | Neutralized writers |", "|---|---|---|---|"])
    if isinstance(integrations, dict):
        for integration_id, record in integrations.items():
            if not isinstance(record, dict):
                continue
            writes = ", ".join(f"`{item}`" for item in record.get("writes", [])) or "none"
            neutralized = ", ".join(f"`{item}`" for item in record.get("neutralized_writers", [])) or "none"
            lines.append(f"| `{integration_id}` | `{record.get('role', '')}` | {writes} | {neutralized} |")
    lines.extend([
        "",
        "## Preferred stack policy",
        "",
        "This is a recommendation boundary, not an uninstall instruction. Compatibility adapters remain supported only where their reviewed writers can be neutralized and restored deterministically.",
        "",
    ])
    if isinstance(preferred, dict):
        for key in ("required_or_primary", "optional", "not_preferred"):
            values = preferred.get(key, [])
            rendered = ", ".join(f"`{item}`" for item in values) if isinstance(values, list) else ""
            lines.append(f"- **{key.replace('_', ' ').title()}**: {rendered}")
    lines.extend([
        "",
        "## Historical convergence",
        "",
        "- `ota-sot` transaction/Restore invariants are retained by the current OTAST transaction engine; its OTA-to-PIF identity coupling is superseded.",
        "- `otasst` capability separation and non-target treatment are adopted here without porting its CAS/state engine wholesale.",
        "- PR #41 canonical PIF ownership, immutable mirror generations and staged-promotion semantics remain authoritative.",
        "- TA UTL remains a compatibility adapter because current upstream reads `boot_hash` before `disable_prop_handler`; a source/WebUI boundary is still required for safe target-list-only coexistence.",
        "- Yurikey and Android VBMeta Fixer are compatibility adapters, not preferred authority providers.",
    ])
    return "\n".join(lines).rstrip() + "\n"
