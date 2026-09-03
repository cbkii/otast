# Architecture

## Authority and platform profile

`/data/adb/ota.prop` is the sole device/OTA authority. Android-version assumptions are owned by an explicit platform profile rather than scattered generic constants. The only supported profile is currently `compatibility/platforms/android-16.json` (Android 16 / SDK 36), mirrored into the small BusyBox-ash `module/runtime/platform.sh` contract and checked for consistency by repository validation.

Unknown SDK/platform versions fail closed. Android 17 is not inferred from Android 16 and requires a separate reviewed profile before it can become supported.

For the Android 16 Google Pixel profile the authority must contain independent system and vendor security patch values, Pixel product/build identity, boot image digest and the complete required VBMeta artifact contract. `ro.vendor.build.security_patch` is not substituted from the system SPL. Runtime/source comparison separately validates live Pixel identity, static system/vendor SPL and bootloader `/proc/bootconfig` evidence.

The platform-visible OTA identity and PIF's process-local attestation profile are separate identity domains. Preserving a selected PIF profile does not permit its values to become ordinary platform identity.

## Qualification model

Pixel-family architectural compatibility and device/build qualification are distinct. The registry defines these evidence tiers:

- `DESIGN_COMPATIBLE` — reviewed architecture/identity contract, no exact fixture or physical proof;
- `FIXTURE_QUALIFIED` — exact device/build authority fixture and synthetic lifecycle proof;
- `DEVICE_VALIDATED` — exact physical device/build lifecycle proof;
- `RELEASE_QUALIFIED` — exact release artefact plus physical release acceptance;
- `UNQUALIFIED` — no device/build compatibility claim.

The Google Pixel / Android 16 family architecture is `DESIGN_COMPATIBLE`, but an undeclared Pixel device/build is `UNQUALIFIED`. Exact current evidence is generated into [Compatibility status](COMPATIBILITY-STATUS.md).

## Compatibility ownership

`compatibility/supported-targets.json` separates three concepts:

1. **Managed targets** — explicit module IDs/paths OTAST may transactionally modify.
2. **Observed dependencies** — explicit read-only environment components whose version/native configuration may affect qualification, including Magisk, Zygisk Next, Vector, Inline Hook Invalidate and PIF's preserved native surface.
3. **Conflicts/exclusions** — explicit integrations that can compete for OTAST-owned identity state, with machine-readable severity/reason.

Normal runtime discovery remains explicit. OTAST does not scan arbitrary installed modules and infer support, and observed dependencies do not become mutation targets.

## Compatibility bases

Each managed target records why its compatibility is trusted:

- whole-file neutraliser with a reviewed module/version-range/path-safety contract;
- structure-sensitive transformation with exact source hash plus anchors;
- exact reviewed installed/distribution artefact.

Yurikey uses the first model. PIF and TA UTL preserve/edit upstream logic and remain exact-hash/anchor gated. VBMeta Fixer remains exact-reviewed because a broader version-range boundary has not been proven.

## Discovery and planning

Discovery checks only declared module IDs and paths. It prefers a staged module under `modules_update` and also evaluates the active module where both exist. Removed, disabled, symlinked and unsafe trees are ignored or rejected according to context.

Each planned path is classified before mutation:

- `CURRENT`: managed bytes, mode and authority are current;
- `NEW`: reviewed path is not yet managed; original bytes or absence are recorded;
- `UPDATE`: previous managed result is intact but authority/template changed;
- `DRIFT`: live bytes/mode differ from recorded managed state; planning stops.

Exact replacement requires the declared compatibility basis. Structure-sensitive transformations require exact reviewed hashes and anchors; whole-file version-range neutralisers require their reviewed module/version/path contract. No fuzzy global matching is used.

## Transactions and persistent state

Apply and Restore acquire a process lock, create a private transaction directory, write `IN_PROGRESS`, journal each path before mutation, preserve the previous state record, atomically replace files, verify bytes/mode, and finally write `COMMITTED`.

A failure rolls the journal back in reverse order. A transaction left `IN_PROGRESS` is recovered during `post-fs-data` before later operations are permitted.

The first Apply stores original bytes/mode under `/data/adb/otast/backups`. Later authority changes retain that original evidence. Restore succeeds only when the current target still equals the recorded managed result and the original backup evidence remains valid.

## Boot behavior

`post-fs-data.sh` performs bounded interrupted-transaction recovery only. `service.sh` exits immediately. OTAST does not automatically Apply or poll target modules.

## Property ownership

`/data/adb/boot_hash` carries `ro.boot.vbmeta.digest`; it never carries `boot.img.sha256`. OTAST's reviewed global contracts keep system/vendor SPL and software-visible boot-state identity coherent with authority while preserving raw bootloader/libavb evidence. `ro.boot.vbmeta.size` from the authority is artifact provenance, not a runtime correction target.

## Upstream-impact maintenance

A branch/repository head is provenance, not by itself the installable compatibility boundary. Target records therefore include distribution identity (branch/tag/release/asset/module/version/hash data as applicable).

`otast review` classifies changed source paths as `DOCS_OR_CI_ONLY`, `PRESERVED_SURFACE_CHANGED`, `NATIVE_DEPENDENCY_CHANGED`, `MANAGED_WHOLE_FILE_CHANGED`, `STRUCTURE_SENSITIVE_CHANGED`, `MODULE_IDENTITY_CHANGED` or `UNKNOWN_PACKAGE_CHANGE`. Specific/higher-risk path rules take precedence over broad globs.

Only a complete `DOCS_OR_CI_ONLY` source delta with a byte/mode-identical immutable module tree is acceptance-ready. Native changes are never auto-accepted merely because OTAST's managed shell writers were unchanged.

## Native/runtime evidence

`scripts/runtime-compatibility-evidence.py` is a bounded read-only collector for explicit dependency IDs. It records runtime page size, ABI, Magisk/Zygisk identity, native-library inventory and ELF `PT_LOAD` alignment evidence. It does not patch or reconfigure Zygisk Next, Vector, Inline Hook Invalidate or other dependencies.

## Legacy transition

Known legacy governor module/state/dispatcher paths remain explicit blockers. OTAST does not adopt or delete them. A restore-first cleanup must prove managed targets were returned to upstream originals before legacy traces are removed.
