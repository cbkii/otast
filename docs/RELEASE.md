# Releasing OTAST

OTAST separates production releases from development branch builds.

Production releases are exact-ZIP and publication-gated. Physical Pixel proof is available as a stronger validation layer and is **required by default**, but the repository owner may explicitly disable that requirement for a manual `workflow_dispatch` publication.

The primary production identity is the module ZIP SHA-256. A source commit is useful provenance, but evidence for one ZIP never authorizes another ZIP.

## Stable Magisk update channel

Every production ZIP contains `module.prop` with:

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

Prereleases may be published as GitHub prereleases but are never marked latest and never alter stable `update.json`.

## Automatic release versioning

When **Version** is blank:

- an existing unpublished candidate on `main` with a newer `versionCode` is reused exactly;
- otherwise the stable final patch version is incremented automatically;
- `versionCode` is generated monotonically.

When **Version** is explicit, OTAST validates it and generates the next monotonic `versionCode` automatically.

Prepare stamps candidate metadata in `module/module.prop` and updates/replaces the matching `CHANGELOG.md` section. It does **not** modify stable `update.json`.

## Production Release form

Open **Actions → Release → Run workflow**.

The form contains:

```text
Action:
  prepare-release | publish-release

Version:
  optional; blank = automatic/reusable candidate

Run full validation:
  checked by default

Require Pixel physical-device proof before publishing:
  checked by default
```

The physical-proof checkbox affects **Publish only**. Prepare always creates the same exact candidate bundle regardless of that setting.

## Prepare release

Typical preparation:

```text
Action:                                  prepare-release
Version:                                 [blank]
Run full validation:                     checked
Require Pixel physical-device proof:     either value; ignored by Prepare
```

Prepare:

1. checks out current `main`;
2. resolves candidate version and automatic `versionCode`;
3. generates concise release notes;
4. stamps `module.prop` and the candidate changelog section;
5. always runs focused release regression/integrity checks;
6. optionally runs `bash scripts/test.sh --full`;
7. persists release metadata to `main` before creating the production draft;
8. builds the canonical production bundle exactly once from that final source commit;
9. creates or refreshes an **unproven** GitHub draft;
10. redownloads the hosted ZIP/checksum/manifest and verifies their exact bytes;
11. verifies the draft `target_commitish` is the qualified source SHA.

A GitHub draft may legitimately have no `refs/tags/vX.Y.Z` yet. That is normal. Prepare therefore does **not** require a release Git tag to exist while the release remains draft. If a tag already exists, it must resolve safely to the qualified source.

A successful Prepare ends with:

```text
DRAFT READY
```

## Validation checkbox

When checked, Prepare also runs:

```bash
bash scripts/test.sh --full
```

When unchecked, only the expensive complete fake-root/full suite is skipped.

The checkbox never disables:

- version validation;
- focused release tests;
- repository/update-channel validation;
- deterministic package validation;
- exact ZIP/checksum/manifest verification;
- embedded Magisk metadata checks;
- source identity validation;
- publication/tag verification;
- stable updater validation.

## Canonical production bundle

Prepare produces:

```text
dist/
├── otast-vX.Y.Z.zip
├── otast-vX.Y.Z.zip.sha256
└── release-manifest.json
```

The ZIP contains `module.prop` and `release.properties`. `release-manifest.json` binds version, `versionCode`, source commit, filenames, release tag and exact ZIP SHA-256.

## Physical Pixel proof

The complete operator procedure is documented in [Physical Pixel release proof](PHYSICAL-DEVICE-PROOF.md).

The recommended proof-only command on the Pixel is:

```bash
cd "$HOME/repos/otast"
git switch main
git pull --ff-only
source scripts/otast-playbook.sh
otast doctor
otast release --no-publish
```

Run the **same** `otast release --no-publish` command after every requested reboot until the wizard reports that PASS proof was uploaded and the draft was intentionally left unpublished.

The wizard locks the exact draft ZIP SHA-256 and proves:

