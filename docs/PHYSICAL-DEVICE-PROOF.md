# Physical Pixel release proof

OTAST binds a stable production release to a real supported Pixel lifecycle before publication. **Stable publication always requires valid physical proof for the exact hosted ZIP.** A prerelease may omit proof only when the Release workflow explicitly permits it.

The proof is generated and validated by the OTAST release tooling; do not write it by hand.

## Preconditions

Use an owned supported Pixel running Android 16 / SDK 36 with Magisk root available. The current release reference is Pixel 9a (`tegu`); other declared Pixel models are qualified independently by the compatibility/qualification registries.

The GitHub CLI must be authenticated for `cbkii/otast`.

From Termux:

```bash
cd "$HOME/repos/otast"
git switch main
git pull --ff-only
source scripts/otast-playbook.sh
otast doctor
```

If `otast` is already sourced by your shell startup files, the `source` command is unnecessary.

A production draft for the candidate should already exist. The first stable Release run creates and verifies that draft, then stops at the physical-proof gate when the proof asset is absent.

## Proof-only command

Use:

```bash
otast release --no-publish
```

This qualifies and uploads proof while leaving publication as a separate GitHub Actions step.

The command is resumable. Whenever it reaches a real reboot boundary it persists private state before requesting the reboot. After Android is fully booted, reopen Termux and run the same command again:

```bash
cd "$HOME/repos/otast"
source scripts/otast-playbook.sh
otast release --no-publish
```

Repeat until PASS proof is uploaded and the draft remains intentionally unpublished.

Private resumable state is stored under:

```text
~/.local/state/otast-release/<version>/
```

Inspect the current phase with:

```bash
otast release --status
```

Do not use `--reset` during an active proof unless intentionally abandoning that local proof state and after confirming no live managed OTAST state still requires Restore.

## What the proof establishes

The wizard first locks the exact hosted draft ZIP SHA-256. That hash is the publication identity; another ZIP cannot be substituted after qualification begins.

The real device sequence is:

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

A first Apply that legitimately reports `NO_CHANGES_REQUIRED` is accepted as already current. If an external writer causes the second Apply to change files, the wizard permits only bounded settling reboots; persistent rewriting fails proof and triggers safe Restore where possible.

## Proof artefact

The generated asset is:

```text
otast-vX.Y.Z-device-proof.json
```

The current proof schema records the exact release identity, module ZIP SHA-256, source/provenance, device/build/platform evidence, phase outcomes, root-stack attribution, and qualification/runtime-equivalence evidence required by the validator.

Before upload, `scripts/validate-device-release-proof.py` verifies the proof against the exact downloaded module ZIP and version. The proof becomes a draft Release asset beside:

```text
otast-vX.Y.Z.zip
otast-vX.Y.Z.zip.sha256
release-manifest.json
otast-vX.Y.Z-device-proof.json
```

The proof filename, version, source/provenance and ZIP hash must agree with the hosted release bundle.

## Runtime-equivalent proof reuse

A previous physical proof is reusable only when all reuse conditions are proven, including:

- the qualification record is `CURRENT` and runtime-digest bound;
- the candidate canonical runtime digest is identical;
- registry/proof provenance remains compatible;
- the evidence records both the original `qualified_source_commit` and current `current_source_commit`;
- CI equivalence evidence is PASS;
- no unbound external input changes effective runtime behaviour.

A source-only change is not enough to permit reuse. Any runtime-byte change invalidates it.

Page-size evidence is also independent. A 4096-byte-page runtime proof does not qualify a 16384-byte-page runtime, and a 16384-byte-page proof does not qualify 4096. An unqualified page-size entry remains an explicit release limitation rather than being inferred from architecture support.

## Publish after proof

After the proof upload succeeds, rerun **Actions -> Release -> Run workflow** with the same version. The workflow:

1. runs a fresh compatibility target/dependency monitor before release mutation;
2. redownloads the exact hosted ZIP, checksum and manifest;
3. validates the physical proof against that ZIP/version;
4. publishes the existing draft without rebuilding;
5. verifies published tag/source identity;
6. updates stable `update.json` only after the public release is verified.

For stable releases the physical-proof checkbox cannot bypass this gate. If stable proof is absent or invalid, the release stays a draft.

For prereleases only, the workflow may allow publication without physical proof according to the explicit input. If a proof asset is present, it is validated regardless.

## Failure handling

If a phase fails, follow the wizard's `STOP:` reason. Do not edit or fabricate proof JSON to force publication.

The wizard has bounded recovery for staged-runtime activation, transaction boot recovery, transient Apply/Restore failures and limited writer-settling reboots. If it cannot prove a safe state, it stops rather than manufacturing PASS.

If proof succeeds but publication later fails, rerunning the same release path reuses the same proof-bearing hosted candidate. It does not repeat physical qualification unless the locked candidate/provenance no longer validates, in which case reuse is rejected.
