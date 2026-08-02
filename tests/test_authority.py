from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.otastctl.authority import parse_authority
from tools.otastctl.util import OtastError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "authority/reference-tegu-CP1A.260305.018.ota.prop"


class AuthorityTests(unittest.TestCase):
    def test_reference_authority(self) -> None:
        authority = parse_authority(FIXTURE)
        self.assertEqual(authority.values["ro.product.device"], "tegu")
        self.assertEqual(authority.values["ro.build.version.sdk"], "36")
        self.assertEqual(authority.values["ro.product.model"], "Pixel 9a")

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

    def test_wrong_device_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "ota.prop"
            path.write_text(FIXTURE.read_text().replace("ro.product.device=tegu", "ro.product.device=shiba"), encoding="utf-8")
            with self.assertRaisesRegex(OtastError, "tegu"):
                parse_authority(path)


if __name__ == "__main__":
    unittest.main()
