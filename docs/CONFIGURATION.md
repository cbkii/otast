# Configuration

## Authority file and platform profile

`/data/adb/ota.prop` is required and remains the sole device/OTA authority. Android-specific interpretation comes from the explicitly supported platform profile; currently that is only `android-16` (Android 16 / SDK 36).

For this profile OTAST requires, at minimum:

- Pixel product identity, build ID and release fingerprint;
- Android SDK;
- **independent** official system and vendor security patch dates;
- `boot.img.sha256`;
- `ro.boot.vbmeta.digest`, `ro.boot.vbmeta.avb_version` and `ro.boot.avb_version`;
- `ro.boot.vbmeta.size` as OTA/factory artifact provenance.

Values are not inferred from target modules. In particular, a missing `ro.vendor.build.security_patch` is an incomplete authority and fails closed; it is never substituted from the system SPL. Duplicate keys, ambiguous whitespace, invalid encoding, unsafe authority paths, unsupported SDK/platform identity and source/live mismatches also stop the operation.

`ro.boot.vbmeta.size` is intentionally **not** a runtime correction target. The extractor records artifact provenance whereas bootloader/libavb publishes runtime size. OTAST reports the distinction and never writes runtime size.

When `/proc/bootconfig` is available, Preflight/Apply/Verify require the reviewed digest/AVB bootconfig evidence to agree with authority. Unknown Android SDK/platform versions do not inherit Android 16 behavior.

## Identity domains

OTAST keeps three domains explicit:

1. **OTA/platform authority** — installed Google build, official system/vendor SPL and artifact-derived VBMeta provenance in `ota.prop`.
2. **PIF attestation profile** — a deliberately selected process-local fingerprint/model/profile patch used by the reviewed PIF implementation. It may differ from the installed device while remaining isolated from ordinary platform properties.
3. **Tricky Store OSS local attestation** — targeted KeyAttestation certificate rewriting. OTAST coordinates its reviewed patch metadata but does not embed a competing keystore interception engine.

The platform must be internally coherent even when the PIF profile intentionally differs.

## OTA security-patch authority

Official system/vendor security patch dates in `ota.prop` are authoritative for ordinary Android runtime identity and are preserved as two distinct fields even when their values happen to be equal.

OTAST reconciles reviewed **global** SPL writers during Apply:

- OTAST runtime `system.prop` exposes authority system/vendor SPL;
- PIF `system.prop` is reconciled line-by-line so unrelated entries survive while global SPL follows authority;
- reviewed PIF `security_patch.sh` global resetprop/system.prop writing is neutralized;
- Tricky Store OSS `security_patch.txt` follows the OTA patch contract.

After reboot, Verify fails if the static/runtime system or vendor patch cannot be read or differs from authority.

## Preserve-first PIF attestation profile

Optional authority keys remain:

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

- `otast.pif.identity=preserve` keeps the selected PIF fingerprint/model/product/profile `SECURITY_PATCH`; OTAST still prevents that profile patch from becoming platform-visible SPL.
- `otast.pif.identity=ota` explicitly aligns the reviewed PIF profile identity fields with OTA authority.
- Each spoof/debug key preserves the current PIF choice unless explicitly set `true` or `false`.
- the effective supported Tricky Store patch contract remains OTA authority.

A different PIF profile fingerprint is not by itself platform drift.

## Software-visible boot-state policy

OTAST owns the reviewed Android-readable Pixel boot-state contract so managed property writers do not compete over the same values:

```text
ro.boot.flash.locked=1
ro.boot.vbmeta.device_state=locked
ro.boot.verifiedbootstate=green
ro.boot.veritymode=enforcing
vendor.boot.vbmeta.device_state=locked
vendor.boot.verifiedbootstate=green
```

This does not rewrite raw bootloader/libavb evidence and does not assert that software property changes alter hardware-backed RootOfTrust.

## Tricky Store OSS and keybox health

The supported implementation is the exact reviewed Tricky Store OSS v3.1.0 release artefact recorded in the compatibility registry. Normal Apply never chooses or replaces `keybox.xml` and does not rebuild `target.txt`.

Runtime health checks classify the active keybox structurally without printing private material. Deep cryptographic keybox qualification and replacement remain explicit local operations; keybox/private-key material must never be committed or uploaded as OTAST evidence.

## Yurikey behavior

For the reviewed Yurikey 3.0.x version-range contract OTAST neutralizes complete high-risk writer entrypoints while preserving original bytes/modes for Restore. The root Action becomes read-only Report, generic boot-time property writing is disabled, boot/PIF/security-patch helpers are redirected through OTAST authority, broad target regeneration/trace cleanup is disabled and unattended remote keybox replacement is disabled.

Compatibility is based on module identity + reviewed version/versionCode range + safe paths, not irrelevant historical source bytes. A new major/minor line requires separate review.

## Observed dependencies

The compatibility registry declares read-only environment dependencies separately from managed targets. Current evidence contracts include Magisk, Zygisk Next (`rezygisk`/`zygisksu` layouts), Vector, Inline Hook Invalidate and PIF's preserved native/Zygisk surface.

OTAST Apply/Restore does **not** change their configuration. In particular it does not alter Zygisk loader mode, denylist enforcement, Vector/LSPosed policy, IHI target lists or detector-hiding settings.

Collect bounded native/runtime evidence with:

```bash
python3 scripts/runtime-compatibility-evidence.py \
  --output "$HOME/otast-runtime-compatibility.json"
```

The collector reads only registry-declared dependency IDs and records runtime page size, primary ABI/ABI list, Magisk/Zygisk identity, native-library inventory and ELF `PT_LOAD` alignment evidence. Missing/unavailable evidence remains explicit rather than being guessed. The collector is observational only.

## Module configuration

`module/otast.conf` remains reserved for bounded OTAST runtime settings. Compatibility registry/platform profiles are repository/release contracts, not dynamically inferred from arbitrary installed modules.

## Test-only environment

The fake-root harness supplies:

- `ADB_ROOT` — isolated fake `/data/adb`;
- `OTAST_AUTHORITY` — fake authority path;
- `OTAST_LIVE_PROP_FILE` — captured/synthetic live properties;
- `OTAST_TEST_MODE=1` — accepted only with a non-live root containing `.otast-fake-root`.

Never set `OTAST_TEST_MODE=1` against live `/data/adb`.
