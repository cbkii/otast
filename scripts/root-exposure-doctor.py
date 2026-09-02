#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MIN_PYTHON = (3, 11)
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
PID_RE = re.compile(r"^[1-9][0-9]*$")
MODULE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SENSITIVE_PATH_MARKERS = (
    "/data/adb/tricky_store/keybox",
    "/data/adb/tricky_store/keybox.xml",
    "/data/adb/tricky_store/keybox2.xml",
    "/data/adb/tricky_store/keybox1.xml",
)
SUSPICIOUS_MAP_MARKERS = (
    "/data/adb/",
    "zygisk",
    "lsposed",
    "riru",
    "magisk",
    "rezygisk",
    "vector",
)
DIRECT_ROOT_MOUNT_TOKENS = (
    "/data/adb/",
    "/sbin/.magisk",
    "/.magisk/",
    "/debug_ramdisk",
    "magisk",
    "zygisk",
    "/modules/",
)
MAX_PIDS = 16
MAX_MAP_LINES = 50_000
MAX_MOUNT_LINES = 8_000
MAX_EVIDENCE_ITEMS = 240
MAX_COMMAND_OUTPUT = 2_000_000
MAX_POLICY_BYTES = 512_000
MAX_MODULES = 128

POLICY_EDGES = (
    {
        "id": "system_server_execmem",
        "source": "system_server",
        "target": "system_server",
        "class": "process",
        "permission": "execmem",
        "known_source": "Magisk core",
        "known_reason": "Magisk's built-in Zygisk policy permits system_server self execmem.",
    },
    {
        "id": "untrusted_app_magisk_binder_call",
        "source": "untrusted_app",
        "target": "magisk",
        "class": "binder",
        "permission": "call",
        "known_source": "Magisk core",
        "known_reason": "Magisk permits domain -> magisk binder call/transfer as part of its root IPC policy.",
    },
    {
        "id": "untrusted_app_xposed_data_read",
        "source": "untrusted_app",
        "target": "xposed_data",
        "class": "file",
        "permission": "read",
        "known_source": "Vector/LSPosed family",
        "known_reason": "Vector's reviewed sepolicy.rule grants wildcard access to xposed_data files/directories.",
    },
    {
        "id": "zygote_adb_data_file_search",
        "source": "zygote",
        "target": "adb_data_file",
        "class": "dir",
        "permission": "search",
        "known_source": "Zygisk-loader family",
        "known_reason": "This is a known Zygisk-loader policy shape; the active module file scan is authoritative for device attribution.",
    },
)


class DoctorError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    backend: str = "direct"


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_command(argv: list[str], *, timeout: int = 8, max_output: int = MAX_COMMAND_OUTPUT) -> CommandResult:
    try:
        completed = subprocess.run(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            124,
            _coerce_text(exc.stdout)[:max_output],
            _coerce_text(exc.stderr)[:max_output],
            timed_out=True,
            backend=Path(argv[0]).name if argv else "unknown",
        )
    return CommandResult(
        completed.returncode,
        completed.stdout[:max_output],
        completed.stderr[:max_output],
        timed_out=False,
        backend=Path(argv[0]).name if argv else "unknown",
    )


class RootRunner:
    def __init__(self) -> None:
        self.kind = "unavailable"
        self.binary = ""
        self.probes: list[dict[str, object]] = []
        self._discover()

    def _candidate_argv(self, kind: str, binary: str, command: str) -> list[str]:
        if kind == "direct":
            return ["sh", "-c", command]
        if kind == "sudo":
            return [binary, "sh", "-c", command]
        return [binary, "-c", command]

    def _discover(self) -> None:
        if os.geteuid() == 0:
            self.kind = "direct"
            self.binary = "sh"
            self.probes.append({"backend": "direct", "status": "READY"})
            return

        candidates: list[tuple[str, str]] = []
        sudo = shutil.which("sudo")
        su = shutil.which("su")
        if sudo:
            candidates.append(("sudo", sudo))
        if su:
            candidates.append(("su", su))

        for kind, binary in candidates:
            result = run_command(self._candidate_argv(kind, binary, "id -u"), timeout=8, max_output=4096)
            ready = result.returncode == 0 and result.stdout.strip() == "0"
            self.probes.append(
                {
                    "backend": kind,
                    "status": "READY" if ready else ("TIMEOUT" if result.timed_out else "UNAVAILABLE"),
                    "returncode": result.returncode,
                }
            )
            if ready:
                self.kind = kind
                self.binary = binary
                return

    @property
    def ready(self) -> bool:
        return self.kind != "unavailable"

    def run(self, command: str, *, timeout: int = 8, max_output: int = MAX_COMMAND_OUTPUT) -> CommandResult:
        if not self.ready:
            return CommandResult(126, "", "no working root backend", backend="unavailable")
        argv = self._candidate_argv(self.kind, self.binary, command)
        result = run_command(argv, timeout=timeout, max_output=max_output)
        return CommandResult(
            result.returncode,
            result.stdout,
            result.stderr,
            timed_out=result.timed_out,
            backend=self.kind,
        )


