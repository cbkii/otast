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

Values are not inferred from target modules. A missing `ro.vendor.build.security_patch`, duplicate/ambiguous authority data, unsupported platform identity or source/live mismatch fails closed.

`ro.boot.vbmeta.size` is provenance only. Runtime bootloader/libavb size is reported separately and never resetprop-corrected.

## Identity domains

OTAST keeps three domains explicit:

1. **OTA/platform authority** — installed Google build and official system/vendor SPL in `ota.prop`.
2. **PIF attestation profile** — mutable custom/fallback profile data owned by PIF/user. It may intentionally identify another/newer Pixel Canary build.
3. **Tricky Store OSS local attestation** — targeted KeyAttestation behavior; OTAST coordinates reviewed patch metadata but not user key material.

The platform must remain internally coherent even when the PIF profile intentionally differs.

## PIF profile configuration

Do not place PIF identity or spoof-option policy in `ota.prop`. Configure PIF through its own profile/WebUI.

`otast.pif.identity=ota` is retired and fails closed if still present. Remove it rather than converting a PIF attestation profile into installed-OTA identity.

OTAST observes, validates and reports:

```text
/data/adb/pif.prop
/data/adb/modules/playintegrityfix/pif.prop
/data/adb/modules_update/playintegrityfix/pif.prop
```

but does not mirror or transactionally own them. Runtime effective precedence is global custom profile, then active module fallback. The staged fallback is future state until Magisk promotion/reboot.

PIF profile `SECURITY_PATCH` is profile metadata and may differ from official OTA system/vendor SPL.

## OTA security-patch authority

Official system/vendor patch dates in `ota.prop` remain authoritative for ordinary Android runtime identity.

OTAST reconciles only the reviewed global writers:

- OTAST runtime `system.prop` exposes authority system/vendor SPL;
- PIF `system.prop` follows the same authority while unrelated entries survive;
- PIF `security_patch.sh` is adapted so profile SPL cannot write Tricky Store/system/vendor runtime state;
- Tricky Store OSS `security_patch.txt` follows OTA authority.

PIF's `pif_auto_security_patch` marker remains PIF/user configuration. Enabling it does not change OTAST's effective OTA patch authority.

## PIF AutoPIF executable updates

The reviewed PIF WebUI can invoke `autopif_ota.sh` merely by opening the UI, and the module Action invokes the updater before AutoPIF. While OTAST is applied, executable AutoPIF replacement is therefore review-gated. The installed reviewed AutoPIF engine still retrieves current profile data when executed, and PIF's WebUI GitHub profile-fetch path remains functional.

## Software-visible boot-state policy

OTAST owns the reviewed Android-readable Pixel boot-state contract:

```text
ro.boot.flash.locked=1
ro.boot.vbmeta.device_state=locked
ro.boot.verifiedbootstate=green
ro.boot.veritymode=enforcing
vendor.boot.vbmeta.device_state=locked
vendor.boot.verifiedbootstate=green
```

This does not rewrite raw bootloader/libavb evidence or assert a hardware-backed RootOfTrust change.

## Tricky Store OSS and keybox health

The supported implementation is the exact reviewed Tricky Store OSS v3.1.0 artefact recorded in the compatibility registry. Apply does not choose/replace `keybox.xml` or rebuild `target.txt`. Private keybox material must never be committed or uploaded as evidence.

## Yurikey behavior

For the reviewed Yurikey 3.0.x range, OTAST neutralizes complete high-risk writers while preserving exact originals for Restore. Compatibility is module identity + reviewed version/versionCode + path safety, not irrelevant source-byte equality.

## Observed dependencies

Magisk, Zygisk Next, Vector, Inline Hook Invalidate and PIF native/Zygisk surfaces are observational dependencies. Apply/Restore does not alter their configuration.

## Module configuration

`module/otast.conf` is reserved for bounded OTAST runtime settings. Compatibility is never inferred from arbitrary installed modules.

## Test-only environment

Fake-root tests use isolated `ADB_ROOT`, `OTAST_AUTHORITY`, `OTAST_LIVE_PROP_FILE` and `OTAST_TEST_MODE=1`. Never enable test mode against live `/data/adb`.
