#!/usr/bin/env python3
"""Collect bounded, read-only native/runtime compatibility evidence for OTAST.

The collector reads only dependency module IDs explicitly declared by the OTAST
compatibility registry. It never changes module configuration, denylist state,
properties, SELinux policy, or target applications.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 2_000_000
MAX_MODULES = 32
MAX_NATIVE_LIBS = 128
MAX_ELF_PREFIX = 262_144
MAX_MODULE_PROP = 32_768
MODULE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class EvidenceError(RuntimeError):
    pass


def _valid_module_id(value: object) -> bool:
    return isinstance(value, str) and value not in {".", ".."} and MODULE_ID_RE.fullmatch(value) is not None


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    backend: str = "direct"


def run_bytes(argv: list[str], *, timeout: int = 10, max_output: int = MAX_OUTPUT) -> CommandResult:
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            124,
            (exc.stdout or b"")[:max_output],
            (exc.stderr or b"")[:max_output],
            timed_out=True,
            backend=Path(argv[0]).name if argv else "unknown",
        )
    return CommandResult(
        completed.returncode,
        completed.stdout[:max_output],
        completed.stderr[:max_output],
        backend=Path(argv[0]).name if argv else "unknown",
    )


class RootRunner:
    def __init__(self) -> None:
        self.kind = "unavailable"
        self.binary = ""
        self.probes: list[dict[str, object]] = []
        self._discover()

    def _argv(self, kind: str, binary: str, command: str) -> list[str]:
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
            result = run_bytes(self._argv(kind, binary, "id -u"), timeout=8, max_output=4096)
            ready = result.returncode == 0 and result.stdout.strip() == b"0"
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

    def run(self, command: str, *, timeout: int = 10, max_output: int = MAX_OUTPUT) -> CommandResult:
        if not self.ready:
            return CommandResult(126, b"", b"no working root backend", backend="unavailable")
        result = run_bytes(self._argv(self.kind, self.binary, command), timeout=timeout, max_output=max_output)
        return CommandResult(
            result.returncode,
            result.stdout,
            result.stderr,
            timed_out=result.timed_out,
            backend=self.kind,
        )


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_registry(root: Path) -> dict[str, object]:
    path = root / "compatibility/supported-targets.json"
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"compatibility registry is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read compatibility registry: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError("compatibility registry must be an object")
    return value


def _module_id_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise EvidenceError(f"{label} must be a list")
    result: list[str] = []
    for module_id in value:
        if not _valid_module_id(module_id):
            raise EvidenceError(f"unsafe {label} module ID: {module_id!r}")
        result.append(module_id)
    return result


def explicit_native_module_ids(registry: dict[str, object]) -> list[str]:
    result: set[str] = set()
    dependencies = registry.get("observed_dependencies")
    targets = registry.get("targets")
    if not isinstance(dependencies, dict) or not isinstance(targets, dict):
        raise EvidenceError("compatibility registry has no observed dependency/target contract")
    for dep_id, raw_record in dependencies.items():
        if not isinstance(raw_record, dict) or raw_record.get("mode") != "READ_ONLY":
            raise EvidenceError(f"observed dependency is not read-only: {dep_id}")
        for module_id in _module_id_list(raw_record.get("module_ids", []), f"observed dependency {dep_id}"):
            result.add(module_id)
        managed_target = raw_record.get("managed_target")
        if managed_target is not None:
            target = targets.get(managed_target)
            if not isinstance(target, dict):
                raise EvidenceError(f"observed dependency references unknown target: {dep_id}")
            for module_id in _module_id_list(target.get("module_ids"), f"managed target {managed_target}"):
                result.add(module_id)
    if len(result) > MAX_MODULES:
        raise EvidenceError(
            f"declared native module inventory exceeds bounded maximum ({len(result)} > {MAX_MODULES})"
        )
    return sorted(result)


def parse_module_prop(raw: bytes) -> dict[str, str]:
    keep = {"id", "name", "version", "versionCode", "author"}
    result: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in keep:
            result[key] = value.strip()[:256]
    return result


def parse_elf_load_alignments(raw: bytes) -> dict[str, object]:
    if len(raw) < 64 or raw[:4] != b"\x7fELF":
        return {"status": "NOT_ELF"}
    elf_class = raw[4]
    data_encoding = raw[5]
    if data_encoding not in (1, 2):
        return {"status": "UNSUPPORTED_ENCODING"}
    endian = "<" if data_encoding == 1 else ">"
    try:
        if elf_class == 2:
            e_phoff = struct.unpack_from(endian + "Q", raw, 32)[0]
            e_phentsize = struct.unpack_from(endian + "H", raw, 54)[0]
            e_phnum = struct.unpack_from(endian + "H", raw, 56)[0]
            minimum = 56
            align_offset = 48
        elif elf_class == 1:
            if len(raw) < 52:
                return {"status": "TRUNCATED"}
            e_phoff = struct.unpack_from(endian + "I", raw, 28)[0]
            e_phentsize = struct.unpack_from(endian + "H", raw, 42)[0]
            e_phnum = struct.unpack_from(endian + "H", raw, 44)[0]
            minimum = 32
            align_offset = 28
        else:
            return {"status": "UNSUPPORTED_CLASS"}
    except struct.error:
        return {"status": "TRUNCATED"}
    if e_phentsize < minimum or e_phnum > 4096:
        return {"status": "INVALID_PROGRAM_HEADERS"}
    required = e_phoff + e_phentsize * e_phnum
    if required > len(raw):
        return {"status": "TRUNCATED_PROGRAM_HEADERS", "required_prefix_bytes": required}
    alignments: list[int] = []
    for index in range(e_phnum):
        offset = e_phoff + index * e_phentsize
        try:
            p_type = struct.unpack_from(endian + "I", raw, offset)[0]
            if p_type != 1:
                continue
            if elf_class == 2:
                p_align = struct.unpack_from(endian + "Q", raw, offset + align_offset)[0]
            else:
                p_align = struct.unpack_from(endian + "I", raw, offset + align_offset)[0]
        except struct.error:
            return {"status": "TRUNCATED_PROGRAM_HEADERS"}
        if p_align:
            alignments.append(int(p_align))
    return {
        "status": "OK",
        "elf_class": 64 if elf_class == 2 else 32,
        "endianness": "little" if data_encoding == 1 else "big",
        "load_alignments": sorted(set(alignments)),
    }


def _root_text(runner: RootRunner, command: str, *, timeout: int = 8, max_output: int = 64_000) -> str:
    result = runner.run(command, timeout=timeout, max_output=max_output)
    if result.returncode != 0 or result.timed_out:
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def collect_platform(runner: RootRunner) -> dict[str, object]:
    page_text = _root_text(runner, "getconf PAGE_SIZE 2>/dev/null || getconf PAGESIZE 2>/dev/null", max_output=4096)
    try:
        page_size = int(page_text)
    except ValueError:
        page_size = 0
    abi = _root_text(runner, "getprop ro.product.cpu.abi", max_output=4096)
    abilist = _root_text(runner, "getprop ro.product.cpu.abilist", max_output=8192)
    sdk = _root_text(runner, "getprop ro.build.version.sdk", max_output=4096)
    release = _root_text(runner, "getprop ro.build.version.release", max_output=4096)
    magisk_version = _root_text(runner, "magisk -v 2>/dev/null", max_output=4096)
    magisk_code = _root_text(runner, "magisk -V 2>/dev/null", max_output=4096)
    return {
        "runtime_page_size": page_size or "UNAVAILABLE",
        "primary_abi": abi or "UNAVAILABLE",
        "abi_list": [item for item in abilist.split(",") if item] if abilist else [],
        "android_sdk": sdk or "UNAVAILABLE",
        "android_release": release or "UNAVAILABLE",
        "magisk": {
            "version": magisk_version or "UNAVAILABLE",
            "version_code": magisk_code or "UNAVAILABLE",
        },
    }


def collect_module(runner: RootRunner, module_id: str, page_size: int) -> dict[str, object]:
    if not _valid_module_id(module_id):
        raise EvidenceError(f"unsafe module ID: {module_id!r}")
    base = f"/data/adb/modules/{module_id}"
    qbase = shlex.quote(base)
    safe = runner.run(f"[ -d {qbase} ] && [ ! -L {qbase} ]", timeout=5, max_output=4096)
    if safe.returncode != 0:
        return {"module_id": module_id, "status": "ABSENT_OR_UNSAFE"}
    prop = runner.run(
        f"if [ -f {qbase}/module.prop ] && [ ! -L {qbase}/module.prop ]; then head -c {MAX_MODULE_PROP} {qbase}/module.prop; fi",
        timeout=5,
        max_output=MAX_MODULE_PROP,
    )
    metadata = parse_module_prop(prop.stdout if prop.returncode == 0 else b"")
    listing = runner.run(
        f"find {qbase} -type f -name '*.so' 2>/dev/null | head -n {MAX_NATIVE_LIBS + 1}",
        timeout=10,
        max_output=256_000,
    )
    libraries: list[dict[str, object]] = []
    inventory_truncated = False
    if listing.returncode == 0:
        raw_paths = listing.stdout.decode("utf-8", errors="replace").splitlines()
        inventory_truncated = len(raw_paths) > MAX_NATIVE_LIBS
        for raw_path in raw_paths[:MAX_NATIVE_LIBS]:
            path = raw_path.strip()
            if not path.startswith(base + "/") or "\n" in path or "\r" in path:
                continue
            qpath = shlex.quote(path)
            prefix = runner.run(
                f"if [ -f {qpath} ] && [ ! -L {qpath} ]; then dd if={qpath} bs=1 count={MAX_ELF_PREFIX} 2>/dev/null; else exit 3; fi",
                timeout=12,
                max_output=MAX_ELF_PREFIX,
            )
            if prefix.returncode != 0:
                libraries.append({"path": path, "status": "UNREADABLE_OR_UNSAFE"})
                continue
            elf = parse_elf_load_alignments(prefix.stdout)
            aligns = elf.get("load_alignments", []) if isinstance(elf, dict) else []
            compatible: object = "INCONCLUSIVE"
            if page_size > 0 and isinstance(aligns, list) and aligns:
                compatible = all(isinstance(value, int) and value >= page_size and value % page_size == 0 for value in aligns)
            libraries.append(
                {
                    "path": path,
                    "prefix_sha256": hashlib.sha256(prefix.stdout).hexdigest(),
                    "elf": elf,
                    "runtime_page_size_compatible": compatible,
                }
            )
    return {
        "module_id": module_id,
        "status": "AVAILABLE",
        "module": metadata,
        "native_libraries": libraries,
        "native_library_count": len(libraries),
        "native_library_inventory_truncated": inventory_truncated,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect read-only OTAST native/runtime compatibility evidence")
    parser.add_argument("--output", help="optional JSON output file")
    return parser


def write_output(path_arg: str | None, encoded: str) -> None:
    if not path_arg:
        return
    path = Path(path_arg).expanduser()
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise EvidenceError(f"output path is unsafe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = load_registry(repo_root())
        explicit_ids = explicit_native_module_ids(registry)
        if not explicit_ids:
            raise EvidenceError("declared native module inventory is empty")
        runner = RootRunner()
        if not runner.ready:
            raise EvidenceError("no working root backend")
        platform = collect_platform(runner)
        page = platform.get("runtime_page_size")
        page_size = page if isinstance(page, int) else 0
        modules = [collect_module(runner, module_id, page_size) for module_id in explicit_ids]
        if any(item.get("native_library_inventory_truncated") is True for item in modules):
            raise EvidenceError("native library inventory exceeds bounded maximum; evidence would be incomplete")
        zygisk_ids = {"rezygisk", "zygisksu"}
        zygisk_present = [
            item
            for item in modules
            if item.get("module_id") in zygisk_ids and item.get("status") == "AVAILABLE"
        ]
        report = {
            "schema_version": 1,
            "collector": "runtime-compatibility-evidence",
            "read_only": True,
            "root_backend": {"selected": runner.kind, "probes": runner.probes},
            "explicit_module_ids": explicit_ids,
            "platform": platform,
            "modules": modules,
            "zygisk_implementation": zygisk_present,
            "notes": [
                "Only module IDs explicitly declared by the compatibility registry are inspected.",
                "ELF evidence is observational; this collector never patches or reconfigures native/Zygisk modules.",
            ],
        }
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        write_output(args.output, encoded)
        sys.stdout.write(encoded)
        return 0
    except (EvidenceError, OSError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
