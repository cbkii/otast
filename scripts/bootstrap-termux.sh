#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'ERROR: Cannot resolve script directory.\n' >&2
    exit 1
}
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

if ! bash "$SCRIPT_DIR/restore-source-modes.sh"; then
    otast_script_fatal 'Cannot restore repository source modes'
fi

check_only=0
for argument in "$@"; do
    case "$argument" in
        --check-only) check_only=1 ;;
        -h|--help)
            printf 'Usage: %s [--check-only]\n' "$0"
            exit 0
            ;;
        *) otast_script_fatal "Unknown argument: $argument" ;;
    esac
done

packages=(bash busybox coreutils findutils git python shellcheck unzip zip jq curl file make tar)
missing=()
commands=(bash busybox sha256sum find git python3 shellcheck unzip zip jq curl file make tar)
for index in "${!commands[@]}"; do
    if ! command -v "${commands[$index]}" >/dev/null 2>&1; then
        missing+=("${packages[$index]}")
    fi
done

if ((${#missing[@]} == 0)); then
    otast_script_info 'All Termux dependencies are already installed'
elif ((check_only == 1)); then
    otast_script_error "Missing Termux packages: ${missing[*]}"
else
    command -v pkg >/dev/null 2>&1 || otast_script_fatal 'pkg is unavailable; install dependencies manually'
    otast_script_info "Installing missing packages: ${missing[*]}"
    if ! otast_script_timeout 900 pkg install -y "${missing[@]}"; then
        otast_script_error 'Termux package installation failed or timed out'
    fi
fi

if ((OTAST_SCRIPT_ERRORS == 0)); then
    if ! bash "$SCRIPT_DIR/check-dev-environment.sh"; then
        otast_script_error 'Development environment check failed'
    fi
fi
otast_script_summary
