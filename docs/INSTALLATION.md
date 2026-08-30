# Installation

## Requirements

- Google Pixel device.
- Android 16 / SDK 36.
- Magisk with working root access.
- A valid, regular `/data/adb/ota.prop` matching the live device.
- Target-module versions matching an accepted profile.
- No active or staged legacy `ota-sot`/`otasst` module, persistent state root or dispatcher.

OTAST documentation is intentionally Pixel-model agnostic. Physical-device testing to date is limited to **Pixel 9a** and **Pixel 8**. Other Pixel models are untested and must be treated as unverified until their exact device/build path passes the same authority, target-profile and physical validation gates. Documentation scope does not override fail-closed runtime compatibility checks.

## After installing the Magisk module

The installer performs a non-mutating Preflight before Magisk completes the installation. A successful installer does **not** Apply OTAST-managed changes automatically.

After the installer reports `SUCCESS !!`:

1. reboot the device;
2. open **Magisk -> Modules -> OTAST -> Action**;
3. select **Preflight (read-only)**;
4. if Preflight passes, run Action again and select **Apply**;
5. if Apply reports `REBOOT_REQUIRED`, reboot again;
6. run **Action -> Verify (read-only)** after that reboot.

Do not run Apply before the first reboot. `Report`, `Preflight` and `Verify` are read-only.

## Production release path

For the repository owner, the authoritative production path is:

```text
Actions -> Release -> Run workflow
```

For a normal release:

```text
Version:          [blank]
Full validation:  off
Physical proof:   off
```

Blank Version automatically resolves the next stable patch and monotonic `versionCode`. The single workflow run stamps the release identity, performs mandatory package integrity checks, builds and verifies the exact Magisk ZIP, publishes the GitHub Release, verifies its tag/source identity, and updates stable `update.json`.

Enable full validation or physical Pixel proof only when those stricter gates are specifically wanted. Both are disabled by default.

See [`docs/RELEASE.md`](RELEASE.md) for the full release and retry contract.

## Optional physical-device qualification

`otast release` is retained for the stronger physical-Pixel proof path; it is not the normal publisher.

```bash
source scripts/otast-playbook.sh
otast release
```

It qualifies the exact proof-gated draft across the required reboot boundaries, uploads proof, and asks the same authoritative GitHub Release workflow to publish that proven candidate.

Use:

```bash
otast release --no-publish
```

to upload proof but intentionally leave the candidate draft unpublished.

## Manual runtime interface

The individual runtime actions remain available for engineering diagnostics and recovery:

```sh
su -c 'sh /data/adb/modules/otast/runtime/entry.sh report'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh preflight'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh apply'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh verify'
su -c 'sh /data/adb/modules/otast/runtime/entry.sh restore'
```

A changing Apply returns `REBOOT_REQUIRED`. An already-current Apply may return `NO_CHANGES_REQUIRED`.

## Before installing outside the release workflow

Remove legacy `ota-sot` and `otasst` only through a restore-first cleanup. Do not manually delete their module or state directories while managed targets may still be active. OTAST intentionally blocks normal operation if known legacy traces remain.

The module installer itself runs a non-mutating target preflight. Installation stops if authority, live identity, target hashes or path safety cannot be proven. It does not Apply target changes during installation.
