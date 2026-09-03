# OTAST — OTA Source of Truth

OTAST is a transactional Magisk module for the reviewed **Google Pixel / Android 16 (SDK 36)** platform contract. It treats `/data/adb/ota.prop` as the sole authority for OTA-derived platform identity and coordinates a reviewed set of interacting integrity modules without silently replacing user-selected attestation-profile configuration.

**`https://github.com/cbkii/otast` is the only supported OTAST repository and module source.** Older similarly named OTA-governor repositories/modules are deprecated and must not be installed or used. OTAST retains legacy-trace detection only so coexistence or an incomplete migration fails closed.

This repository is the complete public source tree. It includes the Magisk module, deterministic release tooling, a fake-Magisk-root lifecycle harness, private device-fixture tooling, CI, target monitoring, bounded read-only diagnostics, and public-repository initialization checks.

> **Release status:** use this repository's GitHub Releases page and stable Magisk `update.json` channel for the current published version. Release candidates and development source may intentionally be ahead of that stable channel.

## Compatibility scope

Runtime validation is Pixel-model-independent inside an explicitly supported platform profile, but **family-level architectural compatibility is not physical qualification of every Pixel**. The machine-readable registry distinguishes `DESIGN_COMPATIBLE`, `FIXTURE_QUALIFIED`, `DEVICE_VALIDATED`, `RELEASE_QUALIFIED`, and `UNQUALIFIED` evidence levels.

Current repository evidence is summarized in [Compatibility status](docs/COMPATIBILITY-STATUS.md):

- Pixel 9a / `tegu` / `CP1A.260305.018`: `DEVICE_VALIDATED`; it remains below `RELEASE_QUALIFIED` until the current release artefact completes the physical release gate.
- Pixel 8 / `shiba`: `DESIGN_COMPATIBLE`; generic Pixel identity/runtime contracts are covered, but the repository holds no exact fixture or physical qualification proof for a Pixel 8 build.
- undeclared Pixel models/builds: `UNQUALIFIED`, even though the Google Pixel / Android 16 architecture is designed to validate them fail-closed when later qualified.

Device-specific OTA identity must always come from `/data/adb/ota.prop` and agree with the live device. Another model's captured identity is never interchangeable.

See [Compatibility model](docs/COMPATIBILITY-MODEL.md) for the machine-readable contract and qualification semantics.

## Managed contracts

OTAST currently supports reviewed managed profiles for:

- PIF Inject (`playintegrityfix`): separates the selected process-local attestation profile from platform identity. In `preserve` mode profile fingerprint/model/`SECURITY_PATCH` and unrelated spoof options remain user-selected, while reviewed global `system.prop` SPL values are reconciled to OTA authority and the competing automatic `security_patch.sh` runtime writer is neutralized. Structure-sensitive transforms remain exact-hash/anchor gated.
- Tricky Store OSS (`tricky_store`): the exact reviewed v3.1.0 release asset uses OTA-aligned `security_patch.txt` as the managed patch contract. Existing targets and active keybox remain user/upstream data.
- Yurikey (`Yurikey`): reviewed 3.0.x whole-file high-risk writers are neutralized through module identity + reviewed version range + path safety rather than irrelevant historical byte identity; exact original bytes/modes remain restorable.
- Tricky Addon Update Target List (`TA_utl` or `.TA_utl`): reviewed `prop.sh` and generated WebUI Boot Hash transforms remain structure-sensitive and exact-hash/anchor gated.
- Android VBMeta Fixer (`vbmeta-fixer`): the reviewed writer is neutralized only under its exact reviewed-artifact contract. It has **not** been broadened to a version range without proof.

The same registry separately declares read-only **observed dependencies** such as Magisk, Zygisk Next, Vector, Inline Hook Invalidate, and PIF's preserved native/Zygisk surface. OTAST does not manage or rewrite their settings. Conflicting/legacy integrations are represented separately with machine-readable reasons and severity.

Unknown target hashes, unsafe links, authority/source mismatch, active deprecated OTA-governor traces, unsafe PIF auto-patch marker types, managed drift, malformed state, and incomplete transaction recovery all fail closed.

## Android platform authority

Android-version assumptions live in explicit platform profiles under `compatibility/platforms/`. Only `android-16` / SDK 36 is currently supported. Unknown SDK/platform versions fail closed; Android 17 is not claimed and requires its own reviewed profile before support can be added.

For official Pixel authority, system and vendor security patch levels are independent required evidence. `ro.vendor.build.security_patch` is never silently substituted from the system SPL. The platform-visible OTA identity remains separate from PIF's process-local attestation profile.

`ota.prop` may contain `ro.boot.vbmeta.size` derived from official OTA/factory artifacts. That value is retained as **artifact provenance**, not assumed identical to bootloader/libavb runtime size, and OTAST never `resetprop`s runtime VBMeta size. Runtime/source validation compares the OTA-derived VBMeta digest and AVB version with `/proc/bootconfig` when available.

## Safety boundary

OTAST:

