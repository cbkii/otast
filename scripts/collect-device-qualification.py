#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.otastctl.qualification import classify_root_exposure_report  # noqa: E402

MAX_OUTPUT = 2_000_000
MODULE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PROP_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class CollectError(RuntimeError):
    pass


def run(argv: list[str], *, timeout: int = 10, max_output: int = MAX_OUTPUT) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CollectError(f"command timed out after {timeout}s: {' '.join(argv)}") from exc
    completed.stdout = completed.stdout[:max_output]
    completed.stderr = completed.stderr[:max_output]
    return completed


def root_read(path: str, *, timeout: int = 8, max_bytes: int = 512_000) -> str:
    if "\x00" in path or "\n" in path or "\r" in path:
        raise CollectError("unsafe root-read path")
    quoted = shlex.quote(path)
    command = f"test -f {quoted} && test ! -L {quoted} && head -c {max_bytes} {quoted}"
    result = run(["su", "-c", command], timeout=timeout, max_output=max_bytes)
    if result.returncode != 0:
        raise CollectError(f"cannot read required root file: {path}")
    return result.stdout[:max_bytes]


def root_command(command: str, *, timeout: int = 8, max_output: int = 256_000) -> str:
    result = run(["su", "-c", command], timeout=timeout, max_output=max_output)
    if result.returncode != 0:
        return ""
    return result.stdout[:max_output].strip()


def getprop(name: str) -> str:
    if not PROP_KEY_RE.fullmatch(name):
        raise CollectError(f"unsafe property name: {name}")
    result = run(["getprop", name], timeout=5, max_output=16_384)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CollectError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise CollectError(f"{label} must be a JSON object")
    return value


