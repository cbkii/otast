# Releasing OTAST

OTAST uses an exact-asset release contract. A GitHub-hosted runner can build and
create a draft, but it cannot reboot or inspect the physical Pixel 9a. The
physical proof is therefore implemented as a resumable Termux state machine.

## Normal release interface

From the repository, source the playbook once per shell:

```bash
source scripts/otast-playbook.sh
```

Then use one command only:

```bash
otast release
```

Run **the same command again after every requested reboot**. Do not manually
substitute `report`, `preflight`, `apply`, `verify` or `restore` commands during a
release proof.

The command automatically:

1. creates the exact GitHub draft through the `Release` workflow if no draft exists;
2. downloads `otast-<version>.zip` and its SHA-256 sidecar;
3. checks that the ZIP version and embedded `commit_sha` match the immutable draft;
4. if an earlier OTAST transaction is still managed, verifies it as `CURRENT`,
   restores it, and requires a real reboot before starting the release proof;
5. installs the exact draft ZIP through `magisk --install-module`;
6. proves the post-install lifecycle:
   `Report -> Preflight -> Apply -> reboot -> Verify -> second Apply -> Verify -> Restore -> reboot -> Report`;
7. requires the first Apply to return `REBOOT_REQUIRED`;
8. requires post-reboot Verify to report managed items as `CURRENT`;
9. requires the second Apply to return `NO_CHANGES_REQUIRED`;
10. verifies that Restore leaves no managed state after the final reboot;
11. writes and uploads a sanitized `otast-<version>-device-proof.json` release asset;
12. asks for confirmation, then dispatches the `Release` workflow in `publish` mode;
13. the workflow re-downloads the original draft ZIP and proof, verifies them, and
    publishes that same draft without rebuilding the ZIP.

The wizard stores private resume state below:

```text
~/.local/state/otast-release/<version>/
```

It stores no GitHub token and the uploaded proof contains no device serial,
absolute Termux path, boot ID, or private module data.

## Reboot boundaries

A hosted CI job cannot cross a physical Android reboot. OTAST detects real reboot
boundaries using `/proc/sys/kernel/random/boot_id`. Before asking for a reboot it
persists the next phase. After Android is fully booted, run:

```bash
otast release
```

again. It resumes rather than repeating completed mutations.

By default the wizard asks before rebooting. To approve its reboot and final
publication prompts automatically:

```bash
otast release --yes
```

To keep the draft unpublished after a successful physical proof:

```bash
otast release --no-publish
```

## Recovery and inspection

Show the current phase without changing anything:

```bash
otast release --status
```

Only if a release attempt must be deliberately abandoned, remove the wizard's
private resume state with:

```bash
otast release --reset
```

`--reset` does **not** restore managed target files. If the wizard stopped because
live OTAST state is drifted or a Restore failed, resolve that reported condition
first; do not use state reset to bypass a safety stop.

## GitHub Release workflow

The `Release` workflow has three operations:

- `validate`: full CI qualification and deterministic build only;
- `draft`: full qualification, deterministic build, exact commit binding, then
  creation of a draft release;
- `publish`: no build. It requires the draft ZIP, SHA sidecar and physical-device
  proof asset to agree on version, immutable commit and ZIP SHA-256, then changes
  that already-existing draft to published.

The normal user path is `otast release`; it dispatches `draft` and `publish`
automatically. The workflow form remains available for diagnostics/manual control.
