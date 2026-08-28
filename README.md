# OTAST — OTA Source of Truth

OTAST is a transactional Magisk module for a **Pixel 9a (`tegu`) running Android 16**. It treats `/data/adb/ota.prop` as the authority for OTA-derived platform identity and coordinates a reviewed set of interacting integrity modules without silently replacing user-selected runtime spoof configuration.

This repository is the complete public source tree. It includes the Magisk module, deterministic release tooling, a fake-Magisk-root lifecycle harness, private device-fixture tooling, CI, target monitoring, and public-repository initialization checks.

> **Release status:** use the repository's GitHub Releases page and stable Magisk `update.json` channel for the current published version. Release candidates and development source may intentionally be ahead of that stable channel.

## Managed contracts

OTAST currently supports reviewed profiles for:

- PIF Inject (`playintegrityfix`): preserves the current PIF identity and spoof booleans by default. OTA identity takeover is explicit opt-in. The competing automatic security-patch writer remains neutralized; upstream Action, post-fs-data, service, WebUI and updater machinery otherwise stay upstream-owned.
- TrickyStore (`tricky_store`): preserves the current `security_patch.txt` by default. OTA-derived patch alignment is explicit opt-in.
- Yurikey (`Yurikey`): replaces reviewed authority/property writers, the empty-digest-to-zero fallback, the root Action and automatic all-packages TrickyStore target regeneration. Yurikey's Magisk Action becomes read-only Report by default.
- Tricky Addon Update Target List (`TA_utl` or `.TA_utl`): exact reviewed `prop.sh` transformation that removes the overlapping VBMeta writer while retaining unrelated behavior.
- Android VBMeta Fixer (`vbmeta-fixer`): if enabled and recognised, its upstream runtime property writer is neutralized. OTAST preserves the bootloader/libavb runtime VBMeta values rather than deriving replacements from block-device geometry.

Unknown target hashes, unsafe links, authority/source mismatch, active legacy `ota-sot`/`otasst` traces, competing PIF automatic patch generation, managed drift, malformed state, and incomplete transaction recovery all fail closed.

## VBMeta evidence model

`ota.prop` may contain `ro.boot.vbmeta.size` derived from the official OTA/factory artifacts. That value is retained as **artifact provenance**. It is not assumed to be identical to the runtime `androidboot.vbmeta.size` emitted by bootloader/libavb, and OTAST never `resetprop`s runtime VBMeta size.

For runtime/source validation OTAST compares the OTA-derived VBMeta digest and AVB version with `/proc/bootconfig` when bootconfig is available. A mismatch in digest or AVB version blocks Preflight/Apply/Verify. The artifact/runtime size pair is reported side-by-side for diagnosis but is informational.

## Safety boundary

OTAST:

- reads authority from `/data/adb/ota.prop`;
- separates official source identity from user-selected PIF/TrickyStore runtime policy;
- defaults PIF identity/options and TrickyStore patch policy to `preserve`;
- records original bytes before the first mutation;
- writes through a journaled transaction;
- verifies every managed hash and mode;
- blocks Apply and Restore when target drift is detected;
- recovers an interrupted transaction during `post-fs-data`;
- does not run a polling service;
- never scans unrelated module trees;
- never uses Yurikey Action as an implicit multi-subsystem mutation trigger.

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

For a private fixture derived from this Pixel:

```bash
bash scripts/capture-device-fixture.sh --label tegu-current
bash scripts/reset-fake-magisk-root.sh \
  "$HOME/.local/share/otast/device-fixtures/tegu-current" \
  tegu-current
bash scripts/validate-fake-magisk-root.sh \
  "$HOME/.cache/otast/fake-roots/tegu-current" \
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
