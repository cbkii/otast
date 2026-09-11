# OTAST — OTA Source of Truth

OTAST is a transactional Magisk module for the reviewed **Google Pixel / Android 16 (SDK 36)** platform contract. `/data/adb/ota.prop` is the sole authority for the installed OTA/platform identity. OTAST coordinates a reviewed set of interacting integrity modules while keeping the installed platform, raw boot evidence, PIF attestation profile and Tricky Store local-attestation state as separate ownership domains.

**`https://github.com/cbkii/otast` is the only supported OTAST repository and module source.** Older similarly named OTA-governor repositories/modules are deprecated and must not coexist. Legacy-trace handling exists only to fail closed or perform bounded migration of known OTAST state.

The repository includes the Magisk module, deterministic release tooling, fake-root lifecycle qualification, private device-fixture tooling, CI, target monitoring and bounded read-only diagnostics.

> **Release status:** use GitHub Releases and stable `update.json` for the published version. Development source may intentionally be ahead of that channel.

## Compatibility scope

Runtime validation is Pixel-model-independent inside an explicitly supported platform profile, but family architecture is not physical qualification of every Pixel. The registry distinguishes `DESIGN_COMPATIBLE`, `FIXTURE_QUALIFIED`, `DEVICE_VALIDATED`, `RELEASE_QUALIFIED` and `UNQUALIFIED`.

Current evidence is summarized in [Compatibility status](docs/COMPATIBILITY-STATUS.md):

- Pixel 9a / `tegu` / `CP1A.260305.018`: `DEVICE_VALIDATED`;
- Pixel 8 / `shiba`: `DESIGN_COMPATIBLE`, with no exact physical-build qualification recorded;
- undeclared Pixel models/builds: `UNQUALIFIED` until separately qualified.

Device-specific OTA identity must come from `/data/adb/ota.prop` and agree with the live device. Another model's captured identity is never interchangeable.

## Ownership model

Consistency means one clear owner per state/contract, not forcing all identity namespaces to be identical.

- **Installed OTA/platform:** `ota.prop`, static build evidence and official system/vendor SPL.
- **Raw boot evidence:** bootconfig/bootloader/libavb evidence; OTAST reads but does not normalize it.
- **PIF attestation profile:** PIF/user-selected identity. It may intentionally differ from the installed OTA.
- **Tricky Store local attestation:** Tricky Store owns key/TEE behavior; OTAST owns only its reviewed external patch metadata contract.

For PIF Inject (`playintegrityfix`), OTAST selects one canonical profile in `global > active > staged` order. The selected source is never rewritten to OTA identity and is never OTAST Restore-owned. Non-source active/staged module fallbacks are transactional mirrors of that canonical source.

`autopif.sh` and `autopif_ota.sh` remain upstream-owned, so normal AutoPIF profile/executable refresh is preserved. `security_patch.sh` remains exact-hash/anchor gated because it crosses domains; OTAST surgically suppresses only its Tricky Store, PIF `system.prop` and runtime SPL writes while preserving marker/profile-selection behavior.

See [PIF compatibility](docs/PIF-COMPATIBILITY.md).

## Managed contracts

OTAST currently coordinates:

- **PIF Inject:** canonical profile/fallback coherence plus the surgical `security_patch.sh` boundary described above;
- **Tricky Store OSS:** exact reviewed v3.1.0 release asset; OTA-aligned `security_patch.txt` is managed while target/keybox/TEE data remain external;
- **Yurikey:** reviewed 3.0.x high-risk writers are neutralized under the existing version-range/path-safety contract, with exact originals restorable;
- **Tricky Addon Update Target List:** reviewed `prop.sh` and generated WebUI Boot Hash transformations remain exact-hash/anchor gated;
- **Android VBMeta Fixer:** the reviewed writer remains neutralized under its existing exact-artifact contract.

This PIF ownership change does not broaden or remove the existing TA/Yurikey/VBMeta Fixer contracts.

The registry separately declares read-only observed dependencies such as Magisk, Zygisk Next, Vector, Inline Hook Invalidate and PIF's native/Zygisk surface.

Unknown writer hashes, unsafe paths/links, authority mismatch, managed drift, malformed state, incomplete transaction recovery and contradictory verified-boot presentation fail closed.