def parse_prop_text(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise CollectError("authority contains malformed line")
        key, value = line.split("=", 1)
        if not PROP_KEY_RE.fullmatch(key) or key in values:
            raise CollectError("authority contains invalid/duplicate key")
        values[key] = value
    return values


def module_prop(module_id: str) -> dict[str, str] | None:
    if not MODULE_ID_RE.fullmatch(module_id):
        raise CollectError(f"unsafe declared module ID: {module_id}")
    path = f"/data/adb/modules/{module_id}/module.prop"
    try:
        raw = root_read(path, max_bytes=32_768)
    except CollectError:
        return None
    keep = {"id", "name", "version", "versionCode", "author"}
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in keep:
            values[key] = value[:256]
    return values


def registry_reference(registry: dict[str, Any]) -> dict[str, Any]:
    support = registry.get("support_model")
    platforms = registry.get("platforms")
    if not isinstance(support, dict) or not isinstance(platforms, dict):
        raise CollectError("compatibility registry support model is incomplete")
    reference = support.get("release_reference")
    devices = support.get("devices")
    if not isinstance(reference, dict) or not isinstance(devices, dict):
        raise CollectError("compatibility release reference is incomplete")
    device = str(reference.get("device", ""))
    record = devices.get(device)
    profile_id = str(reference.get("platform_profile", ""))
    platform = platforms.get(profile_id)
    if not isinstance(record, dict) or not isinstance(platform, dict):
        raise CollectError("release-reference device/platform is undeclared")
    profile_path = platform.get("profile")
    if not isinstance(profile_path, str):
        raise CollectError("release-reference profile path is missing")
    profile = load_json(ROOT / profile_path, "platform profile")
    return {"reference": reference, "device_record": record, "profile": profile}


def declared_module_ids(registry: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    managed: dict[str, list[str]] = {}
    targets = registry.get("targets")
    if not isinstance(targets, dict):
        raise CollectError("compatibility registry has no managed targets")
    for target, record in sorted(targets.items()):
        if not isinstance(record, dict) or record.get("target_role") != "MANAGED":
            continue
        ids = [str(value) for value in record.get("module_ids", []) if isinstance(value, str)]
        if ids:
            managed[str(target)] = ids

    observed: dict[str, list[str]] = {}
    dependencies = registry.get("observed_dependencies")
    if isinstance(dependencies, dict):
        for name, record in sorted(dependencies.items()):
            if not isinstance(record, dict) or record.get("mode") != "READ_ONLY":
                continue
            ids = [str(value) for value in record.get("module_ids", []) if isinstance(value, str)]
            if ids:
                observed[str(name)] = ids
    return managed, observed


def first_installed(ids: list[str]) -> dict[str, object]:
    for module_id in ids:
        meta = module_prop(module_id)
        if meta is not None:
            return {"module_directory": module_id, "module": meta}
    return {"status": "ABSENT", "declared_module_ids": ids}


def ihi_summary(module_ids: list[str]) -> dict[str, object]:
    summary = first_installed(module_ids)
    selected = summary.get("module_directory")
    if not isinstance(selected, str):
        return summary
    path = f"/data/adb/modules/{selected}/config.txt"
    try:
        raw = root_read(path, max_bytes=64_000)
    except CollectError:
        summary["config"] = {"status": "UNAVAILABLE"}
        return summary
    lines = raw.splitlines()
    header = lines[0].split(":") if lines else []
    summary["config"] = {
        "status": "AVAILABLE",
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "enabled": bool(header and header[0] == "1"),
        "library": header[1] if len(header) > 1 else "",
        "method": header[2] if len(header) > 2 else "",
        "target_count": max(len(lines) - 1, 0),
    }
    return summary


def load_optional_report(path_text: str | None, label: str) -> dict[str, Any] | None:
    if not path_text:
        return None
    return load_json(Path(path_text).expanduser().resolve(), label)


def validate_native_evidence(value: dict[str, Any], *, page_size: str, sdk: str) -> list[str]:
    failures: list[str] = []
    if value.get("schema_version") != 1 or value.get("collector") != "runtime-compatibility-evidence" or value.get("read_only") is not True:
        return ["native/runtime evidence schema/read-only contract is invalid"]
    platform = value.get("platform")
    if not isinstance(platform, dict):
        return ["native/runtime evidence platform section is missing"]
    if str(platform.get("runtime_page_size", "")) != page_size:
        failures.append("native/runtime evidence page size disagrees with device capture")
    if str(platform.get("android_sdk", "")) != sdk:
        failures.append("native/runtime evidence SDK disagrees with device capture")
    modules = value.get("modules")
    if not isinstance(modules, list):
        failures.append("native/runtime evidence module inventory is missing")
    return failures


def collect(args: argparse.Namespace) -> dict[str, object]:
    registry = load_json(ROOT / "compatibility/supported-targets.json", "compatibility registry")
    ref = registry_reference(registry)
    reference = ref["reference"]
    profile = ref["profile"]

    authority_raw = root_read("/data/adb/ota.prop")
    authority = parse_prop_text(authority_raw)
    authority_sha = hashlib.sha256(authority_raw.encode("utf-8")).hexdigest()

    identity = {
        "codename": getprop("ro.product.device"),
        "model": getprop("ro.product.model"),
        "manufacturer": getprop("ro.product.manufacturer"),
        "build_id": getprop("ro.build.id"),
        "fingerprint": getprop("ro.build.fingerprint"),
        "platform_profile": reference.get("platform_profile"),
        "sdk": getprop("ro.build.version.sdk"),
        "sdk_full": getprop("ro.build.version.sdk_full"),
        "system_spl": getprop("ro.build.version.security_patch"),
        "vendor_spl": getprop("ro.vendor.build.security_patch"),
        "authority_sha256": authority_sha,
        "authority": {
            key: authority.get(key, "")
            for key in (
                "boot.img.sha256",
                "ro.boot.vbmeta.digest",
                "ro.boot.vbmeta.size",
                "ro.boot.vbmeta.avb_version",
                "ro.boot.avb_version",
            )
        },
        "kernel": root_command("uname -a", timeout=5, max_output=16_384) or run(["uname", "-a"], timeout=5).stdout.strip(),
        "runtime_page_size": root_command("getconf PAGE_SIZE", timeout=5, max_output=4096) or run(["getconf", "PAGE_SIZE"], timeout=5).stdout.strip(),
        "primary_abi": getprop("ro.product.cpu.abi"),
        "abi_list": getprop("ro.product.cpu.abilist"),
        "page_size_qualification_required": True,
    }

    expected = {
        "codename": reference.get("device"),
        "model": reference.get("model"),
        "manufacturer": profile.get("device_family", {}).get("manufacturer", "") if isinstance(profile.get("device_family"), dict) else "",
        "build_id": reference.get("build"),
        "platform_profile": reference.get("platform_profile"),
        "sdk": str(profile.get("sdk", "")),
    }
    failures: list[str] = []
    for key, wanted in expected.items():
        if str(identity.get(key, "")) != str(wanted):
            failures.append(f"{key}: expected {wanted!r}, observed {identity.get(key)!r}")
    for key in (
        "ro.product.device",
        "ro.product.model",
        "ro.product.manufacturer",
        "ro.build.id",
        "ro.build.fingerprint",
        "ro.build.version.sdk",
        "ro.build.version.security_patch",
        "ro.vendor.build.security_patch",
    ):
        live_key = {
            "ro.product.device": "codename",
            "ro.product.model": "model",
            "ro.product.manufacturer": "manufacturer",
            "ro.build.id": "build_id",
            "ro.build.fingerprint": "fingerprint",
            "ro.build.version.sdk": "sdk",
            "ro.build.version.security_patch": "system_spl",
            "ro.vendor.build.security_patch": "vendor_spl",
        }[key]
        if authority.get(key, "") != str(identity.get(live_key, "")):
            failures.append(f"authority/live mismatch: {key}")

    page_size = str(identity["runtime_page_size"])
    if not page_size.isdigit() or int(page_size) <= 0:
        failures.append("runtime page size is unavailable or invalid")

    managed_ids, observed_ids = declared_module_ids(registry)
    managed = {name: first_installed(ids) for name, ids in managed_ids.items()}
    observed: dict[str, object] = {}
    for name, ids in observed_ids.items():
        observed[name] = ihi_summary(ids) if name == "inline-hook-invalidate" else first_installed(ids)

    magisk = {
        "version": root_command("magisk -v", timeout=5, max_output=4096),
        "version_code": root_command("magisk -V", timeout=5, max_output=4096),
        "zygisk_enabled": root_command("magisk --sqlite 'SELECT value FROM settings WHERE key=\"zygisk\";' 2>/dev/null", timeout=5, max_output=4096),
    }

    root_doctor = load_optional_report(args.root_doctor_json, "root-exposure report")
    root_attribution = classify_root_exposure_report(root_doctor) if root_doctor is not None else {
        "result": "INCONCLUSIVE",
        "reason": "no root-exposure report supplied",
    }
    acceptance = load_optional_report(args.acceptance_json, "external acceptance evidence") or {
        "status": "NOT_SUPPLIED"
    }
    native_evidence = load_optional_report(args.runtime_evidence_json, "native/runtime compatibility evidence")
    if native_evidence is None:
        failures.append("native/runtime compatibility evidence was not supplied")
        native_evidence = {"status": "NOT_SUPPLIED"}
    else:
        failures.extend(validate_native_evidence(native_evidence, page_size=page_size, sdk=str(identity["sdk"])))

    return {
        "schema_version": 1,
        "result": "PASS" if not failures else "FAIL",
        "read_only": True,
        "device": identity,
        "magisk": magisk,
        "managed_targets": managed,
        "observed_dependencies": observed,
        "native_runtime_evidence": native_evidence,
        "root_exposure_attribution": root_attribution,
        "external_acceptance": acceptance,
        "validation_failures": failures,
        "privacy": {
            "keybox_material_exported": False,
            "arbitrary_module_enumeration": False,
            "mutation_performed": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only OTAST physical qualification evidence collector")
    parser.add_argument("--root-doctor-json", help="optional sanitized root-exposure-doctor JSON")
    parser.add_argument("--acceptance-json", help="optional sanitized external verdict/attestation JSON")
    parser.add_argument("--runtime-evidence-json", help="read-only native/runtime compatibility evidence JSON")
    parser.add_argument("--output", required=True, help="private JSON output path")
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if output.exists() and output.is_symlink():
        print(f"STOP: output is a symlink: {output}", file=sys.stderr)
        return 2
    try:
        report = collect(args)
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_name(output.name + f".tmp.{os.getpid()}")
        temp.write_text(encoded, encoding="utf-8")
        temp.chmod(0o600)
        temp.replace(output)
        sys.stdout.write(encoded)
        return 0 if report["result"] == "PASS" else 1
    except (CollectError, OSError, ValueError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
