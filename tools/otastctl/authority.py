from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .util import OtastError, sha256_file

KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DEVICE_RE = re.compile(r"^[a-z0-9_]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
AVB_RE = re.compile(r"^\d+\.\d+$")
REQUIRED = (
    "boot.img.sha256",
    "ro.boot.vbmeta.digest",
    "ro.boot.vbmeta.size",
    "ro.boot.vbmeta.avb_version",
    "ro.boot.avb_version",
    "ro.build.fingerprint",
    "ro.build.id",
    "ro.build.version.sdk",
    "ro.build.version.security_patch",
    "ro.product.device",
    "ro.product.manufacturer",
    "ro.product.model",
)


@dataclass(frozen=True)
class Authority:
    path: Path
    values: dict[str, str]
    sha256: str


def parse_authority(path: Path) -> Authority:
    if path.is_symlink() or not path.is_file():
        raise OtastError(f"authority is missing or unsafe: {path}")
    raw = path.read_bytes()
    if not raw or len(raw) > 512 * 1024:
        raise OtastError("authority size is outside the supported range")
    if b"\x00" in raw or b"\r" in raw:
        raise OtastError("authority must be NUL-free LF text")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OtastError("authority is not valid UTF-8") from exc
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise OtastError(f"authority line {number} has no '='")
        key, value = line.split("=", 1)
        if not KEY_RE.fullmatch(key):
            raise OtastError(f"authority line {number} has an invalid key")
        if key in values:
            raise OtastError(f"authority contains duplicate key: {key}")
        if value != value.strip():
            raise OtastError(f"authority value has ambiguous whitespace: {key}")
        values[key] = value
    missing = [key for key in REQUIRED if not values.get(key)]
    if missing:
        raise OtastError("authority is missing: " + ", ".join(missing))

    device = values["ro.product.device"]
    manufacturer = values["ro.product.manufacturer"]
    model = values["ro.product.model"]
    fingerprint = values["ro.build.fingerprint"]
    sdk = values["ro.build.version.sdk"]

    if not DEVICE_RE.fullmatch(device):
        raise OtastError("authority Pixel device identity is malformed")
    if sdk != "36":
        raise OtastError("authority SDK must be 36")
    if manufacturer != "Google" or not model.startswith("Pixel "):
        raise OtastError("authority product identity must describe a Google Pixel device")
    expected_fingerprint_prefix = f"google/{device}/{device}:16/"
    if not fingerprint.startswith(expected_fingerprint_prefix) or not fingerprint.endswith(":user/release-keys"):
        raise OtastError("authority fingerprint is not a matching Google Pixel Android 16 release fingerprint")

    if not DATE_RE.fullmatch(values["ro.build.version.security_patch"]):
        raise OtastError("invalid system security patch date")
    vendor = values.get("ro.vendor.build.security_patch", values["ro.build.version.security_patch"])
    if not DATE_RE.fullmatch(vendor):
        raise OtastError("invalid vendor security patch date")
    if not HEX64_RE.fullmatch(values["boot.img.sha256"]):
        raise OtastError("boot.img.sha256 must be lowercase SHA-256")
    if not HEX64_RE.fullmatch(values["ro.boot.vbmeta.digest"]):
        raise OtastError("ro.boot.vbmeta.digest must be lowercase SHA-256")
    if not values["ro.boot.vbmeta.size"].isdigit() or int(values["ro.boot.vbmeta.size"]) <= 0:
        raise OtastError("ro.boot.vbmeta.size must be positive artifact provenance")
    for key in ("ro.boot.vbmeta.avb_version", "ro.boot.avb_version"):
        if not AVB_RE.fullmatch(values[key]):
            raise OtastError(f"{key} must be major.minor")

    identity_policy = values.get("otast.pif.identity", "preserve")
    if identity_policy not in {"preserve", "ota"}:
        raise OtastError("otast.pif.identity must be preserve or ota")
    tricky_policy = values.get("otast.trickystore.securityPatch", "preserve")
    if tricky_policy not in {"preserve", "ota"}:
        raise OtastError("otast.trickystore.securityPatch must be preserve or ota")
    for key in (
        "otast.pif.spoofBuild",
        "otast.pif.spoofProps",
        "otast.pif.spoofProvider",
        "otast.pif.spoofSignature",
        "otast.pif.spoofVendingBuild",
        "otast.pif.spoofVendingSdk",
        "otast.pif.DEBUG",
    ):
        if key in values and values[key] not in {"preserve", "true", "false"}:
            raise OtastError(f"{key} must be preserve, true or false")
    return Authority(path=path, values=values, sha256=sha256_file(path))