```text
baseline recovery if required
→ exact draft install through Magisk
→ reboot
→ Report
→ Preflight READY
→ Apply
→ reboot if required
→ Verify CURRENT
→ second Apply NO_CHANGES_REQUIRED
→ second Verify CURRENT
→ Restore
→ reboot
→ confirm managed state absent
→ final Report
→ write + validate + upload proof
```

Successful proof is uploaded as:

```text
otast-vX.Y.Z-device-proof.json
```

It records schema 2, `result=PASS`, exact ZIP SHA-256, candidate version, diagnostic source commit, `tegu`, SDK 36 and the required lifecycle phase results.

## Publish with physical proof

Use:

```text
Action:                                  publish-release
Version:                                 [blank]
Require Pixel physical-device proof:     checked
```

Blank Version requires exactly one eligible draft. If several drafts are eligible, specify the exact version.

With proof required, Publish requires the draft to contain:

```text
otast-vX.Y.Z.zip
otast-vX.Y.Z.zip.sha256
release-manifest.json
otast-vX.Y.Z-device-proof.json
```

Publish validates the proof against the exact ZIP before publication.

If proof is missing, Publish stops with an actionable message: run `otast release` or explicitly disable the proof requirement for that manual publication.

## Publish without physical proof

For an owner-triggered manual release, uncheck:

```text
Require Pixel physical-device proof before publishing
```

This bypasses **only** the physical-device proof requirement.

The release still must have a complete canonical bundle and still undergoes:

- ZIP structural validation;
- checksum validation;
- manifest and embedded Magisk metadata validation;
- source identity validation;
- publication of the existing draft without rebuilding;
- post-publication Git tag verification against the manifest source SHA;
- public ZIP SHA-256 verification;
- final-release stable `update.json` synchronization and verification.

If a device-proof asset is already present, Publish validates it even when the checkbox is unchecked.

## Publication sequence

Publish never rebuilds.

For a final release it:

1. selects the exact eligible candidate;
2. downloads ZIP/checksum/manifest and optional/required proof;
3. verifies the canonical bundle;
4. validates proof when present, and requires it when the checkbox is checked;
5. publishes the existing draft;
6. waits boundedly for GitHub to create/resolve the release tag;
7. verifies the tag points to the exact manifest source commit;
8. verifies the public ZIP SHA-256;
9. generates stable `update.json` from the release manifest;
10. refuses updater downgrade or conflicting equal-version metadata;
11. persists and rereads stable updater metadata;
12. confirms Magisk's stable update channel points to the exact published ZIP.

A prerelease follows the same exact-bundle publication and tag verification but leaves stable `update.json` unchanged.

## Physical proof recovery

Private physical-release state is stored under:

```text
~/.local/state/otast-release/<version>/
```

Use:

```bash
otast release --status
```

to inspect progress.

The wizard is resumable across reboot boundaries. If a valid proof asset is already present on the draft, it can recover that proof instead of repeating device qualification. If publication fails after proof succeeds, rerunning the release flow reuses the same proof-bearing candidate rather than rebuilding it.

Do not manually create or edit proof JSON to force publication.

## Development branch build

Development builds use **Actions → Build Branch**.

Its form contains only:

```text
Branch:
  optional; blank = main
```

It resolves the selected branch HEAD, builds a Magisk-installable ZIP, structurally validates it and uploads the ZIP as an Actions artifact.

It uses read-only repository permissions and never creates/releases tags, modifies production Releases, requires physical proof, updates `update.json`, or substitutes a branch into production release preparation.

## Hard stops

OTAST still stops rather than manufacturing success for states such as:

- wrong device/SDK during physical proof;
- unavailable Magisk root;
- unverifiable or drifted pre-existing managed state;
- candidate ZIP substitution after proof begins;
- persistent second-Apply writer conflict;
- failed Restore that cannot be recovered safely;
- malformed or mismatched proof;
- incomplete canonical release bundle;
- published tag/source mismatch;
- updater downgrade or conflicting equal-version metadata.
