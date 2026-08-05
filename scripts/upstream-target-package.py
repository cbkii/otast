#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from otast_safety_guard import (
    GuardError,
    assert_fake_root,
    assert_upstream_cache_path,
    require_non_root,
)

MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 96 * 1024 * 1024
MAX_TOTAL_BYTES = 384 * 1024 * 1024
MAX_MEMBERS = 8192
MAX_ANALYSED_TEXT_BYTES = 2 * 1024 * 1024
USER_AGENT = "otast-upstream-evidence/4"

INSTALL_ONLY_PATHS = {
    "customize.sh",
    "install.sh",
}
INSTALLER_BASENAMES = {
    "customize.sh",
    "install.sh",
    "update-binary",
    "updater-script",
}
SHELL_BASENAMES = {
    "action.sh",
    "customize.sh",
    "install.sh",
    "post-fs-data.sh",
    "service.sh",
    "uninstall.sh",
    "update-binary",
}


class ControlledError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "compatibility/supported-targets.json").is_file():
        raise ControlledError(f"OTAST repository metadata is missing: {root}")
    return root


def stable_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(stable_json(value), encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str, label: str) -> str:
    if not value or re.fullmatch(r"[A-Za-z0-9._-]+", value) is None:
        raise ControlledError(f"unsafe {label}: {value!r}")
    return value


def load_registry() -> dict[str, Any]:
    path = repo_root() / "compatibility/supported-targets.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("targets"), dict):
        raise ControlledError("supported-targets.json has an invalid shape")
    return value


def resolve_target(name: str) -> tuple[str, dict[str, Any]]:
    registry = load_registry()["targets"]
    aliases: dict[str, str] = {}
    for key, record in registry.items():
        aliases[key.lower()] = key
        for module_id in record.get("module_ids", []):
            aliases[str(module_id).lower()] = key
    canonical = aliases.get(name.lower())
    if canonical is None:
        raise ControlledError(
            f"unknown target {name!r}; available: {', '.join(sorted(registry))}"
        )
    record = registry[canonical]
    monitor = record.get("monitor")
    if not isinstance(monitor, dict) or not monitor.get("repository"):
        raise ControlledError(f"target has no upstream repository metadata: {canonical}")
    return canonical, record


