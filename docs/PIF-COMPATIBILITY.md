# PIF Inject compatibility contract

## Ownership model

OTAST keeps the installed OTA/platform identity and the PIF attestation-profile identity as separate domains. It does not rewrite a selected PIF fingerprint, model or profile `SECURITY_PATCH` to match `/data/adb/ota.prop`.

The three possible profile layers are:

- `/data/adb/pif.prop` - global custom profile;
- `/data/adb/modules/playintegrityfix/pif.prop` - active module fallback;
- `/data/adb/modules_update/playintegrityfix/pif.prop` - staged future fallback.

OTAST selects one canonical source in strict order:

```text
GLOBAL_CUSTOM > ACTIVE_FALLBACK > STAGED_FALLBACK
```

The selected source remains PIF/user-owned and is never rewritten by OTAST Apply or rolled back by OTAST Restore. Every other installed active/staged module fallback is a transactional mirror of that source. `Report` classifies each layer as `SOURCE`, `MIRROR_CURRENT`, `MIRROR_UPDATE_REQUIRED`, `ABSENT` or `UNSAFE`; `Verify` fails on a stale installed fallback until explicit Apply reconciles it.

This solves a different problem from forcing the PIF profile to equal the installed OTA: the attestation identity may legitimately differ from the device build, while every fallback that PIF could later expose remains internally consistent with the currently selected profile.

`otast.pif.identity=ota` remains retired.

## AutoPIF lifecycle

`autopif.sh` and `autopif_ota.sh` are upstream-owned surfaces. OTAST no longer transforms either executable.

Consequences:

- AutoPIF may refresh `/data/adb/pif.prop` normally;
- the upstream executable updater may refresh `autopif.sh` normally;
- OTAST does not pin the live AutoPIF engine merely because the monitored branch moves;
- after a legitimate global profile refresh, `Report` can show module-local fallbacks as `MIRROR_UPDATE_REQUIRED`; explicit Apply mirrors the new canonical bytes transactionally.

The monitored upstream source remains relevant for compatibility review, but executable freshness and profile freshness are not conflated with OTAST ownership.

## Security-patch writer boundary

`security_patch.sh` remains structure-sensitive because it can write outside the PIF profile domain. OTAST exact-hash gates its reviewed source and applies a surgical transform.

The transform preserves:

- the PIF/user `pif_auto_security_patch` marker enable/disable controls;
- global-first, module-fallback profile selection;
- upstream profile parsing and control flow.

The transform suppresses only competing writes that would export PIF profile SPL into another authority domain:

- writes to Tricky Store `security_patch.txt` or `devconfig.toml`;
- creation of PIF `system.prop` from the profile SPL;
- `resetprop` mutation of platform system/vendor SPL.

The transform is anchor-checked, exact-source-hash gated and byte-idempotent. Existing v1 OTAST-managed `security_patch.sh` state is rebuilt from its verified original backup rather than treating the old OTAST wrapper as upstream source.

`/data/adb/tricky_store/pif_auto_security_patch` itself remains user/PIF data and its bytes/mode are preserved.

## OTA/platform SPL

The installed platform has its own authority:

```text
ro.build.version.security_patch  <- /data/adb/ota.prop
ro.vendor.build.security_patch   <- /data/adb/ota.prop
```

OTAST's own `system.prop` contains only those two installed-platform SPL values. PIF profile `SECURITY_PATCH` is reported separately and is not used as the OTA system/vendor SPL.

Tricky Store's OTAST-managed patch contract likewise remains derived from OTA authority, not the selected PIF profile.

## Verified-boot presentation

OTAST no longer synthesizes these values in its own `system.prop`:

```text
ro.boot.flash.locked
ro.boot.vbmeta.device_state
ro.boot.verifiedbootstate
ro.boot.veritymode
vendor.boot.vbmeta.device_state
vendor.boot.verifiedbootstate
```

Raw bootloader/libavb evidence is read-only evidence. `Report` prints raw bootconfig evidence separately from Android runtime-visible values.

`Verify` specifically rejects a contradictory presentation where `ro.boot.verifiedbootstate=green` while `ro.boot.verifiedbooterror` or `ro.boot.verifyerrorpart` still reports a verification failure. OTAST does not hide that contradiction by adding another property writer.

## Migration from v1 ownership

Existing installations can contain durable OTAST state for older PIF ownership, including profile records and transformed AutoPIF/PIF runtime files.

Explicit Apply validates those records and backups before retirement. For obsolete writer ownership such as `autopif.sh`, `autopif_ota.sh` and generated PIF `system.prop`, OTAST restores the exact verified original bytes/mode when the live file still matches the old managed hash, then moves the superseded state record into bounded retired evidence. Drift blocks migration.

Legacy profile-ownership records are retired without replacing the current canonical source. If a module-local profile becomes the canonical source, obsolete mirror ownership for that same source is retired rather than allowing Restore to roll it backwards.

Malformed state, missing/mismatched original backups or unexpected live drift fail closed.

## Current reviewed upstream baseline

The monitored `KOWX712/PlayIntegrityFix@inject_s` baseline is commit `73552eec78f1e733573192333e9a7453b8de0662`.

Its `security_patch.sh` resetprop-rebuild change remains review-significant because that file crosses authority domains. The accepted source hashes in `compatibility/supported-targets.json` cover the reviewed legacy compact form and current rebuild-capable form. `autopif.sh` and `autopif_ota.sh` hashes are retained as observed provenance rather than managed-source allowlists.

Future upstream movement is classified semantically: a change to `security_patch.sh` requires structure-sensitive review; changes to AutoPIF executables are preserved-surface changes and must be reviewed for interactions but are not automatically turned into OTAST-owned code.

## Required qualification

Regression qualification must prove that:

- canonical precedence is global, then active, then staged;
- the canonical profile is never rewritten to OTA identity;
- non-source active/staged fallbacks are mirrored transactionally;
- a legitimate global AutoPIF refresh becomes a mirror reconciliation on the next explicit Apply;
- `autopif.sh` and `autopif_ota.sh` remain upstream-owned;
- the surgical `security_patch.sh` transform preserves marker/profile flow while removing all competing patch/runtime SPL writes;
- OTA system/vendor SPL remain independent of PIF profile SPL;
- `green` plus verification-error evidence fails Verify;
- v1 writer/profile ownership migrates without losing original recovery evidence;
- Restore never rolls back the current canonical PIF source;
- unsafe profiles, unsupported writer hashes, state corruption and writer drift fail closed.
