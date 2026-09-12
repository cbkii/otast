#!/system/bin/sh

# Tricky Addon v4.4 compatibility. Under OTAST, TA UTL is a target-list/UI
# compatibility adapter: its property/VBMeta governor exits before the first
# write, and its independent WebUI boot-hash save path is neutralised.

OTAST_TA_GUARD_BEGIN='# --- otast target-only prop guard BEGIN ---'
OTAST_TA_GUARD_END='# --- otast target-only prop guard END ---'
OTAST_TA_BEGIN='# --- otast vbmeta ownership BEGIN ---'
OTAST_TA_END='# --- otast vbmeta ownership END ---'
OTAST_TA_WEBUI_MARKER='        # OTAST owns boot_hash and ro.boot.vbmeta.digest; TA UTL save is read-only.'

otast_transform_ta_prop() {
  local source output temp line skip guard_inserted vbmeta_inserted
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1

  if grep -Fxq "$OTAST_TA_GUARD_BEGIN" "$source" 2>/dev/null && \
     grep -Fxq "$OTAST_TA_GUARD_END" "$source" 2>/dev/null && \
     grep -Fxq "$OTAST_TA_BEGIN" "$source" 2>/dev/null && \
     grep -Fxq "$OTAST_TA_END" "$source" 2>/dev/null; then
    cat "$source" >"$output" || return 1
    chmod 0600 "$output" || return 1
    otast_shell_file_valid "$output"
    return $?
  fi

  temp=${output}.new.$$
  skip=0
  guard_inserted=0
  vbmeta_inserted=0
  : >"$temp" || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$guard_inserted" -eq 0 ]; then
      case "$line" in
        '#!'*)
          printf '%s\n' "$line" >>"$temp" || { rm -f "$temp"; return 1; }
          cat >>"$temp" <<EOF_GUARD
$OTAST_TA_GUARD_BEGIN
# OTAST owns global sensitive-property and VBMeta-digest capability boundaries.
# Presence of disable_prop_handler turns TA UTL into target-list/UI-only mode.
if [ -f "/data/adb/disable_prop_handler" ]; then
    exit 0
fi
$OTAST_TA_GUARD_END
EOF_GUARD
          guard_inserted=1
          continue
          ;;
      esac
    fi

    if [ "$skip" -eq 0 ] && [ "$line" = '# Reset vbmeta related prop' ]; then
      cat >>"$temp" <<EOF_OWNER
$OTAST_TA_BEGIN
# Defense in depth: even if the external guard is later removed, TA UTL's
# overlapping trailing VBMeta writer remains disabled by this reviewed adapter.
$OTAST_TA_END
EOF_OWNER
      skip=1
      vbmeta_inserted=1
      continue
    fi
    if [ "$skip" -eq 1 ]; then
      case "$line" in
        'empty_reset_prop "ro.boot.vbmeta.size" '*|'empty_reset_prop "ro.boot.vbmeta.size"'*) skip=0 ;;
      esac
      continue
    fi
    printf '%s\n' "$line" >>"$temp" || { rm -f "$temp"; return 1; }
  done <"$source"
  [ "$guard_inserted" -eq 1 ] && [ "$vbmeta_inserted" -eq 1 ] && [ "$skip" -eq 0 ] || {
    rm -f "$temp"
    return 1
  }
  mv -f "$temp" "$output" || return 1
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}

_otast_ta_webui_boot_hash_valid() {
  local file
  file=$1
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  grep -Fxq "$OTAST_TA_WEBUI_MARKER" "$file" 2>/dev/null || return 1
  grep -Fq 'a.disabled=!0;window.trimInput=' "$file" 2>/dev/null || return 1
  grep -Fq "sed '/[^#]/d; /^$/d' /data/adb/boot_hash" "$file" 2>/dev/null || return 1
  if grep -Fq 'resetprop -n ro.boot.vbmeta.digest' "$file" 2>/dev/null || \
     grep -Fq 'resetprop -c || true' "$file" 2>/dev/null || \
     grep -Fq 'rm -f /data/adb/boot_hash' "$file" 2>/dev/null || \
     grep -Fq '> /data/adb/boot_hash' "$file" 2>/dev/null || \
     grep -Fq 'chmod 644 /data/adb/boot_hash' "$file" 2>/dev/null; then
    return 1
  fi
  return 0
}

otast_transform_ta_webui_boot_hash() {
  local source output temp line skip inserted disabled
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1

  if grep -Fxq "$OTAST_TA_WEBUI_MARKER" "$source" 2>/dev/null; then
    _otast_ta_webui_boot_hash_valid "$source" || return 1
    cat "$source" >"$output" || return 1
    chmod 0600 "$output" || return 1
    return 0
  fi

  temp=${output}.new.$$
  skip=0
  inserted=0
  disabled=0
  : >"$temp" || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$disabled" -eq 0 ]; then
      case "$line" in
        *';window.trimInput='*)
          printf '%s\n' "$line" | sed 's/;window\.trimInput=/;a.disabled=!0;window.trimInput=/' >>"$temp" || { rm -f "$temp"; return 1; }
          disabled=1
          continue
          ;;
      esac
    fi

    if [ "$skip" -eq 0 ] && [ "$line" = '        resetprop -n ro.boot.vbmeta.digest "${a}"' ]; then
      printf '%s\n' "$OTAST_TA_WEBUI_MARKER" >>"$temp" || { rm -f "$temp"; return 1; }
      printf '%s\n' '        true' >>"$temp" || { rm -f "$temp"; return 1; }
      skip=1
      inserted=1
      continue
    fi
    if [ "$skip" -eq 1 ]; then
      if [ "$line" = '        resetprop -c || true' ]; then
        skip=0
      fi
      continue
    fi
    printf '%s\n' "$line" >>"$temp" || { rm -f "$temp"; return 1; }
  done <"$source"

  [ "$inserted" -eq 1 ] && [ "$skip" -eq 0 ] && [ "$disabled" -eq 1 ] || { rm -f "$temp"; return 1; }
  _otast_ta_webui_boot_hash_valid "$temp" || { rm -f "$temp"; return 1; }

  mv -f "$temp" "$output" || return 1
  chmod 0600 "$output" || return 1
  return 0
}
