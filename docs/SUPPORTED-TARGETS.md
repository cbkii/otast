# Supported targets

The machine-readable source of truth is `compatibility/supported-targets.json`.

## Compatibility policy

OTAST intentionally distinguishes two kinds of managed integration:

1. **Whole-file neutralizers** — OTAST replaces the complete upstream writer with a small OTAST-owned no-op/read-only entrypoint. These are gated by module identity, a reviewed compatible version range, and safe regular-file/path checks. The upstream file's exact SHA-256 is diagnostic provenance only; harmless upstream byte changes must not block installation. OTAST still records the original bytes and mode exactly and Restore must recover them exactly.
2. **Structure-sensitive transforms** — OTAST preserves substantial upstream logic and edits selected blocks/anchors. These remain exact-hash gated because a changed upstream layout can make a surgical transform unsafe even when the module version string is unchanged.

A hash mismatch by itself is therefore not a failure for a whole-file neutralizer. An unsupported module/version, unsafe path type, missing required file, changed transformation anchors, or unknown structure-sensitive source remains a fail-closed condition.

## Device scope

OTAST is documented for Google Pixel devices rather than a single Pixel model. Physical-device testing to date is limited to **Pixel 9a** and **Pixel 8**. Other Pixel models remain untested until their exact device/build path and managed-module combination have been qualified.

This model-agnostic documentation does not weaken the fail-closed compatibility boundary: authority identity, live-device identity, supported module/version contracts and structure-sensitive transformation anchors must still match what the running release accepts.

## PIF Inject

OTAST separates the selected PIF attestation profile from ordinary platform-visible identity:

- `action.sh`, `post-fs-data.sh`, `service.sh`, `common_func.sh`, WebUI files and Zygisk binaries remain upstream-owned and byte-identical.
- `pif.prop` is merged rather than blindly replaced. Its fingerprint/model/profile `SECURITY_PATCH` and spoof booleans are preserved by default for the process-local attestation profile.
- `otast.pif.identity=ota` is an explicit opt-in that constrains the reviewed profile identity fields to `ota.prop`; without that opt-in, AutoPIF selection remains upstream/user-owned.
- individual `otast.pif.spoof*` and `otast.pif.DEBUG` values default to `preserve`; explicit `true` or `false` is required for OTAST to replace a selected boolean.
- PIF's global `system.prop` SPL entries are reconciled to the official OTA system/vendor security patch so profile values cannot leak into normal Android runtime identity.
- `security_patch.sh` is transformed into a managed no-op competing writer.
- an existing `/data/adb/tricky_store/pif_auto_security_patch` flag is accepted when it is a safe regular file. The flag is user configuration, not the writer itself; OTAST preserves it and neutralizes the reviewed global writer on Apply.

PIF's `autopif.sh`, `autopif_ota.sh` and `security_patch.sh` handling preserves portions of upstream code, so those structure-sensitive transforms remain exact-hash/anchor gated. Unsafe flag types/links or missing transformation anchors stop Preflight. See [PIF compatibility](PIF-COMPATIBILITY.md).

## Tricky Store OSS

The supported implementation is the exact reviewed Tricky Store OSS v3.1.0 build recorded in `compatibility/supported-targets.json`.

`/data/adb/tricky_store/security_patch.txt` is OTA-owned for the supported runtime contract and is aligned to the official system/vendor security patch. Normal Apply does not choose or replace `keybox.xml` and does not prune or rebuild `target.txt`.

Runtime health checks validate target/keybox readiness without printing key material. If configured targets depend on an empty, malformed, unreadable or unsafe active keybox, Verify fails rather than reporting a clean state. Deep cryptographic keybox validation remains an explicit local operation.

## Yurikey

OTAST replaces only the high-risk whole-file writer surfaces and leaves unrelated functionality upstream-owned. Yurikey compatibility is now based on module identity plus the reviewed **3.0.x** line (`versionCode` 305..399), rather than requiring every managed source file to match one historical SHA-256.

