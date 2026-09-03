# Supported targets

The machine-readable source of truth is `compatibility/supported-targets.json`; Android-version assumptions are in the referenced files under `compatibility/platforms/`. The generated [Compatibility status](COMPATIBILITY-STATUS.md) is validated in CI and must match the registry exactly.

## Device/platform scope

OTAST currently supports only the reviewed `android-16` profile (Android 16 / SDK 36) for the Google Pixel family. Family architectural compatibility and device/build qualification are deliberately separate:

- Pixel 9a / `tegu` / `CP1A.260305.018` is `DEVICE_VALIDATED` in current repository evidence;
- Pixel 8 / `shiba` is `DESIGN_COMPATIBLE` only; no exact fixture/build or physical qualification is recorded;
- undeclared Pixel models/builds are `UNQUALIFIED` until explicit evidence is added;
- `RELEASE_QUALIFIED` is reserved for an exact release artefact that completes the physical release acceptance gate.

A model-independent runtime does not make every Pixel physically supported. Unknown Android SDK/platform versions fail closed rather than inheriting Android 16 assumptions.

## Ownership model

The registry distinguishes:

- **managed targets** — reviewed surfaces OTAST may transactionally modify;
- **observed dependencies** — read-only environment evidence such as Magisk, Zygisk Next, Vector, Inline Hook Invalidate and PIF native/Zygisk surfaces;
- **conflicts/exclusions** — explicit integrations that overlap authority ownership, with reason/severity.

Observed dependencies are not managed by OTAST. Runtime target discovery remains explicit and does not infer support from arbitrary installed modules.

## Compatibility bases

Three compatibility bases are currently used by managed targets:

1. **`WHOLE_FILE_VERSION_RANGE`** — complete upstream writers are replaced by OTAST-owned no-op/read-only implementations. Compatibility is based on module identity, reviewed version/versionCode range and safe regular-file/path checks. Harmless upstream source-byte changes do not matter to the replacement boundary; original bytes/mode are still stored and restored exactly.
2. **`STRUCTURE_SENSITIVE_TRANSFORM`** — OTAST preserves or surgically edits upstream logic. Exact reviewed SHA-256 values and transformation anchors remain mandatory.
3. **`EXACT_REVIEWED_ARTIFACT`** — compatibility is tied to a specific reviewed installed/distribution artefact. It remains exact until a broader semantic boundary is separately proven.

No global fuzzy matching replaces exact gates.

## PIF Inject

PIF Inject (`playintegrityfix`) remains `STRUCTURE_SENSITIVE_TRANSFORM` because `autopif.sh`, `autopif_ota.sh` and `security_patch.sh` handling preserves/edits upstream logic.

OTAST separates the selected PIF attestation profile from normal platform-visible identity:

- `pif.prop` is merged rather than blindly replaced; profile fingerprint/model/profile `SECURITY_PATCH` and spoof booleans are preserve-first unless explicit authority policy says otherwise;
- PIF global `system.prop` system/vendor SPL entries follow OTA authority;
- the reviewed `security_patch.sh` global writer is neutralized;
- action/post-fs-data/service/common/WebUI/Zygisk surfaces remain upstream-owned and are classified as preserved or native dependency surfaces, not managed shell writers.

The monitored source baseline remains `b994391970b51a2dfefed0e1d420dd6b017756e8`. The known upstream `inject_s` movement to `2f8199a90a150ad98921438608e1e0e951ba2d5f` changes Gradle/Zygisk build surfaces and is therefore classified `NATIVE_DEPENDENCY_CHANGED`, not auto-accepted as an ordinary package-neutral change.

## Tricky Store OSS

Tricky Store OSS (`tricky_store`) is `EXACT_REVIEWED_ARTIFACT`. The registry records the exact v3.1.0 release identity, module ID, author, versionCode, release-asset filename and SHA-256.

`/data/adb/tricky_store/security_patch.txt` is the managed OTA patch contract. `keybox.xml`, `target.txt` and TEE status remain observed/user/upstream data. OTAST does not choose or publish private key material.

## Yurikey

Yurikey (`Yurikey`) uses `WHOLE_FILE_VERSION_RANGE` for the reviewed 3.0.x line (`versionCode` 305..399). This is the intentional semantic model introduced for whole-file neutralisers: comments, logging changes or other irrelevant historical bytes do not block a replacement whose actual compatibility boundary is module identity + version range + path safety.

Managed high-risk entrypoints include the root Action, generic service property writer, boot/PIF/security-patch helpers, target regeneration, broad cleanup and unattended keybox updater. Their original bytes/mode remain transactionally restorable.

A new major/minor version line still requires review before the version-range contract may expand.

## TA UTL

TA UTL (`TA_utl` / `.TA_utl`) remains `STRUCTURE_SENSITIVE_TRANSFORM`. Its reviewed `prop.sh` VBMeta block and generated WebUI Boot Hash save backend are exact-hash/anchor managed while unrelated behavior is preserved.

A specific Boot Hash writer path is structure-sensitive even though it also matches broad WebUI preserved-surface globs; semantic classification resolves overlapping rules to the higher-risk/specific class.

## Android VBMeta Fixer

Android VBMeta Fixer (`vbmeta-fixer`) remains `EXACT_REVIEWED_ARTIFACT`. OTAST neutralizes the reviewed upstream `service.sh` runtime property writer and preserves bootloader/libavb evidence.

It is a whole-file replacement in implementation, but the repository does not yet hold evidence sufficient to claim a reviewed version-range boundary. It therefore remains exact-gated rather than being migrated merely for convenience.

## Distribution identity

Each managed target records the installable/distribution model appropriate to that upstream: branch build, branch source, release asset, release/workflow artefact, or branch source plus reviewed version range. Source commit/ref is provenance; release asset/module identity and hashes are recorded where available.

This allows a source-only docs/CI change to be distinguished from a changed installable package or native dependency.

## Semantic upstream impact

`otast review TARGET` classifies changed paths deterministically as:

- `DOCS_OR_CI_ONLY`;
- `PRESERVED_SURFACE_CHANGED`;
- `NATIVE_DEPENDENCY_CHANGED`;
- `MANAGED_WHOLE_FILE_CHANGED`;
- `STRUCTURE_SENSITIVE_CHANGED`;
- `MODULE_IDENTITY_CHANGED`;
- `UNKNOWN_PACKAGE_CHANGE`.

Only a complete `DOCS_OR_CI_ONLY` source delta with a byte/mode-identical immutable module tree may be accepted automatically. Every other class remains review-required; a native dependency change is never accepted simply because managed shell writer hashes did not move.

## Legacy governors

Known legacy authority governors remain explicit hard-stop conflicts. Normal Report, Preflight, Apply and Verify stop on their established traces while Restore remains available for safe recovery. Runtime discovery does not scan or mutate arbitrary excluded modules.
