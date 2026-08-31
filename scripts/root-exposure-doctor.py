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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
SUSPICIOUS_MOUNT_MARKERS = (
    "/data/adb",
    "/debug_ramdisk",
    "/sbin/.magisk",
    "magisk",
    "overlay",
    "zygisk",
    "lsposed",
    "modules",
)
MAX_PIDS = 8
MAX_MAP_LINES = 50_000
MAX_MOUNT_LINES = 25_000
MAX_EVIDENCE_ITEMS = 160
MAX_COMMAND_OUTPUT = 2_000_000


class DoctorError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


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
        raise DoctorError(f"command timed out after {timeout}s: {argv[0]}") from exc
    stdout = completed.stdout[:max_output]
    stderr = completed.stderr[:max_output]
    return CommandResult(completed.returncode, stdout, stderr)


def root_command(command: str, *, timeout: int = 8) -> CommandResult:
    if os.geteuid() == 0:
        return run_command(["sh", "-c", command], timeout=timeout)
    return run_command(["su", "-c", command], timeout=timeout)


def safe_root_read(path: str, *, max_bytes: int = MAX_COMMAND_OUTPUT, timeout: int = 8) -> str:
    if any(marker in path for marker in SENSITIVE_PATH_MARKERS):
        raise DoctorError(f"refusing sensitive path: {path}")
    quoted = shlex.quote(path)
    result = root_command(f"cat -- {quoted}", timeout=timeout)
    if result.returncode != 0:
        raise DoctorError(f"cannot read {path}: status={result.returncode}")
    return result.stdout[:max_bytes]


def safe_root_readlink(path: str) -> str:
    quoted = shlex.quote(path)
    result = root_command(f"readlink -- {quoted}", timeout=5)
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


def parse_mountinfo(raw: str, package: str) -> tuple[int, list[str]]:
    selected: list[str] = []
    lines = raw.splitlines()[:MAX_MOUNT_LINES]
    for line in lines:
        lowered = line.lower()
        if not any(marker in lowered for marker in SUSPICIOUS_MOUNT_MARKERS):
            continue
        selected.append(sanitize_text(line, package)[:4096])
        if len(selected) >= MAX_EVIDENCE_ITEMS:
            break
    return len(lines), selected


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
        timeout=5,
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


def resolve_pids(package: str, explicit_pid: int | None) -> list[int]:
    if explicit_pid is not None:
        return [explicit_pid]
    if not PACKAGE_RE.fullmatch(package):
        raise DoctorError("package name has unsafe or invalid syntax")
    result = root_command(f"pidof {shlex.quote(package)}", timeout=5)
    if result.returncode != 0 or not result.stdout.strip():
        raise DoctorError(f"target package is not running: {package}")
    pids: list[int] = []
    for token in result.stdout.split():
        if PID_RE.fullmatch(token):
            pids.append(int(token))
        if len(pids) >= MAX_PIDS:
            break
    if not pids:
        raise DoctorError(f"pidof returned no usable PID for {package}")
    return sorted(set(pids))


