# Physical Pixel release proof

OTAST can bind a production draft to a real Pixel 9a (`tegu`) lifecycle before publication. This proof is **optional for an owner-triggered manual Release workflow**, but when **Require Pixel physical-device proof before publishing** is checked, Publish will not proceed without it.

The proof is not written by hand. The `otast release` wizard generates, validates, and uploads it.

## Preconditions

Use the owned Pixel 9a running Android 16 / SDK 36 with Magisk root available. The GitHub CLI must be authenticated for `cbkii/otast`.

From Termux:

```bash
cd "$HOME/repos/otast"
git switch main
git pull --ff-only
source scripts/otast-playbook.sh
otast doctor
```

If `otast` is already sourced by your shell startup files, the `source` command is unnecessary.

A production draft for the candidate should already exist. The wizard can also request Prepare when required, but preparing the draft first in **Actions → Release** makes the lifecycle easier to observe.

## Recommended proof-only command

Use:

```bash
otast release --no-publish
```

`--no-publish` is recommended when the goal is to satisfy physical proof first and make publication a separate deliberate GitHub Actions step.

The command is resumable. Whenever it reaches a real reboot boundary it persists private state before asking for reboot.

After Android is fully booted again, reopen Termux and run the same command:

```bash
cd "$HOME/repos/otast"
source scripts/otast-playbook.sh
otast release --no-publish
```

Repeat until the wizard reports that PASS proof was uploaded and the draft was intentionally left unpublished.

Private resumable state is stored under:

```text
~/.local/state/otast-release/<version>/
```

To inspect the current phase:

```bash
otast release --status
```

Do not use `--reset` during an active proof unless you intentionally want to abandon that local proof state and have confirmed there is no live managed OTAST state that still needs Restore.

## What the wizard proves

The wizard first locks the exact draft ZIP SHA-256. That hash is the publication identity; another ZIP is never substituted once proof is active.

The device sequence is:

```text
clean/verified baseline if required
        ↓
install exact draft ZIP through Magisk
        ↓
real reboot
        ↓
Report
        ↓
Preflight → READY
        ↓
first Apply
        ↓
real reboot when changes require it
        ↓
Verify → CURRENT
        ↓
second Apply → NO_CHANGES_REQUIRED
        ↓
second Verify → CURRENT
        ↓
Restore
        ↓
real reboot
        ↓
confirm managed state is absent
        ↓
final Report
        ↓
write + validate + upload proof
```

A first Apply that legitimately reports `NO_CHANGES_REQUIRED` is accepted as an already-current state. If an external writer causes the second Apply to change files, the wizard allows only bounded settling reboots; persistent rewriting fails the proof and triggers safe Restore where possible.

## Proof artifact

On success the wizard generates:

```text
otast-vX.Y.Z-device-proof.json
```

The proof uses schema 2 and records at least:

```json
{
  "schema_version": 2,
  "result": "PASS",
  "version": "vX.Y.Z",
  "module_sha256": "<exact draft ZIP SHA-256>",
  "source_commit": "<diagnostic source commit>",
  "device": "tegu",
  "sdk": 36,
  "phases": {
    "baseline": "PASS or NOT_REQUIRED",
    "install_reboot": "PASS",
    "apply_reboot": "PASS, PASS_AFTER_SETTLING_REBOOT, or SKIPPED_NO_CHANGES",
    "verify_noop_restore": "PASS",
    "restore_reboot_report": "PASS"
  },
  "generated_utc": "<UTC timestamp>"
}
```

Before upload, `scripts/validate-device-release-proof.py` verifies the proof against the exact downloaded module ZIP and version.

The uploaded proof becomes a draft Release asset beside the ZIP, checksum, and `release-manifest.json`.

## Confirm proof is present

After the wizard reports success, the draft should contain:

```text
otast-vX.Y.Z.zip
otast-vX.Y.Z.zip.sha256
release-manifest.json
otast-vX.Y.Z-device-proof.json
```

The proof filename and ZIP version must match exactly.

## Publish with proof required

Open **Actions → Release → Run workflow** and use:

```text
Action:
  publish-release

Version:
  [blank]

Run full validation:
  any value

Require Pixel physical-device proof before publishing:
  checked
```

Publish downloads the exact release bundle and proof, validates the proof against that ZIP, publishes the existing draft without rebuilding, then verifies the published tag/asset. Final releases update stable Magisk `update.json` only after the public ZIP is verified.

## Publish without physical proof

For an owner-triggered manual release, physical proof may be deliberately bypassed:

```text
Require Pixel physical-device proof before publishing:
  unchecked
```

This bypasses only the physical-device proof requirement. It does **not** bypass deterministic ZIP, checksum, manifest, embedded Magisk metadata, source identity, published tag, public asset SHA-256, or stable `update.json` verification.

If a proof asset already exists, Publish still validates it even when the checkbox is unchecked.

## Failure handling

If a phase fails, follow the wizard's STOP message. Do not manually fabricate or edit proof JSON to force publication.

The wizard has bounded recovery for ordinary failures such as staged-runtime activation, transaction boot recovery, transient Apply/Restore failures, and limited writer-settling reboots. If it cannot prove a safe state, it stops rather than manufacturing PASS.

If proof succeeds but publication later fails, rerunning `otast release` or the Publish workflow reuses the same proof-bearing candidate. It does not require repeating physical qualification unless the locked candidate itself changed, which is intentionally rejected.
