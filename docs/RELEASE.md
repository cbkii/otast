# Releasing OTAST

OTAST has two intentionally different build paths:

- a production release path that locks and physically proves one exact ZIP before publication;
- a simple branch-head build path for development/testing that produces a Magisk-installable Actions artifact without touching release state.

The production invariant is the module ZIP SHA-256. A source commit is useful provenance, but a proof for one ZIP never authorizes another ZIP.

## Magisk update channel

Every production OTAST ZIP contains `module.prop` with:

```text
updateJson=https://raw.githubusercontent.com/cbkii/otast/main/update.json
```

The stable `update.json` advertises the latest successfully published release using the Magisk update metadata contract:

```json
{
  "version": "vX.Y.Z",
  "versionCode": 123,
  "zipUrl": "https://github.com/cbkii/otast/releases/download/vX.Y.Z/otast-vX.Y.Z.zip",
  "changelog": "https://raw.githubusercontent.com/cbkii/otast/main/CHANGELOG.md"
}
```

`module/module.prop` is allowed to move ahead during development. `update.json` represents the latest published/updateable release and is synchronized only after the corresponding GitHub Release is public and its exact ZIP has been verified.

## Canonical release bundle

Production packaging is implemented by OTAST host tooling rather than by GitHub Actions YAML.

`scripts/build-release.sh` produces and verifies:

```text
dist/
├── otast-vX.Y.Z.zip
├── otast-vX.Y.Z.zip.sha256
└── release-manifest.json
```

The checksum sidecar contains only the ZIP basename so the ZIP and sidecar remain relocatable. `otastctl verify-release` resolves the supplied paths explicitly and therefore does not depend on the caller's current working directory.

The manifest records the release version, versionCode, source commit, asset names and exact ZIP SHA-256. The ZIP itself contains `module.prop` and `release.properties`; verification cross-checks all of these identities and confirms that the embedded `updateJson` points to the stable OTAST update channel.

## GitHub Actions manual workflow

Open **Actions → Release → Run workflow**.

### Prepare release

Select:

```text
What do you want to do?  prepare-release
Branch to build:          [blank]
Existing draft tag:       [blank]
Legacy version:           [blank]
```

Preparation always uses current GitHub `main`; the branch field cannot override production release source.

The job:

1. checks out `main` and records its exact SHA;
2. runs `bash scripts/test.sh --full`;
3. builds the canonical release bundle exactly once;
4. verifies the ZIP/checksum/manifest and Magisk updater schema;
5. creates or refreshes an **unproven draft**;
6. refuses to alter a draft that already contains physical-device proof;
7. redownloads the draft assets into a clean directory and verifies the hosted bytes against the locally qualified SHA.

The successful summary ends with `DRAFT READY FOR PHYSICAL QUALIFICATION`.

## Physical qualification

The supported owner-facing physical-device command remains:

```bash
otast release
```

Run the same command after every requested reboot. Its private state is resumable under:

```text
~/.local/state/otast-release/<version>/
```

The wizard installs the exact draft ZIP, crosses the required reboot boundaries, performs the OTAST Report/Preflight/Apply/Verify/idempotence/Restore lifecycle, and uploads a sanitized proof bound to that ZIP SHA-256.

Once physical proof exists, the draft candidate is immutable. A later `main` commit cannot replace its ZIP, checksum or release manifest.

The workflow still accepts the legacy `draft`/`publish` dispatch values and `version` input used by the current `otast release` wizard, while the Actions UI exposes the clearer production operation names.

## Publish release

After physical proof is attached to the draft, use:

```text
What do you want to do?  publish-release
Branch to build:          [blank]
Existing draft tag:       vX.Y.Z
Legacy version:           [blank]
```

Publication **never builds**.

The job:

1. downloads ZIP, checksum, release manifest and physical proof from the existing release;
2. runs the canonical bundle verifier;
3. validates the proof against that exact ZIP;
4. publishes the already-proven draft, or resumes safely if it was already published by a previous partial run;
5. verifies the public release still contains the proven ZIP;
6. deterministically generates the stable Magisk `update.json` metadata from the release manifest;
7. refuses to downgrade or overwrite conflicting metadata at the same versionCode;
8. updates `main/update.json` only when advancing the stable update channel;
9. reads the resulting `update.json` back from GitHub and verifies it byte-for-byte;
10. redownloads the public ZIP and confirms its digest still equals the physically proven digest.

Only then does the job report the release as published and Magisk-updateable.

If repository branch protection prevents the GitHub token from updating `main/update.json`, the release remains public but the workflow fails explicitly at updater synchronization rather than claiming full success. Resolve the repository write policy and rerun `publish-release`; publication is idempotent and the job will continue to updater verification without rebuilding.

## Build branch

For a quick development/test ZIP, select:

```text
What do you want to do?  build-branch
Branch to build:          agent/example
Existing draft tag:       [blank]
Legacy version:           [blank]
```

Blank branch means `main`.

The workflow validates that the requested value is an actual repository branch, fetches its current HEAD, records the exact commit, builds the branch's Magisk ZIP, validates its ZIP structure and uploads the ZIP as a GitHub Actions artifact.

This mode deliberately does **not**:

- create or alter a GitHub Release or tag;
- require a production checksum/proof gate;
- change `update.json`;
- publish anything;
- substitute its branch into `prepare-release` or `publish-release`.

It is an explicit branch-head build escape hatch, not a release qualification path.

## Automatic recovery and hard stops

The physical `otast release` wizard retains its existing bounded recovery policy for network/API failures, clean-main refresh, draft recovery before proof, interrupted OTAST transactions, staged module activation, late-writer settling and Restore recovery.

It still stops rather than manufacturing success when continuing would be unsafe or misleading, including wrong device/SDK, unavailable Magisk root, unverifiable pre-existing managed state, proven-asset substitution, persistent competing writes or unrecoverable Restore failure.

## Inspection and recovery

Show physical release state without changing it:

```bash
otast release --status
```

Discard only the wizard's private resume metadata when safe:

```bash
otast release --reset
```

`--reset` does not restore live managed files and is refused when throwing away state would lose an active lifecycle position.
