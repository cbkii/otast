#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'ERROR: Cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

case "$REPO_ROOT" in
    /storage/*|/sdcard/*|/mnt/media_rw/*)
        otast_script_fatal "Repository must be in Termux private storage, not Android shared storage: $REPO_ROOT"
        ;;
esac

required=(bash busybox git python3 sha256sum unzip zip)
for command_name in "${required[@]}"; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        otast_script_error "Missing required command: $command_name"
    fi
done

if command -v shellcheck >/dev/null 2>&1; then
    shellcheck_version=$(shellcheck --version 2>/dev/null | awk -F': ' '/^version:/ {print $2; exit}') || shellcheck_version=unknown
    otast_script_info "ShellCheck: $shellcheck_version"
else
    otast_script_warn 'ShellCheck is not installed; run scripts/bootstrap-termux.sh'
fi

probe=$(otast_script_private_tmp) || otast_script_fatal 'Cannot create a private temporary directory'
cleanup() {
    [[ -n ${probe:-} ]] && rm -rf -- "$probe"
}
trap cleanup EXIT INT TERM
printf '#!/usr/bin/env bash\nexit 0\n' >"$probe/exec-probe" || otast_script_fatal 'Cannot write filesystem probe'
chmod 0755 "$probe/exec-probe" || otast_script_fatal 'Filesystem does not preserve executable mode'
if ! "$probe/exec-probe"; then
    otast_script_error 'Filesystem does not permit execution'
fi
if ! ln -s exec-probe "$probe/link-probe" 2>/dev/null; then
    otast_script_error 'Filesystem does not support symbolic links'
else
    link_target=$(readlink "$probe/link-probe" 2>/dev/null) || link_target=
    if [[ $link_target != exec-probe ]]; then
        otast_script_error 'Filesystem changed symbolic-link target text'
    fi
fi

if command -v busybox >/dev/null 2>&1; then
    if busybox sh -c 'f() { local x; x=ok; [ "$x" = ok ]; }; f'; then
        otast_script_info "BusyBox ash local scope: supported"
    else
        otast_script_error 'BusyBox ash does not support required local function scope'
    fi
fi

python3 --version 2>&1 || otast_script_error 'Python version query failed'
git --version 2>&1 || otast_script_error 'Git version query failed'
otast_script_summary
