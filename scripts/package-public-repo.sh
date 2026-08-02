#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || exit 1
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1
output=${1:-"$REPO_ROOT/dist/otast-public-ready.zip"}
case "$output" in /*) ;; *) output=$REPO_ROOT/$output ;; esac
if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" package-source --output "$output"; then
    otast_script_error 'Public repository packaging failed'
else
    otast_script_info "Public repository ZIP: $output"
    otast_script_info "Checksum: $output.sha256"
fi
otast_script_summary
