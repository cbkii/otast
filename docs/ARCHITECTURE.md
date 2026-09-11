# Architecture

## Authority and platform profile

`/data/adb/ota.prop` is the sole device/OTA authority. Android-version assumptions are owned by an explicit platform profile rather than scattered generic constants. The only supported profile is currently `compatibility/platforms/android-16.json` (Android 16 / SDK 36), mirrored into the small BusyBox-ash `module/runtime/platform.sh` contract and checked by repository validation.

Unknown SDK/platform versions fail closed. Android 17 is not inferred from Android 16 and requires a separate reviewed profile.

For the Android 16 Google Pixel profile the authority must contain independent system and vendor security patch values, Pixel product/build identity, boot image digest and the complete required VBMeta artifact contract. `ro.vendor.build.security_patch` is never substituted from the system SPL.

## Identity and evidence domains

OTAST deliberately does not make every visible identity equal. It assigns one owner to each domain and prevents one domain's writer from silently exporting state into another:

1. **Installed OTA/platform** - `/data/adb/ota.prop` plus static/live Android build and system/vendor SPL evidence.
2. **Raw boot evidence** - `/proc/bootconfig`, bootloader/libavb state and verification-error evidence. Read-only to OTAST.
3. **PIF attestation profile** - one canonical PIF/user-selected profile plus coherent active/staged fallbacks.
4. **Tricky Store local attestation** - key/TEE behavior and target configuration, with only the reviewed patch metadata contract owned by OTAST.

A PIF profile may intentionally identify another Pixel build. That does not authorize its profile SPL to become ordinary platform SPL.

## Qualification model

Pixel-family architectural compatibility and device/build qualification are distinct. The registry defines:

- `DESIGN_COMPATIBLE` - reviewed architecture/identity contract, no exact fixture or physical proof;
- `FIXTURE_QUALIFIED` - exact device/build authority fixture and synthetic lifecycle proof;
- `DEVICE_VALIDATED` - exact physical device/build lifecycle proof;
- `RELEASE_QUALIFIED` - exact release artefact plus physical release acceptance;
- `UNQUALIFIED` - no device/build compatibility claim.

The Google Pixel / Android 16 family architecture is `DESIGN_COMPATIBLE`, while an undeclared Pixel device/build remains `UNQUALIFIED` until separately qualified.

## Compatibility ownership

`compatibility/supported-targets.json` separates managed targets, read-only observed dependencies and conflicts/exclusions. Within a managed target it can also distinguish an always-managed path from a conditionally managed role.

PIF is the important example:

- `security_patch.sh` is always a reviewed structure-sensitive boundary because it can write outside PIF's own profile domain;
- `autopif.sh` and `autopif_ota.sh` are preserved upstream-owned executables;
- a module-local `pif.prop` is conditionally managed only when it is a non-canonical fallback mirror;
- the selected canonical `pif.prop` source is never OTAST Restore-owned.

Normal runtime discovery remains explicit. OTAST does not scan arbitrary module trees and infer mutation rights.

## PIF canonical-source model

Canonical precedence is:

```text
/data/adb/pif.prop
  > /data/adb/modules/playintegrityfix/pif.prop
  > /data/adb/modules_update/playintegrityfix/pif.prop
```

The first valid available profile is the canonical source. OTAST validates it but does not rewrite its PIF identity to OTA identity. Every installed active/staged PIF fallback other than the source is transactionally mirrored from it.

This creates a stable invariant: whichever fallback PIF later exposes carries the same profile bytes as the selected source, while the source itself remains controlled by PIF/user workflows. An AutoPIF refresh of the global profile therefore becomes a normal `MIRROR_UPDATE_REQUIRED` reconciliation on the next explicit Apply rather than OTAST drift or an implicit rollback.

The staged fallback is reconciled before reboot but is not treated as current runtime-effective state before Magisk promotes it.

## PIF writer boundary

OTAST does not patch `autopif.sh` or `autopif_ota.sh`. Their normal refresh/update lifecycle remains upstream-owned.

`security_patch.sh` is exact-hash/anchor transformed. The transform retains marker controls and profile selection while removing only cross-domain writes:

- Tricky Store patch-file mutation derived from PIF profile SPL;
- PIF `system.prop` generation derived from profile SPL;
- direct `resetprop` of platform system/vendor SPL.