ROOT: RootRunner | None = None


def get_root_runner() -> RootRunner:
    global ROOT
    if ROOT is None:
        ROOT = RootRunner()
    return ROOT


def root_command(command: str, *, timeout: int = 8, max_output: int = MAX_COMMAND_OUTPUT) -> CommandResult:
    return get_root_runner().run(command, timeout=timeout, max_output=max_output)


def safe_root_read(path: str, *, max_bytes: int = MAX_COMMAND_OUTPUT, timeout: int = 8) -> str:
    if any(marker in path for marker in SENSITIVE_PATH_MARKERS):
        raise DoctorError(f"refusing sensitive path: {path}")
    quoted = shlex.quote(path)
    result = root_command(f"cat -- {quoted}", timeout=timeout, max_output=max_bytes)
    if result.timed_out:
        raise DoctorError(f"timed out reading {path} via {result.backend}")
    if result.returncode != 0:
        raise DoctorError(f"cannot read {path}: status={result.returncode}")
    return result.stdout[:max_bytes]


def safe_root_readlink(path: str) -> str:
    quoted = shlex.quote(path)
    result = root_command(f"readlink -- {quoted}", timeout=5, max_output=4096)
    if result.returncode != 0:
        return "UNAVAILABLE"
    return result.stdout.strip()[:512] or "UNAVAILABLE"


def sanitize_text(value: str, package: str) -> str:
    text = value.replace("\x00", " ")
    if package:
        text = text.replace(package, "<target-package>")
    text = re.sub(r"/data/user(?:_de)?/[0-9]+/[^/\s]+", "/data/user/<user>/<app>", text)
    text = re.sub(r"/storage/emulated/[0-9]+", "/storage/emulated/<user>", text)
    text = re.sub(r"/data/data/[^/\s]+", "/data/data/<app>", text)
    return text


def module_id_from_path(path: str) -> str | None:
    marker = "/data/adb/modules/"
    if marker not in path:
        return None
    tail = path.split(marker, 1)[1]
    module_id = tail.split("/", 1)[0]
    return module_id if MODULE_ID_RE.fullmatch(module_id) else None


def parse_maps(raw: str, package: str) -> tuple[int, list[dict[str, str]], set[str]]:
    evidence: list[dict[str, str]] = []
    module_ids: set[str] = set()
    lines = raw.splitlines()[:MAX_MAP_LINES]
    for line in lines:
        fields = line.split(None, 5)
        if len(fields) < 5:
            continue
        perms = fields[1]
        path = fields[5] if len(fields) == 6 else ""
        if "x" not in perms or not path:
            continue
        lowered = path.lower()
        if not any(marker in lowered for marker in SUSPICIOUS_MAP_MARKERS):
            continue
        module_id = module_id_from_path(path)
        if module_id:
            module_ids.add(module_id)
        evidence.append(
            {
                "perms": perms,
                "path": sanitize_text(path, package),
                "module_id": module_id or "",
            }
        )
        if len(evidence) >= MAX_EVIDENCE_ITEMS:
            break
    return len(lines), evidence, module_ids


