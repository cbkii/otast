#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || exit 1
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1
output=${1:-"$REPO_ROOT/reports/fake-magisk-root"}
case "$output" in /*) ;; *) output=$REPO_ROOT/$output ;; esac
if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" fake-root --output "$output"; then
    otast_script_error 'Fake Magisk root qualification failed'
else
    otast_script_info "Evidence: $output/fake-magisk-root.json"
    otast_script_info "Log: $output/fake-magisk-root.log"
fi
otast_script_summary
