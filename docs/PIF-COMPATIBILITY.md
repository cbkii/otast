# PIF Inject compatibility contract

## Design source

This contract is maintained only in `cbkii/otast`. Historical predecessor repositories are deprecated; their earlier findings are relevant only as migration history, not as supported runtime authorities.

Rules:

1. Prefer preservation and narrow configuration transforms over replacing upstream lifecycle entrypoints.
2. Preserve update, self-repair, Action, service, post-fs-data, WebUI and process-restart behavior unless a specific writer is proven to conflict.
3. Preserve the currently selected PIF identity and spoof booleans by default; official OTA identity is source evidence, not an instruction to overwrite a working attestation profile.
4. Make OTA identity takeover explicit with `otast.pif.identity=ota`.
5. Preserve unrelated PIF options/comments in `pif.prop`.
6. Make refresh reconciliation read-only; only an explicit OTAST Apply may mutate reviewed targets.
7. Disable exact competing writer surfaces and fail closed when their source or anchors drift.
8. Treat `/data/adb/tricky_store/pif_auto_security_patch` as user configuration, not as the writer itself. A safe regular flag may exist at Preflight; Apply must neutralize the reviewed `security_patch.sh` writer before OTAST considers the stack managed.

## Managed surface

For the reviewed PIF Inject source lineage at commits `ea93222c58f90108cef0c02a11e66bdfdf4b21b6`, `8b4a00cef9536dc9c8428d392725eacf364605a9`, and current monitored head `b994391970b51a2dfefed0e1d420dd6b017756e8`, OTAST manages:

- module and global `pif.prop` — preserve current identity/options by default; optionally align selected fields with OTA authority;
- `security_patch.sh` — exact wrapper because uncontrolled automatic patch writes conflict with OTAST's cross-module ownership model;
- `autopif.sh` and `autopif_ota.sh` **only when** `otast.pif.identity=ota` is explicitly selected. In default `preserve` mode these remain upstream/user-owned.

The `8b4a00ce` review changed AutoPIF Pixel download-page selection (reverse-sorted FI/OTA URLs). The later `b994391` monitored delta is documentation/WebUI localization only: no OTAST-managed runtime source or reviewed lifecycle entrypoint changed, so the existing source hashes and transformations remain valid.

The following are observed or preserved, not patched:

- `action.sh`;
- `post-fs-data.sh`;
- `service.sh`;
- `common_func.sh`;
- `classes.dex`;
- WebUI assets and configuration;
- Zygisk libraries;
- uninstall and installer behavior;
- a safe regular `/data/adb/tricky_store/pif_auto_security_patch` flag. Its existence is preserved across Apply/Restore, while the reviewed script it would invoke is neutralized during OTAST ownership.

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

For a Pixel stack, `preserve` is the safe default because the active PIF profile may intentionally be a different or newer attestation-compatible Pixel profile while `ota.prop` continues to describe the installed official OS image for the live device.

## Runtime consequence

In `preserve` mode, OTAST does not rewrite AutoPIF selection or the chosen fingerprint/model/security patch. It still prevents known competing security-patch writers from silently changing cross-module state.

PIF's own Auto Security Patch toggle is implemented as a marker file. Upstream `autopif.sh` checks that marker and invokes `security_patch.sh`; the reviewed upstream `security_patch.sh` then rewrites TrickyStore patch state and runtime security-patch properties. OTAST therefore governs the writer, not the marker. An already-enabled marker is accepted when safe, and Apply replaces the reviewed writer with the managed no-op form. Restore recovers the exact upstream writer while leaving the user's original marker state intact.

In explicit `ota` mode, an upstream `autopif_ota.sh` refresh may replace `autopif.sh`; OTAST then performs read-only preflight. Until the refreshed source hash and anchors are reviewed and an explicit Apply succeeds, preflight/Verify blocks. OTAST never silently re-patches downloaded source at boot.

## Regression requirements

A PIF change is acceptable only when tests prove:

- upstream Action, post-fs-data and service bytes do not change;
- unknown `pif.prop` keys and comments survive OTAST's merge;
- preserve mode leaves the selected identity and spoof booleans unchanged;
- explicit OTA mode propagates authority fingerprint, model, product, device and security patch;
- transformation is byte-idempotent;
- a safe existing `pif_auto_security_patch` marker does not block Preflight merely because the user previously enabled the option;
- Apply neutralizes the reviewed automatic security-patch writer before managed verification succeeds;
- unsafe marker types/symlinks, unknown writer hashes or missing anchors fail before mutation;
- Restore recovers exact upstream originals.
