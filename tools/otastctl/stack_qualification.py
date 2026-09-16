from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .pif_providers import load_pif_providers
from .qualification import load_qualification_registry
from .stack_observers import load_stack_observers
from .util import OtastError

STACK_BINDING_SCHEMA_VERSION = 1
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
COMPONENT_STATES = {"ABSENT", "PRESENT"}
ACCEPTANCE_STATES = {"PASS", "FAIL", "NOT_TESTED", "INCONCLUSIVE"}


def _required_string(record: dict[str, Any], key: str, label: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value or any(ch in value for ch in "\r\n\0"):
        raise OtastError(f"{label} {key} is missing or invalid")
    return value


def _required_sha(record: dict[str, Any], key: str, label: str) -> str:
    value = _required_string(record, key, label)
    if SHA64_RE.fullmatch(value) is None:
        raise OtastError(f"{label} {key} is not a SHA-256 digest")
    return value


def _validate_optional_component(record: object, label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise OtastError(f"{label} binding must be an object")
    state = record.get("state")
    if state not in COMPONENT_STATES:
        raise OtastError(f"{label} state is invalid")
    if state == "PRESENT":
        _required_string(record, "version", label)
        _required_string(record, "source", label)
        _required_sha(record, "module_prop_sha256", label)
    return record


def _validate_external_acceptance(record: object) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise OtastError("stack binding external_acceptance must be an object")
    required = {
        "play_integrity",
        "play_protect_certification",
        "wallet",
        "banking_or_app_root_detection",
    }
    if set(record) != required:
        raise OtastError("stack binding external_acceptance dimensions are incomplete or unexpected")
    for name in required:
        value = record[name]
        if not isinstance(value, dict) or value.get("status") not in ACCEPTANCE_STATES:
            raise OtastError(f"external acceptance status is invalid: {name}")
        if name == "play_integrity" and value.get("status") == "PASS":
            verdicts = value.get("verdicts")
            if not isinstance(verdicts, list) or not verdicts or not all(
                isinstance(item, str) and item for item in verdicts
            ):
                raise OtastError("PASS Play Integrity evidence requires explicit verdicts")
    return record


def validate_stack_binding(root: Path, binding: object) -> dict[str, object]:
    """Validate one exact-stack physical qualification binding."""
    if not isinstance(binding, dict):
        raise OtastError("stack_binding must be an object")
    if binding.get("schema_version") != STACK_BINDING_SCHEMA_VERSION:
        raise OtastError(f"stack binding schema must be {STACK_BINDING_SCHEMA_VERSION}")
    expected = {
        "schema_version",
        "pif_provider",
        "trickystore",
        "zygisk_provider",
        "vector",
        "bki",
        "concealment",
        "zygisk_detach",
        "page_size",
        "external_acceptance",
    }
    if set(binding) != expected:
        raise OtastError("stack binding fields are incomplete or unexpected")

    providers = load_pif_providers(root).get("providers")
    if not isinstance(providers, dict):
        raise OtastError("PIF provider registry is malformed while validating stack binding")
    pif = binding.get("pif_provider")
    if not isinstance(pif, dict):
        raise OtastError("stack binding PIF provider is missing")
    provider_id = _required_string(pif, "id", "PIF provider")
    if provider_id not in providers:
        raise OtastError(f"stack binding uses an unreviewed PIF provider: {provider_id}")
    _required_string(pif, "version", "PIF provider")
    _required_string(pif, "source", "PIF provider")
    _required_sha(pif, "profile_sha256", "PIF provider")

    tricky = binding.get("trickystore")
    if not isinstance(tricky, dict):
        raise OtastError("stack binding TrickyStore evidence is missing")
    _required_string(tricky, "version", "TrickyStore")
    _required_string(tricky, "source", "TrickyStore")
    _required_sha(tricky, "policy_sha256", "TrickyStore")

    zygisk = binding.get("zygisk_provider")
    if not isinstance(zygisk, dict):
        raise OtastError("stack binding Zygisk provider is missing")
    _required_string(zygisk, "id", "Zygisk provider")
    _required_string(zygisk, "version", "Zygisk provider")
    _required_string(zygisk, "source", "Zygisk provider")
    _required_sha(zygisk, "module_prop_sha256", "Zygisk provider")

    _validate_optional_component(binding.get("vector"), "Vector")
    _validate_optional_component(binding.get("bki"), "BKI")

    concealment = binding.get("concealment")
    if not isinstance(concealment, list):
        raise OtastError("stack binding concealment evidence must be a list")
    seen_ids: set[str] = set()
    for index, component in enumerate(concealment):
        if not isinstance(component, dict):
            raise OtastError(f"concealment component {index} is malformed")
        component_id = _required_string(component, "id", f"concealment component {index}")
        if component_id in seen_ids:
            raise OtastError(f"duplicate concealment component: {component_id}")
        seen_ids.add(component_id)
        _required_string(component, "version", f"concealment component {component_id}")
        _required_string(component, "source", f"concealment component {component_id}")
        _required_sha(component, "evidence_sha256", f"concealment component {component_id}")

    detach = binding.get("zygisk_detach")
    if not isinstance(detach, dict) or detach.get("state") not in COMPONENT_STATES:
        raise OtastError("stack binding zygisk-detach state is invalid")
    critical_targets = detach.get("critical_targets")
    if not isinstance(critical_targets, list) or not all(isinstance(item, str) and item for item in critical_targets):
        raise OtastError("stack binding zygisk-detach critical_targets is invalid")
    if critical_targets:
        raise OtastError("CURRENT qualification cannot bind detached qualification-critical packages")
    if detach["state"] == "PRESENT":
        _required_string(detach, "version", "zygisk-detach")
        _required_sha(detach, "config_sha256", "zygisk-detach")

    page_size = binding.get("page_size")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0:
        raise OtastError("stack binding page_size is invalid")
    _validate_external_acceptance(binding.get("external_acceptance"))

    observer_registry = load_stack_observers(root)
    critical = set(observer_registry["observers"]["zygisk-detach"]["critical_packages"])
    if critical.intersection(critical_targets):
        raise OtastError("stack binding detaches a registry-declared qualification-critical package")
    digest = stack_binding_digest(binding)
    return {
        "schema_version": STACK_BINDING_SCHEMA_VERSION,
        "pif_provider": provider_id,
        "page_size": page_size,
        "digest": digest,
    }


def stack_binding_digest(binding: object) -> str:
    """Return a deterministic digest used to detect material stack changes."""
    if not isinstance(binding, dict):
        raise OtastError("stack binding must be an object before digesting")
    encoded = json.dumps(binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stack_binding_reuse_decision(previous: object, current: object) -> dict[str, object]:
    """Decide whether physical stack evidence is byte-for-byte reusable."""
    previous_digest = stack_binding_digest(previous)
    current_digest = stack_binding_digest(current)
    return {
        "reusable": previous_digest == current_digest,
        "reason": "stack binding unchanged" if previous_digest == current_digest else "material stack binding changed",
        "previous_digest": previous_digest,
        "current_digest": current_digest,
    }


def validate_stack_bound_qualification(root: Path) -> dict[str, object]:
    """Require full stack evidence for every future CURRENT qualification record."""
    root = root.resolve()
    registry = load_qualification_registry(root)
    if registry.get("stack_binding_schema_version") != STACK_BINDING_SCHEMA_VERSION:
        raise OtastError(f"qualification registry stack binding schema must be {STACK_BINDING_SCHEMA_VERSION}")
    records = registry.get("records")
    if not isinstance(records, dict):
        raise OtastError("qualification records are malformed while validating stack bindings")
    bound = 0
    current = 0
    for record_id, record in records.items():
        if not isinstance(record, dict):
            raise OtastError(f"qualification record is malformed: {record_id}")
        binding = record.get("stack_binding")
        if record.get("current_state") == "CURRENT":
            current += 1
            if binding is None:
                raise OtastError(f"CURRENT qualification lacks full stack binding: {record_id}")
        if binding is not None:
            validate_stack_binding(root, binding)
            bound += 1
    return {
        "schema_version": STACK_BINDING_SCHEMA_VERSION,
        "records_with_stack_binding": bound,
        "current_records": current,
        "all_current_records_bound": bound >= current,
    }
