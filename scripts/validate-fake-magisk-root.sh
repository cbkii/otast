#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1
root_input=${1:-}
action=${2:-report}
[[ -n $root_input ]] || otast_script_fatal "Usage: $0 FAKE_ROOT [report|preflight|apply|reboot|verify|restore|boot-recover]"
root=$(cd -- "$root_input" >/dev/null 2>&1 && pwd -P) || otast_script_fatal "Fake root does not exist: $root_input"
case $root in "${HOME:?}/.cache/otast/fake-roots"/*) ;; *) otast_script_fatal 'Fake root is outside $HOME/.cache/otast/fake-roots' ;; esac
case $action in report|status|preflight|apply|reboot|verify|restore|boot-recover) ;; *) otast_script_fatal "Unsafe action: $action" ;; esac
adb_root=$root/data/adb
entry=$adb_root/modules/otast/runtime/entry.sh
live=$root/live.prop
[[ -f $live ]] || live=$adb_root/live.prop
[[ -f $entry && ! -L $entry ]] || otast_script_fatal 'Candidate runtime entrypoint is missing or unsafe'
[[ -f $adb_root/ota.prop && ! -L $adb_root/ota.prop ]] || otast_script_fatal 'Fake authority is missing or unsafe'
[[ -f $live && ! -L $live ]] || otast_script_fatal 'Captured live properties are missing or unsafe'

if [[ $action == reboot ]]; then
    service=$adb_root/modules/vbmeta-fixer/service.sh
    [[ -f $service && ! -L $service ]] || otast_script_fatal 'Managed VBMeta Fixer service is missing or unsafe'
    shim_dir=$root/.otast-reboot-shim
    rm -rf -- "$shim_dir" || otast_script_fatal 'Cannot reset the private reboot shim'
    mkdir -p -- "$shim_dir" || otast_script_fatal 'Cannot create the private reboot shim'
    chmod 0700 "$shim_dir" || otast_script_fatal 'Cannot secure the private reboot shim'
    bash_path=$(command -v bash) || otast_script_fatal 'Bash is required for fake-root reboot simulation'
    cat >"$shim_dir/resetprop" <<EOF_SHIM
#!$bash_path
live=\${OTAST_FAKE_LIVE_PROP:?}
[[ \${1:-} == -n && \$# -eq 3 ]] || exit 64
key=\$2
value=\$3
[[ \$key =~ ^[A-Za-z0-9._-]+$ ]] || exit 65
[[ \$value != *\$'\n'* && \$value != *\$'\r'* ]] || exit 66
tmp=\${live}.resetprop.\$\$
found=0
: >"\$tmp" || exit 67
while IFS= read -r line || [[ -n \$line ]]; do
    case \$line in
        "\$key="*)
            if [[ \$found -eq 0 ]]; then
                printf '%s=%s\n' "\$key" "\$value" >>"\$tmp" || exit 68
                found=1
            fi
            ;;
        *) printf '%s\n' "\$line" >>"\$tmp" || exit 68 ;;
    esac
done <"\$live"
if [[ \$found -eq 0 ]]; then
    printf '%s=%s\n' "\$key" "\$value" >>"\$tmp" || exit 68
fi
chmod 0600 "\$tmp" || exit 69
mv -f -- "\$tmp" "\$live" || exit 70
EOF_SHIM
    chmod 0700 "$shim_dir/resetprop" || otast_script_fatal 'Cannot make resetprop shim executable'
    if ! PATH="$shim_dir:$PATH" \
        OTAST_FAKE_LIVE_PROP="$live" \
        ADB_ROOT="$adb_root" \
        busybox sh "$service"; then
        otast_script_error 'Fake-root reboot simulation failed'
    fi
    rm -rf -- "$shim_dir" || otast_script_warn 'Could not remove the private reboot shim'
    otast_script_summary
    exit $?
fi
if ! ADB_ROOT="$adb_root" \
    OTAST_AUTHORITY="$adb_root/ota.prop" \
    OTAST_LIVE_PROP_FILE="$live" \
    OTAST_TEST_MODE=0 \
    busybox sh "$entry" "$action"; then
    otast_script_error "Fake-root action failed: $action"
fi
otast_script_summary
