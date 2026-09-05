# Repository governance

OTAST's source, release and qualification controls are designed to fail closed, but GitHub repository settings are an independent control plane. Source changes cannot enable branch protection for themselves.

## `main` protection contract

The intended repository configuration for `main` is:

- changes arrive through pull requests rather than direct routine pushes;
- the canonical **CI / full-validation** check must pass on the current PR head/merge state before merge;
- conversations and requested changes must be resolved before merge;
- force pushes are disabled;
- branch deletion is disabled;
- required checks must apply to the latest reviewed head rather than an older successful commit;
- bypass is reserved for deliberate repository-owner recovery, not normal development or release operation.

GitHub branch/ruleset configuration lives outside this repository and must be verified in repository settings. A green workflow by itself does not prove that GitHub is configured to require it.

## Review contract

Before a PR is called review-ready:

1. compare the complete current diff against `main`;
2. inspect review submissions, inline threads, bot findings and applicable check results;
3. run `bash scripts/test.sh --full` on the exact current code;
4. build and verify the exact Magisk deliverable/provenance evidence;
5. keep physical-device qualification and release publication separate unless explicitly being performed;
6. preserve open upstream-review gates when a dependency changed semantically.

A mergeable PR is not automatically merge-ready. A release artefact produced from a PR is not automatically release-qualified.

## Workflow dependency policy

External GitHub Actions are pinned to immutable commit SHAs. Human-readable version comments identify the intended upstream major version, while Dependabot provides reviewable updates to the pinned SHAs.

Do not replace immutable action pins with floating major-version tags merely to simplify updates.

## Release authority

The production Release workflow operates from authoritative `main`. Stable publication additionally requires the release-time compatibility monitor, full deterministic qualification, exact hosted-bundle verification, and valid physical Pixel proof for the exact candidate.

No branch-protection setting, bot status or CI success may be treated as a substitute for those release gates.

## Periodic verification

Repository maintainers should periodically confirm that GitHub-side settings still match this document, especially after changing repository ownership, Actions permissions, rulesets, branch-protection configuration or required check names.
