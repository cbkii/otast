#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || exit 1
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

output=${1:-"$REPO_ROOT/dist"}
case "$output" in /*) ;; *) output=$REPO_ROOT/$output ;; esac

commit_sha=unknown
if git -C "$REPO_ROOT" rev-parse --verify HEAD >/dev/null 2>&1; then
    commit_sha=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null)
    rc=$?
    if ((rc != 0)) || [[ -z $commit_sha ]]; then
        otast_script_warn 'Cannot resolve source commit; recording release source as unknown'
        commit_sha=unknown
    fi
fi

if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" build-release \
    --output "$output" \
    --commit-sha "$commit_sha"; then
    otast_script_error 'Release bundle build/verification failed'
fi

otast_script_summary
