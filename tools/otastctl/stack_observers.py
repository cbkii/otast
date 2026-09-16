from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import OtastError

STACK_OBSERVER_SCHEMA_VERSION = 1


def load_stack_observers(root: Path) -> dict[str, Any]:
    """Load the read-only integrity-stack observer registry."""
    path = root / "compatibility/stack-observers.json"
    if path.is_symlink() or not path.is_file():
        raise OtastError("stack observer registry is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtastError(f"cannot read stack observer registry: {exc}") from exc
    if not isinstance(value, dict):
        raise OtastError("stack observer registry must be an object")
    return value


def _module_ids(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise OtastError(f"{label} module_ids must be a non-empty list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or any(ch in item for ch in "\r\n\0/\\"):
            raise OtastError(f"{label} has an unsafe module ID")
        result.append(item)
    if len(result) != len(set(result)):
        raise OtastError(f"{label} module IDs contain duplicates")
    return result


def validate_stack_observers(root: Path) -> dict[str, object]:
    """Validate read-only stack inventory and generated qualification guidance."""
    root = root.resolve()
    document = load_stack_observers(root)
    if document.get("schema_version") != STACK_OBSERVER_SCHEMA_VERSION:
        raise OtastError(f"stack observer registry schema must be {STACK_OBSERVER_SCHEMA_VERSION}")
    zygisk = document.get("zygisk_provider")
    if not isinstance(zygisk, dict) or zygisk.get("exclusive") is not True:
        raise OtastError("Zygisk provider must remain an exclusive qualification domain")
    known = _module_ids(zygisk.get("known_module_ids"), "Zygisk provider")
    if known != ["rezygisk", "zygisksu"]:
        raise OtastError("reviewed module-based Zygisk provider inventory changed")
    if zygisk.get("zero_module_provider_state") != "EXTERNAL_OR_BUILTIN_UNRESOLVED":
        raise OtastError("zero module-based Zygisk providers must remain unresolved, not absent")

    observers = document.get("observers")
    if not isinstance(observers, dict) or set(observers) != {"vector", "treat-wheel", "zygisk-detach"}:
        raise OtastError("stack observer set is incomplete or unexpected")
    all_ids: set[str] = set(known)
    for observer_id, record in observers.items():
        if not isinstance(record, dict) or record.get("mode") != "READ_ONLY":
            raise OtastError(f"stack observer must be read-only: {observer_id}")
        module_ids = _module_ids(record.get("module_ids"), observer_id)
        overlap = all_ids.intersection(module_ids)
        if overlap:
            raise OtastError(f"stack observer module ID overlaps another role: {sorted(overlap)}")
        all_ids.update(module_ids)
    detach = observers["zygisk-detach"]
    if detach.get("config_path") != "/data/adb/zygisk-detach/detach.bin":
        raise OtastError("zygisk-detach reviewed configuration path changed")
    critical = detach.get("critical_packages")
    if critical != [
        "com.google.android.gms",
        "com.android.vending",
        "com.google.android.apps.walletnfcrel",
    ]:
        raise OtastError("qualification-critical detach package baseline changed")

    capabilities = json.loads((root / "compatibility/capabilities.json").read_text(encoding="utf-8"))
    strict = json.loads((root / "compatibility/supported-targets.json").read_text(encoding="utf-8"))["strict_exclusions"]
    for module_id in strict:
        if module_id in all_ids:
            raise OtastError(f"strict non-target leaked into runtime stack observer inventory: {module_id}")
    cap_integrations = capabilities.get("integrations", {})
    if not isinstance(cap_integrations, dict) or "vector" not in cap_integrations or "rezygisk" not in cap_integrations:
        raise OtastError("stack observer registry is not aligned with capability integrations")

    doc = root / "docs/STACK-QUALIFICATION.md"
    if doc.is_symlink() or not doc.is_file():
        raise OtastError("generated stack qualification document is missing")
    if doc.read_text(encoding="utf-8") != render_stack_qualification(root):
        raise OtastError("docs/STACK-QUALIFICATION.md is stale; regenerate it from compatibility/stack-observers.json")
    return {
        "schema_version": STACK_OBSERVER_SCHEMA_VERSION,
        "zygisk_module_providers": known,
        "observers": sorted(observers),
        "critical_detach_packages": critical,
    }


def render_stack_qualification(root: Path) -> str:
    """Render qualification guidance from the stack observer registry."""
    document = load_stack_observers(root)
    zygisk = document["zygisk_provider"]
    detach = document["observers"]["zygisk-detach"]
    lines = [
        "<!-- GENERATED from compatibility/stack-observers.json; do not hand-edit. -->",
        "# Integrity stack qualification",
        "",
        "OTAST treats the surrounding root/integrity stack as read-only qualification evidence, not as additional OTA-property authority.",
        "",
        "## Runtime preconditions",
        "",
        f"- Known module-based Zygisk providers: {', '.join(f'`{item}`' for item in zygisk['known_module_ids'])}.",
        "- Active and staged copies of the same module ID count as one provider transition; different effective provider IDs are a qualification conflict.",
        "- Zero visible module-based providers are reported `EXTERNAL_OR_BUILTIN_UNRESOLVED`, because Magisk built-in Zygisk cannot be disproved from module-tree absence.",
        "- Vector and Treat Wheel are observed only; neither becomes an OTAST writer.",
        f"- zygisk-detach is read from `{detach['config_path']}` without executing its CLI.",
        "- Protected BKI/Ash non-target trees remain outside runtime discovery and are bound only by host/physical qualification evidence.",
        "",
        "Qualification-critical detached packages:",
        "",
    ]
    lines.extend(f"- `{package}`" for package in detach["critical_packages"])
    lines.extend([
        "- the configured Play Integrity test package, when `OTAST_PI_TEST_PACKAGE` is set.",
        "",
        "## Physical Pixel qualification sequence",
        "",
        "1. Bind the exact OTAST source commit, deterministic ZIP SHA-256 and runtime digest.",
        "2. Bind the exact device/build/authority digest and runtime page size.",
        "3. Record the selected PIF provider, version/source and effective profile digest.",
        "4. Record TrickyStore version/source and the OTAST-owned security-patch policy digest.",
        "5. Record the actual Zygisk provider/version/source; unresolved built-in/external state is not release proof.",
        "6. Record Vector, BKI and concealment-module state/version evidence without mutating them.",
        "7. Record zygisk-detach version/config digest and confirm no qualification-critical package is detached.",
        "8. Run OTAST Preflight/Apply/Verify across the required reboot boundaries and confirm provider/ownership health.",
        "9. Perform one fresh Play Integrity evaluation and separately check Play Store Play Protect certification.",
        "10. Record Wallet and banking/app root-detection results separately when tested; they are not substitutes for Play Integrity or certification.",
        "11. Exercise Restore and repeat Apply/Verify where the release lifecycle requires repeatability proof.",
        "",
        "Fork v18 remains a supported candidate until this exact-stack physical evidence exists for Pixel 9a (`tegu`); repository support alone does not make it preferred.",
    ])
    return "\n".join(lines).rstrip() + "\n"
