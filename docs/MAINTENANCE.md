# OTAST maintenance from Termux

This is the normal ongoing maintenance interface for the repository. The commands are sourceable through `scripts/otast-playbook.sh` and are designed to return controlled statuses rather than terminate the interactive Termux shell.

## Commands to remember

```bash
otast maintain
```

Runs the normal end-to-end maintenance sequence:

1. checks Termux and repository prerequisites;
2. verifies authenticated GitHub CLI access and API allowance;
3. compares all monitored upstream refs with reviewed baselines;
4. runs the standard repository tests when all targets are current;
5. writes structured Markdown/JSON output;
6. removes superseded transient reports only after a successful run.

```bash
otast review TARGET
```

Investigates one changed target using the exact old and observed Git commits. It retains both immutable source archives, compares the module trees including hashes and modes, creates a staged fake root, and runs Report and Preflight. It never executes upstream installers.

```bash
otast accept TARGET
```

Permitted only after a completed `NO_PACKAGE_IMPACT` review. It updates only:

```text
targets.<target>.monitor.expected_head
```

It deliberately leaves historical `reviewed_sources` provenance unchanged. It then runs an authenticated monitor and restores the original registry automatically if the accepted target is not confirmed.

```bash
otast prepush
```

Runs the public-boundary audit, device-derived lifecycle proof, and exact-commit qualification. Run it after committing locally and before pushing.

```bash
otast cleanup --dry-run
```

Shows which old transient monitor, review, and maintenance reports would be removed. The automatic cleanup contract never removes device fixtures, fake roots, upstream source evidence, qualification evidence, non-matching report directories, or directories containing `.otast-keep`.

## Exit statuses

The maintenance commands use distinct statuses:

| Status | Meaning |
|---|---|
| `0` | Requested workflow completed successfully. |
| `10` | A valid comparison completed and target review is required. |
| `20` | Authentication, API, registry, validation, or tooling failure prevented a reliable result. |

Status `10` is not a network retry condition and must not be hidden with `|| true`.

## GitHub authentication

Local monitoring uses `gh api`. Run this once during Termux setup:

```bash
gh auth login --hostname github.com
```

Check it with:

```bash
otast doctor
```

The maintenance script uses an existing `GH_TOKEN`/`GITHUB_TOKEN` when provided. Otherwise it obtains the active credential through `gh auth token` only for child processes. The token is not printed, written to reports, or stored in the repository.

Before target lookup, the command reads the authenticated core API allowance and stops before making partial comparisons when the remaining budget is too low.

## Normal target-update sequence

### 1. Detect

```bash
otast maintain
```

When a target changed, the command exits `10`, writes a target-monitor report, and prints the exact review command.

### 2. Review

```bash
otast review yurikey
```

Possible results:

- `NO_PACKAGE_IMPACT`: old and new immutable module package trees are byte/mode identical and comparison/Report evidence is valid; staged Preflight is retained as diagnostic evidence when static source topology cannot model installer-derived runtime topology;
- `PACKAGE_CHANGED`: compatibility/runtime work is required before the baseline can move;
- `VALIDATION_FAILED`: the generated review log must be investigated.

Review outputs are stored under:

```text
reports/target-review-<target>-<observed-sha>-<timestamp>/
```

The output includes `review.json`, `review.md`, `module-comparison.json`, and `review.log`.

### 3A. Accept a proven no-impact update

```bash
otast accept yurikey
```

This selects the latest passing review for that target, performs a structured single-field update, confirms it through the authenticated monitor, records `acceptance.json`, and prints the resulting Git diff boundary.

### 3B. Handle a changed package

Do not run `accept`. Update the relevant compatibility profile, templates, writer/path rules, tests, and documentation. Obtain device-derived installed-tree proof when installer-generated files or runtime branching prevents static certainty. Then rerun:

```bash
otast review TARGET
otast maintain --full
otast prepush
```

## Fake-root names

Commands that accept a fake root now support a safe bare name:

```bash
otast action review-yurikey-5330b77c0b79 report
```

A bare name resolves only below:

```text
~/.cache/otast/fake-roots
```

