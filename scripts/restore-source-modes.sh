#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'ERROR: Cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || {
    printf 'ERROR: Cannot resolve repository root.\n' >&2
    exit 1
}
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

case "$REPO_ROOT" in
    /storage/*|/sdcard/*|/mnt/media_rw/*)
        otast_script_fatal "Repository must be in Termux private storage before restoring modes: $REPO_ROOT"
        ;;
esac

entrypoints=(
    module/action.sh
    module/customize.sh
    module/post-fs-data.sh
    module/service.sh
    module/uninstall.sh
    module/runtime/entry.sh
)

python_entrypoints=(
    scripts/otast-maintenance.py
    scripts/otast_safety_guard.py
    scripts/upstream-target-package.py
)

mapfile -d '' host_scripts < <(find "$REPO_ROOT/scripts" -type f -name '*.sh' -print0 | sort -z)
for path in "${host_scripts[@]}"; do
    if ! chmod 0755 -- "$path"; then
        otast_script_error "Cannot set executable mode: ${path#"$REPO_ROOT"/}"
    fi
done

for relative in "${python_entrypoints[@]}"; do
    path=$REPO_ROOT/$relative
    if [[ ! -f $path || -L $path ]]; then
        otast_script_error "Required Python entrypoint is missing or unsafe: $relative"
    elif ! chmod 0755 -- "$path"; then
        otast_script_error "Cannot set executable mode: $relative"
    fi
done

for relative in "${entrypoints[@]}"; do
    path=$REPO_ROOT/$relative
    if [[ ! -f $path || -L $path ]]; then
        otast_script_error "Required entrypoint is missing or unsafe: $relative"
    elif ! chmod 0755 -- "$path"; then
        otast_script_error "Cannot set executable mode: $relative"
    fi
done

while IFS= read -r -d '' path; do
    relative=${path#"$REPO_ROOT"/}
    case $relative in
        scripts/*.sh|scripts/otast-maintenance.py|scripts/otast_safety_guard.py|scripts/upstream-target-package.py|\
        module/action.sh|module/customize.sh|module/post-fs-data.sh|module/service.sh|module/uninstall.sh|module/runtime/entry.sh)
            continue
            ;;
    esac
    if ! chmod 0644 -- "$path"; then
        otast_script_error "Cannot set regular-file mode: $relative"
    fi
done < <(find "$REPO_ROOT" -type f \
    ! -path "$REPO_ROOT/.git/*" \
    ! -path "$REPO_ROOT/dist/*" \
    ! -path "$REPO_ROOT/reports/*" \
    -print0)

if ((OTAST_SCRIPT_ERRORS == 0)); then
    otast_script_info 'Repository source modes restored by file role'
fi
otast_script_summary
