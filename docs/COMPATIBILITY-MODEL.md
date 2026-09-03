# Compatibility model

OTAST separates **design scope**, **physical qualification**, **managed ownership**, and **observed environment evidence**. Passing a generic Pixel identity check is not the same thing as proving an exact device/build/release artefact.

The machine-readable sources of truth are:

- `compatibility/supported-targets.json` — support tiers, device/build evidence, managed targets, observed dependencies, conflicts, distribution identity and upstream-impact policy;
- `compatibility/platforms/android-16.json` — reviewed Android 16 / SDK 36 platform contract;
- `module/runtime/platform.sh` — small BusyBox-ash runtime mirror whose constants are checked against the machine-readable platform profile by repository verification;
- `docs/COMPATIBILITY-STATUS.md` — generated human-readable status. Do not hand-edit it.

## Qualification tiers

- `DESIGN_COMPATIBLE` — the fail-closed architecture is designed for the declared family/platform, but there is no exact fixture or physical proof.
- `FIXTURE_QUALIFIED` — an exact authority fixture and synthetic lifecycle have been qualified.
- `DEVICE_VALIDATED` — the exact device/build completed physical OTAST lifecycle validation, but the current release artefact has not completed release qualification.
- `RELEASE_QUALIFIED` — the exact release artefact and device/build completed the release acceptance lifecycle.
- `UNQUALIFIED` — no compatibility claim is made.

The Pixel 9a (`tegu`) build `CP1A.260305.018` is the current release reference and is recorded as `DEVICE_VALIDATED`. Release qualification remains a separate evidence gate. Pixel 8 (`shiba`) is currently only `DESIGN_COMPATIBLE`: generic Pixel parsing/runtime tests exist, but this repository does not contain an exact physical qualification record for a Pixel 8 build. Other Android 16 Google Pixels inherit only the family design claim until exact evidence is added.

## Platform profiles

Platform assumptions are versioned rather than spread as editable magic numbers. Android 16 is the only supported profile. The profile owns the Android release/SDK, Pixel identity grammar, required authority keys, static SPL sources, bootconfig evidence, software boot-state keys and native-environment evidence requirements.

Unknown SDKs fail closed. Android 17 must be introduced as a separate reviewed profile and qualification; changing SDK 36 to 37 in place is not a valid upgrade strategy.

For the official Pixel contract, **system SPL and vendor SPL are independent required authority values**. OTAST does not infer `ro.vendor.build.security_patch` from `ro.build.version.security_patch`.

## Ownership classes

### Managed targets

`targets` is the explicit managed-target namespace retained by runtime and maintenance consumers. Every target declares `target_role=MANAGED`, module IDs, compatibility basis, managed/preserved paths, distribution identity and semantic upstream-impact rules.

Managed target discovery remains explicit. No code scans arbitrary Magisk modules and guesses ownership.

### Observed dependencies

`observed_dependencies` declares components that materially affect the supported environment but remain `READ_ONLY`, including Magisk, Zygisk Next, Vector, Inline Hook Invalidate and the preserved PIF native/Zygisk surface. OTAST may collect bounded version/config/native evidence for these components. It does not reconfigure them to obtain a detector-clean result.

### Conflicts

`conflicts` gives explicit competing integrations a reason and severity. `strict_exclusions` remains as the established runtime/test sentinel list and is validated to match the conflict module IDs exactly. Runtime discovery still does not traverse those excluded module trees.

## Compatibility basis

Managed targets declare why their integration is safe:

- `WHOLE_FILE_VERSION_RANGE` — complete high-risk writers are replaced under a reviewed module/version/path contract; unrelated upstream byte changes do not become false incompatibilities. Yurikey 3.0.x is the current example.
- `STRUCTURE_SENSITIVE_TRANSFORM` — OTAST preserves or surgically edits upstream logic; exact reviewed hashes and anchors remain mandatory. PIF and TA UTL use this model.
- `EXACT_REVIEWED_ARTIFACT` — compatibility is bound to an exact reviewed implementation/artefact where a broader contract is not yet proven. Tricky Store OSS and VBMeta Fixer currently use this model.

VBMeta Fixer remains exact-hash gated. No version-range migration is claimed without evidence that module identity/version/path safety fully define the replacement boundary.

## Distribution identity

A Git branch head is provenance, not necessarily the installable thing users run. Each managed target therefore records a `distribution_identity` describing its source/distribution type and the strongest available artefact identity: repository/ref or release, reviewed commit, module ID/version/versionCode/author and asset hash where available.

This lets maintenance distinguish source movement from installable/runtime movement and gives later release qualification a place to bind exact installed artefacts.

## Semantic upstream impact

`impact_policy` classifies changed source paths into:

- `DOCS_OR_CI_ONLY`
- `PRESERVED_SURFACE_CHANGED`
- `NATIVE_DEPENDENCY_CHANGED`
- `MANAGED_WHOLE_FILE_CHANGED`
- `STRUCTURE_SENSITIVE_CHANGED`
- `MODULE_IDENTITY_CHANGED`
- `UNKNOWN_PACKAGE_CHANGE`

Use:

```bash
python3 scripts/classify-target-impact.py playintegrityfix \
  --paths-json tests/fixtures/upstream/pif-b994-to-2f8199-paths.json
```

The real PIF delta from `b994391970b51a2dfefed0e1d420dd6b017756e8` to `2f8199a90a150ad98921438608e1e0e951ba2d5f` changes `.github/workflows/android.yml`, Gradle dependency/wrapper metadata and `zygisk/build.gradle.kts`. It is therefore `NATIVE_DEPENDENCY_CHANGED`, not a managed-shell-writer change. It still requires review; classification is not automatic acceptance.

Current `otast accept` remains deliberately stricter: it advances a monitor baseline automatically only after exact `NO_PACKAGE_IMPACT` evidence. Semantic classification provides the correct compatibility work category for changed packages without weakening that fail-closed acceptance boundary.

## Native/runtime environment evidence

OTAST itself is shell/Python, but its environment includes native Zygisk components. The Android 16 profile therefore requires the qualification system to be able to record, where available:

- runtime page size (`getconf PAGE_SIZE`);
- primary ABI and ABI list;
- declared native-library inventory;
- ELF `LOAD` alignment via `readelf -l`;
- relevant dependency/module build identity;
- Zygisk implementation identity.

These are observational compatibility facts. They do not authorise OTAST to mutate Magisk, Zygisk Next, Vector or Inline Hook Invalidate.
