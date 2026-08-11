# Releasing OTAST

OTAST deliberately separates **production releases** from **development branch builds**.

Production releases are exact-ZIP, physical-proof-bound and publication-gated. Branch builds are read-only development artifacts and never modify release state.

The production invariant is the module ZIP SHA-256. A source commit is useful provenance, but proof for one ZIP never authorizes another ZIP.

## Stable Magisk update channel

Every production OTAST ZIP contains `module.prop` with:

```text
updateJson=https://raw.githubusercontent.com/cbkii/otast/main/update.json
```

Stable `update.json` represents the latest successfully published **final** release:

```json
{
  "version": "vX.Y.Z",
  "versionCode": 123,
  "zipUrl": "https://github.com/cbkii/otast/releases/download/vX.Y.Z/otast-vX.Y.Z.zip",
  "changelog": "https://raw.githubusercontent.com/cbkii/otast/main/CHANGELOG.md"
}
```

Candidate source metadata in `module/module.prop` may be ahead of `update.json`. Preparing a candidate never advertises it to Magisk users. Stable `update.json` changes only after the exact final GitHub Release is public and verified.

Prereleases such as `v1.2.0-rc1` may be prepared, physically proven and published as GitHub prereleases, but are never marked latest and never alter stable `update.json`.

## Automatic release versioning

The production Release workflow exposes one optional **Version** field.

When Version is blank:

- if `main` already contains an unpublished candidate with a `versionCode` newer than stable `update.json`, that candidate is reused exactly;
- otherwise the stable final patch version is incremented automatically, for example `v1.0.0` → `v1.0.1`;
- `versionCode` is generated automatically and monotonically.

When Version is explicit, for example `v1.1.0` or `v1.1.0-rc1`, OTAST validates it and generates the next monotonic `versionCode`. Operators never type `versionCode`.

Repeated Prepare runs for the same unpublished candidate are idempotent and do not increment the version again.

Release preparation stamps the authoritative candidate fields in `module/module.prop` and updates/replaces the matching `CHANGELOG.md` section. It does **not** modify stable `update.json`.

The installer reads its displayed version from packaged `module.prop`; there is no separate installer version string to maintain.

## Production Release workflow

Open **Actions → Release → Run workflow**.

The form contains only:

```text
Action:
  prepare-release | publish-release

Version:
  optional; blank = automatic/reusable candidate

Run full validation:
  checked by default
```

There are no branch, tag, legacy-operation, legacy-version or manual versionCode inputs.

### Prepare release

Typical automatic patch preparation:

```text
Action:               prepare-release
Version:              [blank]
Run full validation:  ☑
```

The workflow:

1. checks out current `main`;
2. resolves the candidate version and automatic `versionCode`;
3. generates concise release notes from repository history;
4. stamps `module.prop` and idempotently updates the candidate `CHANGELOG.md` section;
5. always runs focused release regression/integrity checks;
6. when **Run full validation** is checked, also runs `bash scripts/test.sh --full`;
7. persists release metadata to `main` before any production draft exists;
8. verifies `main` contains the resolved candidate;
9. builds the canonical production bundle exactly once from that final source commit;
10. creates or refreshes an **unproven** GitHub draft;
11. pins the lightweight release tag to the exact qualified source commit;
12. redownloads the hosted ZIP/checksum/manifest and verifies the remote bytes.

A successful run ends with:

```text
DRAFT READY FOR PHYSICAL QUALIFICATION
```

### Validation checkbox

When checked:

```text
FULL VALIDATION: RUN / PASS
```

and the complete repository/fake-root gate runs.

When unchecked:

```text
FULL VALIDATION: SKIPPED BY OWNER
MANDATORY RELEASE INTEGRITY: PASS
```

The checkbox never disables:

- release-version validation;
- focused release regression tests;
- repository/update-channel contract validation;
- deterministic package checks;
- canonical ZIP/checksum/manifest verification;
- embedded Magisk metadata validation;
- physical proof requirements;
- publication/updater validation.

Unchecked therefore means only that the expensive complete fake-root/full suite was intentionally skipped.