The transformation is byte-idempotent. A previously managed v1 wrapper is rebuilt from the verified original backup, not recursively transformed as if it were upstream source.

## Discovery and planning

Discovery checks only declared module IDs and paths. It prefers a staged module under `modules_update` and also evaluates the active module where both exist. Removed, disabled, symlinked and unsafe trees are ignored or rejected according to context.

Each planned path is classified before mutation as `CURRENT`, `NEW`, `UPDATE` or `DRIFT`. Structure-sensitive transformations require exact reviewed hashes and anchors; whole-file version-range neutralizers require their reviewed module/version/path contract. No fuzzy global matching is used.

## Transactions and persistent state

Apply and Restore acquire a process lock, create a private transaction directory, write `IN_PROGRESS`, journal each path before mutation, preserve the previous state record, atomically replace files, verify bytes/mode, and finally write `COMMITTED`.

A failure rolls the journal back in reverse order. A transaction left `IN_PROGRESS` is recovered during `post-fs-data` before later operations are permitted.

The first Apply stores original bytes/mode under `/data/adb/otast/backups`. Later authority changes retain that original evidence. Restore succeeds only when the current target still equals the recorded managed result and original backup evidence remains valid.

Superseded PIF v1 ownership is migrated conservatively: obsolete managed executables/runtime files are restored from verified original backup bytes before their records are retired. Legacy profile ownership records are retired without replacing the current canonical profile. Drift or malformed historical state blocks migration.

## Boot behavior

`post-fs-data.sh` performs bounded interrupted-transaction recovery only. `service.sh` exits immediately. OTAST does not automatically Apply or poll target modules.

## Property ownership

`/data/adb/boot_hash` continues to carry the reviewed VBMeta digest contract used by the existing TA/Yurikey/VBMeta integrations; it never carries `boot.img.sha256`.

OTAST's own `system.prop` now contains only the installed-platform system and vendor SPL values. OTAST no longer writes synthetic `locked`, `green` or `enforcing` boot-state properties.

Raw bootloader/libavb evidence remains read-only. `Verify` rejects a `green` runtime presentation when `ro.boot.verifiedbooterror` or `ro.boot.verifyerrorpart` still exposes verification failure, rather than trying to hide the contradiction with another writer.

`ro.boot.vbmeta.size` from authority remains artifact provenance, not a runtime correction target.

## Reporting and verification

Report keeps the domains separate:

- authority/static installed-platform identity;
- live Android-visible system/vendor SPL and boot-state properties;
- raw bootconfig VBMeta/boot evidence;
- canonical PIF path, role, profile metadata and active/staged mirror relations;
- PIF AutoPIF/update ownership policy;
- Tricky Store health and managed patch state.

Verify checks the relevant invariant for each domain rather than requiring cross-domain byte equality.

## Upstream-impact maintenance

A branch/repository head is provenance, not by itself the installable compatibility boundary. Target records include distribution identity and semantic source-surface classification.

`otast review` classifies changes as `DOCS_OR_CI_ONLY`, `PRESERVED_SURFACE_CHANGED`, `NATIVE_DEPENDENCY_CHANGED`, `MANAGED_WHOLE_FILE_CHANGED`, `STRUCTURE_SENSITIVE_CHANGED`, `MODULE_IDENTITY_CHANGED` or `UNKNOWN_PACKAGE_CHANGE`.

For PIF, changes to `security_patch.sh` are structure-sensitive; AutoPIF executable changes are preserved-surface changes. This prevents ordinary upstream executable refresh from being treated as an OTAST-owned fork while still requiring review of interactions.

Only a complete docs/CI-only delta with a byte/mode-identical immutable module tree is acceptance-ready automatically. Native or authority-crossing changes remain review-required.

## Native/runtime evidence

`scripts/runtime-compatibility-evidence.py` is a bounded read-only collector for explicit dependency IDs. It records runtime page size, ABI, Magisk/Zygisk identity, native-library inventory and ELF `PT_LOAD` alignment evidence. It does not reconfigure those dependencies.

## Legacy transition

Known deprecated OTA-governor traces remain explicit blockers. The PIF v1-to-v2 ownership migration is separately bounded to known OTAST state IDs and verified original backups; it never grants ownership of arbitrary files.
