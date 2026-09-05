# OTAST maintenance from Termux

This is the normal ongoing maintenance interface. Commands are exposed through `scripts/otast-playbook.sh` and return controlled statuses rather than terminating the interactive Termux shell.

## Commands

```bash
otast maintain
```

Checks prerequisites/authentication, compares all explicit monitored upstream refs against reviewed baselines, then runs repository validation only when every target is current.

```bash
otast review TARGET
```

Reviews one changed target using exact old/observed commits. It now performs **two independent comparisons** before any baseline may move:

1. GitHub source changed paths are classified by the target's machine-readable impact policy;
2. retained immutable old/new installable module trees are compared by path/hash/mode.

It then stages the candidate into a fake Magisk root and runs read-only Report/Preflight evidence. Upstream installers are never executed.

```bash
otast accept TARGET
```

Permitted only after a review whose result is `DOCS_OR_CI_ONLY` **and** whose immutable old/new module trees are byte/mode identical. It updates only:

```text
targets.<target>.monitor.expected_head
```

Native, preserved, managed, structure-sensitive, module-identity and unknown changes are never automatically accepted.

```bash
otast prepush
```

Runs the public-boundary audit, device-derived lifecycle proof and exact-commit qualification. Run it after committing locally and before pushing release-sensitive work.

```bash
otast cleanup --dry-run
```

Shows removable transient monitor/review/maintenance reports. Cleanup never removes private device fixtures, fake roots, retained upstream evidence or `.otast-keep` directories.

## Exit statuses

| Status | Meaning |
|---|---|
| `0` | Requested workflow completed; monitor is current or a docs/CI-only review is acceptance-ready. |
| `10` | A reliable comparison completed and compatibility review/qualification is required. |
| `20` | Authentication, API, registry, evidence or tooling failure prevented a reliable result. |

Status `10` is a completed review state, not a network retry condition.

## Semantic upstream-impact classes

Every changed source path is classified deterministically using the reviewed target record:

- `DOCS_OR_CI_ONLY` — documentation/workflow/metadata surface only;
- `PRESERVED_SURFACE_CHANGED` — upstream-owned surface OTAST deliberately preserves;
- `NATIVE_DEPENDENCY_CHANGED` — Zygisk/native/build-toolchain surface requiring ABI/platform review;
- `MANAGED_WHOLE_FILE_CHANGED` — a whole-file neutraliser surface changed;
- `STRUCTURE_SENSITIVE_CHANGED` — an exact-hash/anchor transform surface changed;
- `MODULE_IDENTITY_CHANGED` — `module.prop`/distribution identity changed;
- `UNKNOWN_PACKAGE_CHANGE` — changed source cannot be safely classified or source comparison is incomplete.

Overlapping path globs resolve to the highest-risk matching class. A broad preserved path cannot mask a structure-sensitive writer.

`DOCS_OR_CI_ONLY` is **not** accepted from source classification alone. The installable module tree must also be byte/mode identical and comparison/Report evidence must succeed. If source appears docs-only but the module tree changes, the review is upgraded to `UNKNOWN_PACKAGE_CHANGE`.

A `NATIVE_DEPENDENCY_CHANGED` result is always review-required even when the current installable module tree happens to be identical. This is intentional: ABI, page-size, linker and build-toolchain changes require the appropriate platform/native evidence rather than automatic baseline movement.

## Current PIF regression fixture

The repository retains the real source-path delta between:

- reviewed baseline `b994391970b51a2dfefed0e1d420dd6b017756e8`;
- observed `inject_s` head `2f8199a90a150ad98921438608e1e0e951ba2d5f`.

The changed paths are workflow/Gradle/Zygisk-build surfaces. Because the highest relevant class is native/build dependency, the deterministic result is `NATIVE_DEPENDENCY_CHANGED`. The PIF monitor baseline therefore remains at the reviewed commit until native/platform qualification is completed; it is not silently advanced merely because managed shell writers did not move.

## Distribution identity

A branch head is provenance, not always the installable compatibility boundary. Each managed target records its relevant distribution model: branch build/source, release asset, release/workflow artefact, or branch source with a reviewed version range. Where available this also records release/tag/ref, source commit, asset name/SHA-256, module ID, author, version and versionCode.

This metadata allows maintenance to distinguish a docs-only source commit from an installable package/native change.

## Normal update sequence

### 1. Detect

```bash
otast maintain
```

A changed target produces `REVIEW_REQUIRED`, exit `10`, and the exact `otast review TARGET` command.

### 2. Review

```bash
otast review playintegrityfix
```

Review outputs live below:

```text
reports/target-review-<target>-<observed-sha>-<timestamp>/
```

and include:

- `source-comparison.json` — exact changed source paths and compare completeness;
- `impact-classification.json` — deterministic semantic class per path and overall class;
- `module-comparison.json` — immutable installable tree hash/mode comparison;
- `review.json` / `review.md` — combined decision and evidence summary;
- `review.log` — fake-root/materialisation validation log.

Possible completed semantic results are the seven impact classes above. `VALIDATION_FAILED` is an evidence/tooling error and exits `20`.

### 3A. Accept a proven docs/CI-only update

```bash
otast accept TARGET
```

Acceptance requires `DOCS_OR_CI_ONLY`, complete source comparison, an identical module tree and valid comparison/Report evidence. The structured update changes only `monitor.expected_head`, then immediately re-runs the authenticated monitor. If confirmation fails, the registry is restored.

### 3B. Handle every runtime-relevant class

Do **not** run `accept`. Inspect the exact changed surface and update compatibility contracts/runtime/tests only when justified. Native changes require native/platform evidence; structure-sensitive changes require reviewed source hashes/anchors; module identity/distribution changes require exact artefact review. Then run the standard full validation and physical/device proof where the supported runtime boundary changed.

## Native/runtime evidence

For read-only environment qualification:

```bash
python3 scripts/runtime-compatibility-evidence.py \
  --output "$HOME/otast-runtime-compatibility.json"
```

The collector reads only compatibility-registry dependency IDs and records runtime page size, ABI, Magisk/Zygisk identity, native `.so` inventory and ELF `PT_LOAD` alignment evidence. It does not modify Zygisk Next, Vector, Inline Hook Invalidate, Magisk denylist state or target applications.

Detector cleanliness is not an OTAST acceptance condition. Use detector diagnostics for attribution, not as a reason to mutate unrelated module configuration.

## GitHub authentication

Local monitoring uses authenticated `gh api`. Configure once with:

```bash
gh auth login --hostname github.com
otast doctor
```

The active token is passed only to child processes and is not printed or written to reports. Monitoring checks API allowance before partial comparisons.

## GitHub Actions issue reconciliation

The target-monitor workflow compares explicit monitored refs and reconciles one deterministic issue per target. A review-required state is an expected monitoring outcome; a monitor/authentication error is not. Issues close only when the default branch contains a reviewed matching baseline.

Issue instructions require semantic source classification, immutable installable-tree comparison, fake-root evidence and full validation before a baseline may advance.

## Report retention

Successful workflows retain the requested recent successful history plus the newest failed diagnostic run. Preserve a report indefinitely with:

```bash
touch reports/<report-directory>/.otast-keep
```

Inspect cleanup without deletion with:

```bash
otast cleanup --dry-run --keep 3
```
