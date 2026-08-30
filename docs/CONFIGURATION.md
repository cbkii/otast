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

When `/proc/bootconfig` is available, Preflight/Apply/Verify require both `androidboot.vbmeta.digest` and `androidboot.vbmeta.avb_version` to be present, non-empty and equal to the OTA authority. Missing bootloader evidence fails closed rather than being treated as an optional comparison.

## OTA security-patch authority

The official system/vendor security patch dates in `ota.prop` are authoritative runtime identity, not optional attestation-profile preferences.

OTAST therefore reconciles all reviewed SPL writers to the authority during Apply:

- OTAST's own runtime `system.prop` exposes the authority system/vendor SPL;
- PIF `pif.prop` `SECURITY_PATCH` is forced to the authority while unrelated PIF fingerprint/options may remain preserved;
- an existing PIF `system.prop` is reconciled line-by-line so unrelated entries survive while the system/vendor SPL matches the authority;
- the reviewed PIF automatic security-patch writer remains neutralized;
- TrickyStore `security_patch.txt` is treated as OTA-owned so its KeyAttestation patch metadata agrees with the same authority.

After the required reboot, Verify fails if `ro.build.version.security_patch` or `ro.vendor.build.security_patch` differs from the authority.

The historical `otast.trickystore.securityPatch=preserve` setting is accepted for compatibility with older authority files but is overridden at runtime. OTAST v1.0.2 and earlier could preserve a non-OTA SPL; that is no longer the intended contract.

## Preserve-first PIF policy

Preserve-first behavior still applies to PIF fields that are not OTA source identity.

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

- `otast.pif.identity=preserve` keeps the current PIF fingerprint/model/product selection. It no longer permits a different `SECURITY_PATCH`; SPL always follows `ota.prop`.
- `otast.pif.identity=ota` additionally aligns the reviewed PIF fingerprint/model/product fields with the OTA authority and enables the reviewed AutoPIF reconciliation transforms.
- Each `otast.pif.spoof*`/`DEBUG` key independently preserves the current value unless explicitly set to `true` or `false`.
- `otast.trickystore.securityPatch` remains parse-compatible with older files, but effective runtime policy is `ota`.

## Software boot-state policy

OTAST owns the conservative Android-readable Pixel boot-state contract so Yurikey, TA UTL, PIF and other property modules do not compete over the same values:

```text
ro.boot.flash.locked=1
ro.boot.vbmeta.device_state=locked
ro.boot.verifiedbootstate=green
ro.boot.veritymode=enforcing
vendor.boot.vbmeta.device_state=locked
vendor.boot.verifiedbootstate=green
```

Verify checks the primary `ro.boot.*` values after reboot. OTAST deliberately does **not** set unrelated semantics such as `ro.oem_unlock_supported=0`; that property describes whether the device supports OEM unlocking, not its current lock state.

This software policy does not rewrite hardware-backed RootOfTrust. A local app that performs genuine KeyAttestation can still observe the physical bootloader state unless it is explicitly handled by an attestation-layer mechanism such as a reviewed TrickyStore leaf-hack target.

## Yurikey behavior

For a reviewed Yurikey build OTAST replaces the dangerous multi-purpose entrypoints:

- boot-time generic `resetprop` writer: disabled;
- boot-hash empty-value fallback: redirected to OTAST, so an empty read can never be converted to a 64-zero digest;
- root Magisk Action: read-only OTAST Report by default;
- automatic `target.txt` rebuild (`all user apps + all system apps`): disabled;
- broad detection-trace cleanup: disabled;
- Yurikey security-patch/PIF helper writers: redirected through OTAST.

Existing TrickyStore targets are not destructively pruned by normal Apply. Target-list reduction and targeted local-attestation handling remain independently reversible operations.

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
