# Configuration

## Authority file

`/data/adb/ota.prop` is required. OTAST consumes, at minimum:

- Pixel product identity and build fingerprint;
- Android SDK and build ID;
- system and vendor security patch dates;
- `boot.img.sha256`;
- `ro.boot.vbmeta.digest` and `ro.boot.vbmeta.size`;
- optional `otast.pif.*` boolean policy keys.

Values are not inferred from target modules. A missing required key, duplicate key, ambiguous whitespace, invalid encoding or live mismatch stops the operation.

## Module configuration

`module/otast.conf` contains bounded VBMeta Fixer companion timing values:

```sh
OTAST_VBMETA_BOOT_ATTEMPTS=120
OTAST_VBMETA_COMMAND_TIMEOUT=15
```

The runtime clamps invalid or excessive values.

## Test-only environment

The fake-root harness supplies:

- `ADB_ROOT` — isolated fake `/data/adb`;
- `OTAST_AUTHORITY` — fake authority path;
- `OTAST_LIVE_PROP_FILE` — captured/synthetic live properties;
- `OTAST_TEST_MODE=1` — accepted only with a non-live root containing `.otast-fake-root`.

Never set `OTAST_TEST_MODE=1` against live `/data/adb`.