def parse_mount_table(raw: str, package: str, source: str) -> tuple[int, list[str], list[dict[str, object]]]:
    lines = raw.splitlines()[:MAX_MOUNT_LINES]
    sanitized: list[str] = []
    matches: list[dict[str, object]] = []
    for index, line in enumerate(lines, 1):
        safe_line = sanitize_text(line, package)[:8192]
        sanitized.append(safe_line)
        lowered = line.lower()
        matched = sorted({token for token in DIRECT_ROOT_MOUNT_TOKENS if token in lowered})
        if matched and len(matches) < MAX_EVIDENCE_ITEMS:
            matches.append(
                {
                    "source": source,
                    "line_number": index,
                    "tokens": matched,
                    "line": safe_line,
                }
            )
    return len(lines), sanitized, matches


def parse_module_prop(raw: str) -> dict[str, str]:
    keep = {"id", "name", "version", "versionCode", "author"}
    result: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in keep:
            result[key] = value.strip()[:256]
    return result


def hash_root_file(path: str) -> dict[str, object] | None:
    quoted = shlex.quote(path)
    result = root_command(
        f"if [ -f {quoted} ] && [ ! -L {quoted} ]; then "
        f"wc -c < {quoted}; sha256sum {quoted}; else exit 3; fi",
        timeout=8,
        max_output=8192,
    )
    if result.returncode != 0:
        return None
    lines = result.stdout.splitlines()
    if len(lines) < 2:
        return None
    try:
        size = int(lines[0].strip())
    except ValueError:
        return None
    digest = lines[1].split()[0] if lines[1].split() else ""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    return {"size": size, "sha256": digest}


def resolve_pids(package: str, explicit_pid: int | None) -> tuple[list[int], list[str]]:
    if explicit_pid is not None:
        return [explicit_pid], []
    if not PACKAGE_RE.fullmatch(package):
        raise DoctorError("package name has unsafe or invalid syntax")

    pids: set[int] = set()
    warnings: list[str] = []
    pidof = root_command(f"pidof {shlex.quote(package)}", timeout=6, max_output=8192)
    if pidof.timed_out:
        warnings.append("pidof timed out; falling back to root ps enumeration")
    elif pidof.returncode == 0:
        for token in pidof.stdout.split():
            if PID_RE.fullmatch(token):
                pids.add(int(token))

    ps = root_command("ps -A -o PID,UID,NAME,ARGS 2>/dev/null || ps -A 2>/dev/null", timeout=8, max_output=1_000_000)
    if ps.timed_out:
        warnings.append("root ps enumeration timed out")
    elif ps.returncode == 0:
        for line in ps.stdout.splitlines():
            if package not in line:
                continue
            fields = line.split()
            for token in fields[:2]:
                if PID_RE.fullmatch(token):
                    pids.add(int(token))
                    break

    ordered = sorted(pids)[:MAX_PIDS]
    if not ordered:
        raise DoctorError(f"no usable PID found for running package {package}")
    if len(pids) > MAX_PIDS:
        warnings.append(f"target process list truncated to {MAX_PIDS} PIDs")
    return ordered, warnings


def _parse_policy_group(value: str) -> set[str]:
    cleaned = value.replace("{", " ").replace("}", " ").replace(";", " ")
    return {token for token in cleaned.split() if token}


def _group_matches(value: str, wanted: str) -> bool:
    values = _parse_policy_group(value)
    return "*" in values or wanted in values


def match_policy_line(line: str, edge: dict[str, str]) -> bool:
    statement = line.split("#", 1)[0].strip()
    if not statement.startswith("allow "):
        return False
    body = statement[6:].strip().rstrip(";")
    match = re.match(r"^(\{[^}]+\}|\S+)\s+(\{[^}]+\}|\S+)\s+(\{[^}]+\}|\S+)\s+(.+)$", body)
    if not match:
        return False
    src, tgt, cls, perms = match.groups()
    return (
        _group_matches(src, edge["source"])
        and _group_matches(tgt, edge["target"])
        and _group_matches(cls, edge["class"])
        and _group_matches(perms, edge["permission"])
    )