def collect_module_metadata(module_ids: Iterable[str]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for module_id in sorted(set(module_ids))[:64]:
        if not MODULE_ID_RE.fullmatch(module_id):
            continue
        base = f"/data/adb/modules/{module_id}"
        try:
            raw = safe_root_read(f"{base}/module.prop", max_bytes=32_768, timeout=5)
        except DoctorError:
            raw = ""
        item: dict[str, object] = {"directory_id": module_id, "module": parse_module_prop(raw)}
        sepolicy = hash_root_file(f"{base}/sepolicy.rule")
        if sepolicy is not None:
            item["sepolicy_rule"] = sepolicy
        output.append(item)
    return output


def collect_selinux(pids: list[int]) -> dict[str, object]:
    result: dict[str, object] = {}
    enforcing = root_command("getenforce", timeout=5)
    result["mode"] = enforcing.stdout.strip()[:64] if enforcing.returncode == 0 else "UNAVAILABLE"
    contexts: dict[str, str] = {}
    for pid in pids:
        try:
            contexts[str(pid)] = safe_root_read(f"/proc/{pid}/attr/current", max_bytes=4096, timeout=5).strip()
        except DoctorError:
            contexts[str(pid)] = "UNAVAILABLE"
    result["process_contexts"] = contexts
    context = root_command("ls -Zd /data/adb/modules 2>/dev/null", timeout=5)
    result["modules_path_context"] = context.stdout.strip()[:1024] if context.returncode == 0 else "UNAVAILABLE"

    sesearch = root_command("command -v sesearch", timeout=5)
    if sesearch.returncode == 0 and sesearch.stdout.strip() and contexts:
        first_context = next((value for value in contexts.values() if value not in {"", "UNAVAILABLE"}), "")
        domain = first_context.split(":")[2] if first_context.count(":") >= 2 else ""
        if re.fullmatch(r"[A-Za-z0-9_]+", domain):
            query = root_command(
                "sesearch -A "
                f"-s {shlex.quote(domain)} -p read -p open -p execute -p map "
                "/sys/fs/selinux/policy 2>/dev/null | head -n 100",
                timeout=8,
            )
            result["sesearch"] = {
                "domain": domain,
                "returncode": query.returncode,
                "lines": [line[:2048] for line in query.stdout.splitlines()[:100]],
            }
        else:
            result["sesearch"] = {"status": "SKIPPED_UNPARSEABLE_DOMAIN"}
    else:
        result["sesearch"] = {"status": "UNAVAILABLE"}
    return result


def collect_otast_report() -> dict[str, object]:
    exists = root_command(
        "test -f /data/adb/modules/otast/runtime/entry.sh && "
        "test ! -L /data/adb/modules/otast/runtime/entry.sh",
        timeout=5,
    )
    if exists.returncode != 0:
        return {"status": "ABSENT"}
    report = root_command("sh /data/adb/modules/otast/runtime/entry.sh report", timeout=15)
    safe_lines: list[str] = []
    for line in report.stdout.splitlines() + report.stderr.splitlines():
        lowered = line.lower()
        if "keybox" in lowered and ("content" in lowered or "private" in lowered):
            continue
        safe_lines.append(line[:4096])
        if len(safe_lines) >= 240:
            break
    return {"status": "PASS" if report.returncode == 0 else "FAIL", "returncode": report.returncode, "lines": safe_lines}


def classify_findings(
    processes: list[dict[str, object]],
    selinux: dict[str, object],
    otast_report: dict[str, object],
    detector_mount_claim: str,
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    mapped_modules: dict[str, int] = {}
    mapped_other: list[str] = []
    mount_evidence = 0

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
        mounts = process.get("selected_mountinfo", [])
        if isinstance(mounts, list):
            mount_evidence += len(mounts)

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

    if detector_mount_claim == "suspicious" and mount_evidence == 0:
        findings.append(
            {
                "category": "detector/report inconsistency",
                "finding": "detector mount headline claimed suspicious state but selected process mountinfo contained no corroborating root/module markers",
            }
        )
    elif detector_mount_claim == "clear" and mount_evidence > 0:
        findings.append(
            {
                "category": "detector/report inconsistency",
                "finding": "detector mount headline claimed clear state but detailed process mountinfo contains root/module markers",
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


def collect_process(pid: int, package: str) -> tuple[dict[str, object], set[str]]:
    maps = safe_root_read(f"/proc/{pid}/maps", max_bytes=MAX_COMMAND_OUTPUT, timeout=8)
    mountinfo = safe_root_read(f"/proc/{pid}/mountinfo", max_bytes=MAX_COMMAND_OUTPUT, timeout=8)
    map_count, mapped, module_ids = parse_maps(maps, package)
    mount_count, selected_mounts = parse_mountinfo(mountinfo, package)
    cmdline = "UNAVAILABLE"
    try:
        cmdline = sanitize_text(safe_root_read(f"/proc/{pid}/cmdline", max_bytes=8192, timeout=5).strip(), package)
    except DoctorError:
        pass
    return (
        {
            "pid": pid,
            "cmdline": cmdline,
            "mount_namespace": safe_root_readlink(f"/proc/{pid}/ns/mnt"),
            "maps_lines_examined": map_count,
            "executable_root_mappings": mapped,
            "mountinfo_lines_examined": mount_count,
            "selected_mountinfo": selected_mounts,
        },
        module_ids,
    )


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
        help="optional detector headline to compare with detailed mount evidence",
    )
    parser.add_argument("--output", help="optional JSON output path; stdout is always emitted")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    package = args.package or ""
    if args.pid is not None and args.pid <= 0:
        print("STOP: --pid must be positive", file=sys.stderr)
        return 2
    if package and not PACKAGE_RE.fullmatch(package):
        print("STOP: invalid package syntax", file=sys.stderr)
        return 2

    started = time.monotonic()
    try:
        pids = resolve_pids(package, args.pid)
        processes: list[dict[str, object]] = []
        module_ids: set[str] = set()
        warnings: list[str] = []
        for pid in pids:
            try:
                process, found_ids = collect_process(pid, package)
                processes.append(process)
                module_ids.update(found_ids)
            except DoctorError as exc:
                warnings.append(f"pid {pid}: {exc}")

        if not processes:
            raise DoctorError("no target process could be inspected")

        selinux = collect_selinux([int(process["pid"]) for process in processes])
        modules = collect_module_metadata(module_ids)
        otast_report = collect_otast_report()
        findings = classify_findings(processes, selinux, otast_report, args.detector_mount_claim)
        report = {
            "schema_version": 1,
            "result": "PASS",
            "collector": "root-exposure-doctor",
            "read_only": True,
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
            "modules": modules,
            "selinux": selinux,
            "otast_report": otast_report,
            "findings": findings,
            "warnings": warnings,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            output = Path(args.output).expanduser()
            if output.exists() and output.is_symlink():
                raise DoctorError(f"output path is a symlink: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            temp = output.with_name(output.name + f".tmp.{os.getpid()}")
            temp.write_text(encoded, encoding="utf-8")
            temp.chmod(0o600)
            temp.replace(output)
        sys.stdout.write(encoded)
        return 0
    except (DoctorError, OSError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