This is deliberate: OTAST replaces these files completely, so comments, logging changes, download URLs or other harmless upstream byte differences do not affect the safety of the managed replacement. Unsafe paths, missing required writers, the wrong module ID, or a Yurikey version outside the reviewed compatibility line still stop Preflight.

Managed behavior includes:

- root `action.sh` becomes a read-only OTAST Report entrypoint by default, preventing one click from simultaneously killing Google processes, rebuilding targets, rewriting PIF/security-patch state or changing Zygisk Next loader settings;
- `service.sh` generic runtime property rewriting is disabled;
- both boot-hash entrypoints are redirected through OTAST, eliminating Yurikey's empty-read fallback to a 64-zero VBMeta digest;
- `Yuri/target_txt.sh` is disabled so Yurikey cannot replace `target.txt` with `all user apps + all system apps`;
- Yurikey security-patch/PIF helper writers redirect through OTAST;
- the broad detection-trace cleanup entrypoint remains disabled by default;
- the unattended remote keybox updater is disabled because it can replace a working keybox with an unusable download/decode result.

Existing Tricky Store targets and the active keybox remain user/upstream data; OTAST does not select replacements for them. Every managed Yurikey file still has its original bytes and mode stored transactionally for exact Restore.

## TA UTL

The supported installed writer contract is TA UTL v4.4, including both the reviewed `prop.sh` writer and the generated WebUI Boot Hash save backend.

OTAST:

- removes only the reviewed `prop.sh` block that writes `ro.boot.vbmeta.*`; verified-boot, lock-state and other non-vbmeta behavior remains in place;
- exact-hash manages `webui/assets/boot_hash-C0kIcwCH.js`, generated from the reviewed v4.4 `webui/scripts/boot_hash.js` source;
- keeps the Boot Hash value readable in the WebUI but makes its direct save shell backend a no-op while OTAST owns `/data/adb/boot_hash` and `ro.boot.vbmeta.digest`;
- preserves every unrelated TA UTL WebUI/action/service path;
- records original bytes/mode transactionally so Restore recovers the exact reviewed TA UTL files.

The generated WebUI asset is not patched heuristically: its exact reviewed SHA-256 and transformation anchors must match. Other TA UTL versions or rebuilt assets fail closed until reviewed. The historical `/data/adb/disable_prop_handler` assumption is not used because v4.4 does not consume it.

TA UTL no longer requires Android VBMeta Fixer to be enabled.

## Android VBMeta Fixer

OTAST does not use the upstream VBMeta Fixer algorithm as a source of truth. The upstream service derives runtime values that do not match the live Pixel device's bootloader/libavb telemetry, including a hard-coded AVB version and a block-size-derived `ro.boot.vbmeta.size`.

For the reviewed **1.2.x** compatibility line (`versionCode` 120..129), OTAST replaces `service.sh` wholesale with a no-op. Because the entire writer is replaced, its upstream file hash is not an installation gate; module identity/version and path safety are the compatibility boundary. Restore still recovers exact original bytes/mode.

VBMeta Fixer does not need to be enabled for OTAST operation.

`ota.prop`'s `ro.boot.vbmeta.size` remains required as OTA/factory artifact provenance, but it is not a managed runtime property. OTAST validates runtime/source agreement using the VBMeta digest and AVB version; runtime size is reported separately and never corrected with `resetprop`.

## Legacy governors

Normal Report, Preflight, Apply and Verify stop while any known `ota-sot` or `otasst` module, state root or dispatcher remains. Restore stays available so a failed transition can still recover OTAST-managed originals.

## Version changes

Version strings are compatibility boundaries, not automatic trust signals. A new major/minor line still requires review before its supported range is expanded. Within a reviewed compatibility line, whole-file neutralizers tolerate harmless source-byte variation; structure-sensitive transforms remain pinned to reviewed hashes/anchors until their changed source is reviewed.
