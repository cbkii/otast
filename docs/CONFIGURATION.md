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

## Identity domains

OTAST keeps three different identity domains explicit rather than forcing them to be byte-for-byte identical:

1. **OTA/platform authority** — the installed Google build, official system/vendor SPL, and artifact-derived VBMeta provenance in `ota.prop`.
2. **PIF attestation profile** — a deliberately selected fingerprint/model/profile patch used by the reviewed PIF implementation. It may differ from the installed device while remaining isolated from ordinary platform properties.
3. **Tricky Store OSS local attestation** — targeted KeyAttestation certificate rewriting. OTAST validates/co-ordinates this layer but does not embed a second competing keystore interception engine.

The platform must be internally coherent even when the PIF profile intentionally differs.

## OTA security-patch authority

The official system/vendor security patch dates in `ota.prop` are authoritative for ordinary Android runtime identity.

OTAST therefore reconciles all reviewed **global** SPL writers during Apply:

- OTAST's own runtime `system.prop` exposes the authority system/vendor SPL;
- PIF `system.prop` is reconciled line-by-line so unrelated entries survive while its global system/vendor SPL matches the authority;
- the reviewed PIF `security_patch.sh` global resetprop/system.prop writer remains neutralized;
- Tricky Store OSS `security_patch.txt` is OTA-owned so its patch metadata agrees with the installed OTA.

After the required reboot, Verify fails if `ro.build.version.security_patch` or `ro.vendor.build.security_patch` is missing or differs from the authority.

The historical `otast.trickystore.securityPatch=preserve` setting is accepted for compatibility with older authority files but is overridden at runtime. OTAST v1.0.2 and earlier could preserve a non-OTA platform SPL; that is no longer the contract.

## Preserve-first PIF attestation profile

The reviewed KOWX712 PIF implementation checks `/data/adb/pif.prop` before its module-local `pif.prop`. Its Zygisk property hook consumes profile `SECURITY_PATCH` only for the targeted DroidGuard process when `spoofProps=true`; this is separate from the reviewed shell `security_patch.sh` global writer.

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

- `otast.pif.identity=preserve` keeps the current PIF fingerprint/model/product/**profile `SECURITY_PATCH`**. OTAST still prevents that profile patch from becoming the platform-visible SPL through PIF's global shell/system.prop path.
- `otast.pif.identity=ota` explicitly aligns the reviewed PIF fingerprint/model/product/profile patch with the OTA authority and enables the reviewed AutoPIF reconciliation transforms.
- Each `otast.pif.spoof*`/`DEBUG` key independently preserves the current value unless explicitly set to `true` or `false`.
- `otast.trickystore.securityPatch` remains parse-compatible with older files, but effective runtime policy is `ota`.

Report identifies the effective PIF profile path, fingerprint/model/profile patch, `spoofProps`, and whether the reviewed process-local patch hook is enabled. A different PIF profile fingerprint is not by itself platform drift.

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

Report also exposes residual `ro.boot.verifiedbooterror` and `ro.boot.verifyerrorpart` values. Their source/semantics are tracked separately and OTAST does not delete them without a reviewed Pixel-specific basis.

## Tricky Store OSS and keybox health

The supported implementation is currently the exact reviewed Tricky Store OSS v3.1.0 build recorded in `compatibility/supported-targets.json`.

Normal OTAST Apply never chooses or replaces `keybox.xml`. Runtime health checks classify the active keybox structurally without printing key material. If Tricky Store has configured targets and the active keybox is empty, malformed, unreadable or unsafe, Verify fails instead of reporting a clean semantic state.

Deep cryptographic keybox qualification and any keybox replacement are explicit local operations. Real keybox/private-key material must never be committed, uploaded as release proof, or printed into OTAST logs.

Physical Pixel 9a validation proved the existing Tricky Store OSS leaf-hack path: after replacing a previously-empty keybox with a cryptographically valid active keybox, fresh local attestation reported locked/Verified RootOfTrust and consistent StrongBox/TEE state. OTAST therefore does not duplicate this interception engine.

## Yurikey behavior

For a reviewed Yurikey build OTAST replaces the dangerous multi-purpose entrypoints:

- boot-time generic `resetprop` writer: disabled;
- boot-hash empty-value fallback: redirected to OTAST, so an empty read can never be converted to a 64-zero digest;
- root Magisk Action: read-only OTAST Report by default;
- automatic `target.txt` rebuild (`all user apps + all system apps`): disabled;
- broad detection-trace cleanup: disabled;
- Yurikey security-patch/PIF helper writers: redirected through OTAST;
- unattended remote keybox replacement: disabled, because the reviewed updater can move aside a working keybox and accept a zero-byte decode result as success.

Existing Tricky Store targets are not destructively pruned by normal Apply. Target-list reduction remains an independently reversible migration.

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
