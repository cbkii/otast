#!/system/bin/sh

# Compatibility-first Play Integrity Fix transformations.
# Only the reviewed identity writers are changed. Upstream action, post-fs-data,
# service, WebUI and update machinery remain byte-for-byte upstream-owned.

OTAST_PIF_OVERRIDE_BEGIN='# --- otast pif authority BEGIN ---'
OTAST_PIF_OVERRIDE_END='# --- otast pif authority END ---'
OTAST_PIF_FINAL_BEGIN='# --- otast pif final identity BEGIN ---'
OTAST_PIF_FINAL_END='# --- otast pif final identity END ---'
OTAST_PIF_OUTPUT_BEGIN='# --- otast pif output identity BEGIN ---'
OTAST_PIF_OUTPUT_END='# --- otast pif output identity END ---'
OTAST_PIF_REFRESH_BEGIN='# --- otast pif refresh reconciliation BEGIN ---'
OTAST_PIF_REFRESH_END='# --- otast pif refresh reconciliation END ---'

otast_shell_file_valid() {
  local path
  path=$1
  [ -s "$path" ] && [ ! -L "$path" ] || return 1
  if od -An -v -tx1 "$path" 2>/dev/null | grep -Eq '(^|[[:space:]])00([[:space:]]|$)'; then
    return 1
  fi
  sh -n "$path" >/dev/null 2>&1
}

otast_strip_literal_block() {
  local path begin end temp line skip seen_begin seen_end
  path=$1
  begin=$2
  end=$3
  temp=${path}.strip.$$
  skip=0
  seen_begin=0
  seen_end=0
  : >"$temp" || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$line" = "$begin" ]; then
      [ "$skip" -eq 0 ] || { rm -f "$temp"; return 1; }
      skip=1
      seen_begin=$((seen_begin + 1))
      continue
    fi
    if [ "$line" = "$end" ]; then
      [ "$skip" -eq 1 ] || { rm -f "$temp"; return 1; }
      skip=0
      seen_end=$((seen_end + 1))
      continue
    fi
    [ "$skip" -eq 1 ] || printf '%s\n' "$line" >>"$temp" || {
      rm -f "$temp"
      return 1
    }
  done <"$path"
  [ "$skip" -eq 0 ] && [ "$seen_begin" -eq "$seen_end" ] && [ "$seen_begin" -le 1 ] || {
    rm -f "$temp"
    return 1
  }
  mv -f "$temp" "$path"
}

otast_prop_set_line() {
  local path key value temp line written
  path=$1
  key=$2
  value=$3
  temp=${path}.prop.$$
  written=0
  : >"$temp" || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "$key="*)
        if [ "$written" -eq 0 ]; then
          printf '%s=%s\n' "$key" "$value" >>"$temp" || { rm -f "$temp"; return 1; }
          written=1
        fi
        ;;
      *) printf '%s\n' "$line" >>"$temp" || { rm -f "$temp"; return 1; } ;;
    esac
  done <"$path"
  if [ "$written" -eq 0 ]; then
    printf '%s=%s\n' "$key" "$value" >>"$temp" || { rm -f "$temp"; return 1; }
  fi
  mv -f "$temp" "$path"
}

otast_transform_pif_prop() {
  local source output
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  cat "$source" >"$output" || return 1
  otast_prop_set_line "$output" FINGERPRINT "$OTAST_FINGERPRINT" || return 1
  otast_prop_set_line "$output" MANUFACTURER "$OTAST_MANUFACTURER" || return 1
  otast_prop_set_line "$output" MODEL "$OTAST_MODEL" || return 1
  otast_prop_set_line "$output" SECURITY_PATCH "$OTAST_SYSTEM_PATCH" || return 1
  otast_prop_set_line "$output" PRODUCT "${OTAST_DEVICE}_beta" || return 1
  otast_prop_set_line "$output" DEVICE "$OTAST_DEVICE" || return 1
  otast_prop_set_line "$output" PRODUCT_LIST '"tegu_beta"' || return 1
  otast_prop_set_line "$output" spoofBuild "$OTAST_PIF_SPOOF_BUILD" || return 1
  otast_prop_set_line "$output" spoofProps "$OTAST_PIF_SPOOF_PROPS" || return 1
  otast_prop_set_line "$output" spoofProvider "$OTAST_PIF_SPOOF_PROVIDER" || return 1
  otast_prop_set_line "$output" spoofSignature "$OTAST_PIF_SPOOF_SIGNATURE" || return 1
  otast_prop_set_line "$output" spoofVendingBuild "$OTAST_PIF_SPOOF_VENDING_BUILD" || return 1
  otast_prop_set_line "$output" spoofVendingSdk "$OTAST_PIF_SPOOF_VENDING_SDK" || return 1
  otast_prop_set_line "$output" DEBUG "$OTAST_PIF_DEBUG" || return 1
  chmod 0600 "$output" || return 1
}