Absolute paths are accepted only when the existing safety guard confirms they remain in that same private disposable root.

## Reports and troubleshooting

Every maintenance stage writes a persistent log and machine-readable JSON. A failure summary always includes the report/log path. Successful runs prune superseded transient reports, keeping the newest three by default.

To preserve a report indefinitely:

```bash
touch reports/<report-directory>/.otast-keep
```

To inspect cleanup without deleting anything:

```bash
otast cleanup --dry-run --keep 3
```

## GitHub Actions issue reconciliation

`.github/workflows/target-monitor.yml` runs twice weekly and on manual dispatch. It uses the workflow `GITHUB_TOKEN` with `contents: read` and `issues: write`, uploads the complete monitor report, and reconciles one deterministic issue per target.

A changed or failed target issue contains:

- a stable hidden target marker;
- expected and observed commits;
- exact Termux reproduction commands;
- required evidence and acceptance criteria;
- the PR closure instruction.

An issue is closed only when a later default-branch monitor reports that target as supported. `REVIEW_REQUIRED` is a successful monitoring outcome and does not fail the workflow; an actual monitor error does.

The workflow raises and maintains issues. It does not itself schedule or operate a ChatGPT agent. A scheduled agent can use the deterministic issue format as its work queue.

## Reliability corrections derived from the initial Termux rollout

The v5 workflow directly addresses these observed failures:

| Earlier failure | Correction |
|---|---|
| Kit checks omitted ShellCheck in the packaging environment and successive warnings appeared only on-device. | Installer and self-test run all available shell lint before copying; regression tests also cover the specific retired colour variables, ambiguous assignments, and completion-array construction that failed previously. |
| Top-level `exit 1` inside a block sourced by `spaste` could close the interactive Termux shell. | User-facing commands return controlled statuses. Documentation no longer requires sourced blocks containing top-level `exit`. |
| `git diff` showed nothing because the overlay files were untracked. | The installer prints every changed path; the commit procedure uses `git status`, `git add -N` for review, and an explicit file list. |
| `REVIEW_REQUIRED` looked like an ordinary failure. | Exit `10` is reserved for a completed comparison requiring review; exit `20` means the comparison itself failed. Reports print exact next commands. |
| `refresh upstream` assumed release assets although Yurikey was monitored by branch commit. | `otast review TARGET` always binds old and observed refs to immutable commit archives and handles branch-monitored targets automatically. |
| Bare fake-root names were interpreted relative to `$HOME` and then rejected. | Safe bare names now resolve only below `~/.cache/otast/fake-roots`. |
| A global SHA text replacement stopped because the same historical commit legitimately appeared twice. | `otast accept` performs a structured update of only `targets.<target>.monitor.expected_head` and proves no other JSON value changed. |
| Monitor requests were unauthenticated and exhausted the low IP-based API allowance. | All monitoring uses authenticated `gh api`, checks the rate budget before lookup, and does not retry deterministic authentication/rate failures. |
| Final `printf` statements masked the failing command status in sourced blocks. | The command hub propagates the documented status from each maintenance stage. |
| Reports accumulated and obscured the current result. | A successful run keeps the newest successful history and newest failed diagnostic run, removes older managed reports, and honours `.otast-keep`. |
| Python contract tests could create `__pycache__` and unrelated untracked files. | Installer syntax checks avoid imports and self-tests set `PYTHONDONTWRITEBYTECODE=1`; a regression test enforces this. |
| Target-update steps were spread across ad hoc commands and manual path/SHA handling. | `maintain → review → accept → prepush` is now the canonical sequence, with JSON/Markdown evidence at each boundary. |
| GitHub monitoring automation was not proven to create deterministic agent-readable issues. | The scheduled workflow now reconciles one marker-based issue per target, binds a newly created issue body to its actual issue number, uploads evidence, and treats review-required as an expected workflow result. |


## Test-process isolation

Contract tests must never assign directly to functions on shared standard-library
modules such as `os.geteuid`. Ownership tests derive the expected UID from the
fixture path owner and use bounded `mock.patch` contexts. The installer self-test
runs maintenance and playbook contracts together in one process so cross-module
state leakage is detected before normal maintenance begins.
