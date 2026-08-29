#!/system/bin/sh

MODDIR=${0%/*}
[ "$MODDIR" != "$0" ] || MODDIR=.
MODDIR=$(CDPATH='' cd "$MODDIR" 2>/dev/null && pwd -P) || exit 70
ENTRY=$MODDIR/runtime/entry.sh

choice=${OTAST_ACTION:-}
if [ -z "$choice" ] && [ -r /dev/tty ]; then
  printf '%s\n' 'OTAST action:'
  printf '%s\n' '  1) Report (read-only, default)'
  printf '%s\n' '  2) Preflight (read-only)'
  printf '%s\n' '  3) Verify (read-only)'
  printf '%s\n' '  4) Apply'
  printf '%s\n' '  5) Restore'
  printf 'Selection [1-5]: '
  if command -v timeout >/dev/null 2>&1; then
    choice=$(timeout 30 sh -c 'IFS= read -r x </dev/tty; printf "%s" "$x"' 2>/dev/null) || choice=1
  else
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