## Protected `main`

Release metadata must reach `main` before a production candidate is built.

The workflow first attempts the normal owner-authorized update. If repository protection rejects that update, it attempts a narrowly scoped internal release-metadata PR and merge without disabling protection.

If repository policy still requires a human-only approval or another condition the workflow token cannot satisfy, the run stops **before creating a production draft**. It does not weaken or disable branch protection.

## Canonical production bundle

After candidate metadata is finalized on `main`, `scripts/build-release.sh` produces:

```text
dist/
├── otast-vX.Y.Z.zip
├── otast-vX.Y.Z.zip.sha256
└── release-manifest.json
```

The portable checksum sidecar contains only the ZIP basename. `otastctl verify-release` resolves explicit paths, so verification is independent of caller working directory.

The manifest binds:

- version;
- versionCode;
- exact source commit;
- ZIP/checksum names;
- exact ZIP SHA-256;
- release tag.

The ZIP itself contains `module.prop` and `release.properties`, which are cross-checked against the manifest.

## Physical qualification

The owner-facing physical workflow remains:

```bash
otast release
```

To request an explicit version:

```bash
otast release --version v1.1.0
```

Run the same command after every requested reboot. State is resumable under:

```text
~/.local/state/otast-release/<version>/
```

The wizard prepares/resolves the candidate through the current Release workflow, downloads the exact draft, installs that ZIP through Magisk, crosses real reboot boundaries, performs the OTAST Report/Preflight/Apply/Verify/idempotence/Restore lifecycle, and uploads sanitized proof bound to that ZIP SHA-256.

Once physical proof exists, the candidate is immutable. A later change to `main` cannot replace its ZIP, checksum, manifest or tag target.

To stop after uploading PASS proof and leave the release as a draft:

```bash
otast release --no-publish
```

## Publish release

From Actions, normal publication is simply:

```text
Action:   publish-release
Version:  [blank]
```

Blank Version selects the candidate only when **exactly one physically proven draft** exists.

If no eligible proven draft exists, publication stops. If multiple proven drafts exist, publication stops and reports their versions rather than guessing.

An explicit Version selects that exact proven candidate:

```text
Action:   publish-release
Version:  v1.1.0
```

Publication never rebuilds.

It:

1. selects the exact physically proven candidate;
2. downloads ZIP, checksum, manifest and device proof;
3. runs the canonical bundle verifier;
4. validates proof against that exact ZIP;
5. publishes the already-proven draft;
6. verifies the public ZIP digest;
7. for a final release, generates stable `update.json` from the proven manifest;
8. refuses updater downgrade or conflicting equal-version metadata;
9. persists and rereads stable updater metadata;
10. confirms the Magisk update channel points to the exact published ZIP.

A prerelease follows the same exact-asset/proof publication path but leaves the stable Magisk channel unchanged.

## Development branch build

Development builds use the separate **Actions → Build Branch** workflow.

Its entire form is:

```text
Branch:
  optional; blank = main
```

The workflow resolves the named repository branch HEAD, builds a Magisk-installable ZIP, structurally validates it and uploads that ZIP as an Actions artifact.

It uses read-only repository permissions and never:

- creates or modifies a GitHub Release;
- creates or moves production release tags;
- requires physical proof;
- changes `update.json`;
- publishes anything;
- substitutes its branch into production release preparation.

## Recovery and hard stops

The physical wizard retains bounded recovery for ordinary network/API failures, clean-main refresh, interrupted OTAST transactions, staged module activation, late-writer settling and Restore recovery.

It still stops rather than manufacturing success when continuing would be unsafe or misleading, including:

- wrong device/SDK;
- unavailable Magisk root;
- unverifiable pre-existing managed state;
- proven-asset substitution;
- persistent competing writers;
- unrecoverable Restore failure;
- release metadata that cannot safely reach protected `main`.

Show resumable state without mutation:

```bash
otast release --status
```

Discard only the wizard's private resume metadata when safe:

```bash
otast release --reset
```

`--reset` does not restore live managed files and is refused when losing the lifecycle position would be unsafe.
