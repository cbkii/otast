# Compatibility model

OTAST separates **family architectural scope**, **per-device/build qualification**, **managed ownership**, and **observed environment evidence**. Passing a generic Pixel identity check is not the same thing as proving an exact device/build/release artefact.

The machine-readable sources of truth are:

- `compatibility/supported-targets.json` — support tiers, device/build evidence, managed targets, observed dependencies, conflicts, distribution identity and upstream-impact policy;
- `compatibility/platforms/android-16.json` — reviewed Android 16 / SDK 36 platform contract;
- `module/runtime/platform.sh` — small BusyBox-ash runtime mirror whose constants are checked against the machine-readable platform profile;
- `docs/COMPATIBILITY-STATUS.md` — generated human-readable status. Do not hand-edit it.

## Qualification tiers

- `DESIGN_COMPATIBLE` — reviewed architecture/identity contract for a declared device/platform, without exact fixture or physical proof.
- `FIXTURE_QUALIFIED` — exact device/build authority fixture and synthetic lifecycle qualified.
- `DEVICE_VALIDATED` — exact physical device/build completed the OTAST lifecycle, but the current release artefact has not completed release qualification.
- `RELEASE_QUALIFIED` — exact release artefact and device/build completed release acceptance.
- `UNQUALIFIED` — no device/build compatibility claim.

The Google Pixel / Android 16 **family architecture** is `DESIGN_COMPATIBLE`; this is not the default qualification of every Pixel. Any undeclared model/build is explicitly `UNQUALIFIED` until a device record and evidence are added.

Pixel 9a (`tegu`) build `CP1A.260305.018` is the current release reference and is `DEVICE_VALIDATED`. Release qualification remains a separate exact-artefact gate. Pixel 8 (`shiba`) is only `DESIGN_COMPATIBLE`: generic Pixel parsing/runtime tests exist, but this repository has no exact Pixel 8 build fixture or physical qualification record.

## Platform profiles

Platform assumptions are versioned rather than spread as editable magic numbers. Android 16 / SDK 36 is the only supported profile. It owns release/SDK identity, Pixel fingerprint/product grammar, required authority fields, static SPL property sources, bootconfig evidence, software-visible boot-state keys and native-environment evidence requirements.

Unknown SDKs fail closed. Android 17 must be introduced as a separate reviewed profile and qualification; changing `36` constants in place is not a valid support strategy.

For official Pixel authority, **system SPL and vendor SPL are independent required values**. OTAST does not infer `ro.vendor.build.security_patch` from the system SPL.

## Ownership classes

### Managed targets

`targets` is the explicit managed-target namespace. Every target declares `target_role=MANAGED`, module IDs, compatibility basis, managed/preserved surfaces, distribution identity and semantic impact rules.

Managed discovery remains explicit. No runtime code scans arbitrary Magisk modules and guesses ownership.

### Observed dependencies

`observed_dependencies` declares components that materially affect qualification but remain `READ_ONLY`, including Magisk, Zygisk Next (`rezygisk`/`zygisksu` layouts), Vector, Inline Hook Invalidate and PIF's preserved native/Zygisk surface. OTAST can collect bounded version/config/native evidence for these explicit dependencies; it does not reconfigure them to obtain detector-clean results.

### Conflicts

`conflicts` assigns competing integrations an explicit reason and severity. `strict_exclusions` is validated to mirror the conflict module IDs exactly. Runtime discovery still does not traverse those excluded module trees.

## Compatibility basis

Managed targets declare why their integration is safe:

- `WHOLE_FILE_VERSION_RANGE` — complete high-risk writers are replaced under a reviewed module/version/path contract; unrelated upstream byte changes do not create false incompatibilities. Yurikey 3.0.x is the current example.
- `STRUCTURE_SENSITIVE_TRANSFORM` — OTAST preserves or surgically edits upstream logic; exact reviewed SHA-256 values and anchors remain mandatory. PIF and TA UTL use this model.
- `EXACT_REVIEWED_ARTIFACT` — compatibility is bound to an exact reviewed implementation/artefact where a broader contract is not proven. Tricky Store OSS and VBMeta Fixer use this model.

VBMeta Fixer remains exact-gated. No version-range migration is claimed without evidence that module identity/version/path safety completely define its compatibility boundary.

## Distribution identity

A Git branch head is provenance, not necessarily the installable package. Each managed target records a `distribution_identity` appropriate to its upstream: branch build/source, release asset, release/workflow artefact, or source plus reviewed version range. Strongest available evidence includes repository/ref/release, reviewed commit, asset filename/SHA-256, module ID, author, version and versionCode.

## Semantic upstream impact

`impact_policy` classifies changed source paths into:

- `DOCS_OR_CI_ONLY`
- `PRESERVED_SURFACE_CHANGED`
- `NATIVE_DEPENDENCY_CHANGED`
- `MANAGED_WHOLE_FILE_CHANGED`
- `STRUCTURE_SENSITIVE_CHANGED`
- `MODULE_IDENTITY_CHANGED`
- `UNKNOWN_PACKAGE_CHANGE`

Specific/higher-risk matches win when globs overlap. A broad WebUI/preserved pattern therefore cannot conceal a known structure-sensitive writer.

The real PIF delta from `b994391970b51a2dfefed0e1d420dd6b017756e8` to `2f8199a90a150ad98921438608e1e0e951ba2d5f` changes workflow/Gradle/Zygisk-build surfaces and deterministically classifies as `NATIVE_DEPENDENCY_CHANGED`. It remains review-required.

`otast review` combines semantic source classification with immutable installable-module-tree comparison. Only a **complete `DOCS_OR_CI_ONLY` source delta whose old/new module trees are also byte/mode identical** is acceptance-ready. If a docs-only source delta changes the package, the result becomes `UNKNOWN_PACKAGE_CHANGE`. Native and every other runtime-relevant class remain review-required even when current package bytes happen to be identical.

## Native/runtime environment evidence

OTAST itself is shell/Python, but its supported environment includes native Zygisk components. The Android 16 profile requires qualification evidence where available for:

- runtime page size (`getconf PAGE_SIZE`);
- primary ABI and ABI list;
- explicit dependency native-library inventory;
- ELF `PT_LOAD` alignment/page-size compatibility;
- dependency/module version/build identity;
- Zygisk implementation identity.

Collect it with:

```bash
python3 scripts/runtime-compatibility-evidence.py \
  --output "$HOME/otast-runtime-compatibility.json"
```

The collector derives module IDs only from the compatibility registry and parses bounded ELF program-header prefixes itself. These are observational facts; they do not authorise OTAST to patch or reconfigure Magisk, Zygisk Next, Vector or Inline Hook Invalidate.