def github_headers(*, binary: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def request_json(url: str) -> Any:
    request = urllib.request.Request(url, headers=github_headers())
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise ControlledError(f"GitHub returned HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise ControlledError(f"GitHub request failed: {url}: {exc.reason}") from exc
    if len(payload) > 4 * 1024 * 1024:
        raise ControlledError("GitHub JSON response exceeded the size limit")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ControlledError("GitHub returned malformed JSON") from exc


def repository_api_base(repository: str) -> str:
    parts = repository.split("/")
    if len(parts) != 2 or any(not part for part in parts):
        raise ControlledError(f"invalid GitHub repository: {repository!r}")
    quoted_repo = "/".join(urllib.parse.quote(part, safe="") for part in parts)
    return f"https://api.github.com/repos/{quoted_repo}"


def default_monitor_ref(record: dict[str, Any]) -> str:
    monitor = record.get("monitor")
    if not isinstance(monitor, dict):
        raise ControlledError("target monitor metadata is invalid")
    value = monitor.get("branch") or monitor.get("ref")
    if not isinstance(value, str) or not value.strip():
        value = "main"
    return value.strip()


def commit_record(repository: str, ref: str) -> dict[str, Any]:
    if not ref or len(ref) > 200 or any(ch in ref for ch in "\r\n\x00"):
        raise ControlledError(f"unsafe GitHub ref: {ref!r}")
    value = request_json(
        f"{repository_api_base(repository)}/commits/{urllib.parse.quote(ref, safe='')}"
    )
    if not isinstance(value, dict):
        raise ControlledError("GitHub commit response is not an object")
    sha = value.get("sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ControlledError("GitHub commit response has no valid SHA")
    html_url = value.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith("https://github.com/"):
        html_url = f"https://github.com/{repository}/commit/{sha}"
    return {"sha": sha, "html_url": html_url}


def download_archive(repository: str, commit_sha: str, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_raw = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temp = Path(temp_raw)
    total = 0
    url = f"https://codeload.github.com/{repository}/zip/{commit_sha}"
    try:
        request = urllib.request.Request(url, headers=github_headers(binary=True))
        with os.fdopen(fd, "wb") as output:
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    final_url = urllib.parse.urlparse(response.geturl())
                    if final_url.scheme != "https" or final_url.hostname not in {
                        "codeload.github.com",
                        "github.com",
                    }:
                        raise ControlledError(
                            f"source archive redirect left the GitHub host allow-list: {response.geturl()}"
                        )
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            raise ControlledError("source archive exceeded the download limit")
                        output.write(chunk)
            except urllib.error.HTTPError as exc:
                raise ControlledError(f"source archive download returned HTTP {exc.code}") from exc
            except urllib.error.URLError as exc:
                raise ControlledError(f"source archive download failed: {exc.reason}") from exc
            output.flush()
            os.fsync(output.fileno())
        if total <= 0:
            raise ControlledError("source archive download was empty")
        os.replace(temp, destination)
        os.chmod(destination, 0o600)
        return total
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def release_record(repository: str, tag: str | None, include_prerelease: bool) -> dict[str, Any]:
    base = repository_api_base(repository)
    if tag:
        value = request_json(f"{base}/releases/tags/{urllib.parse.quote(tag, safe='')}")
        if not isinstance(value, dict):
            raise ControlledError("GitHub release response is not an object")
        return value
    if not include_prerelease:
        value = request_json(f"{base}/releases/latest")
        if not isinstance(value, dict):
            raise ControlledError("GitHub latest-release response is not an object")
        return value
    values = request_json(f"{base}/releases?per_page=20")
    if not isinstance(values, list):
        raise ControlledError("GitHub releases response is not a list")
    for value in values:
        if isinstance(value, dict) and not value.get("draft"):
            return value
    raise ControlledError("no non-draft GitHub release was found")


def release_assets(release: dict[str, Any]) -> list[dict[str, Any]]:
    values = release.get("assets")
    if not isinstance(values, list):
        raise ControlledError("release assets are missing")
    assets: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        name = value.get("name")
        url = value.get("browser_download_url")
        size = value.get("size")
        if not isinstance(name, str) or not isinstance(url, str) or not isinstance(size, int):
            continue
        if not url.startswith("https://github.com/"):
            raise ControlledError(f"release asset URL is not a GitHub HTTPS URL: {url}")
        assets.append({"name": name, "url": url, "size": size, "id": value.get("id")})
    return assets


def select_asset(assets: list[dict[str, Any]], exact: str | None, regex: str | None) -> dict[str, Any]:
    if exact and regex:
        raise ControlledError("use either --asset or --asset-regex, not both")
    if exact:
        matches = [asset for asset in assets if asset["name"] == exact]
    elif regex:
        try:
            pattern = re.compile(regex)
        except re.error as exc:
            raise ControlledError(f"invalid asset regex: {exc}") from exc
        matches = [asset for asset in assets if pattern.search(asset["name"])]
    else:
        matches = [asset for asset in assets if asset["name"].lower().endswith(".zip")]
    if len(matches) != 1:
        names = ", ".join(asset["name"] for asset in assets) or "(none)"
        raise ControlledError(
            f"asset selection matched {len(matches)} files; use --asset or --asset-regex. Assets: {names}"
        )
    selected = matches[0]
    if selected["size"] <= 0 or selected["size"] > MAX_DOWNLOAD_BYTES:
        raise ControlledError(f"release asset has an unsafe size: {selected['size']}")
    return selected


def download_asset(url: str, destination: Path, expected_size: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_raw = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temp = Path(temp_raw)
    total = 0
    try:
        request = urllib.request.Request(url, headers=github_headers(binary=True))
        with os.fdopen(fd, "wb") as output:
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    final_url = urllib.parse.urlparse(response.geturl())
                    if final_url.scheme != "https" or final_url.hostname not in {
                        "github.com",
                        "objects.githubusercontent.com",
                        "release-assets.githubusercontent.com",
                    }:
                        raise ControlledError(
                            f"asset redirect left the GitHub host allow-list: {response.geturl()}"
                        )
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            raise ControlledError("release asset exceeded the download limit")
                        output.write(chunk)
            except urllib.error.HTTPError as exc:
                raise ControlledError(f"asset download returned HTTP {exc.code}") from exc
            except urllib.error.URLError as exc:
                raise ControlledError(f"asset download failed: {exc.reason}") from exc
            output.flush()
            os.fsync(output.fileno())
        if total != expected_size:
            raise ControlledError(
                f"downloaded size differs from GitHub metadata: expected {expected_size}, got {total}"
            )
        os.replace(temp, destination)
        os.chmod(destination, 0o600)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def normalized_member(name: str) -> PurePosixPath:
    if "\\" in name or "\x00" in name or name.startswith("/"):
        raise ControlledError(f"unsafe ZIP member path: {name!r}")
    pure = PurePosixPath(name)
    if any(part in ("", ".", "..") for part in pure.parts):
        raise ControlledError(f"unsafe ZIP member path: {name!r}")
    return pure


def validate_infos(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_MEMBERS:
        raise ControlledError(f"unsafe ZIP member count: {len(infos)}")
    seen: set[str] = set()
    total = 0
    result: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for info in infos:
        stripped = info.filename.rstrip("/")
        if not stripped:
            continue
        pure = normalized_member(stripped)
        key = pure.as_posix()
        if key in seen:
            raise ControlledError(f"duplicate normalized ZIP member: {key}")
        seen.add(key)
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ControlledError(f"ZIP contains a link or special file: {key}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ControlledError(f"ZIP member exceeds size limit: {key}")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise ControlledError("ZIP expanded size exceeds limit")
        result.append((info, pure))
    ordered = sorted(seen)
    info_by_key = {pure.as_posix(): info for info, pure in result}
    for index, key in enumerate(ordered):
        prefix = key + "/"
        if index + 1 < len(ordered) and ordered[index + 1].startswith(prefix):
            if not info_by_key[key].is_dir():
                raise ControlledError(f"ZIP path-prefix collision: {key}")
    return result


def module_root_from_infos(infos: Iterable[tuple[zipfile.ZipInfo, PurePosixPath]]) -> PurePosixPath:
    roots: set[PurePosixPath] = set()
    for info, pure in infos:
        if not info.is_dir() and pure.name == "module.prop":
            roots.add(pure.parent)
    if len(roots) != 1:
        labels = ", ".join(sorted(root.as_posix() for root in roots)) or "none"
        raise ControlledError(f"package must contain exactly one module.prop root; found: {labels}")
    return next(iter(roots))


def parse_module_id(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ControlledError("module.prop is not UTF-8") from exc
    ids = [line.removeprefix("id=").strip() for line in text.splitlines() if line.startswith("id=")]
    if len(ids) != 1:
        raise ControlledError("module.prop must contain exactly one id= line")
    return safe_name(ids[0], "module ID")


def inferred_mode(info: zipfile.ZipInfo, data: bytes) -> int:
    raw_mode = (info.external_attr >> 16) & 0o777
    if raw_mode:
        return raw_mode
    if data.startswith(b"#!") or info.filename.endswith(".sh"):
        return 0o755
    return 0o644


def is_binary_magic(data: bytes) -> str | None:
    if data.startswith(b"\x7fELF"):
        return "ELF"
    if data.startswith(b"dex\n"):
        return "DEX"
    if data.startswith(b"MZ"):
        return "PE"
    return None


def installer_role(path: PurePosixPath, module_root: PurePosixPath) -> str:
    try:
        relative = path.relative_to(module_root)
    except ValueError:
        return "OUTSIDE_MODULE_ROOT"
    label = relative.as_posix()
    if label == "customize.sh":
        return "MAGISK_CUSTOMIZE"
    if label == "install.sh":
        return "LEGACY_INSTALL_SH"
    if relative.parts and relative.parts[0] == "META-INF":
        return "RECOVERY_INSTALLER"
    return "MODULE_PAYLOAD"


def shell_candidate(path: PurePosixPath, data: bytes) -> bool:
    if len(data) > MAX_ANALYSED_TEXT_BYTES or b"\x00" in data:
        return False
    if path.name in SHELL_BASENAMES or path.suffix == ".sh":
        return True
    return data.startswith((b"#!/system/bin/sh", b"#!/bin/sh", b"#!/usr/bin/env bash", b"#!/bin/bash"))


def add_finding(
    findings: list[dict[str, Any]],
    *,
    path: str,
    line_number: int,
    category: str,
    severity: str,
    line: str,
) -> None:
    findings.append(
        {
            "path": path,
            "line": line_number,
            "category": category,
            "severity": severity,
            "evidence": line[:500],
        }
    )


def analyse_shell(path: str, text: str, native_names: set[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    patterns: list[tuple[str, str, re.Pattern[str]]] = [
        ("INSTALLER_CONTROL", "INFO", re.compile(r"\b(SKIPUNZIP|REPLACE|REMOVE)\s*=")),
        ("PERMISSION_MODEL", "INFO", re.compile(r"\b(set_perm|set_perm_recursive|chmod|chown|chcon|restorecon)\b")),
        ("MODULE_FILE_MUTATION", "INFO", re.compile(r"\b(cp|mv|rm|mkdir|ln|sed|awk|unzip|tar)\b")),
        ("NETWORK_OPERATION", "BLOCK", re.compile(r"(^|[;&|\s])(curl|wget|nc|ncat|ssh|scp|sftp|git)(\s|$)")),
        ("PRIVILEGED_ANDROID_OPERATION", "BLOCK", re.compile(r"\b(su|magisk|magiskpolicy|resetprop|setprop|settings|pm|cmd|mount|umount|mknod|setenforce|reboot|avbctl|blockdev)\b")),
        ("DYNAMIC_EXECUTION", "BLOCK", re.compile(r"\b(eval|sh\s+-c|bash\s+-c|exec\s+\$|source\s+\$|\.\s+\$)\b|`|\$\(")),
        ("DEVICE_ABSOLUTE_PATH", "WARN", re.compile(r"/(data/adb|data/property|system|system_ext|vendor|product|odm|metadata|dev/block)(/|\b)")),
        ("GLOBAL_MAGISK_SCRIPT", "WARN", re.compile(r"/(service\.d|post-fs-data\.d)(/|\b)")),
        ("BLOCK_DEVICE_WRITE", "BLOCK", re.compile(r"\b(dd|cat|cp)\b[^#\n]*(/dev/block|vbmeta|boot(_[ab])?\b)")),
    ]

    native_names_sorted = sorted(native_names)

    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for category, severity, pattern in patterns:
            if pattern.search(line):
                add_finding(
                    findings,
                    path=path,
                    line_number=number,
                    category=category,
                    severity=severity,
                    line=raw_line,
                )
        if any(name in line for name in native_names_sorted):
            add_finding(
                findings,
                path=path,
                line_number=number,
                category="PACKAGED_NATIVE_EXECUTION_REFERENCE",
                severity="BLOCK",
                line=raw_line,
            )
        source_match = re.search(r"(?:^|[;&|\s])(?:source|\.)\s+([^;&|\s]+)", line)
        if source_match:
            token = source_match.group(1).strip("\"'")
            add_finding(
                findings,
                path=path,
                line_number=number,
                category="SOURCED_HELPER",
                severity="INFO" if "$" not in token else "WARN",
                line=raw_line,
            )
    return findings


def collect_path_surfaces(
    files: dict[str, bytes],
    native_names: set[str],
) -> dict[str, Any]:
    surfaces: dict[str, list[dict[str, Any]]] = {
        "literal_data_adb": [],
        "magisk_tree_paths": [],
        "global_script_paths": [],
        "path_variable_assignments": [],
        "sourced_helpers": [],
        "native_executable_references": [],
        "unresolved_variable_paths": [],
    }
    seen: dict[str, set[tuple[Any, ...]]] = {key: set() for key in surfaces}
    common_path_variables = {
        "ADBDIR",
        "ADB_ROOT",
        "DATA_ADB",
        "MAGISKTMP",
        "MODDIR",
        "MODPATH",
        "MODULES",
        "MODULES_UPDATE",
        "NVBASE",
        "POSTFSDATAD",
        "POST_FS_DATA_D",
        "SERVICED",
        "SERVICE_D",
        "TMPDIR",
    }
    assignment_pattern = re.compile(
        r"^\s*(?:(?:export|readonly|local)\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$"
    )
    source_pattern = re.compile(r"(?:^|[;&|\s])(?:source|\.)\s+([^;&|\s]+)")
    variable_pattern = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")

    def add(category: str, item: dict[str, Any], identity: tuple[Any, ...]) -> None:
        if identity in seen[category]:
            return
        seen[category].add(identity)
        surfaces[category].append(item)

    for path, data in sorted(files.items()):
        if len(data) > MAX_ANALYSED_TEXT_BYTES or b"\x00" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for number, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            base = {"path": path, "line": number, "evidence": raw_line[:500]}
            if "/data/adb" in line:
                add("literal_data_adb", base, (path, number))
            if re.search(r"/data/adb/(?:modules|modules_update)(?:/|\b)", line):
                add("magisk_tree_paths", base, (path, number))
            if re.search(r"/(?:data/adb/)?(?:service\.d|post-fs-data\.d)(?:/|\b)", line):
                add("global_script_paths", base, (path, number))

            assignment = assignment_pattern.match(raw_line)
            if assignment:
                variable = assignment.group(1)
                value = assignment.group(2).strip()
                if variable in common_path_variables:
                    item = dict(base)
                    item.update({"variable": variable, "value": value[:500]})
                    add("path_variable_assignments", item, (path, number, variable))
                    if "$" in value or "`" in value:
                        variables = sorted(
                            {left or right for left, right in variable_pattern.findall(value)}
                        )
                        unresolved = dict(item)
                        unresolved["referenced_variables"] = variables
                        add(
                            "unresolved_variable_paths",
                            unresolved,
                            (path, number, variable, tuple(variables)),
                        )

            source_match = source_pattern.search(line)
            if source_match:
                token = source_match.group(1).strip("\"'")
                item = dict(base)
                item.update(
                    {
                        "token": token,
                        "resolved_statically": "$" not in token and "`" not in token,
                    }
                )
                add("sourced_helpers", item, (path, number, token))

            referenced_native = sorted(name for name in native_names if name in line)
            if referenced_native:
                item = dict(base)
                item["native_files"] = referenced_native
                add(
                    "native_executable_references",
                    item,
                    (path, number, tuple(referenced_native)),
                )

            variables = sorted({left or right for left, right in variable_pattern.findall(line)})
            if variables and ("/" in line or "/data/adb" in line):
                item = dict(base)
                item["referenced_variables"] = variables
                add(
                    "unresolved_variable_paths",
                    item,
                    (path, number, tuple(variables)),
                )

    return {
        "policy": "REPORT_ONLY_SOURCE_BYTES_UNCHANGED",
        "literal_rewrite_performed": False,
        "common_path_variables": sorted(common_path_variables),
        "counts": {key: len(value) for key, value in surfaces.items()},
        **surfaces,
    }


def static_installer_analysis(
    archive: zipfile.ZipFile,
    infos: list[tuple[zipfile.ZipInfo, PurePosixPath]],
    module_root: PurePosixPath,
) -> dict[str, Any]:
    native_files: list[dict[str, Any]] = []
    native_names: set[str] = set()
    shell_files: list[str] = []
    findings: list[dict[str, Any]] = []
    installer_files: list[str] = []

    file_bytes: dict[str, bytes] = {}
    for info, pure in infos:
        if info.is_dir():
            continue
        data = archive.read(info)
        key = pure.as_posix()
        file_bytes[key] = data
        magic = is_binary_magic(data)
        if magic:
            native_files.append(
                {
                    "path": key,
                    "format": magic,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            native_names.add(pure.name)
        role = installer_role(pure, module_root)
        if role in {"MAGISK_CUSTOMIZE", "LEGACY_INSTALL_SH", "RECOVERY_INSTALLER"}:
            installer_files.append(key)

    path_surfaces = collect_path_surfaces(file_bytes, native_names)

    for info, pure in infos:
        if info.is_dir():
            continue
        key = pure.as_posix()
        data = file_bytes[key]
        if not shell_candidate(pure, data):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(
                {
                    "path": key,
                    "line": 0,
                    "category": "NON_UTF8_SHELL_CANDIDATE",
                    "severity": "BLOCK",
                    "evidence": "file could not be decoded as UTF-8",
                }
            )
            continue
        shell_files.append(key)
        findings.extend(analyse_shell(key, text, native_names))

    counts: dict[str, int] = {"INFO": 0, "WARN": 0, "BLOCK": 0}
    categories: dict[str, int] = {}
    for finding in findings:
        severity = str(finding["severity"])
        counts[severity] = counts.get(severity, 0) + 1
        category = str(finding["category"])
        categories[category] = categories.get(category, 0) + 1

    if not installer_files:
        model_status = "NO_CUSTOM_INSTALLER"
    elif counts.get("BLOCK", 0) > 0:
        model_status = "STATIC_MODEL_INCOMPLETE"
    else:
        model_status = "STATIC_MODEL_PARTIAL"

    return {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "analysis_mode": "STATIC_ONLY_NO_EXECUTION",
        "safe_to_execute_on_device": False,
        "module_root": module_root.as_posix(),
        "installer_files": sorted(installer_files),
        "shell_files_analysed": sorted(shell_files),
        "native_files": native_files,
        "path_surfaces": path_surfaces,
        "finding_counts": counts,
        "category_counts": dict(sorted(categories.items())),
        "findings": findings,
        "model_status": model_status,
        "recommended_authority": (
            "DEVICE_CAPTURE_REQUIRED"
            if model_status == "STATIC_MODEL_INCOMPLETE"
            else "STATIC_MODEL_PLUS_DEVICE_COMPARE"
        ),
        "execution_policy": {
            "customize_sh": "RETAINED_NOT_EXECUTED",
            "install_sh": "RETAINED_NOT_EXECUTED",
            "recovery_installer": "RETAINED_NOT_EXECUTED",
            "packaged_native_files": "INVENTORIED_NOT_EXECUTED",
            "network": "NOT_USED_BY_TOOL",
            "root": "NOT_USED_BY_TOOL",
        },
        "limitations": [
            "static analysis cannot resolve all shell control flow or generated paths",
            "path surfaces are reported without rewriting source literals or variables",
            "the static installed tree models Magisk default extraction only",
            "device capture remains authoritative for actual installer postimages",
        ],
    }


def immutable_extract(
    archive: zipfile.ZipFile,
    infos: list[tuple[zipfile.ZipInfo, PurePosixPath]],
    destination: Path,
    module_root: PurePosixPath,
) -> list[dict[str, Any]]:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, mode=0o700)
    inventory: list[dict[str, Any]] = []
    for info, pure in infos:
        output = destination.joinpath(*pure.parts)
        try:
            output.resolve(strict=False).relative_to(destination.resolve())
        except ValueError as exc:
            raise ControlledError(f"member escapes evidence tree: {pure}") from exc
        if info.is_dir():
            output.mkdir(parents=True, exist_ok=True)
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        data = archive.read(info)
        output.write_bytes(data)
        mode = inferred_mode(info, data)
        os.chmod(output, 0o400)
        inventory.append(
            {
                "archive_path": pure.as_posix(),
                "module_relative_path": (
                    pure.relative_to(module_root).as_posix()
                    if pure == module_root or module_root in pure.parents
                    else None
                ),
                "role": installer_role(pure, module_root),
                "size": len(data),
                "archive_mode": f"{mode:04o}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "binary_format": is_binary_magic(data),
            }
        )
    return inventory


def evidence_dir_for_package(target: str, package: Path, output_root: Path) -> Path:
    digest = sha256_file(package)
    return output_root / safe_name(target, "target") / f"local-{digest[:16]}"


def publish_evidence(
    *,
    target: str,
    record: dict[str, Any],
    package: Path,
    evidence_dir: Path,
    provenance: dict[str, Any] | None,
    force: bool,
) -> dict[str, Any]:
    evidence_dir = assert_upstream_cache_path(evidence_dir, "evidence directory")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(evidence_dir, 0o700)
    if evidence_dir.is_symlink():
        raise ControlledError(f"evidence directory is a symlink: {evidence_dir}")

    digest = sha256_file(package)
    candidate_path = evidence_dir / "candidate.json"
    if candidate_path.is_file() and not force:
        existing = json.loads(candidate_path.read_text(encoding="utf-8"))
        complete = (
            isinstance(existing, dict)
            and existing.get("schema_version") == 2
            and existing.get("asset_sha256") == digest
            and (evidence_dir / "source-tree").is_dir()
            and (evidence_dir / "inventory.json").is_file()
            and (evidence_dir / "installer-analysis.json").is_file()
        )
        if complete:
            return existing

    with zipfile.ZipFile(package) as archive:
        infos = validate_infos(archive)
        module_root = module_root_from_infos(infos)
        module_prop_member = (module_root / "module.prop").as_posix()
        module_id = parse_module_id(archive.read(module_prop_member))
        expected_ids = {str(value) for value in record.get("module_ids", [])}
        if module_id not in expected_ids:
            raise ControlledError(
                f"package module id {module_id!r} is not registered for {target}: {sorted(expected_ids)}"
            )
        analysis = static_installer_analysis(archive, infos, module_root)
        inventory = immutable_extract(
            archive,
            infos,
            evidence_dir / "source-tree",
            module_root,
        )

    write_json(evidence_dir / "inventory.json", {"schema_version": 1, "files": inventory})
    write_json(evidence_dir / "installer-analysis.json", analysis)
    (evidence_dir / "module-root.txt").write_text(module_root.as_posix() + "\n", encoding="utf-8")
    os.chmod(evidence_dir / "module-root.txt", 0o400)

    metadata = {
        "schema_version": 2,
        "fetched_or_analysed_utc": utc_now(),
        "target": target,
        "repository": record["monitor"]["repository"],
        "module_id": module_id,
        "module_root": module_root.as_posix(),
        "package": str(package),
        "asset_sha256": digest,
        "asset_size": package.stat().st_size,
        "evidence_dir": str(evidence_dir),
        "source_tree": str(evidence_dir / "source-tree"),
        "inventory": str(evidence_dir / "inventory.json"),
        "installer_analysis": str(evidence_dir / "installer-analysis.json"),
        "installer_model_status": analysis["model_status"],
        "execution": "NEVER_EXECUTED",
        "source_retention": "FULL_ARCHIVE_TREE_RETAINED",
        "provenance": provenance,
    }
    write_json(candidate_path, metadata)
    return metadata


def command_ref(args: argparse.Namespace) -> int:
    target, record = resolve_target(args.target)
    repository = record["monitor"]["repository"]
    requested_ref = args.ref or default_monitor_ref(record)
    commit = commit_record(repository, requested_ref)
    result = {
        "target": target,
        "repository": repository,
        "requested_ref": requested_ref,
        "resolved_commit": commit["sha"],
        "commit_url": commit["html_url"],
        "source_kind": "github-ref",
    }
    print(stable_json(result), end="")
    return 0


def command_fetch_ref(args: argparse.Namespace) -> int:
    target, record = resolve_target(args.target)
    repository = record["monitor"]["repository"]
    requested_ref = args.ref or default_monitor_ref(record)
    commit = commit_record(repository, requested_ref)
    commit_sha = commit["sha"]
    output_root = assert_upstream_cache_path(Path(args.output_root), "upstream candidate root")
    candidate_dir = output_root / safe_name(target, "target") / f"ref-{commit_sha[:12]}"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(candidate_dir, 0o700)
    repo_name = safe_name(repository.split("/", 1)[1], "repository name")
    package = candidate_dir / f"{repo_name}-{commit_sha[:12]}.zip"
    archive_url = f"https://codeload.github.com/{repository}/zip/{commit_sha}"
    if package.exists():
        if package.is_symlink() or not package.is_file():
            raise ControlledError(f"candidate package path is unsafe: {package}")
        if args.force:
            package.unlink()
        else:
            candidate_path = candidate_dir / "candidate.json"
            if not candidate_path.is_file() or candidate_path.is_symlink():
                raise ControlledError(
                    f"unbound existing candidate package: {package}; use --force to re-download"
                )
            existing = json.loads(candidate_path.read_text(encoding="utf-8"))
            provenance = existing.get("provenance") if isinstance(existing, dict) else None
            if (
                not isinstance(existing, dict)
                or existing.get("asset_sha256") != sha256_file(package)
                or not isinstance(provenance, dict)
                or provenance.get("resolved_commit") != commit_sha
                or provenance.get("archive_url") != archive_url
            ):
                raise ControlledError(
                    f"existing ref candidate provenance differs: {package}; use --force to refresh"
                )
    if not package.exists():
        archive_size = download_archive(repository, commit_sha, package)
    else:
        archive_size = package.stat().st_size
    provenance = {
        "source_kind": "github-ref-archive",
        "requested_ref": requested_ref,
        "resolved_commit": commit_sha,
        "commit_url": commit["html_url"],
        "archive_url": archive_url,
        "archive_size": archive_size,
    }
    metadata = publish_evidence(
        target=target,
        record=record,
        package=package,
        evidence_dir=candidate_dir,
        provenance=provenance,
        force=args.force,
    )
    print(stable_json(metadata), end="")
    return 0


def command_assets(args: argparse.Namespace) -> int:
    target, record = resolve_target(args.target)
    repository = record["monitor"]["repository"]
    release = release_record(repository, args.tag, args.include_prerelease)
    result = {
        "target": target,
        "repository": repository,
        "tag": release.get("tag_name"),
        "prerelease": bool(release.get("prerelease")),
        "published_at": release.get("published_at"),
        "html_url": release.get("html_url"),
        "assets": release_assets(release),
    }
    print(stable_json(result), end="")
    return 0


def command_fetch(args: argparse.Namespace) -> int:
    target, record = resolve_target(args.target)
    repository = record["monitor"]["repository"]
    release = release_record(repository, args.tag, args.include_prerelease)
    asset = select_asset(release_assets(release), args.asset, args.asset_regex)
    tag = safe_name(str(release.get("tag_name") or "untagged"), "release tag")
    output_root = assert_upstream_cache_path(Path(args.output_root), "upstream candidate root")
    candidate_dir = output_root / safe_name(target, "target") / tag
    candidate_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(candidate_dir, 0o700)
    package = candidate_dir / Path(asset["name"]).name
    if package.exists():
        if package.is_symlink() or not package.is_file():
            raise ControlledError(f"candidate package path is unsafe: {package}")
        if args.force:
            package.unlink()
        else:
            candidate_path = candidate_dir / "candidate.json"
            if not candidate_path.is_file() or candidate_path.is_symlink():
                raise ControlledError(
                    f"unbound existing candidate package: {package}; use --force to re-download"
                )
            existing = json.loads(candidate_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                raise ControlledError(f"existing candidate metadata is invalid: {candidate_path}")
            if existing.get("asset_sha256") != sha256_file(package):
                raise ControlledError(f"existing candidate hash differs from candidate.json: {package}")
            existing_provenance = existing.get("provenance") or {}
            if (
                existing_provenance.get("asset_url") != asset["url"]
                or existing_provenance.get("asset_name") != asset["name"]
                or package.stat().st_size != asset["size"]
            ):
                raise ControlledError(
                    f"existing candidate provenance differs from current release metadata: {package}; "
                    "use --force to refresh"
                )
    if not package.exists():
        download_asset(asset["url"], package, asset["size"])

    provenance = {
        "release_tag": release.get("tag_name"),
        "release_prerelease": bool(release.get("prerelease")),
        "release_url": release.get("html_url"),
        "asset_name": asset["name"],
        "asset_url": asset["url"],
        "asset_size": asset["size"],
    }
    metadata = publish_evidence(
        target=target,
        record=record,
        package=package,
        evidence_dir=candidate_dir,
        provenance=provenance,
        force=args.force,
    )
    print(stable_json(metadata), end="")
    return 0


def command_analyse(args: argparse.Namespace) -> int:
    target, record = resolve_target(args.target)
    package = Path(args.package).expanduser().resolve()
    if not package.is_file() or package.is_symlink():
        raise ControlledError(f"candidate package is missing or unsafe: {package}")
    output_root = assert_upstream_cache_path(Path(args.output_root), "upstream evidence root")
    evidence_dir = evidence_dir_for_package(target, package, output_root)
    retained = evidence_dir / package.name
    evidence_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(evidence_dir, 0o700)
    if not retained.exists() or args.force:
        temporary = retained.with_name(f".{retained.name}.{os.getpid()}.tmp")
        shutil.copyfile(package, temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, retained)
    metadata = publish_evidence(
        target=target,
        record=record,
        package=retained,
        evidence_dir=evidence_dir,
        provenance={"local_source": str(package)},
        force=args.force,
    )
    print(stable_json(metadata), end="")
    return 0


def ensure_fake_root(root: Path, operation: str) -> Path:
    try:
        return assert_fake_root(root, operation)
    except GuardError as exc:
        raise ControlledError(str(exc)) from exc


def copy_evidence_sidecar(evidence_dir: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, mode=0o700)
    for name in ("candidate.json", "inventory.json", "installer-analysis.json", "module-root.txt"):
        source = evidence_dir / name
        if source.is_file() and not source.is_symlink():
            shutil.copyfile(source, destination / name)
            os.chmod(destination / name, 0o600)

    source_tree = evidence_dir / "source-tree"
    shell_destination = destination / "shell-source"
    for source in sorted(source_tree.rglob("*")):
        if source.is_symlink() or not source.is_file():
            continue
        relative = source.relative_to(source_tree)
        data = source.read_bytes()
        if not shell_candidate(PurePosixPath(relative.as_posix()), data):
            continue
        output = shell_destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        os.chmod(output, 0o400)


def materialize_default_tree(
    package: Path,
    destination: Path,
    module_root: PurePosixPath,
) -> tuple[list[dict[str, Any]], list[str]]:
    with zipfile.ZipFile(package) as archive:
        infos = validate_infos(archive)
        stage = destination.parent / f".{destination.name}.otast-stage-{os.getpid()}"
        previous = destination.parent / f".{destination.name}.otast-previous-{os.getpid()}"
        for transient in (stage, previous):
            if transient.is_symlink():
                raise ControlledError(f"unsafe transient path: {transient}")
            if transient.exists():
                shutil.rmtree(transient)
        stage.mkdir(parents=True, mode=0o700)
        omitted: list[str] = []
        inventory: list[dict[str, Any]] = []
        try:
            for info, pure in infos:
                try:
                    relative = pure.relative_to(module_root)
                except ValueError:
                    omitted.append(pure.as_posix())
                    continue
                if not relative.parts:
                    continue
                label = relative.as_posix()
                if label in INSTALL_ONLY_PATHS or relative.parts[0] == "META-INF":
                    omitted.append(label)
                    continue
                output = stage.joinpath(*relative.parts)
                try:
                    output.resolve(strict=False).relative_to(stage.resolve())
                except ValueError as exc:
                    raise ControlledError(f"member escapes module destination: {relative}") from exc
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(info)
                output.write_bytes(data)
                mode = inferred_mode(info, data)
                output.chmod(mode)
                inventory.append(
                    {
                        "path": label,
                        "size": len(data),
                        "mode": f"{mode:04o}",
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            if destination.exists():
                os.replace(destination, previous)
            try:
                os.replace(stage, destination)
            except Exception:
                if previous.exists() and not destination.exists():
                    os.replace(previous, destination)
                raise
            if previous.exists():
                shutil.rmtree(previous)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            if previous.exists() and not destination.exists():
                os.replace(previous, destination)
            raise
    return inventory, sorted(omitted)


def resolve_package_evidence(
    target: str,
    record: dict[str, Any],
    package: Path,
    output_root: Path,
) -> dict[str, Any]:
    candidate_path = package.parent / "candidate.json"
    if candidate_path.is_file() and not candidate_path.is_symlink():
        loaded = json.loads(candidate_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and loaded.get("asset_sha256") == sha256_file(package):
            evidence = assert_upstream_cache_path(
                Path(str(loaded.get("evidence_dir", package.parent))),
                "candidate evidence directory",
            )
            if evidence == package.parent.resolve():
                return loaded
    evidence_dir = evidence_dir_for_package(target, package, output_root)
    retained = evidence_dir / package.name
    evidence_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(evidence_dir, 0o700)
    if not retained.exists():
        shutil.copyfile(package, retained)
        os.chmod(retained, 0o600)
    return publish_evidence(
        target=target,
        record=record,
        package=retained,
        evidence_dir=evidence_dir,
        provenance={"local_source": str(package)},
        force=False,
    )


def command_materialize(args: argparse.Namespace) -> int:
    target, record = resolve_target(args.target)
    package = Path(args.package).expanduser().resolve()
    if not package.is_file() or package.is_symlink():
        raise ControlledError(f"candidate package is missing or unsafe: {package}")
    fake_root = ensure_fake_root(Path(args.fake_root), "upstream materialization")
    tree = args.tree
    if tree not in ("modules", "modules_update"):
        raise ControlledError("--tree must be modules or modules_update")

    evidence = resolve_package_evidence(
        target,
        record,
        package,
        assert_upstream_cache_path(Path(args.evidence_root), "upstream evidence root"),
    )
    evidence_dir = Path(str(evidence["evidence_dir"])).resolve()
    module_id = safe_name(str(evidence["module_id"]), "module ID")
    module_root = PurePosixPath(str(evidence["module_root"]))

    destination = fake_root / "data/adb" / tree / module_id
    adb_root = (fake_root / "data/adb").resolve()
    try:
        destination.resolve(strict=False).relative_to(adb_root)
    except ValueError as exc:
        raise ControlledError("target destination escapes fake /data/adb") from exc
    if destination.is_symlink():
        raise ControlledError(f"target destination is a symlink: {destination}")

    fake_root = ensure_fake_root(fake_root, "upstream materialization before module-tree write")
    inventory, omitted = materialize_default_tree(package, destination, module_root)
    evidence_sidecar = (
        fake_root
        / ".otast/upstream-evidence"
        / safe_name(target, "target")
        / str(evidence["asset_sha256"])[:16]
    )
    fake_root = ensure_fake_root(fake_root, "upstream materialization before evidence-sidecar write")
    copy_evidence_sidecar(evidence_dir, evidence_sidecar)

    analysis = json.loads((evidence_dir / "installer-analysis.json").read_text(encoding="utf-8"))
    marker = {
        "schema_version": 2,
        "created_utc": utc_now(),
        "target": target,
        "module_id": module_id,
        "tree": tree,
        "destination": str(destination),
        "package": str(package),
        "package_sha256": sha256_file(package),
        "evidence_dir": str(evidence_dir),
        "fake_root_evidence": str(evidence_sidecar),
        "layout": "MAGISK_DEFAULT_EXTRACTION_STATIC_MODEL",
        "installer_executed": False,
        "qualification": "STATIC_INSTALL_MODEL_ONLY",
        "installer_model_status": analysis.get("model_status"),
        "installer_code_retained": True,
        "omitted_from_installed_tree_but_retained_in_evidence": omitted,
        "inventory": inventory,
        "limitations": [
            "customize.sh/install.sh/recovery installer code is retained but never executed",
            "installer-generated files and conditional postimages require device capture",
            "the fake module tree cannot affect live /data/adb",
        ],
    }
    marker_dir = fake_root / ".otast/upstream-materializations"
    fake_root = ensure_fake_root(fake_root, "upstream materialization before marker write")
    write_json(marker_dir / f"{safe_name(target, 'target')}.json", marker)
    write_json(fake_root / "upstream-materialization.json", marker)
    print(stable_json(marker), end="")
    return 0


def module_dir_for_target(root: Path, tree: str, record: dict[str, Any]) -> Path | None:
    matches: list[Path] = []
    for module_id in record.get("module_ids", []):
        candidate = root / "data/adb" / tree / str(module_id)
        if candidate.is_dir() and not candidate.is_symlink():
            matches.append(candidate)
    if len(matches) > 1:
        raise ControlledError(f"multiple target aliases exist in {tree}: {matches}")
    return matches[0] if matches else None


def file_map(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ControlledError(f"module comparison encountered symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.stat().st_mode)
        result[relative] = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "mode": f"{mode:04o}",
        }
    return result


def command_compare(args: argparse.Namespace) -> int:
    target, record = resolve_target(args.target)
    fake_root = ensure_fake_root(Path(args.fake_root), "upstream comparison")
    active = module_dir_for_target(fake_root, args.active_tree, record)
    candidate = module_dir_for_target(fake_root, args.candidate_tree, record)
    if active is None or candidate is None:
        raise ControlledError(
            f"comparison requires one active and one candidate target: active={active}, candidate={candidate}"
        )
    active_map = file_map(active)
    candidate_map = file_map(candidate)
    added: list[str] = []
    removed: list[str] = []
    changed: list[dict[str, Any]] = []
    same = 0
    for path in sorted(set(active_map) | set(candidate_map)):
        left = active_map.get(path)
        right = candidate_map.get(path)
        if left is None:
            added.append(path)
        elif right is None:
            removed.append(path)
        elif left == right:
            same += 1
        else:
            changed.append({"path": path, "active": left, "candidate": right})
    result = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "target": target,
        "active_tree": args.active_tree,
        "candidate_tree": args.candidate_tree,
        "active_path": str(active),
        "candidate_path": str(candidate),
        "classification": "IDENTICAL" if not added and not removed and not changed else "DIFFERENT",
        "same_files": same,
        "added_in_candidate": added,
        "removed_from_candidate": removed,
        "changed": changed,
        "interpretation": "ACTIVE_DEVICE_CAPTURE_VS_STATIC_CANDIDATE_DELTA",
    }
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else fake_root / ".otast/upstream-comparisons" / f"{safe_name(target, 'target')}.json"
    )
    write_json(output, result)
    print(stable_json(result), end="")
    return 0


def command_show(args: argparse.Namespace) -> int:
    path = assert_upstream_cache_path(Path(args.path), "candidate evidence path")
    if path.is_dir():
        candidate = path / "candidate.json"
    elif path.is_file() and path.name == "candidate.json":
        candidate = path
    elif path.is_file():
        candidate = path.parent / "candidate.json"
    else:
        raise ControlledError(f"evidence path does not exist: {path}")
    if not candidate.is_file() or candidate.is_symlink():
        raise ControlledError(f"candidate.json is missing: {candidate}")
    value = json.loads(candidate.read_text(encoding="utf-8"))
    print(stable_json(value), end="")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description=(
            "Fetch, retain, statically analyse and safely materialize upstream "
            "target-module packages without executing installer code"
        )
    )
    sub = root.add_subparsers(dest="command", required=True)

    ref = sub.add_parser("ref", help="resolve a branch, tag or commit for a registered target")
    ref.add_argument("target")
    ref.add_argument("--ref")

    fetch_ref = sub.add_parser(
        "fetch-ref",
        help="download a GitHub source archive at an exact resolved commit",
    )
    fetch_ref.add_argument("target")
    fetch_ref.add_argument("--ref")
    fetch_ref.add_argument(
        "--output-root",
        default=str(Path.home() / ".cache/otast/upstream-candidates"),
    )
    fetch_ref.add_argument("--force", action="store_true")

    assets = sub.add_parser("assets", help="list release assets for a registered target")
    assets.add_argument("target")
    assets.add_argument("--tag")
    assets.add_argument("--include-prerelease", action="store_true")

    fetch = sub.add_parser(
        "fetch",
        help="download one release asset and retain its complete source/installer evidence",
    )
    fetch.add_argument("target")
    fetch.add_argument("--tag")
    fetch.add_argument("--include-prerelease", action="store_true")
    fetch.add_argument("--asset")
    fetch.add_argument("--asset-regex")
    fetch.add_argument(
        "--output-root",
        default=str(Path.home() / ".cache/otast/upstream-candidates"),
    )
    fetch.add_argument("--force", action="store_true")

    analyse = sub.add_parser(
        "analyse",
        help="retain and statically analyse a local module ZIP without executing it",
    )
    analyse.add_argument("target")
    analyse.add_argument("package")
    analyse.add_argument(
        "--output-root",
        default=str(Path.home() / ".cache/otast/upstream-candidates"),
    )
    analyse.add_argument("--force", action="store_true")

    materialize = sub.add_parser(
        "materialize",
        help="derive a static installed tree in an existing disposable fake root",
    )
    materialize.add_argument("target")
    materialize.add_argument("package")
    materialize.add_argument("fake_root")
    materialize.add_argument("--tree", default="modules_update")
    materialize.add_argument(
        "--evidence-root",
        default=str(Path.home() / ".cache/otast/upstream-candidates"),
    )

    compare = sub.add_parser(
        "compare",
        help="compare a device-captured active target with the static candidate tree",
    )
    compare.add_argument("target")
    compare.add_argument("fake_root")
    compare.add_argument("--active-tree", default="modules")
    compare.add_argument("--candidate-tree", default="modules_update")
    compare.add_argument("--output")

    show = sub.add_parser("show", help="show candidate evidence metadata")
    show.add_argument("path")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        require_non_root(f"upstream {args.command}")
        commands = {
            "ref": command_ref,
            "fetch-ref": command_fetch_ref,
            "assets": command_assets,
            "fetch": command_fetch,
            "analyse": command_analyse,
            "materialize": command_materialize,
            "compare": command_compare,
            "show": command_show,
        }
        command = commands.get(args.command)
        if command is None:
            raise ControlledError(f"unknown command: {args.command}")
        return command(args)
    except (GuardError, ControlledError, OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
