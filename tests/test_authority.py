from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.otastctl.authority import parse_authority
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "authority/reference-tegu-CP1A.260305.018.ota.prop"


class AuthorityTests(unittest.TestCase):
    def _write_variant(self, root: Path, text: str) -> Path:
        path = root / "ota.prop"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reference_authority(self) -> None:
        authority = parse_authority(FIXTURE)
        self.assertEqual(authority.platform_profile, "android-16")
        self.assertEqual(authority.values["ro.product.device"], "tegu")
        self.assertEqual(authority.values["ro.build.version.sdk"], "36")
        self.assertEqual(authority.values["ro.product.model"], "Pixel 9a")
        self.assertEqual(authority.values["ro.boot.vbmeta.avb_version"], "1.3")
        self.assertEqual(authority.values["ro.boot.avb_version"], "1.3")
        self.assertEqual(authority.values["otast.pif.identity"], "preserve")
        self.assertEqual(authority.values["otast.trickystore.securityPatch"], "ota")

    def test_pixel_8_identity_shape_is_accepted_without_implying_physical_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            text = FIXTURE.read_text(encoding="utf-8")
            text = text.replace("ro.product.device=tegu", "ro.product.device=shiba")
            text = text.replace("ro.product.model=Pixel 9a", "ro.product.model=Pixel 8")
            text = text.replace("google/tegu/tegu:16/", "google/shiba/shiba:16/")
            authority = parse_authority(self._write_variant(root, text))
            self.assertEqual(authority.values["ro.product.device"], "shiba")
            self.assertEqual(authority.values["ro.product.model"], "Pixel 8")

    def test_unknown_android_sdk_is_rejected_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            text = FIXTURE.read_text(encoding="utf-8").replace(
                "ro.build.version.sdk=36",
                "ro.build.version.sdk=37",
            )
            with self.assertRaisesRegex(OtastError, "SDK must match supported platform profile android-16: 36"):
                parse_authority(self._write_variant(root, text))

    def test_missing_vendor_security_patch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lines = [
                line
                for line in FIXTURE.read_text(encoding="utf-8").splitlines()
                if not line.startswith("ro.vendor.build.security_patch=")
            ]
            with self.assertRaisesRegex(OtastError, "ro.vendor.build.security_patch"):
                parse_authority(self._write_variant(root, "\n".join(lines) + "\n"))

    def test_system_and_vendor_security_patch_values_remain_independent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            text = FIXTURE.read_text(encoding="utf-8").replace(
                "ro.vendor.build.security_patch=2026-03-05",
                "ro.vendor.build.security_patch=2026-02-05",
            )
            authority = parse_authority(self._write_variant(root, text))
            self.assertEqual(authority.values["ro.build.version.security_patch"], "2026-03-05")
            self.assertEqual(authority.values["ro.vendor.build.security_patch"], "2026-02-05")
            self.assertNotEqual(
                authority.values["ro.build.version.security_patch"],
                authority.values["ro.vendor.build.security_patch"],
            )

    def test_duplicate_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "ota.prop"
            path.write_bytes(FIXTURE.read_bytes() + b"ro.product.device=tegu\n")
            with self.assertRaisesRegex(OtastError, "duplicate"):
                parse_authority(path)

    def test_nul_rejected_without_false_positive(self) -> None:
        parse_authority(FIXTURE)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "ota.prop"
            path.write_bytes(FIXTURE.read_bytes() + b"bad=before\x00after\n")
            with self.assertRaisesRegex(OtastError, "NUL"):
                parse_authority(path)

    def test_symlink_authority_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "real.prop"
            target.write_bytes(FIXTURE.read_bytes())
            path = root / "ota.prop"
            path.symlink_to(target)
            with self.assertRaisesRegex(OtastError, "missing or unsafe"):
                parse_authority(path)

    def test_non_pixel_product_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            text = FIXTURE.read_text(encoding="utf-8").replace(
                "ro.product.manufacturer=Google",
                "ro.product.manufacturer=Other",
            )
            with self.assertRaisesRegex(OtastError, "Google Pixel"):
                parse_authority(self._write_variant(root, text))

    def test_non_pixel_google_model_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            text = FIXTURE.read_text(encoding="utf-8").replace(
                "ro.product.model=Pixel 9a",
                "ro.product.model=Other Google Device",
            )
            with self.assertRaisesRegex(OtastError, "Google Pixel"):
                parse_authority(self._write_variant(root, text))

    def test_device_fingerprint_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            text = FIXTURE.read_text(encoding="utf-8").replace(
                "ro.product.device=tegu",
                "ro.product.device=shiba",
            )
            with self.assertRaisesRegex(OtastError, "matching Google Pixel"):
                parse_authority(self._write_variant(root, text))

    def test_preserve_policy_is_valid_and_invalid_policy_is_rejected(self) -> None:
        authority = parse_authority(FIXTURE)
        self.assertEqual(authority.values["otast.pif.spoofVendingSdk"], "preserve")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            text = FIXTURE.read_text().replace(
                "otast.pif.spoofVendingSdk=preserve",
                "otast.pif.spoofVendingSdk=maybe",
            )
            with self.assertRaisesRegex(OtastError, "preserve, true or false"):
                parse_authority(self._write_variant(root, text))

    def test_vbmeta_avb_version_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lines = [
                line
                for line in FIXTURE.read_text(encoding="utf-8").splitlines()
                if not line.startswith("ro.boot.vbmeta.avb_version=")
            ]
            with self.assertRaisesRegex(OtastError, "ro.boot.vbmeta.avb_version"):
                parse_authority(self._write_variant(root, "\n".join(lines) + "\n"))


if __name__ == "__main__":
    unittest.main()
