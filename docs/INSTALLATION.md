# Installation

## Requirements

- Pixel 9a (`tegu`).
- Android 16 / SDK 36.
- Magisk with working root access.
- A valid, regular `/data/adb/ota.prop` matching the live device.
- Target-module versions matching an accepted profile.
- No active or staged legacy `ota-sot`/`otasst` module, persistent state root or dispatcher.

## Before installing

Remove legacy `ota-sot` and `otasst` only through a restore-first cleanup. Do not manually delete their module or state directories while managed targets may still be active. OTAST intentionally blocks normal operation if known legacy traces remain.


From the repository:

```bash
bash scripts/test.sh --full
bash scripts/build-release.sh
```

Copy the generated `dist/otast-v1.0.0-rc.3.zip` to a location visible to the Magisk app and install it there.

The installer runs a non-mutating target preflight. Installation stops if authority, live identity, target hashes or path safety cannot be proven. It does not Apply target changes during installation.

## After reboot

Open the module action and select **Report** or run:

```sh
su -c 'sh /data/adb/modules/otast/runtime/entry.sh report'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh preflight'
```

Review the planned operation count. Apply explicitly:

```sh
su -c 'sh /data/adb/modules/otast/runtime/entry.sh apply'
```

Then reboot if the changed target modules execute during boot, and verify:

```sh
su -c 'sh /data/adb/modules/otast/runtime/entry.sh verify'
```