## Android platform authority

Only `android-16` / SDK 36 is currently supported. Android 17 is not inferred from Android 16.

Official system and vendor SPL are independent required authority values. OTAST's own `system.prop` contains only those two installed-platform values:

```text
ro.build.version.security_patch=<OTA system SPL>
ro.vendor.build.security_patch=<OTA vendor SPL>
```

OTAST no longer writes synthetic `ro.boot.flash.locked`, `ro.boot.vbmeta.device_state`, `ro.boot.verifiedbootstate`, `ro.boot.veritymode` or vendor locked/green values. Runtime boot-state properties and raw bootconfig evidence are reported separately. `Verify` rejects `ro.boot.verifiedbootstate=green` when `ro.boot.verifiedbooterror` or `ro.boot.verifyerrorpart` still exposes a verification error.

`ro.boot.vbmeta.size` in `ota.prop` remains OTA/factory artifact provenance, not a runtime correction target. VBMeta digest/version evidence is compared with `/proc/bootconfig` where available.

## Safety boundary

OTAST:

- inspects authority and live state before mutation;
- uses explicit Apply/Restore transactions with original-byte backups and drift rejection;
- reconciles only declared paths;
- never rewrites the selected canonical PIF profile to OTA identity;
- mirrors only non-source PIF fallbacks;
- leaves AutoPIF executables upstream-owned;
- keeps OTA system/vendor SPL separate from PIF profile SPL;
- restores verified original bytes when retiring superseded OTAST PIF writer ownership;
- recovers interrupted transactions during `post-fs-data`;
- does not poll or automatically Apply;
- does not claim software property changes alter hardware-backed RootOfTrust.

## Local setup in Termux

Keep the repository in Termux private storage:

```bash
cd "$HOME/repos/otast"
bash scripts/bootstrap-termux.sh
bash scripts/test.sh --full
```

Build the deterministic release bundle:

```bash
bash scripts/build-release.sh
```

`dist/` receives the Magisk ZIP, portable `.sha256` sidecar and `release-manifest.json`.

## Fake Magisk root

Run the exact built ZIP through synthetic lifecycle qualification:

```bash
bash scripts/fake-magisk-root.sh
```

The harness covers active/staged targets, Apply/Verify/no-op Apply, authority rollover, interrupted-transaction recovery, drift rejection, Restore, symlink containment, identity mismatch, unknown hashes and strict-exclusion preservation. PIF-specific regression tests additionally cover canonical precedence/mirroring, AutoPIF ownership, surgical writer suppression and verified-boot contradiction handling.

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

```sh
sh /data/adb/modules/otast/runtime/entry.sh report
sh /data/adb/modules/otast/runtime/entry.sh preflight
sh /data/adb/modules/otast/runtime/entry.sh verify
sh /data/adb/modules/otast/runtime/entry.sh apply
sh /data/adb/modules/otast/runtime/entry.sh restore
```

`Report`, `Preflight` and `Verify` are read-only. Run `preflight` before the first Apply and after target-module updates.

## Read-only diagnostics

```bash
python3 scripts/root-exposure-doctor.py \
  --package com.example.detector \
  --output "$HOME/otast-root-doctor.json"

python3 scripts/runtime-compatibility-evidence.py \
  --output "$HOME/otast-runtime-compatibility.json"
```

These diagnostics do not reconfigure target or observed dependency modules.

## Upstream maintenance

```bash
otast maintain
otast review TARGET
otast accept TARGET
```

`otast review` classifies source movement semantically. For PIF, `security_patch.sh` remains structure-sensitive while `autopif.sh`/`autopif_ota.sh` are preserved surfaces. Only a complete `DOCS_OR_CI_ONLY` delta with byte/mode-identical installable module evidence is acceptance-ready automatically.

## Public GitHub initialization

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
- [Repository governance](docs/REPOSITORY-GOVERNANCE.md)
- [Release workflow](docs/RELEASE.md)
- [Security](SECURITY.md)

## License

OTAST is licensed under GPL-3.0-only. Reviewed third-party compatibility information and adapted templates are documented in [NOTICE.md](NOTICE.md) and `third_party/licenses/`.
