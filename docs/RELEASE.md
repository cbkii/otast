# Releasing OTAST

`Actions -> Release -> Run workflow` is the **authoritative production release path**.

There is one production workflow, one release job, and no operator-facing prepare/publish state machine.

## Release form

The form contains only:

```text
Version:
  optional; blank = automatic next stable patch

Run full test/fake-root qualification:
  optional for prereleases; stable releases run it regardless

Require physical Pixel proof before publishing:
  on by default; stable releases require it regardless
```

The checkboxes therefore control only prerelease policy. They cannot weaken a stable release.

## Stable release contract

A stable publication is fail-closed unless all of the following succeed:

1. current `main` is checked out;
2. the requested/automatic version and monotonic `versionCode` are resolved;
3. a **fresh compatibility target monitor** reports `SUPPORTED` before release metadata, `main`, tags or Releases are mutated;
4. release notes and candidate metadata are generated;
5. new-candidate source integrity passes;
6. `bash scripts/test.sh --full` passes, including the complete Python suite, BusyBox-shell validation and fake-root qualification;
7. the version bump is persisted to the same `main` head that was qualified;
8. the canonical Magisk ZIP, checksum and `release-manifest.json` are built from that exact source commit;
9. the hosted draft bundle is redownloaded and independently verified;
10. an exact physical Pixel proof asset for that ZIP/version is present and validates;
11. that same draft is published without rebuilding;
12. the published tag resolves to the manifest source commit;
13. stable `update.json` is changed only after the published release is verified.

A stable release cannot bypass the full-validation or physical-proof gates through workflow inputs.

## Fresh target/dependency monitoring

Every release run executes:

```bash
python3 scripts/otast-maintenance.py monitor --output <temporary-evidence> --no-cleanup
```

before release mutation. A semantic upstream movement such as a managed-surface, structure-sensitive, module-identity or native-build dependency change blocks qualification and requires review. Docs/CI-only movement is handled only through the reviewed maintenance acceptance path.

The monitor evidence is uploaded as an Actions artefact for the run. The daily target-monitor workflow remains the early-warning path; release-time monitoring is the final freshness gate.

## Versioning

When **Version** is blank, OTAST uses stable `update.json` plus current `module.prop` to choose the next release:

- an unpublished newer candidate on `main` is reused;
- otherwise the stable patch version is incremented;
- `versionCode` is generated monotonically.

An explicit version must be a newer valid `vMAJOR.MINOR.PATCH[-prerelease]` identity. `versionCode` remains automatic.

## Hosted artefact integrity

Every workflow run validates the exact hosted bundle that may be published or resumed:

- canonical ZIP structure;
- SHA-256 sidecar;
- `release-manifest.json`;
- manifest version and `versionCode`;
- source commit provenance;
- hosted draft target against manifest source;
- physical proof when present and always for stable publication;
- published tag/source identity;
- stable updater downgrade/conflict protection.

A retry of an existing draft is bound to the historical hosted manifest and artefacts; it does not silently rebuild the same version from newer source.

## Full deterministic qualification

Stable candidates always run:

```bash
bash scripts/test.sh --full
```

This includes the complete unit/contract suite, ShellCheck/BusyBox validation, exact-ZIP fake-root lifecycle and clean-room source checks. It also exercises the managed upgrade/reinstall contract, including persistent state/backups, active and `modules_update` targets, candidate reinstall, second-Apply no-op, fail-closed active/staged disagreement and malformed state.

A prerelease may explicitly use the faster path by leaving **Run full test/fake-root qualification** off. This is not available to stable publication.

## Physical Pixel proof

Stable publication always requires an exact proof for the hosted ZIP. If that proof is absent, the workflow leaves the verified release as a draft and reports:

```text
DRAFT READY — PHYSICAL PROOF REQUIRED
```

Use the device helper to qualify that exact draft:

```bash
source scripts/otast-playbook.sh
otast release --no-publish
```

The proof lifecycle binds to the hosted ZIP SHA-256, executes the real Report/Preflight/Apply/reboot/Verify/no-op/Restore boundaries, validates the generated proof, and uploads `otast-vX.Y.Z-device-proof.json` beside the draft assets.

Rerun **Release** with the same version after proof upload. The workflow redownloads and validates the proof against the exact hosted ZIP before publication.

A prerelease may omit proof only when its workflow input explicitly permits that. If a proof asset exists, it is still validated.

See [Physical Pixel release proof](PHYSICAL-DEVICE-PROOF.md) for the device procedure.

## Runtime-equivalent proof reuse

Physical qualification may be reused across source commits only when the qualification registry has a `CURRENT` record whose canonical runtime digest is byte-identical to the current candidate. Reuse evidence must bind both:

- the original `qualified_source_commit`; and
- the new `current_source_commit`.

Any runtime digest change, stale/unbound record, incompatible registry provenance, or proof input mismatch invalidates reuse. Page-size qualification is independent: a 4 KiB proof does not qualify 16 KiB and vice versa.

## Canonical release bundle

Each release uses:

```text
otast-vX.Y.Z.zip
otast-vX.Y.Z.zip.sha256
release-manifest.json
```

`release-manifest.json` binds version, `versionCode`, source commit, filenames, release tag, exact ZIP SHA-256 and canonical runtime digest/provenance used by qualification.

## Failure and rerun behaviour

The workflow is intentionally idempotent around hosted release state:

- failure before a Release exists: rerun against current `main`;
- verified draft exists: rerun redownloads and validates that same hosted bundle;
- stable release published but updater sync failed: rerun resumes only after verifying the published manifest/tag;
- `main` moves during the version-bump write: the run stops before publication;
- fresh target monitoring reports semantic review required: no release mutation occurs.

The workflow never creates an internal release PR or silently selects another branch.

## Stable Magisk update channel

Stable releases update:

```text
https://raw.githubusercontent.com/cbkii/otast/main/update.json
```

to the exact verified published asset. Prereleases do not modify stable `update.json`.

## Development branch builds

Development ZIPs remain separate under **Actions -> Build Branch**. That workflow is read-only and does not create/publish Releases, create production tags, change release identity, update `update.json`, or substitute a branch for production `main`.

All external GitHub Actions used by the repository workflows are pinned to immutable commit SHAs. Dependabot is the reviewable update path for those pins.
