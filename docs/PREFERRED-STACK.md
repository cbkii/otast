# Preferred integrity stack

This document describes the preferred architecture, not an automatic migration or uninstall policy. OTAST continues to provide reviewed compatibility adapters where existing installations need deterministic neutralisation and Restore.

## Preferred baseline

- **OTAST** — OTA authority coordinator, transaction owner, platform SPL owner, TrickyStore patch-contract owner and boot-hash/VBMeta contract owner.
- **TrickyStore OSS** — key-attestation provider. OTAST owns only the external security-patch contract and observes keybox/TEE health.
- **One PIF provider** — currently the reviewed KOWX PlayIntegrityFix `inject_s` provider. A second provider may be supported by an adapter, but providers are mutually exclusive because they share the `playintegrityfix` module identity.
- **One Zygisk provider** — treated as an external runtime prerequisite, not an OTA-property authority.

Optional, separate domains:

- **BetterKnownInstalled/BKI** — package-install provenance only. It is not an OTA, PIF or boot-property governor and OTAST must not modify its database or module tree. Current v1.6.1 retains the v1.6.0 migration caveat: apps first patched before v1.6.0 may have already-patched values recorded as their apparent originals, so OTAST must not claim those historical values can be reconstructed.
- **Vector** — LSPosed/ART framework where required by PixelXpert or other explicitly scoped modules; observed only.
- **Root-concealment modules** — separate detection-hiding domain; observed for qualification where useful but not an OTAST authority.
- **AshLooper/AshReXcue** — boot/recovery protection. Their module trees remain write-protected non-targets, but their presence is not an identity conflict.

## Compatibility-only integrations

### TA UTL

TA UTL remains useful as a target-list UI, but current upstream is not a clean target-only implementation. `module/prop.sh` consumes `/data/adb/boot_hash` before its late `disable_prop_handler` check and otherwise writes global sensitive/verified-boot properties. OTAST therefore keeps an exact reviewed compatibility boundary: it moves the disable guard ahead of every property writer, transactionally owns the guard while TA is effective, and neutralises the independent WebUI boot-hash save path. Target-list/UI functionality remains available.

### Yurikey

Yurikey is not part of the preferred stack. Its reviewed service/action/helper surfaces overlap PIF profile, global sensitive properties, TrickyStore patch/keybox, target-list and VBMeta capabilities. Existing supported 3.0.x installations remain transactionally neutralised and exactly restorable; OTAST does not silently uninstall Yurikey or introduce a dependency on it.

### Android VBMeta Fixer

Android VBMeta Fixer is not part of the preferred stack. Its reviewed service is retained only as a legacy compatibility adapter whose competing VBMeta writer is neutralised transactionally. OTAST does not synthesize unrelated AVB fields simply to emulate the module.

## PIF security-patch boundary

PR #41's surgical `security_patch.sh` transform remains intentional. Merely deleting `pif_auto_security_patch` is not a durable ownership guarantee because the upstream helper exposes an enable path that can recreate the marker and resume TrickyStore, PIF `system.prop` and resetprop SPL writes. OTAST therefore preserves upstream profile/marker control while suppressing only the competing write domains. `autopif.sh` and `autopif_ota.sh` remain upstream-owned.

## Non-preferred combinations

The following are outside the preferred baseline unless separately qualified as alternatives:

- Yurikey as a second identity/key/VBMeta governor;
- Android VBMeta Fixer as a second VBMeta writer;
- TA UTL property/VBMeta writer functions;
- multiple PIF providers;
- multiple Zygisk providers;
- TEESimulator, OhMyKeymint or another key-attestation owner concurrently with TrickyStore OSS.

OTAST must report conflicts rather than silently toggling or uninstalling external modules.
