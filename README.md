# OTAST — OTA Source of Truth

OTAST is a transactional Magisk module for a **Pixel 9a (`tegu`) running Android 16**. It treats `/data/adb/ota.prop` as the sole authority for the device's OTA identity and keeps a reviewed set of interacting modules consistent with that authority.

This repository is the complete public source tree. It includes the Magisk module, deterministic release tooling, a fake-Magisk-root lifecycle harness, private device-fixture tooling, CI, target monitoring, and public-repository initialization checks.

> **Release status:** `v1.0.0-rc.3` is a release candidate. Apply and Restore are explicit operations. OTAST does not continuously rewrite target files.

## Managed contracts

OTAST currently supports reviewed profiles for:

- PIF Inject (`playintegrityfix`): configuration-preserving transforms for `autopif.sh`, `autopif_ota.sh` and `pif.prop`, plus a narrow wrapper around the competing `security_patch.sh`; upstream Action, post-fs-data, service, WebUI and updater machinery stay intact.
- TrickyStore (`tricky_store`): `/data/adb/tricky_store/security_patch.txt`.
- Yurikey (`Yurikey`): exact replacement of reviewed authority-writing entrypoints only.
- Tricky Addon Update Target List (`TA_utl` or `.TA_utl`): exact v4.4 `prop.sh` transformation that removes only the overlapping VBMeta block while retaining every other behavior.
- Android VBMeta Fixer (`vbmeta-fixer`): the sole managed runtime writer for authoritative VBMeta digest, size and AVB versions, while preserving TrickyStore target registration.

Unknown target hashes, unsafe links, authority/live-identity mismatch, active legacy `ota-sot`/`otasst` traces, competing PIF automatic patch generation, managed drift, malformed state, and incomplete transaction recovery all fail closed.

## Safety boundary

OTAST:

- reads authority from `/data/adb/ota.prop`;
- records original bytes before the first mutation;
- writes through a journaled transaction;
- verifies every managed hash and mode;
- blocks Apply and Restore when target drift is detected;
- recovers an interrupted transaction during `post-fs-data`;
- does not run a polling service;
- never scans unrelated module trees.

The strict exclusions listed in `compatibility/supported-targets.json` are represented only as policy and test sentinels. Runtime discovery never names or traverses them.

## Local setup in Termux

Keep the repository in Termux private storage, not `/storage/emulated/0`. `bootstrap-termux.sh` first restores canonical executable and library modes, so the repository remains usable even when the downloaded ZIP passed through Android shared storage:

```bash
cd "$HOME/repos/otast"
bash scripts/bootstrap-termux.sh
bash scripts/test.sh --full
```

Build the deterministic Magisk ZIP:

```bash
bash scripts/build-release.sh
```

The output is written to `dist/` with a SHA-256 sidecar.

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

After installation and reboot, use the Magisk module action or run the runtime entrypoint as root:

```sh
sh /data/adb/modules/otast/runtime/entry.sh report
sh /data/adb/modules/otast/runtime/entry.sh preflight
sh /data/adb/modules/otast/runtime/entry.sh apply
sh /data/adb/modules/otast/runtime/entry.sh verify
sh /data/adb/modules/otast/runtime/entry.sh restore
```

Run `preflight` before the first Apply and after any target-module update.

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
- [Releases](docs/RELEASES.md)
- [Security](SECURITY.md)

## License

OTAST is licensed under GPL-3.0-only. Reviewed third-party compatibility information and adapted templates are documented in [NOTICE.md](NOTICE.md) and `third_party/licenses/`.
