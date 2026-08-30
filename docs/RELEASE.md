# Releasing OTAST

`Actions -> Release -> Run workflow` is the **authoritative production release path**.

There is one production workflow, one release job, and no operator-facing prepare/publish state machine.

## Normal release

Open **Actions -> Release -> Run workflow**.

The form contains only:

```text
Version:
  optional; blank = automatic next stable patch

Run full test/fake-root qualification:
  off by default

Require physical Pixel proof before publishing:
  off by default
```

For the normal release, leave both checkboxes off and run the workflow once.

The workflow will:

1. check out current `main`;
2. resolve the next release version and monotonic `versionCode`;
3. generate release notes;
4. stamp `module/module.prop` and `CHANGELOG.md`;
5. run new-candidate source-integrity checks;
6. persist the version bump to `main`;
7. build the canonical Magisk ZIP once from that exact source commit;
8. verify ZIP, checksum and release manifest;
9. create a temporary GitHub draft containing those exact assets;
10. redownload and run mandatory hosted-release integrity checks;
11. publish that same verified draft;
12. verify the published Git tag resolves to the manifest source commit;
13. for a stable release, update `main/update.json` to the published ZIP.

A successful normal run therefore goes from current `main` to a published, version-bumped module without a second workflow dispatch.

## Versioning

When **Version** is blank, OTAST uses the stable `update.json` channel and current `module.prop` to choose the next release:

- an unpublished newer candidate on `main` is reused;
- otherwise the stable patch version is incremented;
- `versionCode` is generated monotonically.

An explicit version must be a newer valid `vMAJOR.MINOR.PATCH[-prerelease]` release identity. `versionCode` remains automatic.

The workflow does not expose a separate `versionCode` field.

## Mandatory integrity contract

The default release path intentionally avoids expensive qualification, but it does not skip integrity of the release artifact that can be published or reused.

Every workflow run validates the exact hosted release bundle before publication or retry continuation:

- canonical ZIP structure;
- SHA-256 sidecar;
- `release-manifest.json`;
- manifest version and `versionCode` identity;
- hosted draft target against the manifest source commit;
- device proof when present, and when required;
- published tag/source identity before stable-channel synchronization;
- stable updater downgrade/conflict protection when applicable.

A newly created candidate additionally runs source-tree checks before the bundle is built:

- focused release-bundle regression tests;
- repository syntax/public-safety verification;
- deterministic module build and manifest-source binding.

Those candidate-source checks deliberately do **not** rerun against whatever `main` happens to contain when resuming an existing draft or already-published release. A retry is bound to the historical release by its hosted manifest and verifies that exact hosted artifact instead of qualifying unrelated newer source.

These integrity checks are not controlled by a workflow checkbox.

## Optional full validation

Enable **Run full test/fake-root qualification** only when the stronger repository gate is wanted for a newly created candidate.

This additionally runs:

```bash
bash scripts/test.sh --full
```

That includes the complete Python suite, ShellCheck BusyBox validation, exact-ZIP fake-root lifecycle and clean-room source checks.

It is **off by default** for routine releases. It is not replayed against current `main` when resuming an already-hosted release.

## Optional physical Pixel proof

Enable **Require physical Pixel proof before publishing** only when pre-publication device proof is required.

On the first proof-gated run, the workflow:

1. prepares and persists the candidate;
2. builds the exact canonical bundle;
3. creates the GitHub draft;
4. redownloads and verifies the draft;
5. leaves it unpublished because the proof asset is absent.

The run succeeds with:

```text
DRAFT READY — PHYSICAL PROOF REQUIRED
```

Qualify that exact draft on the Pixel, then rerun **the same Release workflow** with the same version and physical proof enabled. The workflow validates the proof asset against the exact ZIP, publishes the existing draft, verifies its tag/source identity and synchronises stable `update.json`.

There is no separate `prepare-release` or `publish-release` action.

### Pixel helper

The optional device helper remains:

```bash
source scripts/otast-playbook.sh
otast release
```

It resolves the same canonical release identity, drives the proven reboot/apply/verify/restore lifecycle, uploads `otast-vX.Y.Z-device-proof.json`, and reruns the same authoritative Release workflow.

Use:

```bash
otast release --no-publish
```

to stop after proof upload and leave the draft unpublished.

See [Physical Pixel release proof](PHYSICAL-DEVICE-PROOF.md) for the device lifecycle itself.

## Canonical release bundle

Each release uses:

```text
otast-vX.Y.Z.zip
otast-vX.Y.Z.zip.sha256
release-manifest.json
```

`release-manifest.json` binds:

- version;
- `versionCode`;
- source commit;
- ZIP/checksum filenames;
- release tag;
- exact ZIP SHA-256.

The workflow builds a new candidate only when that release does not already exist. Existing drafts or a partially completed published release are resumed from their hosted manifest instead of being rebuilt under the same version.

## Failure and rerun behaviour

The workflow is designed so ordinary retries do not require selecting a different release operation.

If a failure occurs:

- before the release exists, rerun **Release**; an already-persisted candidate version is reused and a new candidate is qualified/built as required;
- after the verified draft exists, rerun **Release**; the exact hosted bundle is redownloaded and revalidated without rebuilding it or requalifying unrelated newer `main` source;
- after the release is public but stable `update.json` did not synchronise, rerun **Release**; the published manifest is revalidated and updater synchronisation resumes;
- if `main` moves during the version-bump push, the workflow stops before publishing and asks for a rerun against current `main`.

The workflow never creates an internal release PR or silently selects a different branch.

## Stable Magisk update channel

Stable releases update:

```text
https://raw.githubusercontent.com/cbkii/otast/main/update.json
```

to the exact published asset:

```text
https://github.com/cbkii/otast/releases/download/vX.Y.Z/otast-vX.Y.Z.zip
```

Prereleases are published as GitHub prereleases and do not change stable `update.json`.

## Development branch builds

Development ZIPs remain separate under **Actions -> Build Branch**.

That workflow is read-only and does not:

- create or publish Releases;
- create production tags;
- update `module.prop` release identity;
- update `update.json`;
- substitute a branch for production `main`.
