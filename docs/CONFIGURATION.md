# Configuration

## Authority file and platform profile

`/data/adb/ota.prop` is required and remains the sole device/OTA authority. Android-specific interpretation comes from the explicitly supported platform profile; currently that is only `android-16` (Android 16 / SDK 36).

For this profile OTAST requires, at minimum:

- Pixel product identity, build ID and release fingerprint;
- Android SDK;
- independent official system and vendor security patch dates;
- `boot.img.sha256`;
- `ro.boot.vbmeta.digest`, `ro.boot.vbmeta.avb_version` and `ro.boot.avb_version`;
- `ro.boot.vbmeta.size` as OTA/factory artifact provenance.

Values are not inferred from target modules. Missing vendor SPL, duplicate/ambiguous authority data, unsupported platform identity or source/live mismatch fails closed.

`ro.boot.vbmeta.size` is provenance only. Runtime bootloader/libavb evidence is reported separately and never resetprop-corrected.

## Identity domains

OTAST keeps these domains separate:

1. **OTA/platform authority** - installed Google build and official system/vendor SPL in `ota.prop`.
2. **Raw boot evidence** - bootconfig/libavb/bootloader state. Read-only evidence, not an OTAST spoof target.
3. **PIF attestation profile** - mutable profile identity selected by PIF/user. It may intentionally identify another/newer Pixel build.
4. **Tricky Store OSS local attestation** - targeted KeyAttestation behavior; OTAST coordinates reviewed patch metadata but not user key material.

Consistency means each domain has one clear source and cross-domain writers cannot silently overwrite another domain. It does not mean the PIF fingerprint must equal the installed OTA fingerprint.

## PIF profile configuration

Do not place PIF identity or spoof-option policy in `ota.prop`. Configure PIF through its own profile/WebUI.

`otast.pif.identity=ota` is retired and fails closed if still present.

The possible profile locations are:

```text
/data/adb/pif.prop
/data/adb/modules/playintegrityfix/pif.prop
/data/adb/modules_update/playintegrityfix/pif.prop
```

OTAST selects the canonical source in `global > active > staged` order. The canonical source remains PIF/user-owned. Installed non-source active/staged `pif.prop` files are transactional mirrors so a later fallback cannot expose stale identity metadata.

PIF's runtime precedence remains global custom, then active module fallback. The staged fallback is future state until Magisk promotion/reboot; OTAST includes it in mirror reconciliation so promotion remains coherent.

After AutoPIF/WebUI legitimately changes `/data/adb/pif.prop`, run `Report`. A stale active/staged fallback is shown as `MIRROR_UPDATE_REQUIRED`; explicit Apply copies the canonical bytes to that fallback. OTAST does not rewrite the canonical identity to the installed OTA.

PIF profile `SECURITY_PATCH` is profile metadata and may differ from official OTA system/vendor SPL.

## OTA security-patch authority

Official system/vendor patch dates in `ota.prop` remain authoritative for ordinary Android runtime identity.

OTAST's own runtime `system.prop` contains only:

```text
ro.build.version.security_patch=<OTA system SPL>
ro.vendor.build.security_patch=<OTA vendor SPL>
```

PIF `security_patch.sh` is exact-hash/anchor transformed only at the cross-domain boundary: its user marker and profile-selection flow remain, but PIF profile SPL cannot write Tricky Store patch metadata, PIF `system.prop`, or runtime system/vendor SPL. Tricky Store OSS `security_patch.txt` continues to follow OTA authority.

`/data/adb/tricky_store/pif_auto_security_patch` remains PIF/user configuration. Its bytes and mode are preserved.

## PIF AutoPIF executable updates

`autopif.sh` and `autopif_ota.sh` are upstream-owned. OTAST does not patch or freeze either executable. Normal AutoPIF profile refresh and executable refresh therefore remain available.

Upstream changes are still classified and reviewed for interactions, but OTAST does not turn a moving upstream executable into a locally owned fork unless it actually crosses an OTAST authority boundary.

## Verified-boot evidence

OTAST no longer writes a synthetic locked/green/enforcing presentation. In particular, its own `system.prop` does not set:

```text
ro.boot.flash.locked
ro.boot.vbmeta.device_state
ro.boot.verifiedbootstate
ro.boot.veritymode
vendor.boot.vbmeta.device_state
vendor.boot.verifiedbootstate
```

`Report` prints Android runtime-visible boot properties separately from raw bootconfig evidence. `Verify` fails if `ro.boot.verifiedbootstate=green` is presented while `ro.boot.verifiedbooterror` or `ro.boot.verifyerrorpart` still contains verification-error evidence.

OTAST continues to validate OTA-derived VBMeta digest/version against available bootloader evidence; it does not claim that a software property changes hardware-backed RootOfTrust.

## Tricky Store OSS and keybox health

The supported implementation is the exact reviewed Tricky Store OSS v3.1.0 artefact recorded in the compatibility registry. Apply does not choose/replace `keybox.xml` or rebuild `target.txt`. Private keybox material must never be committed or uploaded as evidence.

## Other managed integrations

This PIF ownership correction does not change the existing reviewed TA UTL, Yurikey or Android VBMeta Fixer contracts. Their current transforms/neutralizers and Restore behavior remain governed by `compatibility/supported-targets.json`.

## Observed dependencies

Magisk, Zygisk Next, Vector, Inline Hook Invalidate and PIF native/Zygisk surfaces are observational dependencies. Apply/Restore does not alter their configuration.

## Module configuration

`module/otast.conf` is reserved for bounded OTAST runtime settings. Compatibility is never inferred from arbitrary installed modules.

## Test-only environment

Fake-root tests use isolated `ADB_ROOT`, `OTAST_AUTHORITY`, `OTAST_LIVE_PROP_FILE` and `OTAST_TEST_MODE=1`. Never enable test mode against live `/data/adb`.
