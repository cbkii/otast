# Supported targets

The machine-readable source of truth is `compatibility/supported-targets.json`.

## PIF Inject

OTAST follows a compatibility-first boundary:

- `action.sh`, `post-fs-data.sh`, `service.sh`, `common_func.sh`, WebUI files and Zygisk binaries remain upstream-owned and byte-identical.
- `pif.prop` is merged rather than replaced, preserving unrelated comments and options while updating authority-backed identity and user-selected spoof booleans.
- `autopif.sh` retains upstream download, selection, validation, process restart and cleanup flow. Narrow managed blocks constrain the selected Pixel identity and the generated output fields to `ota.prop`.
- `autopif_ota.sh` retains upstream refresh behavior and adds only read-only OTAST preflight after refresh. It never triggers implicit Apply.
- `security_patch.sh` is wrapped as an exact competing writer because OTAST owns the TrickyStore security-patch contract.
- `/data/adb/tricky_store/pif_auto_security_patch` blocks preflight because it would re-enable a competing writer.

Unknown managed-source hashes or missing transformation anchors stop preflight. See [PIF compatibility](PIF-COMPATIBILITY.md).

## TrickyStore

The TrickyStore module remains upstream-owned. OTAST manages only `/data/adb/tricky_store/security_patch.txt` in its advanced matrix format.

## Yurikey

OTAST replaces only reviewed authority-writing entrypoints. Keybox, process, target-list, WebUI and unrelated functionality remain upstream-owned. Missing required writer paths or unknown hashes stop preflight.

## TA UTL

The supported installed writer contract is TA UTL v4.4 `prop.sh`. OTAST removes only the block that writes `ro.boot.vbmeta.*`; verified-boot, lock-state and non-vbmeta behavior remains in place. The historical `/data/adb/disable_prop_handler` assumption is not used because v4.4 does not consume it.

Other TA UTL versions fail closed until their exact writer surface is reviewed.

## Android VBMeta Fixer

OTAST replaces the reviewed `service.sh` as the sole managed writer of:

- `ro.boot.vbmeta.digest`;
- `ro.boot.vbmeta.size`;
- `ro.boot.vbmeta.avb_version`;
- `ro.boot.avb_version`.

The service reads those values directly from `/data/adb/ota.prop` and retains TrickyStore target registration. TA UTL's overlapping block is disabled by its own narrow transform.

## Legacy governors

Normal Report, Preflight, Apply and Verify stop while any known `ota-sot` or `otasst` module, state root or dispatcher remains. Restore stays available so a failed transition can still recover OTAST-managed originals.

## Version changes

A target update is not accepted because its version string looks compatible. Update compatibility only after reviewing the relevant writer inventory and recording exact hashes and provenance.