otast_transform_pif_autopif() {
  local source output temp line list_inserted final_inserted output_inserted
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  cat "$source" >"$output" || return 1
  otast_strip_literal_block "$output" "$OTAST_PIF_OVERRIDE_BEGIN" "$OTAST_PIF_OVERRIDE_END" || return 1
  otast_strip_literal_block "$output" "$OTAST_PIF_FINAL_BEGIN" "$OTAST_PIF_FINAL_END" || return 1
  otast_strip_literal_block "$output" "$OTAST_PIF_OUTPUT_BEGIN" "$OTAST_PIF_OUTPUT_END" || return 1
  temp=${output}.new.$$
  list_inserted=0
  final_inserted=0
  output_inserted=0
  : >"$temp" || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$list_inserted" -eq 0 ] && [ "$line" = '# List available devices' ]; then
      cat >>"$temp" <<EOF_LIST
$OTAST_PIF_OVERRIDE_BEGIN
MODEL_LIST='$OTAST_MODEL'
PRODUCT_LIST='${OTAST_DEVICE}_beta'
$OTAST_PIF_OVERRIDE_END
EOF_LIST
      list_inserted=1
    fi
    if [ "$final_inserted" -eq 0 ] && [ "$line" = '# Preserve previous setting' ]; then
      cat >>"$temp" <<EOF_FINAL
$OTAST_PIF_FINAL_BEGIN
MODEL='$OTAST_MODEL'
PRODUCT='${OTAST_DEVICE}_beta'
DEVICE='$OTAST_DEVICE'
FINGERPRINT='$OTAST_FINGERPRINT'
SECURITY_PATCH='$OTAST_SYSTEM_PATCH'
$OTAST_PIF_FINAL_END
EOF_FINAL
      final_inserted=1
    fi
    if [ "$output_inserted" -eq 0 ] && [ "$line" = 'SECURITY_PATCH=$SECURITY_PATCH' ]; then
      cat >>"$temp" <<EOF_OUTPUT
$OTAST_PIF_OUTPUT_BEGIN
PRODUCT=\$PRODUCT
DEVICE=\$DEVICE
PRODUCT_LIST="tegu_beta"
$OTAST_PIF_OUTPUT_END
EOF_OUTPUT
      output_inserted=1
    fi
    printf '%s\n' "$line" >>"$temp" || { rm -f "$temp"; return 1; }
  done <"$output"
  [ "$list_inserted" -eq 1 ] && [ "$final_inserted" -eq 1 ] && [ "$output_inserted" -eq 1 ] || {
    rm -f "$temp"
    return 1
  }
  mv -f "$temp" "$output" || return 1
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}

otast_trim_trailing_blank_lines() {
  local path temp
  path=$1
  temp=${path}.trim.$$
  awk 'NF { while (blank > 0) { print ""; blank-- } print; next } { blank++ }' "$path" >"$temp" || {
    rm -f "$temp"
    return 1
  }
  mv -f "$temp" "$path"
}

otast_transform_pif_ota() {
  local source output
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  cat "$source" >"$output" || return 1
  otast_strip_literal_block "$output" "$OTAST_PIF_REFRESH_BEGIN" "$OTAST_PIF_REFRESH_END" || return 1
  otast_trim_trailing_blank_lines "$output" || return 1
  cat >>"$output" <<EOF_REFRESH

$OTAST_PIF_REFRESH_BEGIN
# Upstream refresh may replace autopif.sh. Reconciliation is read-only; an
# explicit OTAST Apply is required before any newly downloaded source is trusted.
OTAST_ENTRY=''
for OTAST_DIR in "\${ADB_ROOT:-/data/adb}/modules_update/otast" "\${ADB_ROOT:-/data/adb}/modules/otast"; do
  [ -d "\$OTAST_DIR" ] && [ ! -L "\$OTAST_DIR" ] || continue
  [ ! -e "\$OTAST_DIR/remove" ] || continue
  [ ! -e "\$OTAST_DIR/disable" ] || continue
  [ -x "\$OTAST_DIR/runtime/entry.sh" ] || continue
  OTAST_ENTRY=\$OTAST_DIR/runtime/entry.sh
  break
done
[ -z "\$OTAST_ENTRY" ] || sh "\$OTAST_ENTRY" preflight >/dev/null 2>&1 || true
$OTAST_PIF_REFRESH_END
EOF_REFRESH
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}

otast_transform_disabled_writer() {
  local source output reason shebang
  source=$1
  output=$2
  reason=$3
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  IFS= read -r shebang <"$source" || return 1
  case "$shebang" in '#!'*) ;; *) return 1 ;; esac
  if sed -n '2p' "$source" | grep -Fxq '# otast managed' &&
     sed -n '3p' "$source" | grep -Fxq "# OTAST disabled this competing writer: $reason" &&
     sed -n '4p' "$source" | grep -Fxq 'exit 0'; then
    cat "$source" >"$output" || return 1
  else
    {
      printf '%s\n' "$shebang"
      printf '%s\n' '# otast managed'
      printf '# OTAST disabled this competing writer: %s\n' "$reason"
      printf '%s\n' 'exit 0'
      printf '%s\n' '# Original upstream body retained below for audit; unreachable by design.'
      sed -n '2,$p' "$source"
    } >"$output" || return 1
  fi
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}


otast_transform_pif_security_patch() {
  otast_transform_disabled_writer "$1" "$2" 'OTAST owns the PIF/TrickyStore security-patch authority'
}
