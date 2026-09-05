from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_RUNTIME = ROOT / "module/runtime/authority.sh"
PIF_RUNTIME = ROOT / "module/runtime/pif.sh"


class PifProfileDateValidatorTests(unittest.TestCase):
    def test_profile_security_patch_uses_production_date_validator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otast-pif-date-") as raw:
            work = Path(raw)
            valid = work / "valid.prop"
            invalid_month = work / "invalid-month.prop"
            invalid_day = work / "invalid-day.prop"
            valid.write_text(
                "FINGERPRINT=google/tegu_beta/tegu:CANARY/KEEP/1:user/release-keys\n"
                "MODEL=Pixel 9a\nSECURITY_PATCH=2026-08-05\n",
                encoding="utf-8",
            )
            invalid_month.write_text(
                "FINGERPRINT=google/tegu_beta/tegu:CANARY/KEEP/1:user/release-keys\n"
                "MODEL=Pixel 9a\nSECURITY_PATCH=2026-13-05\n",
                encoding="utf-8",
            )
            invalid_day.write_text(
                "FINGERPRINT=google/tegu_beta/tegu:CANARY/KEEP/1:user/release-keys\n"
                "MODEL=Pixel 9a\nSECURITY_PATCH=2026-08-32\n",
                encoding="utf-8",
            )
            command = f'''
                otast_stop() {{ printf '%s\\n' "$*" >&2; }}
                . "{AUTHORITY_RUNTIME}" || exit 1
                . "{PIF_RUNTIME}" || exit 2
                otast_validate_pif_profile_file "{valid}" || exit 3
                if otast_validate_pif_profile_file "{invalid_month}"; then exit 4; fi
                if otast_validate_pif_profile_file "{invalid_day}"; then exit 5; fi
            '''
            subprocess.run(["busybox", "sh", "-c", command], check=True, timeout=20)


if __name__ == "__main__":
    unittest.main()
