# PIF Inject compatibility contract

## Design source

The compatibility boundary is derived from the merged `ota-sot` PIF hardening and v4 runtime work, especially PRs #67, #69, #77 and #79.

Those changes established the following rules:

1. Prefer configuration injection and narrow transformations over replacing upstream lifecycle entrypoints.
2. Preserve update, self-repair, Action, service, post-fs-data, WebUI and process-restart behavior unless a specific writer is proven to conflict.
3. Preserve unrelated PIF options and comments when updating `pif.prop`.
4. Require complete OTA-derived identity and reject stale or incomplete authority.
5. Make refresh reconciliation read-only; only an explicit OTAST Apply may mutate reviewed targets.
6. Disable only exact competing writer surfaces and fail closed when their source or anchors drift.

## Managed surface

For the reviewed PIF Inject source at commit `ea93222c58f90108cef0c02a11e66bdfdf4b21b6`, OTAST manages only:

- `autopif.sh` — deterministic Pixel 9a selection and generated identity fields;
- `autopif_ota.sh` — upstream refresh plus read-only OTAST preflight;
- module and global `pif.prop` — merge authority values without discarding unrelated configuration;
- `security_patch.sh` — exact wrapper because OTAST owns the same TrickyStore and runtime security-patch outputs.

The following are observed or preserved, not patched:

- `action.sh`;
- `post-fs-data.sh`;
- `service.sh`;
- `common_func.sh`;
- `classes.dex`;
- WebUI assets and configuration;
- Zygisk libraries;
- uninstall and installer behavior.

## Runtime consequence

An upstream `autopif_ota.sh` refresh may replace `autopif.sh`. OTAST then runs read-only preflight. Until the refreshed source hash and anchors are reviewed and an explicit Apply succeeds, Verify reports drift or preflight blocks. OTAST never silently re-patches downloaded source at boot.

## Regression requirements

A PIF change is acceptable only when tests prove:

- upstream Action, post-fs-data and service bytes do not change;
- unknown `pif.prop` keys and comments survive OTAST's merge;
- authority fingerprint, model, product, device and security patch reach generated PIF output;
- spoof booleans continue to follow `ota.prop` options;
- transformation is byte-idempotent;
- automatic PIF security-patch generation blocks rather than competing;
- unknown hashes or missing anchors fail before mutation;
- Restore recovers exact upstream originals.
