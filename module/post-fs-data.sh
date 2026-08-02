#!/system/bin/sh

MODDIR=${0%/*}
[ "$MODDIR" != "$0" ] || MODDIR=.
MODDIR=$(CDPATH='' cd "$MODDIR" 2>/dev/null && pwd -P) || exit 0
if command -v timeout >/dev/null 2>&1; then
  timeout -s TERM -k 2 10 sh "$MODDIR/runtime/entry.sh" boot-recover >/dev/null 2>&1 || :
elif command -v toybox >/dev/null 2>&1; then
  toybox timeout -s TERM -k 2 10 sh "$MODDIR/runtime/entry.sh" boot-recover >/dev/null 2>&1 || :
elif command -v busybox >/dev/null 2>&1; then
  busybox timeout -s TERM -k 2 10 sh "$MODDIR/runtime/entry.sh" boot-recover >/dev/null 2>&1 || :
fi
exit 0
