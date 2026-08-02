#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || exit 1
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

create_commit=0
while (($#)); do
    case $1 in
        --commit) create_commit=1; shift ;;
        -h|--help)
            printf 'Usage: %s [--commit]\n' "$0"
            exit 0
            ;;
        *) otast_script_fatal "Unknown argument: $1" ;;
    esac
done

if [[ -e $REPO_ROOT/.git ]]; then
    [[ -d $REPO_ROOT/.git && ! -L $REPO_ROOT/.git ]] || otast_script_fatal 'Existing .git path is unsafe'
    if git -C "$REPO_ROOT" rev-parse --verify HEAD >/dev/null 2>&1; then
        otast_script_fatal 'Repository already has Git history; public initialization is intentionally one-time'
    fi
    remotes=$(git -C "$REPO_ROOT" remote 2>/dev/null) || remotes=
    if [[ -n $remotes ]]; then
        otast_script_fatal 'Repository already has a remote; remove it only after explicit review'
    fi
else
    if ! git -C "$REPO_ROOT" init -q -b main; then
        otast_script_fatal 'Git initialization failed'
    fi
fi

if ! bash "$SCRIPT_DIR/test.sh" --full; then
    otast_script_fatal 'Full public-init validation failed; no commit was created'
fi
if ! git -C "$REPO_ROOT" add --all; then
    otast_script_fatal 'Git staging failed'
fi
if ((create_commit == 1)); then
    if ! git -C "$REPO_ROOT" diff --cached --check; then
        otast_script_fatal 'Staged content contains whitespace errors'
    fi
    if ! git -C "$REPO_ROOT" commit -m 'Initial public release candidate'; then
        otast_script_fatal 'Initial commit failed; configure git user.name and user.email'
    fi
    initial_commit=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null) || otast_script_fatal 'Cannot read the initial commit ID'
    otast_script_info "Initial commit: $initial_commit"
else
    otast_script_info 'Repository initialized and staged without committing'
    otast_script_info "Review: git -C '$REPO_ROOT' diff --cached --stat"
    otast_script_info "Commit: git -C '$REPO_ROOT' commit -m 'Initial public release candidate'"
fi
otast_script_info 'No GitHub remote was added and nothing was pushed'
otast_script_summary
