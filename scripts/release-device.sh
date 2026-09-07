#!/usr/bin/env bash
# Fail-closed public entry guard for the OTAST physical release workflow.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'STOP: cannot resolve script directory.\n' >&2
    exit 1
}

[[ -n ${HOME:-} ]] || {
    printf 'STOP: HOME is unavailable; private release state cannot be addressed safely.\n' >&2
    exit 1
}
STATE_BASE=$HOME/.local/state/otast-release
if [[ -L $STATE_BASE ]]; then
    printf 'STOP: private release state base is a symlink: %s\n' "$STATE_BASE" >&2
    exit 1
fi

CORE=$SCRIPT_DIR/release-device-core.sh
[[ -f $CORE && ! -L $CORE ]] || {
    printf 'STOP: qualified release core is missing or unsafe: %s\n' "$CORE" >&2
    exit 1
}

# The core owns option parsing, candidate reconciliation, device lifecycle, and
# publication. Guarding the state root here ensures even --status/--reset cannot
# reach state operations through a symlinked private base.
# shellcheck source=scripts/release-device-core.sh
source "$CORE" "$@"
