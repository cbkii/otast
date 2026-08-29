#!/system/bin/sh

LC_ALL=C
export LC_ALL

MODDIR=${0%/*}
[ "$MODDIR" != "$0" ] || MODDIR=.
MODDIR=$(CDPATH='' cd "$MODDIR" 2>/dev/null && pwd -P) || {
  printf '%s\n' 'STOP: cannot resolve OTAST runtime directory' >&2
  exit 70
}
ADB_ROOT=${ADB_ROOT:-/data/adb}
case "$ADB_ROOT" in /*) ;; *) printf '%s\n' 'STOP: ADB_ROOT must be absolute' >&2; exit 70 ;; esac
case "$ADB_ROOT" in *[!A-Za-z0-9._/-]*) printf '%s\n' 'STOP: ADB_ROOT contains unsafe characters' >&2; exit 70 ;; esac
OTAST_STATE_ROOT=${OTAST_STATE_ROOT:-$ADB_ROOT/otast}
case "$OTAST_STATE_ROOT" in "$ADB_ROOT"/*) ;; *) printf '%s\n' 'STOP: OTAST_STATE_ROOT must be below ADB_ROOT' >&2; exit 70 ;; esac
case "$OTAST_STATE_ROOT" in *[!A-Za-z0-9._/-]*) printf '%s\n' 'STOP: OTAST_STATE_ROOT contains unsafe characters' >&2; exit 70 ;; esac
OTAST_TMP_ROOT=$OTAST_STATE_ROOT/tmp
OTAST_AUTHORITY=${OTAST_AUTHORITY:-$ADB_ROOT/ota.prop}
OTAST_LIVE_PROP_FILE=${OTAST_LIVE_PROP_FILE:-}
OTAST_BOOTCONFIG_FILE=${OTAST_BOOTCONFIG_FILE:-/proc/bootconfig}
case "$OTAST_BOOTCONFIG_FILE" in
  /proc/bootconfig) ;;
  "$ADB_ROOT"/*)
    [ "$ADB_ROOT" != /data/adb ] && [ -f "$ADB_ROOT/.otast-fake-root" ] && [ ! -L "$ADB_ROOT/.otast-fake-root" ] || {
      printf '%s\n' 'STOP: custom bootconfig is allowed only below a guarded fake ADB root' >&2
      exit 70
    }
    ;;
  *)
    printf '%s\n' 'STOP: OTAST_BOOTCONFIG_FILE is outside the guarded fake ADB root' >&2
    exit 70
    ;;
esac

. "$MODDIR/common.sh" || exit 70
. "$MODDIR/authority.sh" || exit 70
. "$MODDIR/transaction.sh" || exit 70
. "$MODDIR/pif.sh" || exit 70
. "$MODDIR/ta.sh" || exit 70
. "$MODDIR/profiles.sh" || exit 70
. "$MODDIR/report.sh" || exit 70
[ ! -f "$MODDIR/../otast.conf" ] || . "$MODDIR/../otast.conf" || exit 70

_otast_cleanup() {
  otast_release_lock
  otast_plan_cleanup
}
trap _otast_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

_otast_load() {
  otast_ensure_dir "$OTAST_STATE_ROOT" || return 1
  otast_ensure_dir "$OTAST_TMP_ROOT" || return 1
  otast_validate_authority_file || return 1
}

_otast_validate_source() {
  otast_compare_live_identity || return 1
  otast_compare_bootloader_vbmeta || return 1
}

_otast_preflight() {
  _otast_load || return 1
  otast_require_no_legacy_governors || return 1
  _otast_validate_source || return 1
  otast_plan_all || return 1
  printf 'READY\toperations=%s\tauthority=%s\n' "$OTAST_PLAN_COUNT" "$OTAST_AUTHORITY_SHA256"
}

_otast_apply() {
  local result plan_count
  _otast_load || return 1
  otast_require_no_legacy_governors || return 1
  _otast_validate_source || return 1
  otast_acquire_lock || return 1
  result=0
  otast_recover_transactions || result=1
  [ "$result" -ne 0 ] || otast_plan_all || result=1
  plan_count=${OTAST_PLAN_COUNT:-0}
  [ "$result" -ne 0 ] || otast_apply_plan || result=1
  otast_release_lock || result=1
  [ "$result" -eq 0 ] || return 1
  otast_verify_managed || return 1
  if [ "$plan_count" -gt 0 ]; then
    printf 'REBOOT_REQUIRED\tmanaged files changed; reboot before Verify\n'
  else
    printf 'NO_CHANGES_REQUIRED\tmanaged files are already current\n'
  fi
}

_otast_verify() {
  _otast_load || return 1
  otast_require_no_legacy_governors || return 1
  _otast_validate_source || return 1
  otast_compare_live_managed_vbmeta || return 1
  otast_verify_managed
}

_otast_restore() {
  local result
  _otast_load || return 1
  otast_acquire_lock || return 1
  result=0
  otast_recover_transactions || result=1
  [ "$result" -ne 0 ] || otast_restore_all || result=1
  otast_release_lock || result=1
  [ "$result" -eq 0 ]
}

_otast_report() {
  _otast_load || return 1
  otast_require_no_legacy_governors || return 1
  otast_report
}

_otast_boot_recover() {
  otast_ensure_dir "$OTAST_STATE_ROOT" || return 1
  otast_recover_transactions
}

case ${1:-report} in
  preflight) _otast_preflight ;;
  apply) _otast_apply ;;
  verify) _otast_verify ;;
  restore) _otast_restore ;;
  report|status) _otast_report ;;
  boot-recover) _otast_boot_recover ;;
  *)
    printf 'Usage: %s {preflight|apply|verify|restore|report|boot-recover}\n' "$0" >&2
    exit 64
    ;;
esac