- reads authority from `/data/adb/ota.prop`;
- separates official OTA/platform identity, the selected PIF attestation profile, and Tricky Store local-attestation state;
- keeps PIF attestation-profile selection preserve-first unless explicit OTA takeover is requested;
- makes platform-visible system/vendor SPL and the reviewed Tricky Store security-patch contract follow OTA authority;
- records original bytes before the first mutation;
- writes through a journaled transaction;
- verifies every managed hash and mode;
- blocks Apply and Restore when target drift is detected;
- recovers an interrupted transaction during `post-fs-data`;
- does not run a polling service;
- never scans unrelated module trees during normal runtime operation;
- never uses Yurikey Action as an implicit multi-subsystem mutation trigger;
- does not rewrite raw bootloader/libavb evidence or claim software property changes alter hardware-backed RootOfTrust;
- does not configure Zygisk Next, Vector, Inline Hook Invalidate, or detector-hiding settings.

The strict exclusions listed in `compatibility/supported-targets.json` are policy/test sentinels. Runtime discovery never traverses arbitrary installed modules to infer support.

## Local setup in Termux

Keep the repository in Termux private storage, not `/storage/emulated/0`:

```bash
cd "$HOME/repos/otast"
bash scripts/bootstrap-termux.sh
bash scripts/test.sh --full
```

Build the deterministic Magisk release bundle:

```bash
bash scripts/build-release.sh
```

`dist/` receives the Magisk ZIP, portable `.sha256` sidecar and `release-manifest.json`. The ZIP contains `release.properties` binding its embedded release identity and source commit.

## Fake Magisk root

Run the exact built ZIP through synthetic lifecycle qualification:

```bash
bash scripts/fake-magisk-root.sh
```

The harness covers active/staged targets, Apply, Verify, no-op Apply, authority rollover, interrupted-transaction recovery, drift rejection, complete Restore, symlink containment, identity mismatch, unknown hashes and strict-exclusion preservation.

For a private device-derived fixture:

```bash
bash scripts/capture-device-fixture.sh --label pixel-current
bash scripts/reset-fake-magisk-root.sh \
  "$HOME/.local/share/otast/device-fixtures/pixel-current" \
  pixel-current
bash scripts/validate-fake-magisk-root.sh \
  "$HOME/.cache/otast/fake-roots/pixel-current" \
  preflight
```

Raw and sanitized device fixtures stay outside Git.

## Install and operate

See [Installation](docs/INSTALLATION.md) and [Configuration](docs/CONFIGURATION.md).

After installation and reboot, use the Magisk module Action or run the runtime entrypoint as root:

```sh
sh /data/adb/modules/otast/runtime/entry.sh report
sh /data/adb/modules/otast/runtime/entry.sh preflight
sh /data/adb/modules/otast/runtime/entry.sh verify
sh /data/adb/modules/otast/runtime/entry.sh apply
sh /data/adb/modules/otast/runtime/entry.sh restore
```

`Report`, `Preflight` and `Verify` are read-only. The Action menu defaults to `Report` on timeout/no selection. Run `preflight` before the first Apply and after any target-module update.

## Read-only diagnostics

For detector attribution, the bounded root-exposure doctor inspects one running process without cleanup/property/module changes:

```bash
python3 scripts/root-exposure-doctor.py \
  --package com.example.detector \
  --output "$HOME/otast-root-doctor.json"
```

For native/runtime compatibility evidence, a separate collector reads only dependency module IDs explicitly declared by the registry and records runtime page size, ABI, Magisk/Zygisk identity, native-library inventory and ELF `PT_LOAD` alignment evidence:

```bash
python3 scripts/runtime-compatibility-evidence.py \
  --output "$HOME/otast-runtime-compatibility.json"
```

Both diagnostics are read-only. Detector cleanliness is not an OTAST mutation requirement and neither tool reconfigures Zygisk Next, Vector or Inline Hook Invalidate.

## Upstream maintenance

The canonical workflow is:

```bash
otast maintain
otast review TARGET
otast accept TARGET
```

`otast review` now classifies changed source paths semantically. Only a complete `DOCS_OR_CI_ONLY` source delta whose immutable installable module tree is also byte/mode-identical is acceptance-ready. Native, preserved, managed, structure-sensitive, module-identity and unknown changes remain review-required even when they do not immediately alter OTAST's managed shell writers.

## Public GitHub initialization

The downloadable repository ZIP contains no Git history or remote. After full validation:

```bash
bash scripts/init-public-repo.sh
```

See [Public initialization](docs/PUBLIC-INITIALIZATION.md).

## Documentation

- [Compatibility status](docs/COMPATIBILITY-STATUS.md)
- [Compatibility model](docs/COMPATIBILITY-MODEL.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Supported targets](docs/SUPPORTED-TARGETS.md)
- [Configuration](docs/CONFIGURATION.md)
- [Maintenance](docs/MAINTENANCE.md)
- [PIF compatibility](docs/PIF-COMPATIBILITY.md)
- [Fake Magisk root](docs/FAKE-MAGISK-ROOT.md)
- [Device fixtures](docs/DEVICE-FIXTURES.md)
- [Restore and recovery](docs/RESTORE-AND-RECOVERY.md)
- [Development](docs/DEVELOPMENT.md)
- [Release workflow](docs/RELEASE.md)
- [Security](SECURITY.md)

## License

OTAST is licensed under GPL-3.0-only. Reviewed third-party compatibility information and adapted templates are documented in [NOTICE.md](NOTICE.md) and `third_party/licenses/`.
