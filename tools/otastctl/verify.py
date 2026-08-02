from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .build import ENTRYPOINTS, build_module, module_metadata
from .privacy import require_public_safe
from .util import OtastError, sha256_file


def _run(command: list[str], cwd: Path, timeout: int = 120) -> None:
    try:
        subprocess.run(command, cwd=cwd, check=True, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise OtastError(f"command failed: {' '.join(command)}") from exc


def verify_repository(root: Path, *, full: bool = False) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise OtastError(f"repository root is missing or unsafe: {root}")
    metadata = module_metadata(root / "module/module.prop")
    update = json.loads((root / "update.json").read_text(encoding="utf-8"))
    if update.get("version") != metadata["version"]:
        raise OtastError("update.json version differs from module.prop")
    if int(update.get("versionCode", -1)) != int(metadata["versionCode"]):
        raise OtastError("update.json versionCode differs from module.prop")
    if f"/releases/download/{metadata['version']}/otast-{metadata['version']}.zip" not in update.get("zipUrl", ""):
        raise OtastError("update.json ZIP URL is not canonical")
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
    if sha256_file(first) != sha256_file(second):
        raise OtastError("module build is not deterministic")
    result: dict[str, object] = {
        "version": metadata["version"],
        "version_code": int(metadata["versionCode"]),
        "module_sha256": sha256_file(first),
        "privacy": "PASS",
        "deterministic": True,
    }
    if full:
        _run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"], root, timeout=600)
    shutil.rmtree(output_one, ignore_errors=True)
    shutil.rmtree(output_two, ignore_errors=True)
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    return result
