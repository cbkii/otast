#!/system/bin/sh

MODDIR=${0%/*}
[ "$MODDIR" != "$0" ] || MODDIR=.
MODDIR=$(CDPATH='' cd "$MODDIR" 2>/dev/null && pwd -P) || exit 1
ADB_ROOT=${ADB_ROOT:-/data/adb}
OTAST_STATE_ROOT=${OTAST_STATE_ROOT:-$ADB_ROOT/otast}
if ! ADB_ROOT="$ADB_ROOT" OTAST_STATE_ROOT="$OTAST_STATE_ROOT" sh "$MODDIR/runtime/entry.sh" restore; then
  mkdir -p "$OTAST_STATE_ROOT" 2>/dev/null || :
  printf '%s\n' 'Restore failed during uninstall. Review managed target drift before deleting the OTAST state root.' > "$OTAST_STATE_ROOT/UNINSTALL_RESTORE_FAILED" 2>/dev/null || :
  exit 1
fi
rm -rf "$OTAST_STATE_ROOT" 2>/dev/null || :
exit 0
