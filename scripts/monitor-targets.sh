#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'ERROR: Cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

output=${1:-"$REPO_ROOT/reports/target-monitor"}
case "$output" in /*) ;; *) output=$REPO_ROOT/$output ;; esac
otast_python -m tools.otastctl --repo-root "$REPO_ROOT" monitor --output "$output"
status=$?
case $status in
    0) otast_script_info "All monitored upstream heads match reviewed baselines" ;;
    2) otast_script_error "One or more upstream heads require compatibility review" ;;
    *) otast_script_error "Target monitoring failed" ;;
esac
otast_script_info "Report: $output/target-monitor.md"
otast_script_summary
