from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/runtime-compatibility-evidence.py"


def load_module():
    spec = importlib.util.spec_from_file_location("otast_runtime_compatibility_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeCompatibilityEvidenceTests(unittest.TestCase):
    def test_explicit_module_inventory_comes_from_registry_only(self) -> None:
        module = load_module()
        ids = set(module.explicit_native_module_ids(module.load_registry(ROOT)))
        self.assertEqual(
            ids,
            {"playintegrityfix", "rezygisk", "zygisksu", "vector", "inline_hook_invalidate"},
        )
        for unmanaged in ("Yurikey", "TA_utl", ".TA_utl", "tricky_store", "vbmeta-fixer"):
            self.assertNotIn(unmanaged, ids)

    def test_elf64_load_alignment_parser(self) -> None:
        module = load_module()
        raw = bytearray(64 + 2 * 56)
        raw[:4] = b"\x7fELF"
        raw[4] = 2
        raw[5] = 1
        struct.pack_into("<Q", raw, 32, 64)
        struct.pack_into("<H", raw, 54, 56)
        struct.pack_into("<H", raw, 56, 2)
        struct.pack_into("<I", raw, 64, 1)
        struct.pack_into("<Q", raw, 64 + 48, 16384)
        struct.pack_into("<I", raw, 64 + 56, 1)
        struct.pack_into("<Q", raw, 64 + 56 + 48, 65536)
        result = module.parse_elf_load_alignments(bytes(raw))
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["elf_class"], 64)
        self.assertEqual(result["load_alignments"], [16384, 65536])

    def test_non_elf_and_truncated_elf_are_inconclusive_not_fabricated(self) -> None:
        module = load_module()
        self.assertEqual(module.parse_elf_load_alignments(b"not an elf")["status"], "NOT_ELF")
        self.assertEqual(module.parse_elf_load_alignments(b"\x7fELF" + b"\x00" * 20)["status"], "NOT_ELF")

    def test_collector_is_read_only_and_reports_required_evidence(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for required in (
            "getconf PAGE_SIZE",
            "ro.product.cpu.abi",
            "ro.product.cpu.abilist",
            "native_libraries",
            "load_alignments",
            "runtime_page_size_compatible",
            "zygisk_implementation",
            '"read_only": True',
        ):
            self.assertIn(required, text)
        for forbidden in (
            "resetprop ",
            "magisk --denylist add",
            "magisk --denylist rm",
            "zygiskd denylist",
            "chmod 000",
            "rm -rf /data/adb",
            "mv /data/adb",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
