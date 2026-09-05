from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .compatibility import load_platform
from .util import OtastError, sha256_file

ROOT = Path(__file__).resolve().parents[2]
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DEVICE_RE = re.compile(r"^[a-z0-9_]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
AVB_RE = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class Authority:
    path: Path
    values: dict[str, str]
    sha256: str
    platform_profile: str


def parse_authority(
    path: Path,
    *,
    platform_profile: str = "android-16",
    root: Path | None = None,
) -> Authority:
    repo_root = (root or ROOT).resolve()
    profile = load_platform(repo_root, platform_profile)
    authority_contract = profile.get("authority")
    device_contract = profile.get("device_family")
    if not isinstance(authority_contract, dict) or not isinstance(device_contract, dict):
        raise OtastError(f"platform profile is incomplete: {platform_profile}")
    required = authority_contract.get("required_keys")
    if not isinstance(required, list) or not required or not all(isinstance(item, str) and item for item in required):
        raise OtastError(f"platform authority contract is invalid: {platform_profile}")

    android_release_value = profile.get("android_release")
    sdk_value = profile.get("sdk")
    if not isinstance(android_release_value, str) or not android_release_value.isdigit():
        raise OtastError(f"platform android_release is invalid: {platform_profile}")
    if not isinstance(sdk_value, int) or isinstance(sdk_value, bool) or sdk_value <= 0:
        raise OtastError(f"platform SDK is invalid: {platform_profile}")
    android_release = android_release_value
    expected_sdk = str(sdk_value)

    manufacturer_contract = device_contract.get("manufacturer")
    model_prefix_contract = device_contract.get("model_prefix")
    fingerprint_vendor_contract = device_contract.get("fingerprint_vendor")
    fingerprint_suffix_contract = device_contract.get("fingerprint_suffix")
    for label, value in (
        ("manufacturer", manufacturer_contract),
        ("model_prefix", model_prefix_contract),
        ("fingerprint_vendor", fingerprint_vendor_contract),
        ("fingerprint_suffix", fingerprint_suffix_contract),
    ):
        if not isinstance(value, str) or not value:
            raise OtastError(f"platform device-family field is invalid: {platform_profile}.{label}")

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

    missing = [key for key in required if not values.get(key)]
    if missing:
        raise OtastError("authority is missing: " + ", ".join(missing))

    device = values["ro.product.device"]
    manufacturer = values["ro.product.manufacturer"]
    model = values["ro.product.model"]
    fingerprint = values["ro.build.fingerprint"]
    sdk = values["ro.build.version.sdk"]

    if not DEVICE_RE.fullmatch(device):
        raise OtastError("authority Pixel device identity is malformed")
    if sdk != expected_sdk:
        raise OtastError(f"authority SDK must match supported platform profile {platform_profile}: {expected_sdk}")
    if manufacturer != manufacturer_contract or not model.startswith(model_prefix_contract):
        raise OtastError("authority product identity must describe a Google Pixel device")
    expected_fingerprint_prefix = f"{fingerprint_vendor_contract}/{device}/{device}:{android_release}/"
    if not fingerprint.startswith(expected_fingerprint_prefix) or not fingerprint.endswith(fingerprint_suffix_contract):
        raise OtastError(f"authority fingerprint is not a matching Google Pixel Android {android_release} release fingerprint")

    for key, label in (
        ("ro.build.version.security_patch", "system"),
        ("ro.vendor.build.security_patch", "vendor"),
    ):
        if not DATE_RE.fullmatch(values[key]):
            raise OtastError(f"invalid {label} security patch date")
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
    if identity_policy != "preserve":
        raise OtastError(
            "otast.pif.identity=ota is retired; remove the key and let PIF own its attestation profiles"
        )
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
        if values.get(key, "preserve") != "preserve":
            raise OtastError(f"{key} takeover is retired; remove the key and let PIF own this option")
    return Authority(path=path, values=values, sha256=sha256_file(path), platform_profile=platform_profile)
