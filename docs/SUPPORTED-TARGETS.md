# Supported targets

The machine-readable source of truth is `compatibility/supported-targets.json`; Android-version assumptions are in `compatibility/platforms/`. Generated compatibility status is validated in CI and must match the registry.

## Device/platform scope

OTAST currently supports only the reviewed `android-16` profile (Android 16 / SDK 36) for the Google Pixel family. Family architectural compatibility and device/build qualification are separate:

- Pixel 9a / `tegu` / `CP1A.260305.018` is `DEVICE_VALIDATED` in current repository evidence;
- Pixel 8 / `shiba` is `DESIGN_COMPATIBLE` only;
- undeclared Pixel models/builds are `UNQUALIFIED` until explicit evidence is added;
- `RELEASE_QUALIFIED` is reserved for an exact release artefact that completes the physical release acceptance gate.

Unknown Android SDK/platform versions fail closed rather than inheriting Android 16 assumptions.

## Ownership model

The registry distinguishes managed targets, mutable external configuration, observed dependencies and explicit conflicts/exclusions. Observed dependencies and PIF profile data are not mutated merely because they are relevant to compatibility.

## Compatibility bases

1. **`WHOLE_FILE_VERSION_RANGE`** — complete upstream writers replaced by reviewed OTAST implementations using module identity/version/path safety as the compatibility boundary.
2. **`STRUCTURE_SENSITIVE_TRANSFORM`** — upstream logic is preserved or surgically edited; exact reviewed hashes and anchors remain mandatory.
3. **`EXACT_REVIEWED_ARTIFACT`** — compatibility is tied to a specific reviewed installed/distribution artefact.

No global fuzzy matching replaces exact gates.

## PIF Inject

PIF Inject (`playintegrityfix`) remains structure-sensitive for its competing writer/code surfaces, but its profile files are now explicitly classified as **PIF-owned mutable configuration**.

Runtime profile topology is:

- `/data/adb/pif.prop` — mutable custom/effective profile;
- active module `pif.prop` — packaged fallback/default/reset profile;
- staged module `pif.prop` — future fallback after promotion, not current native fallback.

A different global/fallback fingerprint, model or profile `SECURITY_PATCH` is expected and is not platform drift. OTAST validates these files but does not merge, mirror, recreate or restore them.

Managed PIF surfaces are limited to:

- `autopif.sh`: retain current profile fetching/writing while preventing its tail from deleting managed `system.prop` or exporting profile SPL into OTA-owned state;
- `autopif_ota.sh`: block moving-branch executable replacement until OTAST compatibility review;
- `security_patch.sh`: preserve PIF preference-marker controls but suppress profile-derived Tricky Store/system/vendor SPL writes;
- `system.prop`: reconcile official OTA system/vendor SPL.

Action, post-fs-data, service, common/WebUI/native/Zygisk behavior remains upstream-owned unless separately reviewed.

`otast.pif.identity=ota` is retired; attestation-profile selection belongs to PIF.

The monitored source baseline remains `b994391970b51a2dfefed0e1d420dd6b017756e8`. Upstream `inject_s` head `2f8199a90a150ad98921438608e1e0e951ba2d5f` was re-inspected for this lifecycle work: shell/profile behavior relevant here is unchanged, but its Gradle/Zygisk/native-build dependency movement remains `NATIVE_DEPENDENCY_CHANGED` and review-required.

## Tricky Store OSS

Tricky Store OSS (`tricky_store`) is `EXACT_REVIEWED_ARTIFACT`. `/data/adb/tricky_store/security_patch.txt` is the managed OTA patch contract. `keybox.xml`, `target.txt` and TEE status remain observed/user/upstream data.

## Yurikey

Yurikey uses `WHOLE_FILE_VERSION_RANGE` for the reviewed 3.0.x line (`versionCode` 305..399). Managed high-risk entrypoints are replaced while exact originals/modes remain restorable. A new major/minor line requires review.

## TA UTL

TA UTL (`TA_utl` / `.TA_utl`) remains `STRUCTURE_SENSITIVE_TRANSFORM`. Its reviewed `prop.sh` VBMeta block and generated WebUI Boot Hash save backend are exact-hash/anchor managed while unrelated behavior is preserved.

## Android VBMeta Fixer

Android VBMeta Fixer remains `EXACT_REVIEWED_ARTIFACT`. OTAST neutralizes the reviewed runtime property writer and preserves bootloader/libavb evidence.

## Distribution identity

Each managed target records its installable/distribution model and provenance. Source-only docs/CI movement is distinguished from changed installable packages and native dependencies.

## Semantic upstream impact

`otast review TARGET` classifies changed paths as docs/CI-only, preserved-surface, native-dependency, managed-whole-file, structure-sensitive, module-identity or unknown-package movement. Only a complete docs/CI-only delta with byte/mode-identical installable module evidence may be accepted automatically.

## Legacy governors

Known legacy authority governors remain hard-stop conflicts. Normal Report, Preflight, Apply and Verify stop on their established traces while Restore remains available for safe recovery.
