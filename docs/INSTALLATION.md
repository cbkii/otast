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
command at a time. The supported release path is the resumable wizard documented
in [`RELEASE.md`](RELEASE.md):

```bash
source scripts/otast-playbook.sh
otast release
```

After every requested reboot, wait for Android to finish booting and run the exact
same command again:

```bash
otast release
```

The wizard creates or reuses the exact GitHub draft, verifies its SHA-256 and
commit binding, installs it through Magisk, performs Report/Preflight/Apply,
proves the reboot boundary, proves second-Apply idempotency, restores originals,
performs the final post-Restore report, uploads a sanitized proof and publishes
only the already-validated draft.

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

A changing Apply returns `REBOOT_REQUIRED`; Verify is expected only after the
required reboot. A second Apply on a current system returns
`NO_CHANGES_REQUIRED`.

## Before installing outside the release wizard

Remove legacy `ota-sot` and `otasst` only through a restore-first cleanup. Do not
manually delete their module or state directories while managed targets may still
be active. OTAST intentionally blocks normal operation if known legacy traces
remain.

The module installer itself runs a non-mutating target preflight. Installation
stops if authority, live identity, target hashes or path safety cannot be proven.
It does not Apply target changes during installation.
