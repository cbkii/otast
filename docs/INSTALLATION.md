# Installation

## Requirements

- Pixel 9a (`tegu`).
- Android 16 / SDK 36.
- Magisk with working root access.
- A valid, regular `/data/adb/ota.prop` matching the live device.
- Target-module versions matching an accepted profile.
- No active or staged legacy `ota-sot`/`otasst` module, persistent state root or dispatcher.

## Normal v1 release/install path

For the repository owner, do **not** manually execute the release lifecycle one
command at a time. The supported release path is:

```bash
source scripts/otast-playbook.sh
otast release
```

The wizard uses the latest GitHub `main` when preparing a new draft. You do not
select or pin a commit SHA. Commit identity is diagnostic metadata only; the
physical proof and final publication are bound to the exact module ZIP SHA-256.

After every requested reboot, wait for Android to finish booting and run the exact
same command again:

```bash
otast release
```

The wizard handles ordinary repair routes automatically where safe: dependency
installation, bounded network/Actions retries, stale draft refresh, transaction
boot-recovery, Apply/Restore retries and settling reboots. Persistent drift or a
state that cannot be safely verified still stops rather than being hidden.

See [`RELEASE.md`](RELEASE.md) for the full recovery policy.

## Manual runtime interface

The individual runtime actions remain available for engineering diagnostics and
recovery, but they are no longer the normal release UX:

```sh
su -c 'sh /data/adb/modules/otast/runtime/entry.sh report'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh preflight'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh apply'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh verify'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh restore'
```

A changing Apply returns `REBOOT_REQUIRED`. An already-current Apply may return
`NO_CHANGES_REQUIRED`; the release wizard treats that as a valid no-op path rather
than forcing an artificial failure.

## Before installing outside the release wizard

Remove legacy `ota-sot` and `otasst` only through a restore-first cleanup. Do not
manually delete their module or state directories while managed targets may still
be active. OTAST intentionally blocks normal operation if known legacy traces
remain.

The module installer itself runs a non-mutating target preflight. Installation
stops if authority, live identity, target hashes or path safety cannot be proven.
It does not Apply target changes during installation.
