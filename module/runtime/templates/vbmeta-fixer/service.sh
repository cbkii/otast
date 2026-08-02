#!/system/bin/sh

# OTAST owns the runtime vbmeta property contract. The companion app is retained
# as a TrickyStore target, but its broadcast writer is not invoked.

ADB_ROOT=${ADB_ROOT:-/data/adb}
AUTHORITY=$ADB_ROOT/ota.prop
PACKAGE=com.reveny.vbmetafix.service
TARGET_DIR=$ADB_ROOT/tricky_store
TARGET=$TARGET_DIR/target.txt

read_authority() {
  local key
  key=$1
  [ -f "$AUTHORITY" ] && [ ! -L "$AUTHORITY" ] || return 1
  awk -F= -v wanted="$key" '
    $1 == wanted { sub(/^[^=]*=/, ""); print; found=1; exit }
    END { if (!found) exit 1 }
  ' "$AUTHORITY"
}

DIGEST=$(read_authority ro.boot.vbmeta.digest) || exit 1
SIZE=$(read_authority ro.boot.vbmeta.size) || exit 1
VBMETA_AVB=$(read_authority ro.boot.vbmeta.avb_version) || exit 1
BOOT_AVB=$(read_authority ro.boot.avb_version) || exit 1
case "$DIGEST" in ''|*[!0-9a-f]*) exit 1 ;; esac
[ "${#DIGEST}" -eq 64 ] || exit 1
case "$SIZE" in ''|*[!0-9]*) exit 1 ;; esac

if command -v resetprop >/dev/null 2>&1; then
  resetprop -n ro.boot.vbmeta.digest "$DIGEST" || exit 1
  resetprop -n ro.boot.vbmeta.size "$SIZE" || exit 1
  resetprop -n ro.boot.vbmeta.avb_version "$VBMETA_AVB" || exit 1
  resetprop -n ro.boot.avb_version "$BOOT_AVB" || exit 1
fi

if [ -d "$TARGET_DIR" ] && [ ! -L "$TARGET_DIR" ]; then
  if [ -e "$TARGET" ] && { [ ! -f "$TARGET" ] || [ -L "$TARGET" ]; }; then
    printf 'STOP: unsafe TrickyStore target path: %s\n' "$TARGET" >&2
    exit 1
  fi
  if [ ! -e "$TARGET" ] || ! grep -Fxq "$PACKAGE" "$TARGET" 2>/dev/null; then
    TMP=$TARGET_DIR/.target.txt.otast.$$
    if [ -e "$TARGET" ]; then cat "$TARGET" >"$TMP" || exit 1; else : >"$TMP" || exit 1; fi
    printf '%s\n' "$PACKAGE" >>"$TMP" || { rm -f "$TMP"; exit 1; }
    chmod 0644 "$TMP" || { rm -f "$TMP"; exit 1; }
    mv -f "$TMP" "$TARGET" || { rm -f "$TMP"; exit 1; }
  fi
fi
exit 0