def enumerate_module_ids() -> tuple[list[str], list[str]]:
    command = (
        "for d in /data/adb/modules/*; do "
        "[ -d \"$d\" ] || continue; [ -L \"$d\" ] && continue; "
        "printf '%s\\n' \"${d##*/}\"; done"
    )
    result = root_command(command, timeout=8, max_output=64_000)
    warnings: list[str] = []
    if result.timed_out:
        return [], ["active Magisk module enumeration timed out"]
    if result.returncode != 0:
        return [], [f"active Magisk module enumeration failed: status={result.returncode}"]
    ids = [line.strip() for line in result.stdout.splitlines() if MODULE_ID_RE.fullmatch(line.strip())]
    if len(ids) > MAX_MODULES:
        warnings.append(f"module list truncated to {MAX_MODULES}")
    return sorted(set(ids))[:MAX_MODULES], warnings


def collect_module_metadata(module_ids: Iterable[str]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for module_id in sorted(set(module_ids))[:MAX_MODULES]:
        if not MODULE_ID_RE.fullmatch(module_id):
            continue
        base = f"/data/adb/modules/{module_id}"
        try:
            raw = safe_root_read(f"{base}/module.prop", max_bytes=32_768, timeout=5)
        except DoctorError:
            raw = ""
        state = root_command(
            f"for f in disable remove update; do [ -e {shlex.quote(base)}/$f ] && printf '%s\\n' $f; done",
            timeout=5,
            max_output=4096,
        )
        item: dict[str, object] = {
            "directory_id": module_id,
            "module": parse_module_prop(raw),
            "state_markers": state.stdout.split() if state.returncode == 0 else [],
        }
        sepolicy = hash_root_file(f"{base}/sepolicy.rule")
        if sepolicy is not None:
            item["sepolicy_rule"] = sepolicy
        output.append(item)
    return output


def collect_policy_attribution(module_ids: Iterable[str]) -> tuple[list[dict[str, object]], list[str]]:
    attribution: dict[str, dict[str, object]] = {}
    warnings: list[str] = []
    for edge in POLICY_EDGES:
        attribution[edge["id"]] = {
            "edge": {key: edge[key] for key in ("source", "target", "class", "permission")},
            "known_source": edge["known_source"],
            "known_reason": edge["known_reason"],
            "module_file_matches": [],
        }

    for module_id in sorted(set(module_ids))[:MAX_MODULES]:
        path = f"/data/adb/modules/{module_id}/sepolicy.rule"
        try:
            raw = safe_root_read(path, max_bytes=MAX_POLICY_BYTES, timeout=6)
        except DoctorError as exc:
            meta = hash_root_file(path)
            if meta is not None:
                warnings.append(f"{module_id}: sepolicy.rule metadata exists but content was unavailable: {exc}")
            continue
        for line_number, line in enumerate(raw.splitlines(), 1):
            for edge in POLICY_EDGES:
                if match_policy_line(line, edge):
                    cast = attribution[edge["id"]]["module_file_matches"]
                    assert isinstance(cast, list)
                    cast.append(
                        {
                            "module_id": module_id,
                            "path": path,
                            "line_number": line_number,
                            "line": line[:4096],
                        }
                    )

    return [attribution[edge["id"]] for edge in POLICY_EDGES], warnings


def _read_small_config(path: str, *, max_bytes: int = 64_000) -> dict[str, object]:
    try:
        raw = safe_root_read(path, max_bytes=max_bytes, timeout=5)
    except DoctorError as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)}
    return {"status": "AVAILABLE", "text": raw}


def collect_ihi_configuration(package: str) -> dict[str, object]:
    path = "/data/adb/modules/inline_hook_invalidate/config.txt"
    value = _read_small_config(path)
    if value.get("status") != "AVAILABLE":
        return {"status": value.get("status"), "path": path, "reason": value.get("reason", "")}
    raw = str(value.get("text", ""))
    lines = [line.rstrip("\r\n") for line in raw.splitlines()]
    header = lines[0].split(":") if lines else []
    targets = [line for line in lines[1:] if line]
    enabled = bool(header and header[0] == "1")
    library = header[1] if len(header) >= 2 and header[1] else "libart.so"
    method = header[2] if len(header) >= 3 and header[2] else "mmap"
    return {
        "status": "AVAILABLE",
        "path": path,
        "enabled": enabled,
        "library": library,
        "method": method,
        "target_count": len(targets),
        "target_package_present": package in targets,
        "target_package_process_matches": [target for target in targets if target == package or target.startswith(package + ":")],
    }


