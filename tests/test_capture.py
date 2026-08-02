from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.otastctl.capture import safe_extract_capture
from tools.otastctl.util import OtastError


class CaptureTests(unittest.TestCase):
    def test_traversal_rejected_and_partial_destination_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "capture.tar"
            with tarfile.open(archive, "w") as handle:
                safe = tarfile.TarInfo("data/adb/ota.prop")
                safe_data = b"ro.product.device=tegu\n"
                safe.size = len(safe_data)
                handle.addfile(safe, io.BytesIO(safe_data))
                bad = tarfile.TarInfo("../outside")
                bad_data = b"bad\n"
                bad.size = len(bad_data)
                handle.addfile(bad, io.BytesIO(bad_data))
            destination = root / "extracted"
            with self.assertRaises(OtastError):
                safe_extract_capture(archive, destination)
            self.assertFalse(destination.exists())
            self.assertFalse((root / "outside").exists())

    def test_regular_capture_extracts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "capture.tar"
            with tarfile.open(archive, "w") as handle:
                info = tarfile.TarInfo("data/adb/ota.prop")
                data = b"ro.product.device=tegu\n"
                info.size = len(data)
                info.mode = 0o600
                handle.addfile(info, io.BytesIO(data))
            destination = root / "extracted"
            safe_extract_capture(archive, destination)
            self.assertEqual((destination / "data/adb/ota.prop").read_bytes(), data)
            self.assertEqual((destination / "data/adb/ota.prop").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
