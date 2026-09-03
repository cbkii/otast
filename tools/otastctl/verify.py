from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .build import ENTRYPOINTS, build_module, module_metadata
from .compatibility import validate_registry
from .privacy import require_public_safe
from .release import UPDATE_JSON_URL, load_update_metadata, version_core
from .util import OtastError, sha256_file


def _run(command: list[str], cwd: Path, timeout: int = 120) -> None:
    try:
        subprocess.run(command, cwd=cwd, check=True, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise OtastError(f"command failed: {' '.join(command)}") from exc


def verify_repository(root: Path, *, full: bool = False) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise OtastError(f"repository root is missing or unsafe: {root}")

    compatibility = validate_registry(root)
    metadata = module_metadata(root / "module/module.prop")
    update = load_update_metadata(root / "update.json")
    current_version = metadata["version"]
    current_code = int(metadata["versionCode"])
    stable_version = str(update["version"])
    stable_code = int(update["versionCode"])
    if metadata["updateJson"] != UPDATE_JSON_URL:
        raise OtastError("module.prop updateJson is not the stable OTAST update channel")
    if current_code < stable_code:
        raise OtastError("module.prop versionCode is behind stable update.json")
    if current_code == stable_code and current_version != stable_version:
        raise OtastError("module.prop version differs from stable update.json at the same versionCode")
    if current_code > stable_code and version_core(current_version) <= version_core(stable_version):
        raise OtastError("unpublished module.prop version must be newer than stable update.json")
    for rel in ENTRYPOINTS:
        path = root / "module" / rel
        if path.is_symlink() or not path.is_file():
            raise OtastError(f"required executable is missing or unsafe: module/{rel}")
        if not path.read_bytes().startswith(b"#!"):
            raise OtastError(f"required executable lacks shebang: module/{rel}")
        if path.stat().st_mode & 0o111 == 0:
            raise OtastError(f"required executable is not executable: module/{rel}")
    require_public_safe(root)
    for path in sorted((root / "module").rglob("*.sh")):
        _run(["busybox", "sh", "-n", str(path)], root)
    for path in sorted((root / "scripts").rglob("*.sh")):
        _run(["bash", "-n", str(path)], root)
    _run(["python3", "-m", "compileall", "-q", "tools", "tests"], root)
    output_one = root / ".verify-dist-one"
    output_two = root / ".verify-dist-two"
    shutil.rmtree(output_one, ignore_errors=True)
    shutil.rmtree(output_two, ignore_errors=True)
    first = build_module(root, output_one)
    second = build_module(root, output_two)
    first_hash = sha256_file(first)
    if first_hash != sha256_file(second):
        raise OtastError("module build is not deterministic")
    result: dict[str, object] = {
        "version": current_version,
        "version_code": current_code,
        "stable_version": stable_version,
        "stable_version_code": stable_code,
        "module_sha256": first_hash,
        "privacy": "PASS",
        "deterministic": True,
        "compatibility": compatibility,
    }
    if full:
        _run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"], root, timeout=600)
    shutil.rmtree(output_one, ignore_errors=True)
    shutil.rmtree(output_two, ignore_errors=True)
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    return result