def collect_zygisk_next_configuration(package: str) -> dict[str, object]:
    base = "/data/adb/zygisksu"
    module = "/data/adb/modules/zygisksu"
    result: dict[str, object] = {"data_root": base, "module_root": module}
    for name in ("denylist_enforce", "memory_type", "linker"):
        item = _read_small_config(f"{base}/{name}", max_bytes=4096)
        if item.get("status") == "AVAILABLE":
            result[name] = str(item.get("text", "")).strip()[:128]
        else:
            result[name] = "UNAVAILABLE"

    try:
        prop = safe_root_read(f"{module}/module.prop", max_bytes=32_768, timeout=5)
        result["module"] = parse_module_prop(prop)
    except DoctorError as exc:
        result["module"] = {"status": "UNAVAILABLE", "reason": str(exc)}

    denylist = root_command("magisk --denylist ls 2>/dev/null", timeout=10, max_output=500_000)
    if denylist.timed_out:
        result["magisk_denylist"] = {"status": "TIMEOUT"}
    elif denylist.returncode == 0:
        matches = [line for line in denylist.stdout.splitlines() if package in line]
        result["magisk_denylist"] = {"status": "AVAILABLE", "target_matches": matches[:128]}
    else:
        result["magisk_denylist"] = {"status": "UNAVAILABLE", "returncode": denylist.returncode}

    zygiskd = f"{module}/bin/zygiskd"
    help_result = root_command(f"{shlex.quote(zygiskd)} --help 2>&1", timeout=6, max_output=64_000)
    result["zygiskd_help"] = {
        "status": "TIMEOUT" if help_result.timed_out else ("AVAILABLE" if help_result.returncode == 0 else "UNAVAILABLE"),
        "returncode": help_result.returncode,
        "lines": help_result.stdout.splitlines()[:120] if help_result.stdout else help_result.stderr.splitlines()[:120],
    }
    return result


def collect_selinux(pids: list[int], module_ids: list[str]) -> tuple[dict[str, object], list[str]]:
    warnings: list[str] = []
    result: dict[str, object] = {}
    enforcing = root_command("getenforce", timeout=5, max_output=4096)
    result["mode"] = enforcing.stdout.strip()[:64] if enforcing.returncode == 0 else "UNAVAILABLE"
    contexts: dict[str, str] = {}
    for pid in pids:
        try:
            contexts[str(pid)] = safe_root_read(f"/proc/{pid}/attr/current", max_bytes=4096, timeout=5).strip()
        except DoctorError as exc:
            contexts[str(pid)] = "UNAVAILABLE"
            warnings.append(f"pid {pid}: SELinux context unavailable: {exc}")
    result["process_contexts"] = contexts
    context = root_command("ls -Zd /data/adb/modules 2>/dev/null", timeout=5, max_output=4096)
    result["modules_path_context"] = context.stdout.strip()[:1024] if context.returncode == 0 else "UNAVAILABLE"

    attributions, attribution_warnings = collect_policy_attribution(module_ids)
    result["policy_edge_attribution"] = attributions
    warnings.extend(attribution_warnings)

    sesearch = root_command("command -v sesearch", timeout=5, max_output=4096)
    if sesearch.returncode == 0 and sesearch.stdout.strip() and contexts:
        first_context = next((value for value in contexts.values() if value not in {"", "UNAVAILABLE"}), "")
        domain = first_context.split(":")[2] if first_context.count(":") >= 2 else ""
        if re.fullmatch(r"[A-Za-z0-9_]+", domain):
            query = root_command(
                "sesearch -A "
                f"-s {shlex.quote(domain)} -p read -p open -p execute -p map "
                "/sys/fs/selinux/policy 2>/dev/null | head -n 100",
                timeout=8,
                max_output=256_000,
            )
            result["sesearch"] = {
                "domain": domain,
                "returncode": query.returncode,
                "timed_out": query.timed_out,
                "lines": [line[:2048] for line in query.stdout.splitlines()[:100]],
            }
        else:
            result["sesearch"] = {"status": "SKIPPED_UNPARSEABLE_DOMAIN"}
    else:
        result["sesearch"] = {"status": "UNAVAILABLE"}
    return result, warnings


