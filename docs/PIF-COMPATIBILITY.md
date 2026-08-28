# PIF Inject compatibility contract

## Design source

The compatibility boundary is derived from the merged `ota-sot` PIF hardening and v4 runtime work, then tightened around the live Pixel configuration validated in August 2026.

Rules:

1. Prefer preservation and narrow configuration transforms over replacing upstream lifecycle entrypoints.
2. Preserve update, self-repair, Action, service, post-fs-data, WebUI and process-restart behavior unless a specific writer is proven to conflict.
3. Preserve the currently selected PIF identity and spoof booleans by default; official OTA identity is source evidence, not an instruction to overwrite a working attestation profile.
4. Make OTA identity takeover explicit with `otast.pif.identity=ota`.
5. Preserve unrelated PIF options/comments in `pif.prop`.
6. Make refresh reconciliation read-only; only an explicit OTAST Apply may mutate reviewed targets.
7. Disable exact competing writer surfaces and fail closed when their source or anchors drift.

## Managed surface

For the reviewed PIF Inject source lineage at commits `ea93222c58f90108cef0c02a11e66bdfdf4b21b6` and `8b4a00cef9536dc9c8428d392725eacf364605a9`, OTAST manages:

- module and global `pif.prop` — preserve current identity/options by default; optionally align selected fields with OTA authority;
- `security_patch.sh` — exact wrapper because uncontrolled automatic patch writes conflict with OTAST's cross-module ownership model;
- `autopif.sh` and `autopif_ota.sh` **only when** `otast.pif.identity=ota` is explicitly selected. In default `preserve` mode these remain upstream/user-owned.

The `8b4a00ce` review changes AutoPIF Pixel download-page selection (reverse-sorted FI/OTA URLs). When OTA identity mode is selected, the reviewed transformation anchors and exact source hashes remain mandatory.

The following are observed or preserved, not patched:

- `action.sh`;
- `post-fs-data.sh`;
- `service.sh`;
- `common_func.sh`;
- `classes.dex`;
- WebUI assets and configuration;
- Zygisk libraries;
- uninstall and installer behavior.

## Policy keys

All omitted values default to `preserve`:

```text
otast.pif.identity=preserve|ota
otast.pif.spoofBuild=preserve|true|false
otast.pif.spoofProps=preserve|true|false
otast.pif.spoofProvider=preserve|true|false
otast.pif.spoofSignature=preserve|true|false
otast.pif.spoofVendingBuild=preserve|true|false
otast.pif.spoofVendingSdk=preserve|true|false
otast.pif.DEBUG=preserve|true|false
```

For this Pixel stack, `preserve` is the safe default because the active PIF profile may intentionally be a newer attestation-compatible Pixel 9a profile while `ota.prop` continues to describe the installed official OS image.

## Runtime consequence

In `preserve` mode, OTAST does not rewrite AutoPIF selection or the chosen fingerprint/model/security patch. It still prevents known competing security-patch writers from silently changing cross-module state.

In explicit `ota` mode, an upstream `autopif_ota.sh` refresh may replace `autopif.sh`; OTAST then performs read-only preflight. Until the refreshed source hash and anchors are reviewed and an explicit Apply succeeds, preflight/Verify blocks. OTAST never silently re-patches downloaded source at boot.

## Regression requirements

A PIF change is acceptable only when tests prove:

- upstream Action, post-fs-data and service bytes do not change;
- unknown `pif.prop` keys and comments survive OTAST's merge;
- preserve mode leaves the selected identity and spoof booleans unchanged;
- explicit OTA mode propagates authority fingerprint, model, product, device and security patch;
- transformation is byte-idempotent;
- automatic PIF security-patch generation blocks rather than competing;
- unknown hashes or missing anchors fail before mutation;
- Restore recovers exact upstream originals.
