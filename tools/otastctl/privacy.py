from __future__ import annotations

import re
from pathlib import Path

from .util import OtastError, iter_regular_files

SKIP_PARTS = {".git", "dist", "reports", "__pycache__", ".pytest_cache"}
FORBIDDEN_NAMES = {
    ".env",
    "keybox.xml",
    "magisk.db",
    "keystore.db",
    "credentials.json",
    "service-account.json",
}
TEXT_SUFFIXES = {
    "", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".py", ".sh", ".prop", ".tsv", ".cfg", ".ini"
}


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    begin_private = "-----BEGIN " + "PRIVATE KEY-----"
    return [
        ("private-key", re.compile(re.escape(begin_private))),
        ("github-token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
        ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
        ("termux-home", re.compile(r"/data/data/com\.termux/files/home/(?!repos/otast\b)[^\s\"']+")),
        ("imei", re.compile(r"(?i)\bimei\s*[:=]\s*\d{14,16}\b")),
        ("android-id", re.compile(r"(?i)\bandroid[_ -]?id\s*[:=]\s*[0-9a-f]{16}\b")),
        ("mac-address", re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")),
    ]


def scan_repository(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        if path.is_symlink():
            findings.append(f"symlink:{rel.as_posix()}")
            continue
        if path.is_dir():
            continue
        if path.name.lower() in FORBIDDEN_NAMES:
            findings.append(f"forbidden-name:{rel.as_posix()}")
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in _patterns():
            if rel.as_posix() == "tools/otastctl/privacy.py" and label in {"private-key", "termux-home"}:
                continue
            if pattern.search(text):
                findings.append(f"{label}:{rel.as_posix()}")
    return findings


def require_public_safe(root: Path) -> None:
    findings = scan_repository(root)
    if findings:
        raise OtastError("public privacy scan failed:\n  " + "\n  ".join(findings))
