# PIF Inject compatibility contract

## Ownership model

OTAST separates PIF attestation-profile configuration from OTA/platform authority.

PIF Inject intentionally has two profile layers:

- `/data/adb/pif.prop` — mutable custom/effective profile, owned by PIF/user;
- `/data/adb/modules/playintegrityfix/pif.prop` — active packaged fallback/default/reset profile, owned by PIF;
- `/data/adb/modules_update/playintegrityfix/pif.prop` — staged future fallback, not runtime-effective before promotion on reboot.

The reviewed native runtime uses global custom first and active module fallback second. Different identity values between these files are expected and are reported as `DISTINCT_EXPECTED`, not OTAST drift.

OTAST validates profile files for safe regular-file structure, bounded size, unambiguous keys, required fingerprint/security-patch fields and valid known booleans, but it does not transactionally own, mirror, restore or recreate their bytes.

`otast.pif.identity=ota` is retired. PIF identity/profile selection belongs to PIF. Existing authority files that still request this takeover fail closed with a migration message.

## Managed writer surface

OTAST continues to manage only reviewed PIF surfaces that can compete with OTA authority:

- `autopif.sh` — profile discovery/generation and `/data/adb/pif.prop` refresh remain intact; only the tail that could delete managed `system.prop` or invoke a profile-SPL global writer is adapted;
- `autopif_ota.sh` — moving-branch executable self-update is replaced by a review gate while OTAST ownership is active;
- `security_patch.sh` — `--enable`/`--disable` marker semantics remain available, but profile `SECURITY_PATCH` is never promoted into platform or Tricky Store SPL state;
- PIF `system.prop` — system/vendor SPL follows official OTA authority.

`action.sh`, post-fs-data/service lifecycle, WebUI profile editing/fetching, native Zygisk behavior and PIF's profile reset/fallback behavior remain upstream/PIF-owned.

## Refresh and reset behavior

PIF may legitimately change profile data outside OTAST Apply:

- AutoPIF dynamically obtains current Pixel Canary data and writes `/data/adb/pif.prop`;
- the WebUI GitHub fetch writes the selected device profile to `/data/adb/pif.prop`;
- WebUI option toggles rewrite the global custom profile;
- WebUI recovery can refresh the module fallback and delete `/data/adb/pif.prop`, causing native fallback to the active module profile;
- a PIF module update can replace the module-local packaged fallback.

These are configuration changes, not OTAST managed-file drift.

Opening the reviewed PIF WebUI also invokes its AutoPIF executable updater in the background. OTAST therefore gates `autopif_ota.sh`: profile freshness remains available through the installed reviewed AutoPIF engine and GitHub profile-fetch path, but newly downloaded executable code cannot replace the live reviewed adapter before compatibility review.

## Auto Security Patch preference

`/data/adb/tricky_store/pif_auto_security_patch` remains a PIF/user preference marker. OTAST preserves it.

The adapted `security_patch.sh` keeps marker enable/disable semantics but does not:

- derive Tricky Store patch metadata from PIF profile SPL;
- create/delete OTAST-owned `system.prop`;
- resetprop system/vendor SPL from the PIF profile.

Report distinguishes the requested preference from the effective policy:

```text
pif_auto_security_patch_requested=true|false
pif_auto_security_patch_effective_policy=OTAST_OTA_AUTHORITY
```

## Legacy OTAST state migration

Older/current OTAST builds may have transaction records for:

```text
pif-global-prop
pif-prop-active
pif-prop-staged
```

Explicit Apply validates these exact historical records, their authorised paths and original backup evidence before atomically retiring the records under `retired/pif-profile-ownership-v1/`. Live PIF profile bytes are not rewritten. Original backup evidence is retained for audit. Restore retires the same legacy ownership records before restoring remaining OTAST-managed surfaces, so a PIF profile cannot be rolled back after ownership retirement.

Malformed, path-mismatched or contradictory historical state fails closed.

## Upstream review state

The monitored acceptance baseline remains `b994391970b51a2dfefed0e1d420dd6b017756e8`.

The `inject_s` head `2f8199a90a150ad98921438608e1e0e951ba2d5f` was re-inspected for this lifecycle work. PIF shell/profile lifecycle behavior remains unchanged from the reviewed baseline, but the delta includes native/build dependency changes. It therefore remains review-required and is not promoted merely to make monitoring green.

## Regression requirements

Qualification must prove at least:

- global custom and module fallback profiles may differ without drift;
- runtime precedence is global custom, then active fallback; staged is not current runtime fallback;
- AutoPIF/WebUI-style profile refresh does not change OTA platform or Tricky Store SPL;
- global reset/deletion exposes active fallback and OTAST does not recreate the custom profile;
- PIF module fallback replacement is not rolled back as OTAST drift;
- AutoPIF executable self-update cannot replace the reviewed live engine;
- marker enable/disable semantics survive while global SPL writes remain suppressed;
- legacy managed-profile state is retired without rewriting current PIF data;
- unsafe profile files, source drift and malformed legacy state fail closed;
- exact managed script originals remain recoverable by Restore.
