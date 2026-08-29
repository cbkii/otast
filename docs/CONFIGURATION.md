# Configuration

## Authority file

`/data/adb/ota.prop` is required. OTAST consumes, at minimum:

- Pixel product identity and build fingerprint;
- Android SDK and build ID;
- official system and vendor security patch dates;
- `boot.img.sha256`;
- `ro.boot.vbmeta.digest`, `ro.boot.vbmeta.avb_version` and `ro.boot.avb_version`;
- `ro.boot.vbmeta.size` as OTA/factory artifact provenance.

Values are not inferred from target modules. A missing required key, duplicate key, ambiguous whitespace, invalid encoding or source-identity mismatch stops the operation.

`ro.boot.vbmeta.size` is intentionally **not** treated as a runtime correction target. The current OTA extractor records an artifact-derived size, whereas bootloader/libavb publishes runtime `androidboot.vbmeta.size`. OTAST reports both and never writes the runtime size.

When `/proc/bootconfig` is available, Preflight/Apply/Verify require both `androidboot.vbmeta.digest` and `androidboot.vbmeta.avb_version` to be present, non-empty and equal to the OTA authority. Missing bootloader evidence fails closed rather than being treated as an optional comparison. Runtime security-patch props are not used as source evidence because integrity modules may legitimately spoof them; OTAST validates the static `/system` and `/vendor` build properties instead.

## Preserve-first integrity policy

The default policy is to preserve current, working integrity configuration rather than overwrite it merely because an OTA authority exists.

Optional authority keys:

```text
otast.pif.identity=preserve|ota
otast.pif.spoofBuild=preserve|true|false
otast.pif.spoofProps=preserve|true|false
otast.pif.spoofProvider=preserve|true|false
otast.pif.spoofSignature=preserve|true|false
otast.pif.spoofVendingBuild=preserve|true|false
otast.pif.spoofVendingSdk=preserve|true|false
otast.pif.DEBUG=preserve|true|false
otast.trickystore.securityPatch=preserve|ota
```

All omitted keys default to `preserve`.

- `otast.pif.identity=preserve` leaves the current PIF fingerprint/model/security patch/product selection unchanged. `ota` explicitly aligns those identity fields with the OTA authority and enables the reviewed AutoPIF reconciliation transforms.
- Each `otast.pif.spoof*`/`DEBUG` key independently preserves the current value unless explicitly set to `true` or `false`.
- `otast.trickystore.securityPatch=preserve` leaves the current TrickyStore `security_patch.txt` unchanged. `ota` explicitly writes the authority's system/vendor patch dates.

Competing automatic writers remain blocked/neutralized even in preserve mode. Preserve means "do not replace the current selected value", not "allow another module to overwrite it unpredictably".

## Yurikey behavior

For a reviewed Yurikey build OTAST replaces the dangerous multi-purpose entrypoints:

- boot-time generic `resetprop` writer: disabled;
- boot-hash empty-value fallback: redirected to OTAST, so an empty read can never be converted to a 64-zero digest;
- root Magisk Action: read-only OTAST Report by default;
- automatic `target.txt` rebuild (`all user apps + all system apps`): disabled;
- broad detection-trace cleanup: disabled;
- Yurikey security-patch/PIF helper writers: redirected through OTAST.

Existing TrickyStore targets are not destructively pruned by normal Apply. Target-list reduction is a separate migration problem and must remain independently reversible.

## Zygisk Next

OTAST does not let Yurikey Action silently change Zygisk Next loader policy. The hardened Yurikey Action does not run `zygiskd` commands. Current ZN configuration should be managed and validated independently; no OTAST Apply operation changes memory type, linker mode or denylist enforcement.

## Module configuration

`module/otast.conf` is reserved for bounded runtime settings. Current VBMeta handling requires no companion-app polling: the upstream VBMeta Fixer writer is neutralized and bootloader/libavb runtime values are preserved.

## Test-only environment

The fake-root harness supplies:

- `ADB_ROOT` — isolated fake `/data/adb`;
- `OTAST_AUTHORITY` — fake authority path;
- `OTAST_LIVE_PROP_FILE` — captured/synthetic live properties;
- `OTAST_TEST_MODE=1` — accepted only with a non-live root containing `.otast-fake-root`.

Never set `OTAST_TEST_MODE=1` against live `/data/adb`.
