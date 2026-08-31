from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/upstream/ta-utl-boot-hash-v4.4.js"
EXPECTED_SHA256 = "bedb09d2538e28d636ea592a58d2a2234849351d49a95175d54c4de7ccf4d5cc"


class TaWebuiTransactionTests(unittest.TestCase):
    def test_apply_and_restore_recover_exact_webui_bytes_and_mode(self) -> None:
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), EXPECTED_SHA256)

        common = ROOT / "module/runtime/common.sh"
        transaction = ROOT / "module/runtime/transaction.sh"
        ta_runtime = ROOT / "module/runtime/ta.sh"

        with tempfile.TemporaryDirectory(prefix="otast-ta-webui-transaction-") as raw:
            work = Path(raw)
            adb_root = work / "data/adb"
            target = adb_root / "modules/.TA_utl/webui/assets/boot_hash-C0kIcwCH.js"
            desired = work / "desired.js"
            target.parent.mkdir(parents=True)
            target.write_bytes(FIXTURE.read_bytes())
            target.chmod(0o640)
            original = target.read_bytes()

            command = f'''
                ADB_ROOT="{adb_root}"
                OTAST_STATE_ROOT="$ADB_ROOT/otast"
                OTAST_TMP_ROOT="$OTAST_STATE_ROOT/tmp"
                OTAST_AUTHORITY_SHA256='{'1' * 64}'
                OTAST_TEST_MODE=0
                . "{common}" || exit 1
                . "{transaction}" || exit 2
                . "{ta_runtime}" || exit 3

                otast_transform_ta_webui_boot_hash "{target}" "{desired}" || exit 4
                otast_plan_begin || exit 5
                otast_plan_add ta-webui-boot-hash-active-hidden ta-utl "{target}" 0644 "{desired}" exact '{EXPECTED_SHA256}' || exit 6
                [ "$OTAST_PLAN_COUNT" -eq 1 ] || exit 7
                otast_apply_plan || exit 8
                _otast_ta_webui_boot_hash_valid "{target}" || exit 9
                [ "$(otast_file_mode "{target}")" = 0644 ] || exit 10
                otast_verify_managed >/dev/null || exit 11

                otast_restore_all || exit 12
                [ "$(otast_file_mode "{target}")" = 0640 ] || exit 13
                [ ! -e "$OTAST_STATE_ROOT/records/ta-webui-boot-hash-active-hidden.state" ] || exit 14
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=30)

            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main()
