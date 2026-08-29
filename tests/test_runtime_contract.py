from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RuntimeContractTests(unittest.TestCase):
    def test_runtime_never_names_strict_exclusions(self) -> None:
        text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "module/runtime").glob("*.sh"))
        for forbidden in ("AshLooper", "AshReXcue", "BetterKnownInstalled", "BKI"):
            self.assertNotIn(forbidden, text)

    def test_compatibility_manifest_templates_match(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["authority"]["device"], "tegu")
        self.assertEqual(manifest["authority"]["sdk"], 36)
        self.assertEqual(set(manifest["strict_exclusions"]), {"AshLooper", "AshReXcue", "BetterKnownInstalled", "BKI"})
        self.assertEqual(
            set(manifest["authority"]["required_vbmeta_keys"]),
            {"ro.boot.vbmeta.digest", "ro.boot.vbmeta.size", "ro.boot.vbmeta.avb_version", "ro.boot.avb_version"},
        )
        self.assertEqual(
            set(manifest["authority"]["runtime_vbmeta_keys"]),
            {"ro.boot.vbmeta.digest", "ro.boot.vbmeta.avb_version", "ro.boot.avb_version"},
        )
        self.assertEqual(
            set(manifest["authority"]["provenance_only_vbmeta_keys"]),
            {"ro.boot.vbmeta.size"},
        )

    def test_id_validation_uses_predicate_not_printing_helper(self) -> None:
        common = ROOT / "module/runtime/common.sh"
        runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "module/runtime").glob("*.sh"))
        self.assertIn("otast_id_valid()", common.read_text(encoding="utf-8"))
        for bad in (
            'otast_safe_id "$prefix" >/dev/null',
            'otast_safe_id "$id" >/dev/null',
            'otast_safe_id "$_otast_id" >/dev/null',
            'otast_safe_id "$_otast_target" >/dev/null',
        ):
            self.assertNotIn(bad, runtime_text)
        subprocess.run(
            [
                "busybox",
                "sh",
                "-c",
                f'. "{common}"; otast_id_valid boot-hash; otast_id_valid pif-autopif-active; '
                '! otast_id_valid "bad/id"; [ "$(otast_safe_id boot-hash)" = boot-hash ]',
            ],
            check=True,
            timeout=10,
        )

    def test_boot_hash_and_live_vbmeta_contract(self) -> None:
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        authority = (ROOT / "module/runtime/authority.sh").read_text(encoding="utf-8")
        self.assertIn("$OTAST_VBMETA_DIGEST", profiles)
        boot_block = profiles.split("otast_plan_global_contracts()", 1)[1].split("otast_plan_pif()", 1)[0]
        self.assertNotIn("$OTAST_BOOT_SHA256", boot_block)
        for key in (
            "ro.boot.vbmeta.digest",
            "ro.boot.vbmeta.size",
            "ro.boot.vbmeta.avb_version",
            "ro.boot.avb_version",
        ):
            self.assertIn(key, authority)

    def test_runtime_vbmeta_contract_excludes_artifact_size(self) -> None:
        authority = (ROOT / "module/runtime/authority.sh").read_text(encoding="utf-8")
        entry = (ROOT / "module/runtime/entry.sh").read_text(encoding="utf-8")
        identity = authority.split("otast_compare_live_identity()", 1)[1].split("otast_compare_bootloader_vbmeta()", 1)[0]
        bootloader = authority.split("otast_compare_bootloader_vbmeta()", 1)[1].split("otast_compare_live_managed_vbmeta()", 1)[0]
        managed = authority.split("otast_compare_live_managed_vbmeta()", 1)[1]

        for key in (
            "ro.boot.vbmeta.digest",
            "ro.boot.vbmeta.avb_version",
            "ro.boot.avb_version",
        ):
            self.assertNotIn(key, identity)
            self.assertIn(key, managed)

        self.assertNotIn("ro.boot.vbmeta.size:OTAST_VBMETA_SIZE", managed)
        self.assertIn("androidboot.vbmeta.digest", bootloader)
        self.assertIn("androidboot.vbmeta.avb_version", bootloader)
        self.assertNotIn("androidboot.vbmeta.size", bootloader)
        self.assertIn("required bootloader VBMeta evidence is missing", bootloader)
        self.assertIn("required bootloader VBMeta evidence is empty", bootloader)
        self.assertNotIn('[ -z "$digest" ] ||', bootloader)
        self.assertNotIn('[ -z "$avb" ] ||', bootloader)

        preflight = entry.split("_otast_preflight()", 1)[1].split("_otast_apply()", 1)[0]
        apply = entry.split("_otast_apply()", 1)[1].split("_otast_verify()", 1)[0]
        verify = entry.split("_otast_verify()", 1)[1].split("_otast_restore()", 1)[0]
        self.assertNotIn("otast_compare_live_managed_vbmeta", preflight)
        self.assertNotIn("otast_compare_live_managed_vbmeta", apply)
        self.assertIn("REBOOT_REQUIRED", apply)
        self.assertIn("NO_CHANGES_REQUIRED", apply)
        self.assertIn("otast_compare_live_managed_vbmeta", verify)

    def test_pif_managed_surface_is_minimal(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        pif = manifest["targets"]["playintegrityfix"]
        self.assertEqual(set(pif["managed_paths"]), {"autopif.sh", "autopif_ota.sh", "pif.prop", "security_patch.sh"})
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        pif_block = profiles.split("otast_plan_pif()", 1)[1].split("otast_plan_ta_utl()", 1)[0]
        for observed in ("action.sh", "post-fs-data.sh", "service.sh"):
            self.assertNotIn(f'"$dir/{observed}"', pif_block)
        self.assertFalse((ROOT / "module/runtime/templates/pif").exists())

    def test_pif_manifest_and_runtime_autopif_allowlists_match(self) -> None:
        manifest = json.loads((ROOT / "compatibility/supported-targets.json").read_text(encoding="utf-8"))
        manifest_hashes = set(
            manifest["targets"]["playintegrityfix"]["accepted_hashes"]["autopif.sh"]
        )
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        pif_block = profiles.split("otast_plan_pif()", 1)[1].split("otast_plan_ta_utl()", 1)[0]
        match = re.search(
            r"otast_transform_pif_autopif \\\n\s+'([0-9a-f,]+)'",
            pif_block,
        )
        self.assertIsNotNone(match)
        runtime_hashes = set(match.group(1).split(","))
        self.assertEqual(runtime_hashes, manifest_hashes)

    def test_legacy_governor_and_auto_generator_fail_closed(self) -> None:
        common = (ROOT / "module/runtime/common.sh").read_text(encoding="utf-8")
        entry = (ROOT / "module/runtime/entry.sh").read_text(encoding="utf-8")
        profiles = (ROOT / "module/runtime/profiles.sh").read_text(encoding="utf-8")
        self.assertIn("otast_require_no_legacy_governors()", common)
        self.assertGreaterEqual(entry.count("otast_require_no_legacy_governors"), 4)
        self.assertIn("pif_auto_security_patch", profiles)

    def test_no_automatic_apply_service(self) -> None:
        service = (ROOT / "module/service.sh").read_text(encoding="utf-8")
        self.assertNotIn("runtime/entry.sh", service)
        self.assertIn("exit 0", service)


if __name__ == "__main__":
    unittest.main()
