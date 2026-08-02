#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'ERROR: Cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

label=
output_root=${HOME:?}/.local/share/otast/device-fixtures
while (($#)); do
    case $1 in
        --label)
            (($# >= 2)) || otast_script_fatal '--label requires a value'
            label=$2
            shift 2
            ;;
        --output-root)
            (($# >= 2)) || otast_script_fatal '--output-root requires a value'
            output_root=$2
            shift 2
            ;;
        -h|--help)
            printf 'Usage: %s [--label NAME] [--output-root PATH]\n' "$0"
            exit 0
            ;;
        *) otast_script_fatal "Unknown argument: $1" ;;
    esac
done

if [[ -z $label ]]; then
    label="tegu-$(date -u +%Y%m%dT%H%M%SZ)"
fi
case $label in
    ''|*[!A-Za-z0-9._-]*) otast_script_fatal "Unsafe fixture label: $label" ;;
esac
case $output_root in
    /storage/*|/sdcard/*|/mnt/media_rw/*) otast_script_fatal 'Private fixtures must not be stored in Android shared storage' ;;
esac

command -v su >/dev/null 2>&1 || otast_script_fatal 'su is unavailable'
if ! otast_script_timeout 20 su -c 'id -u' 2>/dev/null | grep -qx 0; then
    otast_script_fatal 'Root access was not granted or did not return UID 0'
fi

product=$(otast_script_timeout 20 su -c 'getprop ro.product.device' 2>/dev/null) || product=
sdk=$(otast_script_timeout 20 su -c 'getprop ro.build.version.sdk' 2>/dev/null) || sdk=
[[ $product == tegu ]] || otast_script_fatal "STOP: Expected tegu, got ${product:-unknown}"
[[ $sdk == 36 ]] || otast_script_fatal "STOP: Expected SDK 36, got ${sdk:-unknown}"

legacy_check_script=$(cat <<'ROOTSCRIPT'
legacy_otasst=otasst
legacy_ota_sot=ota-sot
legacy_aaa=aaa_ota_sot
found=0
for path in \
  "/data/adb/modules/$legacy_otasst" \
  "/data/adb/modules_update/$legacy_otasst" \
  "/data/adb/modules/$legacy_ota_sot" \
  "/data/adb/modules_update/$legacy_ota_sot" \
  "/data/adb/modules/$legacy_aaa" \
  "/data/adb/modules_update/$legacy_aaa" \
  "/data/adb/$legacy_otasst" \
  /data/adb/aaa-ota-sot-BAKs \
  "/data/adb/post-fs-data.d/000-$legacy_otasst.sh" \
  "/data/adb/post-fs-data.d/000-$legacy_aaa.sh"; do
  if [ -e "$path" ] || [ -L "$path" ]; then
    printf '%s\n' "$path"
    found=1
  fi
done
[ "$found" -eq 0 ]
ROOTSCRIPT
)
legacy_output=$(otast_script_timeout 30 su -c "$legacy_check_script" 2>/dev/null)
legacy_rc=$?
if [[ $legacy_rc -ne 0 ]]; then
    printf '%s\n' "$legacy_output" >&2
    otast_script_fatal 'STOP: legacy ota-sot/otasst governor traces remain; run the standalone cleanup and reboot before capture'
fi

final=$output_root/$label
[[ ! -e $final && ! -L $final ]] || otast_script_fatal "Fixture already exists: $final"
mkdir -p -- "$output_root" || otast_script_fatal "Cannot create fixture root: $output_root"
chmod 0700 -- "$output_root" 2>/dev/null || true

temp=$(otast_script_private_tmp) || otast_script_fatal 'Cannot create private capture workspace'
cleanup() {
    [[ -n ${temp:-} ]] && rm -rf -- "$temp"
}
trap cleanup EXIT INT TERM

cat >"$temp/allowlist.txt" <<'PATHS'
data/adb/ota.prop
data/adb/boot_hash
data/adb/disable_prop_handler
data/adb/tricky_store/security_patch.txt
data/adb/modules/playintegrityfix
data/adb/modules/tricky_store
data/adb/modules/Yurikey
data/adb/modules/TA_utl
data/adb/modules/.TA_utl
data/adb/modules/vbmeta-fixer
data/adb/modules_update/playintegrityfix
data/adb/modules_update/tricky_store
data/adb/modules_update/Yurikey
data/adb/modules_update/TA_utl
data/adb/modules_update/.TA_utl
data/adb/modules_update/vbmeta-fixer
PATHS

root_tar_script=$(cat <<'ROOTSCRIPT'
cd / || exit 1
bb=$(command -v busybox 2>/dev/null)
[ -n "$bb" ] || bb=/data/adb/magisk/busybox
[ -x "$bb" ] || exit 2
list=$(mktemp /data/local/tmp/otast-capture-list.XXXXXX) || exit 3
trap 'rm -f "$list"' EXIT INT TERM
while IFS= read -r path; do
    case "$path" in data/adb/*) ;; *) exit 4 ;; esac
    if [ -e "/$path" ] || [ -L "/$path" ]; then
        printf '%s\n' "$path" >>"$list" || exit 5
    fi
done
[ -s "$list" ] || exit 6
"$bb" tar -cf - -T "$list"
ROOTSCRIPT
)
otast_script_info 'Capturing the explicit OTAST target allow-list without following symlinks'
if ! otast_script_timeout 180 su -c "$root_tar_script" <"$temp/allowlist.txt" >"$temp/capture.tar"; then
    otast_script_fatal 'Root capture failed or timed out'
fi
[[ -s $temp/capture.tar ]] || otast_script_fatal 'Root capture produced an empty archive'

live_script=$(cat <<'ROOTSCRIPT'
for key in \
  ro.product.device \
  ro.build.id \
  ro.build.version.sdk \
  ro.build.version.security_patch \
  ro.vendor.build.security_patch \
  ro.build.fingerprint \
  ro.boot.vbmeta.digest \
  ro.boot.vbmeta.size \
  ro.boot.vbmeta.avb_version \
  ro.boot.avb_version; do
    value=$(getprop "$key" 2>/dev/null)
    printf '%s=%s\n' "$key" "$value"
done
ROOTSCRIPT
)
if ! otast_script_timeout 30 su -c "$live_script" >"$temp/live.prop"; then
    otast_script_fatal 'Live property capture failed'
fi

metadata_script=$(cat <<'ROOTSCRIPT'
while IFS= read -r path; do
    case "$path" in data/adb/*) ;; *) exit 4 ;; esac
    full=/$path
    if [ -e "$full" ] || [ -L "$full" ]; then
        if command -v stat >/dev/null 2>&1; then
            stat -c '%n\t%F\t%a\t%u\t%g\t%s' "$full" 2>/dev/null || :
        fi
        ls -Zd "$full" 2>/dev/null | sed 's/^/selinux\t/' || :
    fi
done
ROOTSCRIPT
)
otast_script_timeout 60 su -c "$metadata_script" <"$temp/allowlist.txt" >"$temp/metadata.tsv" || otast_script_warn 'Some top-level metadata could not be recorded'

if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" capture-extract "$temp/capture.tar" "$temp/raw"; then
    otast_script_fatal 'Safe capture extraction failed'
fi
cp -- "$temp/live.prop" "$temp/raw/live.prop" || otast_script_fatal 'Cannot add live property evidence'
cp -- "$temp/metadata.tsv" "$temp/raw/metadata.tsv" || otast_script_fatal 'Cannot add metadata evidence'
if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" fixture-sanitize "$temp/raw" "$temp/sanitized" >"$temp/sanitize-report.json"; then
    otast_script_fatal 'Fixture sanitization failed'
fi
[[ -f $temp/sanitized/data/adb/ota.prop ]] || otast_script_fatal 'Captured fixture does not contain data/adb/ota.prop'
printf '1\n' >"$temp/sanitized/data/adb/.otast-fake-root" || otast_script_fatal 'Cannot write fake-root marker'
chmod 0600 "$temp/sanitized/data/adb/.otast-fake-root" || otast_script_fatal 'Cannot secure fake-root marker'
mv -- "$temp/sanitized" "$final" || otast_script_fatal 'Cannot publish sanitized fixture atomically'
otast_script_info "Private sanitized fixture: $final"
otast_script_info 'No live /data/adb content was modified'
otast_script_summary
