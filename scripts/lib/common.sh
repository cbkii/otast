#!/usr/bin/env bash

OTAST_SCRIPT_WARNINGS=${OTAST_SCRIPT_WARNINGS:-0}
OTAST_SCRIPT_ERRORS=${OTAST_SCRIPT_ERRORS:-0}

otast_script_info() {
    printf '[INFO] %s\n' "$*"
}

otast_script_warn() {
    OTAST_SCRIPT_WARNINGS=$((OTAST_SCRIPT_WARNINGS + 1))
    printf '[WARN] %s\n' "$*" >&2
}

otast_script_error() {
    OTAST_SCRIPT_ERRORS=$((OTAST_SCRIPT_ERRORS + 1))
    printf '[ERROR] %s\n' "$*" >&2
}

otast_script_fatal() {
    otast_script_error "$*"
    exit 1
}

otast_script_root() {
    local source_dir
    source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[1]}")" >/dev/null 2>&1 && pwd -P) || return 1
    cd -- "$source_dir/.." >/dev/null 2>&1 && pwd -P
}

otast_python() {
    if [[ -z ${REPO_ROOT:-} || ! -d ${REPO_ROOT:-} ]]; then
        printf '%s\n' '[ERROR] REPO_ROOT is unavailable for the OTAST Python module path.' >&2
        return 1
    fi
    PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 "$@"
}

otast_script_private_tmp() {
    local base
    if [[ -n ${TMPDIR:-} && -d ${TMPDIR:-} && -w ${TMPDIR:-} ]]; then
        base=$TMPDIR
    elif [[ -n ${PREFIX:-} && -d ${PREFIX:-}/tmp && -w ${PREFIX:-}/tmp ]]; then
        base=$PREFIX/tmp
    elif [[ -d /tmp && -w /tmp ]]; then
        base=/tmp
    else
        base=${HOME:?}/.cache/otast/tmp
        mkdir -p -- "$base" || return 1
        chmod 0700 -- "$base" 2>/dev/null || true
    fi
    mktemp -d "$base/otast.XXXXXXXX" 2>/dev/null
}

otast_script_timeout() {
    local seconds
    seconds=$1
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout --signal=TERM --kill-after=10 "$seconds" "$@"
        return $?
    fi
    if command -v busybox >/dev/null 2>&1 && busybox timeout --help >/dev/null 2>&1; then
        busybox timeout -s TERM -k 10 "$seconds" "$@"
        return $?
    fi
    printf '%s\n' '[ERROR] No bounded timeout implementation is available.' >&2
    return 127
}

otast_script_summary() {
    local result
    if ((OTAST_SCRIPT_ERRORS > 0)); then
        result=FAILED
    elif ((OTAST_SCRIPT_WARNINGS > 0)); then
        result='COMPLETED WITH WARNINGS'
    else
        result=SUCCESS
    fi
    printf '\n==================================================\n'
    printf 'RESULT:      %s\n' "$result"
    printf 'WARNINGS:    %s\n' "$OTAST_SCRIPT_WARNINGS"
    printf 'ERRORS:      %s\n' "$OTAST_SCRIPT_ERRORS"
    printf '==================================================\n'
    ((OTAST_SCRIPT_ERRORS == 0))
}
