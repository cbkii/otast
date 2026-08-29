#!/system/bin/sh

MODDIR=${0%/*}
[ "$MODDIR" != "$0" ] || MODDIR=.
MODDIR=$(CDPATH='' cd "$MODDIR" 2>/dev/null && pwd -P) || exit 70
ENTRY=$MODDIR/runtime/entry.sh

otast_key_from_events() {
  local events line
  events=$1

  while IFS= read -r line; do
    case $line in
      *KEY_VOLUMEUP*DOWN*)
        printf '%s\n' up
        return 0
        ;;
      *KEY_VOLUMEDOWN*DOWN*)
        printf '%s\n' down
        return 0
        ;;
    esac
  done <<EOF_EVENTS
$events
EOF_EVENTS

  return 1
}

otast_read_volume_key() {
  local events rc

  events=$(/system/bin/timeout 1 /system/bin/getevent -ql 2>/dev/null)
  rc=$?

  # Android timeout returns 124 on expiry. Some BusyBox timeout builds return
  # 143 after terminating the child. Either is expected for a one-second
  # sampling window; parse any events collected before that boundary.
  case $rc in
    0|124|143) ;;
    *) return 2 ;;
  esac

  otast_key_from_events "$events"
}

otast_option_label() {
  case $1 in
    1) printf '%s\n' 'Report (read-only)' ;;
    2) printf '%s\n' 'Preflight (read-only)' ;;
    3) printf '%s\n' 'Verify (read-only)' ;;
    4) printf '%s\n' 'Apply' ;;
    5) printf '%s\n' 'Restore' ;;
    *) return 1 ;;
  esac
}

otast_print_current() {
  local selection label
  selection=$1
  label=$(otast_option_label "$selection") || return 1
  printf 'Current: %s) %s\n' "$selection" "$label"
}

otast_select_action() {
  local selection windows key rc label
  selection=1
  windows=30

  printf '%s\n' 'OTAST action:'
  printf '%s\n' '  1) Report (read-only, safe default)'
  printf '%s\n' '  2) Preflight (read-only)'
  printf '%s\n' '  3) Verify (read-only)'
  printf '%s\n' '  4) Apply'
  printf '%s\n' '  5) Restore'
  printf '%s\n' 'Controls: Vol+ = next, Vol- = select'
  otast_print_current "$selection"

  while [ "$windows" -gt 0 ]; do
    key=$(otast_read_volume_key)
    rc=$?

    case $rc in
      0)
        case $key in
          up)
            selection=$((selection % 5 + 1))
            otast_print_current "$selection"
            ;;
          down)
            choice=$selection
            label=$(otast_option_label "$selection") || return 1
            printf 'Selected: %s) %s\n' "$selection" "$label"
            return 0
            ;;
        esac
        ;;
      1)
        :
        ;;
      *)
        printf '%s\n' 'WARNING: volume-key input failed; defaulting to read-only Report.' >&2
        choice=1
        return 0
        ;;
    esac

    windows=$((windows - 1))
  done

  printf '%s\n' 'No volume-key selection received within 30 seconds; defaulting to read-only Report.' >&2
  choice=1
  return 0
}

choice=${OTAST_ACTION:-}
if [ -z "$choice" ]; then
  if [ -x /system/bin/getevent ] && [ -x /system/bin/timeout ]; then
    otast_select_action
  else
    printf '%s\n' 'WARNING: getevent/timeout unavailable; defaulting to read-only Report.' >&2
    choice=1
  fi
fi

case ${choice:-1} in
  1|report|status) exec sh "$ENTRY" report ;;
  2|preflight) exec sh "$ENTRY" preflight ;;
  3|verify) exec sh "$ENTRY" verify ;;
  4|apply) exec sh "$ENTRY" apply ;;
  5|restore) exec sh "$ENTRY" restore ;;
  *) printf 'Invalid OTAST action: %s\n' "$choice" >&2; exit 64 ;;
esac
