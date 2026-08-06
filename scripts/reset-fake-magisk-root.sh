#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'ERROR: Cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

fixture_input=${1:-}
name=${2:-current}
candidate_zip=${3:-}
(($# <= 3)) || otast_script_fatal "Usage: $0 FIXTURE_DIR [WORKING_NAME] [MODULE_ZIP]"
[[ -n $fixture_input ]] || otast_script_fatal "Usage: $0 FIXTURE_DIR [WORKING_NAME] [MODULE_ZIP]"
fixture=$(cd -- "$fixture_input" >/dev/null 2>&1 && pwd -P) || otast_script_fatal "Fixture does not exist: $fixture_input"
case $name in ''|*[!A-Za-z0-9._-]*) otast_script_fatal "Unsafe working-root name: $name" ;; esac
allowed=${HOME:?}/.cache/otast/fake-roots
destination=$allowed/$name
mkdir -p -- "$allowed" || otast_script_fatal "Cannot create fake-root cache: $allowed"
chmod 0700 -- "$allowed" 2>/dev/null || true

clone_args=(
    -m tools.otastctl
    --repo-root "$REPO_ROOT"
    fixture-clone
    "$fixture"
    "$destination"
    --allowed-root "$allowed"
)
if [[ -n $candidate_zip ]]; then
    [[ -f $candidate_zip && ! -L $candidate_zip ]] || \
        otast_script_fatal "Candidate module ZIP is missing or unsafe: $candidate_zip"
    clone_args+=(--module-zip "$candidate_zip")
fi

report=$allowed/.${name}.clone-report.$$.json
if ! otast_python "${clone_args[@]}" >"$report"; then
    rm -f -- "$report"
    otast_script_fatal 'Exact-ZIP fixture clone failed'
fi
mv -- "$report" "$destination/clone-report.json" || otast_script_fatal 'Cannot publish clone report'
otast_script_info "Disposable fake Magisk root: $destination"
otast_script_info "Exact candidate evidence: $destination/candidate-module.json"
printf 'Validate with:\n'
printf '  bash %q %q preflight\n' "$SCRIPT_DIR/validate-fake-magisk-root.sh" "$destination"
otast_script_summary
