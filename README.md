# OTAST — OTA Source of Truth

OTAST is a transactional Magisk module for **Google Pixel devices running Android 16**. It treats `/data/adb/ota.prop` as the authority for OTA-derived platform identity and coordinates a reviewed set of interacting integrity modules without silently replacing user-selected attestation-profile configuration.

**`https://github.com/cbkii/otast` is the only supported OTAST repository and module source.** Older similarly named OTA-governor repositories/modules are deprecated and must not be installed or used. OTAST retains legacy-trace detection only so coexistence or an incomplete migration fails closed.

This repository is the complete public source tree. It includes the Magisk module, deterministic release tooling, a fake-Magisk-root lifecycle harness, private device-fixture tooling, CI, target monitoring, bounded read-only diagnostics, and public-repository initialization checks.

> **Release status:** use this repository's GitHub Releases page and stable Magisk `update.json` channel for the current published version. Release candidates and development source may intentionally be ahead of that stable channel.

## Device scope

OTAST's project scope and documentation are **Pixel-device model-agnostic** rather than tied to one Pixel model. Device-specific OTA identity must come from the authority file and must agree with the live device; OTAST does not treat another model's captured identity as interchangeable.

Physical-device testing to date is limited to:

- **Pixel 9a**;
- **Pixel 8**.

Other Pixel models are currently **untested**. Treat them as unverified until the exact device/build path has been qualified; OTAST's authority, source-hash and live-identity checks are intended to fail closed rather than assume compatibility.

## Managed contracts

OTAST currently supports reviewed profiles for:

- PIF Inject (`playintegrityfix`): separates the selected attestation profile from platform identity. In `preserve` mode the profile fingerprint/model/`SECURITY_PATCH` and unrelated spoof options remain user-selected, while reviewed global `system.prop` SPL values are reconciled to OTA authority and the competing automatic `security_patch.sh` runtime writer is neutralized. Explicit `otast.pif.identity=ota` may additionally replace the profile identity.
- Tricky Store OSS (`tricky_store`): the reviewed v3.1.0 implementation uses OTA-aligned `security_patch.txt` as the managed patch contract. Existing targets and the active keybox are preserved; OTAST reports keybox/target/TEE health and semantic Verify fails when configured targets depend on an unusable active keybox.
- Yurikey (`Yurikey`): replaces reviewed authority/property writers, the empty-digest-to-zero fallback, the root Action and automatic all-packages TrickyStore target regeneration. Its unattended remote keybox replacement path is also neutralized. Yurikey's Magisk Action becomes read-only Report by default.
- Tricky Addon Update Target List (`TA_utl` or `.TA_utl`): exact reviewed `prop.sh` transformation that removes its overlapping boot-time VBMeta writer while retaining unrelated behavior. The separate WebUI Boot Hash mutation path is explicitly tracked and is not silently treated as governed until its exact installed bundle is reviewed.
- Android VBMeta Fixer (`vbmeta-fixer`): if enabled and recognised, its upstream runtime property writer is neutralized. OTAST preserves bootloader/libavb runtime VBMeta values rather than deriving replacements from block-device geometry.

Unknown target hashes, unsafe links, authority/source mismatch, active deprecated OTA-governor traces, unsafe PIF auto-patch marker types, managed drift, malformed state, and incomplete transaction recovery all fail closed. A normal regular PIF Auto Security Patch marker is preserved while its reviewed global writer is neutralized.

## VBMeta evidence model

`ota.prop` may contain `ro.boot.vbmeta.size` derived from the official OTA/factory artifacts. That value is retained as **artifact provenance**. It is not assumed to be identical to the runtime `androidboot.vbmeta.size` emitted by bootloader/libavb, and OTAST never `resetprop`s runtime VBMeta size.

For runtime/source validation OTAST compares the OTA-derived VBMeta digest and AVB version with `/proc/bootconfig` when bootconfig is available. A mismatch in digest or AVB version blocks Preflight/Apply/Verify. The artifact/runtime size pair is reported side-by-side for diagnosis but is informational.

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
- does not rewrite raw bootloader/libavb evidence or claim software property changes alter hardware-backed RootOfTrust.

The strict exclusions listed in `compatibility/supported-targets.json` are represented only as policy and test sentinels. Runtime discovery never names or traverses them.

## Local setup in Termux

Keep the repository in Termux private storage, not `/storage/emulated/0`. `bootstrap-termux.sh` first restores canonical executable and library modes, so the repository remains usable even when the downloaded ZIP passed through Android shared storage:

```bash
cd "$HOME/repos/otast"
bash scripts/bootstrap-termux.sh
bash scripts/test.sh --full
```

Build the deterministic Magisk release bundle:

```bash
bash scripts/build-release.sh
```

`dist/` receives the Magisk ZIP, its portable `.sha256` sidecar, and `release-manifest.json`. The ZIP also contains `release.properties`, which binds its embedded release identity and source commit.

## Fake Magisk root

Run the exact built ZIP through the synthetic lifecycle qualification:

```bash
bash scripts/fake-magisk-root.sh
```

The harness tests active and staged targets, Apply, Verify, no-op Apply, authority rollover, interrupted-transaction recovery, drift rejection, complete Restore, symlink containment, identity mismatch, unknown hashes, and strict-exclusion byte preservation.

For a private fixture derived from a test Pixel device:

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

## Read-only root-exposure doctor

`OTAST` does not mutate unrelated Zygisk/LSPosed/root-hiding configuration. For detector attribution, an explicit bounded doctor can inspect one running process without exporting private keybox contents or performing cleanup/property/module changes:

```bash
python3 scripts/root-exposure-doctor.py \
  --package com.example.detector \
  --output "$HOME/otast-root-doctor.json"
```

If a detector reports a suspicious or clear mount headline, pass `--detector-mount-claim suspicious` or `--detector-mount-claim clear` to compare that headline with the selected detailed mount evidence. The report records only bounded root-relevant mappings/mount entries, module identity/version metadata, `sepolicy.rule` hashes rather than contents, process mount namespaces, SELinux context evidence where available, and a read-only OTAST Report result. Findings are classified as OTAST semantic inconsistency, another reviewed module's exposure, unknown/needs investigation, or detector/report inconsistency.

## Public GitHub initialization

The downloadable repository ZIP contains no Git history or remote. After full validation:

```bash
bash scripts/init-public-repo.sh
```

This initializes `main`, runs the complete gate, and stages the source without committing or adding a remote. See [Public initialization](docs/PUBLIC-INITIALIZATION.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Supported targets](docs/SUPPORTED-TARGETS.md)
- [PIF compatibility](docs/PIF-COMPATIBILITY.md)
- [Fake Magisk root](docs/FAKE-MAGISK-ROOT.md)
- [Device fixtures](docs/DEVICE-FIXTURES.md)
- [Restore and recovery](docs/RESTORE-AND-RECOVERY.md)
- [Development](docs/DEVELOPMENT.md)
- [Release workflow](docs/RELEASE.md)
- [Security](SECURITY.md)

## License

OTAST is licensed under GPL-3.0-only. Reviewed third-party compatibility information and adapted templates are documented in [NOTICE.md](NOTICE.md) and `third_party/licenses/`.