def collect_otast_report() -> dict[str, object]:
    exists = root_command(
        "test -f /data/adb/modules/otast/runtime/entry.sh && "
        "test ! -L /data/adb/modules/otast/runtime/entry.sh",
        timeout=5,
        max_output=4096,
    )
    if exists.timed_out:
        return {"status": "TIMEOUT", "stage": "presence-check"}
    if exists.returncode != 0:
        return {"status": "ABSENT"}
    report = root_command("sh /data/adb/modules/otast/runtime/entry.sh report", timeout=30, max_output=1_000_000)
    safe_lines: list[str] = []
    for line in report.stdout.splitlines() + report.stderr.splitlines():
        lowered = line.lower()
        if "keybox" in lowered and ("content" in lowered or "private" in lowered):
            continue
        safe_lines.append(line[:4096])
        if len(safe_lines) >= 320:
            break
    if report.timed_out:
        return {"status": "TIMEOUT", "returncode": report.returncode, "lines": safe_lines}
    return {"status": "PASS" if report.returncode == 0 else "FAIL", "returncode": report.returncode, "lines": safe_lines}


def collect_namespace_baseline(package: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for label, path in (("init", "/proc/1/mountinfo"), ("root_shell", "/proc/self/mountinfo")):
        try:
            raw = safe_root_read(path, max_bytes=1_000_000, timeout=8)
            count, lines, matches = parse_mount_table(raw, package, f"{label}_mountinfo")
            result[label] = {"status": "AVAILABLE", "line_count": count, "lines": lines, "token_matches": matches}
        except DoctorError as exc:
            result[label] = {"status": "UNAVAILABLE", "reason": str(exc)}
    return result


def classify_findings(
    processes: list[dict[str, object]],
    selinux: dict[str, object],
    otast_report: dict[str, object],
    detector_mount_claim: str,
    ihi: dict[str, object],
    zygisk_next: dict[str, object],
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    mapped_modules: dict[str, int] = {}
    mapped_other: list[str] = []
    mount_evidence = 0
    ihi_mapped = False
    zn_mapped = False

    for process in processes:
        for mapping in process.get("executable_root_mappings", []):
            if not isinstance(mapping, dict):
                continue
            module_id = str(mapping.get("module_id") or "")
            path = str(mapping.get("path") or "")
            if module_id:
                mapped_modules[module_id] = mapped_modules.get(module_id, 0) + 1
            elif path:
                mapped_other.append(path)
            if "inline_hook_invalidate" in path:
                ihi_mapped = True
            if "/zygisksu/" in path or path.endswith("/libzygisk.so"):
                zn_mapped = True
        for key in ("mount_token_matches", "mountinfo_token_matches"):
            entries = process.get(key, [])
            if isinstance(entries, list):
                mount_evidence += len(entries)

    for module_id, count in sorted(mapped_modules.items()):
        category = "OTAST-owned semantic inconsistency" if module_id == "otast" else "another reviewed module's exposure"
        findings.append(
            {
                "category": category,
                "finding": "executable mapping from Magisk module directory",
                "module_id": module_id,
                "count": count,
            }
        )

    if mapped_other:
        findings.append(
            {
                "category": "another reviewed module's exposure",
                "finding": "executable root/Zygisk mapping outside a directly attributable module directory",
                "count": len(mapped_other),
                "examples": mapped_other[:12],
            }
        )

    if ihi_mapped:
        findings.append(
            {
                "category": "another reviewed module's exposure",
                "finding": "Inline Hook Invalidate library remains mapped in target process",
                "target_configured": bool(ihi.get("target_package_present")),
                "interpretation": (
                    "IHI target selection controls its post-specialize remap work; it does not by itself prove the Zygisk module library is unloaded from non-target processes."
                ),
            }
        )

    if zn_mapped:
        findings.append(
            {
                "category": "another reviewed module's exposure",
                "finding": "Zygisk Next loader remains mapped in target process",
                "denylist_enforce": zygisk_next.get("denylist_enforce", "UNAVAILABLE"),
                "interpretation": (
                    "Observed process exposure is compatible with an unmount-only denylist policy; a full no-injection mode must be proven from the installed zygiskd interface before changing it."
                ),
            }
        )

    if selinux.get("mode") not in {"Enforcing", "UNAVAILABLE"}:
        findings.append(
            {
                "category": "unknown/needs investigation",
                "finding": "SELinux mode is not Enforcing",
                "observed": selinux.get("mode"),
            }
        )

    if otast_report.get("status") == "FAIL":
        findings.append(
            {
                "category": "OTAST-owned semantic inconsistency",
                "finding": "OTAST read-only Report returned non-zero",
                "returncode": otast_report.get("returncode"),
            }
        )
    elif otast_report.get("status") == "TIMEOUT":
        findings.append(
            {
                "category": "diagnostic coverage limitation",
                "finding": "OTAST read-only Report timed out but the doctor continued",
            }
        )

    if detector_mount_claim == "suspicious" and mount_evidence == 0:
        findings.append(
            {
                "category": "detector/report inconsistency",
                "finding": "detector mount headline claimed suspicious state but exact target-process mount snapshots contained no configured direct root tokens",
            }
        )
    elif detector_mount_claim == "clear" and mount_evidence > 0:
        findings.append(
            {
                "category": "detector/report inconsistency",
                "finding": "detector mount headline claimed clear state but exact target-process mount snapshots contain direct root tokens",
                "selected_mount_entries": mount_evidence,
            }
        )

    if not findings:
        findings.append(
            {
                "category": "unknown/needs investigation",
                "finding": "no directly attributable exposure was observed in the bounded evidence set",
            }
        )
    return findings


def collect_process(pid: int, package: str) -> tuple[dict[str, object], set[str], list[str]]:
    warnings: list[str] = []
    module_ids: set[str] = set()
    process: dict[str, object] = {
        "pid": pid,
        "mount_namespace": safe_root_readlink(f"/proc/{pid}/ns/mnt"),
    }

    try:
        maps = safe_root_read(f"/proc/{pid}/maps", max_bytes=MAX_COMMAND_OUTPUT, timeout=10)
        map_count, mapped, found_ids = parse_maps(maps, package)
        module_ids.update(found_ids)
        process["maps_status"] = "AVAILABLE"
        process["maps_lines_examined"] = map_count
        process["executable_root_mappings"] = mapped
    except DoctorError as exc:
        process["maps_status"] = "UNAVAILABLE"
        process["maps_lines_examined"] = 0
        process["executable_root_mappings"] = []
        warnings.append(f"pid {pid}: maps unavailable: {exc}")

    try:
        mounts = safe_root_read(f"/proc/{pid}/mounts", max_bytes=1_000_000, timeout=10)
        count, lines, matches = parse_mount_table(mounts, package, "mounts")
        process["mounts_status"] = "AVAILABLE"
        process["mounts_lines_examined"] = count
        process["mounts"] = lines
        process["mount_token_matches"] = matches
    except DoctorError as exc:
        process["mounts_status"] = "UNAVAILABLE"
        process["mounts_lines_examined"] = 0
        process["mounts"] = []
        process["mount_token_matches"] = []
        warnings.append(f"pid {pid}: mounts unavailable: {exc}")

    try:
        mountinfo = safe_root_read(f"/proc/{pid}/mountinfo", max_bytes=1_000_000, timeout=10)
        count, lines, matches = parse_mount_table(mountinfo, package, "mountinfo")
        process["mountinfo_status"] = "AVAILABLE"
        process["mountinfo_lines_examined"] = count
        process["mountinfo"] = lines
        process["mountinfo_token_matches"] = matches
    except DoctorError as exc:
        process["mountinfo_status"] = "UNAVAILABLE"
        process["mountinfo_lines_examined"] = 0
        process["mountinfo"] = []
        process["mountinfo_token_matches"] = []
        warnings.append(f"pid {pid}: mountinfo unavailable: {exc}")

    try:
        process["cmdline"] = sanitize_text(
            safe_root_read(f"/proc/{pid}/cmdline", max_bytes=8192, timeout=5).strip(), package
        )
    except DoctorError:
        process["cmdline"] = "UNAVAILABLE"

    return process, module_ids, warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded, read-only OTAST root-exposure doctor for one running Android app"
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--package", help="running Android package to inspect")
    target.add_argument("--pid", type=int, help="explicit positive process ID")
    parser.add_argument(
        "--detector-mount-claim",
        choices=("unknown", "suspicious", "clear"),
        default="unknown",
        help="optional detector headline to compare with exact mount evidence",
    )
    parser.add_argument("--output", help="optional JSON output path; stdout is always emitted")
    return parser


def _write_report(encoded: str, output_arg: str | None) -> None:
    if not output_arg:
        return
    output = Path(output_arg).expanduser()
    if output.exists() and output.is_symlink():
        raise DoctorError(f"output path is a symlink: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + f".tmp.{os.getpid()}")
    temp.write_text(encoded, encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(output)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"STOP: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required", file=sys.stderr)
        return 2

    args = build_parser().parse_args(argv)
    package = args.package or ""
    if args.pid is not None and args.pid <= 0:
        print("STOP: --pid must be positive", file=sys.stderr)
        return 2
    if package and not PACKAGE_RE.fullmatch(package):
        print("STOP: invalid package syntax", file=sys.stderr)
        return 2

    started = time.monotonic()
    warnings: list[str] = []
    processes: list[dict[str, object]] = []
    mapped_module_ids: set[str] = set()
    fatal_reason = ""

    root = get_root_runner()
    if not root.ready:
        fatal_reason = "no working root backend (tried Binder-safe sudo first when present, then su)"
    else:
        try:
            pids, pid_warnings = resolve_pids(package, args.pid)
            warnings.extend(pid_warnings)
            for pid in pids:
                process, found_ids, process_warnings = collect_process(pid, package)
                processes.append(process)
                mapped_module_ids.update(found_ids)
                warnings.extend(process_warnings)
        except DoctorError as exc:
            fatal_reason = str(exc)

    module_ids, module_warnings = enumerate_module_ids() if root.ready else ([], [])
    warnings.extend(module_warnings)
    all_module_ids = sorted(set(module_ids) | mapped_module_ids)
    modules = collect_module_metadata(all_module_ids) if root.ready else []

    selinux: dict[str, object] = {"mode": "UNAVAILABLE", "policy_edge_attribution": []}
    if root.ready:
        selinux, selinux_warnings = collect_selinux(
            [int(process["pid"]) for process in processes], all_module_ids
        )
        warnings.extend(selinux_warnings)

    otast_report = collect_otast_report() if root.ready else {"status": "UNAVAILABLE"}
    namespace_baseline = collect_namespace_baseline(package) if root.ready else {}
    ihi = collect_ihi_configuration(package) if root.ready and package else {"status": "SKIPPED"}
    zygisk_next = collect_zygisk_next_configuration(package) if root.ready and package else {"status": "SKIPPED"}

    findings = classify_findings(
        processes,
        selinux,
        otast_report,
        args.detector_mount_claim,
        ihi,
        zygisk_next,
    ) if processes else []

    result = "PASS"
    if fatal_reason or not processes:
        result = "PARTIAL"
    elif warnings or otast_report.get("status") in {"TIMEOUT", "FAIL"}:
        result = "PASS_WITH_WARNINGS"

    report = {
        "schema_version": 2,
        "result": result,
        "collector": "root-exposure-doctor",
        "read_only": True,
        "root_backend": {
            "selected": root.kind,
            "probes": root.probes,
        },
        "target": {
            "package": package or "<explicit-pid>",
            "pids": [process["pid"] for process in processes],
        },
        "bounds": {
            "max_pids": MAX_PIDS,
            "max_map_lines_per_pid": MAX_MAP_LINES,
            "max_mount_lines_per_pid": MAX_MOUNT_LINES,
            "max_evidence_items_per_section": MAX_EVIDENCE_ITEMS,
        },
        "processes": processes,
        "namespace_baseline": namespace_baseline,
        "modules": modules,
        "selinux": selinux,
        "inline_hook_invalidate": ihi,
        "zygisk_next": zygisk_next,
        "otast_report": otast_report,
        "findings": findings,
        "warnings": warnings,
        "fatal_reason": fatal_reason,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    try:
        _write_report(encoded, args.output)
    except (DoctorError, OSError) as exc:
        print(f"STOP: cannot write diagnostic output: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(encoded)
    return 0 if result != "PARTIAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
