# Supported targets

The machine-readable source of truth is `compatibility/supported-targets.json`.

## PIF Inject

OTAST follows a preserve-first compatibility boundary:

- `action.sh`, `post-fs-data.sh`, `service.sh`, `common_func.sh`, WebUI files and Zygisk binaries remain upstream-owned and byte-identical.
- `pif.prop` is merged rather than replaced. Existing PIF identity and boolean options are preserved by default.
- `otast.pif.identity=ota` is an explicit opt-in that constrains the reviewed Pixel identity fields to `ota.prop`; without that opt-in, AutoPIF selection remains upstream/user-owned.
- individual `otast.pif.spoof*` and `otast.pif.DEBUG` values default to `preserve`; explicit `true` or `false` is required for OTAST to replace a selected boolean.
- `security_patch.sh` is wrapped as a competing writer so one helper cannot silently rewrite the TrickyStore patch contract.
- an existing `/data/adb/tricky_store/pif_auto_security_patch` flag is accepted when it is a safe regular file. The flag is user configuration, not the writer itself; on Apply OTAST neutralizes the reviewed `security_patch.sh`, so later AutoPIF runs cannot rewrite the TrickyStore/runtime security-patch contract while OTAST owns the stack. The flag is preserved so Restore returns the exact pre-OTAST user behavior.

Unknown managed-source hashes, unsafe flag types/links or missing transformation anchors stop preflight. See [PIF compatibility](PIF-COMPATIBILITY.md).

## TrickyStore

The TrickyStore module remains upstream-owned. OTAST preserves `/data/adb/tricky_store/security_patch.txt` by default. `otast.trickystore.securityPatch=ota` explicitly aligns it with the official OTA authority.

Normal Apply does not prune or rebuild `target.txt`. In particular, OTAST prevents Yurikey from deleting the list and repopulating it with every user and system package, but existing targets remain untouched until a separately reviewed reversible migration is performed.

## Yurikey

OTAST replaces only reviewed high-risk writer surfaces and leaves keybox/WebUI/unrelated functionality upstream-owned. Missing required writer paths or unknown hashes stop preflight.

Managed behavior includes:

- root `action.sh` becomes a read-only OTAST Report entrypoint by default, preventing one click from simultaneously killing Google processes, rebuilding targets, rewriting PIF/security-patch state or changing Zygisk Next loader settings;
- `service.sh` generic runtime property rewriting is disabled;
- both reviewed boot-hash entrypoints are redirected through OTAST, eliminating Yurikey's empty-read fallback to a 64-zero VBMeta digest;
- `Yuri/target_txt.sh` is disabled so Yurikey cannot replace `target.txt` with `all user apps + all system apps`;
- reviewed Yurikey security-patch/PIF helper writers redirect through OTAST;
- the broad detection-trace cleanup entrypoint remains disabled by default.

## TA UTL

The supported installed writer contract is TA UTL v4.4 `prop.sh`. OTAST removes only the block that writes `ro.boot.vbmeta.*`; verified-boot, lock-state and non-vbmeta behavior remains in place. The historical `/data/adb/disable_prop_handler` assumption is not used because v4.4 does not consume it.

TA UTL no longer requires Android VBMeta Fixer to be enabled. Other TA UTL versions fail closed until their exact writer surface is reviewed.

## Android VBMeta Fixer

OTAST does not use the upstream VBMeta Fixer algorithm as a source of truth. The reviewed upstream service currently derives runtime values that do not match this Pixel's bootloader/libavb telemetry, including a hard-coded AVB version and a block-size-derived `ro.boot.vbmeta.size`.

If a recognised VBMeta Fixer module is enabled, OTAST replaces its `service.sh` with a no-op. This preserves bootloader/libavb runtime values and prevents the companion-app writer from overwriting them. VBMeta Fixer does not need to be enabled for OTAST operation.

`ota.prop`'s `ro.boot.vbmeta.size` remains required as OTA/factory artifact provenance, but it is not a managed runtime property. OTAST validates runtime/source agreement using the VBMeta digest and AVB version; runtime size is reported separately and never corrected with `resetprop`.

## Legacy governors

Normal Report, Preflight, Apply and Verify stop while any known `ota-sot` or `otasst` module, state root or dispatcher remains. Restore stays available so a failed transition can still recover OTAST-managed originals.

## Version changes

A target update is not accepted because its version string looks compatible. Update compatibility only after reviewing the relevant writer inventory and recording exact hashes and provenance.
