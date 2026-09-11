# Supported targets

The machine-readable source of truth is `compatibility/supported-targets.json`; Android-version assumptions are in `compatibility/platforms/`. Generated [Compatibility status](COMPATIBILITY-STATUS.md) is validated in CI and must match the registry.

## Device/platform scope

OTAST currently supports only the reviewed `android-16` profile (Android 16 / SDK 36) for the Google Pixel family. Family architectural compatibility and device/build qualification are separate:

- Pixel 9a / `tegu` / `CP1A.260305.018` is `DEVICE_VALIDATED` in current repository evidence;
- Pixel 8 / `shiba` is `DESIGN_COMPATIBLE` only;
- undeclared Pixel models/builds are `UNQUALIFIED` until explicit evidence is added;
- `RELEASE_QUALIFIED` is reserved for an exact release artefact that completes the physical release acceptance gate.

Unknown Android SDK/platform versions fail closed rather than inheriting Android 16 assumptions.

## Ownership model

The registry distinguishes managed targets, conditionally managed roles, observed dependencies and explicit conflicts/exclusions. Relevance to Play Integrity does not itself grant OTAST mutation ownership.

## Compatibility bases

1. **`WHOLE_FILE_VERSION_RANGE`** - complete upstream writers replaced under a reviewed module/version/path contract.
2. **`STRUCTURE_SENSITIVE_TRANSFORM`** - upstream logic is preserved or surgically edited; exact reviewed source hashes and anchors are mandatory.
3. **`EXACT_REVIEWED_ARTIFACT`** - compatibility is tied to a specific reviewed installed/distribution artefact.

No global fuzzy matching replaces exact gates.

## PIF Inject

PIF Inject (`playintegrityfix`) uses a canonical-source plus fallback-mirror model.

Canonical selection order is:

```text
/data/adb/pif.prop
  > active module pif.prop
  > staged module pif.prop
```

The selected source is PIF/user-owned. OTAST validates it but never rewrites its fingerprint/model/profile SPL to the installed OTA and never makes Restore roll that source backwards.

Every installed non-source active/staged `pif.prop` is a transactional mirror. This prevents stale packaged/staged fallback identity from becoming effective if the global profile is later deleted or a staged module is promoted.

Always-managed PIF surface:

- `security_patch.sh` - exact-hash/anchor transformed only at its cross-domain write boundary. Marker enable/disable and profile selection remain; Tricky Store patch writes, PIF profile-derived `system.prop`, and profile-derived runtime SPL resetprop writes are suppressed.

Conditionally managed PIF surface:

- `pif.prop` - only when the file is a non-canonical active/staged fallback mirror.

Preserved upstream-owned PIF surfaces include:

- `autopif.sh`;
- `autopif_ota.sh`;
- action/post-fs-data/service/common/WebUI/native/Zygisk behavior except where separately declared.

Normal AutoPIF profile and executable refresh therefore remains available. When `/data/adb/pif.prop` changes legitimately, `Report` identifies stale fallback mirrors and explicit Apply reconciles them.

`otast.pif.identity=ota` remains retired.

The current monitored `KOWX712/PlayIntegrityFix@inject_s` baseline is `73552eec78f1e733573192333e9a7453b8de0662`. `security_patch.sh` changes remain `STRUCTURE_SENSITIVE_CHANGED`; AutoPIF executable movement is classified as `PRESERVED_SURFACE_CHANGED` rather than converted into an OTAST-owned fork.

## Tricky Store OSS

Tricky Store OSS (`tricky_store`) remains `EXACT_REVIEWED_ARTIFACT`. `/data/adb/tricky_store/security_patch.txt` is the managed OTA patch contract. `keybox.xml`, `target.txt` and TEE status remain observed/user/upstream data.

## Yurikey

Yurikey retains the existing `WHOLE_FILE_VERSION_RANGE` contract for reviewed 3.0.x builds (`versionCode` 305..399). Managed high-risk entrypoints are replaced while exact originals/modes remain restorable. This PR does not broaden that contract.

## TA UTL

TA UTL (`TA_utl` / `.TA_utl`) retains its existing `STRUCTURE_SENSITIVE_TRANSFORM` contract. Its reviewed `prop.sh` VBMeta block and generated WebUI Boot Hash save backend remain exact-hash/anchor managed while unrelated behavior is preserved.

## Android VBMeta Fixer

Android VBMeta Fixer retains its existing `EXACT_REVIEWED_ARTIFACT` contract. OTAST neutralizes the reviewed runtime property writer and preserves bootloader/libavb evidence.

## OTAST runtime property contract

OTAST's own `system.prop` is limited to official OTA system/vendor SPL. It no longer publishes synthetic locked/green/enforcing verified-boot properties.

Runtime-visible boot properties are evidence, not OTAST-owned truth. `Verify` rejects `green` when verification-error properties remain populated.

## Distribution identity

Each managed target records its installable/distribution model and provenance. Source-only docs/CI movement is distinguished from changed installable packages and native dependencies.

## Semantic upstream impact

`otast review TARGET` classifies changed paths as docs/CI-only, preserved-surface, native-dependency, managed-whole-file, structure-sensitive, module-identity or unknown-package movement. Only a complete docs/CI-only delta with byte/mode-identical installable module evidence may be accepted automatically.

## Legacy ownership migration

Known legacy authority governors remain hard-stop conflicts. Separately, OTAST understands its own superseded PIF state IDs. During explicit Apply it validates old records/backups, restores obsolete PIF writer surfaces from verified originals when required, then retires those records. Drift or malformed state fails closed.
