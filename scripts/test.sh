#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'ERROR: Cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

mode=standard
case ${1:-} in
    '') ;;
    --quick) mode=quick ;;
    --standard) mode=standard ;;
    --full) mode=full ;;
    -h|--help)
        printf 'Usage: %s [--quick|--standard|--full]\n' "$0"
        exit 0
        ;;
    *) otast_script_fatal "Unknown test mode: $1" ;;
esac

run_required() {
    local label
    label=$1
    shift
    otast_script_info "$label"
    if ! "$@"; then
        otast_script_error "$label failed"
        return 1
    fi
    return 0
}

if ! run_required 'Environment preflight' bash "$SCRIPT_DIR/check-dev-environment.sh"; then
    otast_script_summary
    exit 1
fi

if [[ $mode != quick ]]; then
    if ! command -v shellcheck >/dev/null 2>&1; then
        otast_script_error 'ShellCheck is required for standard/full tests; run scripts/bootstrap-termux.sh'
    elif ! shellcheck --shell=busybox /dev/null >/dev/null 2>&1; then
        shellcheck_version=$(shellcheck --version 2>/dev/null | awk -F': ' '/^version:/ {print $2; exit}') || shellcheck_version=unknown
        otast_script_error "ShellCheck ${shellcheck_version:-unknown} does not support --shell=busybox; install ShellCheck v0.11.0 or newer"
    else
        mapfile -d '' host_scripts < <(find "$REPO_ROOT/scripts" -type f -name '*.sh' -print0 | sort -z)
        if ((${#host_scripts[@]} > 0)); then
            run_required 'ShellCheck host Bash sources' shellcheck --shell=bash --severity=warning "${host_scripts[@]}" || true
        fi
        mapfile -d '' module_scripts < <(find "$REPO_ROOT/module" -type f -name '*.sh' -print0 | sort -z)
        if ((${#module_scripts[@]} > 0)); then
            run_required 'ShellCheck Magisk BusyBox sources' shellcheck --shell=busybox --severity=error "${module_scripts[@]}" || true
        fi
    fi
fi

if ((OTAST_SCRIPT_ERRORS == 0)); then
    verify_args=(--repo-root "$REPO_ROOT" verify)
    [[ $mode == quick ]] || verify_args+=(--full)
    run_required "Repository verification ($mode)" otast_python -m tools.otastctl "${verify_args[@]}" || true
fi

if [[ $mode == full && $OTAST_SCRIPT_ERRORS -eq 0 ]]; then
    temp_root=$(otast_script_private_tmp) || otast_script_fatal 'Cannot create clean-room test directory'
    cleanup_clean_room() {
        [[ -n ${temp_root:-} ]] && rm -rf -- "$temp_root"
    }
    trap cleanup_clean_room EXIT INT TERM
    source_zip=$temp_root/otast-public-ready.zip

    # Run clean-room stages sequentially and break out upon failure
    while true; do
        run_required 'Build clean public source archive' otast_python -m tools.otastctl --repo-root "$REPO_ROOT" package-source --output "$source_zip" || break
        run_required 'Validate clean public source archive' otast_python -m tools.otastctl --repo-root "$REPO_ROOT" validate-source "$source_zip" || break

        mkdir -p -- "$temp_root/extracted" || otast_script_fatal 'Cannot create clean-room extraction directory'
        run_required 'Extract clean-room archive' unzip -q "$source_zip" -d "$temp_root/extracted" || break

        extracted=$temp_root/extracted/otast
        while IFS= read -r -d '' path; do
            chmod 0600 -- "$path" || otast_script_fatal "Cannot flatten clean-room source mode: $path"
        done < <(find "$extracted" -type f -print0)

        run_required 'Restore clean-room source modes after flattened extraction' bash "$extracted/scripts/restore-source-modes.sh" || break
        run_required 'Run extracted repository from unrelated directory' bash -c 'cd / && bash "$1/scripts/test.sh" --quick' _ "$extracted" || break

        run_required 'Initialise clean local Git repository' git -C "$extracted" init -q -b main || break
        if git -C "$extracted" rev-parse --verify HEAD >/dev/null 2>&1; then
            otast_script_error 'Clean public archive unexpectedly contains Git history'
        fi
        clean_remotes=$(git -C "$extracted" remote 2>/dev/null) || clean_remotes=
        if [[ -n $clean_remotes ]]; then
            otast_script_error 'Clean public archive unexpectedly contains a Git remote'
        fi
        if ! git -C "$extracted" add --all --dry-run >/dev/null 2>&1; then
            otast_script_error 'Clean public archive cannot be staged in Git'
        fi
        break
    done
fi

otast_script_summary
