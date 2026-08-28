#!/system/bin/sh

ADB_ROOT=${ADB_ROOT:-/data/adb}
OTAST_ENTRY=''
for OTAST_DIR in "$ADB_ROOT/modules_update/otast" "$ADB_ROOT/modules/otast"; do
  [ -d "$OTAST_DIR" ] && [ ! -L "$OTAST_DIR" ] || continue
  [ ! -e "$OTAST_DIR/remove" ] || continue
  [ ! -e "$OTAST_DIR/disable" ] || continue
  [ -x "$OTAST_DIR/runtime/entry.sh" ] || continue
  OTAST_ENTRY=$OTAST_DIR/runtime/entry.sh
  break
done
if [ -z "$OTAST_ENTRY" ]; then
  printf '%s\n' 'OTAST: Yurikey action is read-only and OTAST is unavailable.' >&2
  exit 1
fi
printf '%s\n' 'OTAST: Yurikey action defaults to read-only Report.'
exec sh "$OTAST_ENTRY" report
