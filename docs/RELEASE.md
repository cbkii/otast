# Releasing OTAST

The supported owner-facing release interface is one resumable command:

```bash
otast release
```

Run the **same command again after every requested reboot**. The script stores its
private phase state and resumes automatically; there is no manual
Report/Preflight/Apply/Verify/Restore sequence to memorise.

## Release source: latest `main`

A new release attempt uses the latest GitHub `main` when it prepares the draft.
The operator does not select, pin or type a commit SHA.

The source commit may still be recorded as diagnostic metadata inside the build,
but it is not a physical-proof or publication gate. The release invariant is the
asset itself: the module ZIP published must have the same SHA-256 as the ZIP that
was installed and proven on the Pixel.

Once physical testing starts, that exact ZIP is locked for the attempt. If `main`
moves while the phone is rebooting, OTAST continues the already-tested asset
rather than silently swapping a different build into the middle of the lifecycle.

## What `otast release` does

The wizard automatically:

1. best-effort fast-forwards a clean local `main`; a dirty or non-main checkout is
   left untouched because GitHub Actions still builds remote `main`;
2. reads the current release version from GitHub `main` when possible;
3. installs missing ordinary Termux dependencies through `pkg` when safe;
4. creates or refreshes a GitHub draft from current `main`;
5. downloads the ZIP and SHA-256 sidecar and locks the exact asset hash;
6. installs that ZIP through Magisk and crosses the required real reboot boundary;
7. performs Report -> Preflight -> Apply;
8. if Apply changes files, reboots and verifies them; if Apply is already a no-op,
   accepts the system as already current instead of manufacturing a failure;
9. requires the later Apply to settle at `NO_CHANGES_REQUIRED`;
10. Restores the managed files, reboots, confirms managed state is gone and runs
    the final Report;
11. writes and uploads a sanitized physical-device proof bound to the ZIP SHA-256;
12. publishes that same draft without rebuilding it.

## Automatic repair/recovery policy

The script treats predictable operational failures as recoverable instead of
immediately halting:

- network, GitHub API, Actions lookup and asset-download failures use bounded retries;
- a missing Termux package is installed with `pkg` when available;
- a clean local `main` is fast-forwarded and the script re-executes itself once;
- an old draft with no device proof is replaced automatically from latest `main`;
- a missing/corrupt draft asset before physical testing causes one automatic draft rebuild;
- interrupted runtime transactions use `boot-recover` before Apply/Verify/Restore retry;
- a staged-but-not-active OTAST module gets an additional activation reboot;
- a late writer that makes the second Apply change files gets bounded settling reboots;
- lingering records after Restore get one additional boot-recover/Restore/reboot cycle;
- if an unrecoverable failure occurs after OTAST has modified managed state, the
  wizard attempts a safe Restore/unwind and reboot before leaving the release unpublished;
- an already-uploaded valid proof can be recovered from the draft if local resume
  state was lost.

Retries are bounded. The script does not loop indefinitely and does not turn a
persistent conflict into a false PASS.

## Conditions that still STOP

A hard stop remains appropriate only when continuing automatically could be
unsafe or misleading, for example:

- the device is not Pixel 9a `tegu` / SDK 36;
- Magisk root or the Magisk CLI never becomes usable after bounded waiting;
- pre-existing managed OTAST state cannot be verified after transaction recovery;
- a different ZIP appears after the physical proof has already locked the asset;
- another writer keeps changing managed files after bounded settling reboots;
- Restore cannot return the device to a known state after bounded recovery.

When a mid-lifecycle condition is recoverable by Restore, the wizard attempts that
unwind itself before reporting the release failure.

## Reboot boundaries

OTAST records `/proc/sys/kernel/random/boot_id` before a required reboot. After
Android is fully booted, run:

```bash
otast release
```

again. If a reboot has not happened yet, the same command simply requests it
again; completed mutations are not repeated blindly.

By default reboot and final publication remain interactive. To approve them
automatically:

```bash
otast release --yes
```

To leave the proven release as a draft:

```bash
otast release --no-publish
```

## Inspection and recovery

Show current private state without changing anything:

```bash
otast release --status
```

Private state and logs live under:

```text
~/.local/state/otast-release/<version>/
```

To deliberately discard only the wizard's private resume metadata:

```bash
otast release --reset
```

`--reset` does not Restore live managed files. If live managed state exists and
resume metadata is corrupt, the wizard refuses to throw that lifecycle position
away automatically.

## GitHub Release workflow

The workflow exposes `validate`, `draft`, and `publish` operations.

- `validate` tests/builds current `main` only;
- `draft` tests/builds current `main` and creates or refreshes an unproven draft;
- `publish` does not rebuild: it downloads the existing draft ZIP, checksum and
  physical proof, verifies the ZIP hash/proof/version, then publishes that draft.

The normal path remains `otast release`; the workflow form is only a lower-level
operator/debugging surface.
