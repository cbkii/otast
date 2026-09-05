#!/system/bin/sh

# Play Integrity Fix compatibility integration.
# PIF profile data remains PIF/user-owned. OTAST manages only reviewed writer
# surfaces that could leak attestation-profile state into OTA-owned platform
# identity or replace reviewed executable code from a moving branch.

OTAST_PIF_REFRESH_AUTHORITY_BEGIN='# --- otast pif refresh authority BEGIN ---'
OTAST_PIF_REFRESH_AUTHORITY_END='# --- otast pif refresh authority END ---'
OTAST_PIF_RETIRED_STATE_VERSION='pif-profile-ownership-v1'
OTAST_PIF_PENDING_RETIREMENTS=0
OTAST_PIF_RETIRED_COUNT=0

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

otast_validate_pif_profile_file() {
  local path size line key value seen entries fingerprint patch
  path=$1
  [ -f "$path" ] && [ ! -L "$path" ] || {
    otast_stop "PIF profile is not a safe regular file: $path"
    return 1
  }
  size=$(wc -c <"$path" 2>/dev/null) || return 1
  case "$size" in ''|*[!0-9]*) return 1 ;; esac
  [ "$size" -gt 0 ] && [ "$size" -le 131072 ] || {
    otast_stop "PIF profile size is outside the supported range: $path"
    return 1
  }
  if LC_ALL=C grep -q "$(printf '\r')" "$path" 2>/dev/null; then
    otast_stop "PIF profile contains CR characters: $path"
    return 1
  fi
  if od -An -v -tx1 "$path" 2>/dev/null | grep -Eq '(^|[[:space:]])00([[:space:]]|$)'; then
    otast_stop "PIF profile contains NUL bytes: $path"
    return 1
  fi

  seen='|'
  entries=0
  fingerprint=''
  patch=''
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
      *=*) ;;
      *) otast_stop "PIF profile contains a malformed line: $path"; return 1 ;;
    esac
    key=${line%%=*}
    value=${line#*=}
    case "$key" in ''|*[!A-Za-z0-9_.-]*) otast_stop "PIF profile contains an invalid key: $path"; return 1 ;; esac
    case "$seen" in *"|$key|"*) otast_stop "PIF profile contains a duplicate key ($key): $path"; return 1 ;; esac
    seen="${seen}${key}|"
    entries=$((entries + 1))
    case "$key" in
      FINGERPRINT)
        [ -n "$value" ] || { otast_stop "PIF profile fingerprint is empty: $path"; return 1; }
        fingerprint=$value
        ;;
      SECURITY_PATCH)
        otast_valid_date "$value" || { otast_stop "PIF profile security patch is invalid: $path"; return 1; }
        patch=$value
        ;;
      spoofBuild|spoofProps|spoofProvider|spoofSignature|spoofVendingBuild|spoofVendingSdk|DEBUG)
        case "$value" in true|false) ;; *) otast_stop "PIF profile boolean $key is invalid: $path"; return 1 ;; esac
        ;;
    esac
  done <"$path"
  [ "$entries" -gt 0 ] && [ -n "$fingerprint" ] && [ -n "$patch" ] || {
    otast_stop "PIF profile is missing required FINGERPRINT or SECURITY_PATCH: $path"
    return 1
  }
  return 0
}

otast_validate_pif_profiles_current() {
  local path module
  path=$ADB_ROOT/pif.prop
  if [ -e "$path" ] || [ -L "$path" ]; then
    otast_validate_pif_profile_file "$path" || return 1
  fi
  for path in \
    "$ADB_ROOT/modules/playintegrityfix/pif.prop" \
    "$ADB_ROOT/modules_update/playintegrityfix/pif.prop"; do
    if [ "$path" = "$ADB_ROOT/modules/playintegrityfix/pif.prop" ]; then
      module=$ADB_ROOT/modules/playintegrityfix
    else
      module=$ADB_ROOT/modules_update/playintegrityfix
    fi
    if [ -e "$module" ] || [ -L "$module" ]; then
      [ -d "$module" ] && [ ! -L "$module" ] || {
        otast_stop "PIF module directory is unsafe: $module"
        return 1
      }
      otast_validate_pif_profile_file "$path" || return 1
    fi
  done
  return 0
}

otast_pif_legacy_state_path_for_id() {
  case $1 in
    pif-global-prop) printf '%s\n' "$ADB_ROOT/pif.prop" ;;
    pif-prop-active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/pif.prop" ;;
    pif-prop-staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/pif.prop" ;;
    *) return 1 ;;
  esac
}

otast_pif_validate_legacy_state_one() {
  local id expected_path state target strategy original_exists original_hash backup backup_hash parent
  id=$1
  expected_path=$(otast_pif_legacy_state_path_for_id "$id") || return 1
  state=$(_otast_state_path "$id") || return 1
  [ -e "$state" ] || return 0
  [ -f "$state" ] && [ ! -L "$state" ] || {
    otast_stop "legacy PIF managed state is unsafe: $state"
    return 1
  }
  _otast_validate_record "$state" "$id" "$expected_path" || {
    otast_stop "legacy PIF managed state is malformed or mismatched: $state"
    return 1
  }
  target=$(_otast_state_get "$state" target) || return 1
  strategy=$(_otast_state_get "$state" strategy) || return 1
  [ "$target" = playintegrityfix ] && [ "$strategy" = external ] || {
    otast_stop "legacy PIF managed state has an unexpected ownership contract: $state"
    return 1
  }
  original_exists=$(_otast_state_get "$state" original_exists) || return 1
  original_hash=$(_otast_state_get "$state" original_hash) || return 1
  backup=$(_otast_state_get "$state" backup) || return 1
  if [ "$original_exists" = 1 ]; then
    [ -f "$backup" ] && [ ! -L "$backup" ] || {
      otast_stop "legacy PIF original backup is missing or unsafe: $backup"
      return 1
    }
    backup_hash=$(otast_sha256 "$backup") || return 1
    [ "$backup_hash" = "$original_hash" ] || {
      otast_stop "legacy PIF original backup hash differs from its record: $backup"
      return 1
    }
  fi

  if [ -e "$expected_path" ] || [ -L "$expected_path" ]; then
    otast_validate_pif_profile_file "$expected_path" || return 1
    return 0
  fi

  case "$id" in
    pif-global-prop) return 0 ;;
    pif-prop-active) parent=$ADB_ROOT/modules/playintegrityfix ;;
    pif-prop-staged) parent=$ADB_ROOT/modules_update/playintegrityfix ;;
  esac
  if [ -e "$parent" ] || [ -L "$parent" ]; then
    [ -d "$parent" ] && [ ! -L "$parent" ] || {
      otast_stop "PIF module directory is unsafe while retiring profile ownership: $parent"
      return 1
    }
    otast_stop "PIF module exists but its fallback pif.prop is missing: $parent"
    return 1
  fi
  return 0
}

otast_pif_inspect_legacy_profile_state() {
  local id state
  OTAST_PIF_PENDING_RETIREMENTS=0
  for id in pif-global-prop pif-prop-active pif-prop-staged; do
    state=$(_otast_state_path "$id") || return 1
    [ -e "$state" ] || continue
    otast_pif_validate_legacy_state_one "$id" || return 1
    OTAST_PIF_PENDING_RETIREMENTS=$((OTAST_PIF_PENDING_RETIREMENTS + 1))
  done
  return 0
}

otast_pif_retire_legacy_profile_state() {
  local id state retired_dir destination state_hash destination_hash
  otast_pif_inspect_legacy_profile_state || return 1
  OTAST_PIF_RETIRED_COUNT=0
  [ "$OTAST_PIF_PENDING_RETIREMENTS" -gt 0 ] || return 0
  retired_dir=$OTAST_STATE_ROOT/retired/$OTAST_PIF_RETIRED_STATE_VERSION
  otast_ensure_dir "$retired_dir" || return 1

  # All records were validated before the first move. Each rename is atomic on
  # /data/adb and the operation is idempotent: a partial interruption can only
  # leave a subset already retired, never modified live PIF profile bytes.
  for id in pif-global-prop pif-prop-active pif-prop-staged; do
    state=$(_otast_state_path "$id") || return 1
    [ -e "$state" ] || continue
    destination=$retired_dir/$id.state
    if [ -e "$destination" ]; then
      [ -f "$destination" ] && [ ! -L "$destination" ] || {
        otast_stop "retired PIF ownership evidence is unsafe: $destination"
        return 1
      }
      state_hash=$(otast_sha256 "$state") || return 1
      destination_hash=$(otast_sha256 "$destination") || return 1
      [ "$state_hash" = "$destination_hash" ] || {
        otast_stop "retired PIF ownership evidence conflicts with active legacy state: $id"
        return 1
      }
      rm -f "$state" || return 1
    else
      mv "$state" "$destination" || return 1
      chmod 0600 "$destination" || return 1
    fi
    OTAST_PIF_RETIRED_COUNT=$((OTAST_PIF_RETIRED_COUNT + 1))
  done
  OTAST_PIF_PENDING_RETIREMENTS=0
  otast_log INFO "retired $OTAST_PIF_RETIRED_COUNT legacy PIF profile ownership record(s); original backup evidence was preserved"
  return 0
}

otast_transform_pif_autopif() {
  local source output temp line trimmed state replaced begin_count end_count
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  cat "$source" >"$output" || return 1

  # Remove only blocks emitted by the superseded identity-takeover transform.
  otast_strip_literal_block "$output" '# --- otast pif authority BEGIN ---' '# --- otast pif authority END ---' || return 1
  otast_strip_literal_block "$output" '# --- otast pif final identity BEGIN ---' '# --- otast pif final identity END ---' || return 1
  otast_strip_literal_block "$output" '# --- otast pif output identity BEGIN ---' '# --- otast pif output identity END ---' || return 1

  begin_count=$(grep -Fxc "$OTAST_PIF_REFRESH_AUTHORITY_BEGIN" "$output" 2>/dev/null || true)
  end_count=$(grep -Fxc "$OTAST_PIF_REFRESH_AUTHORITY_END" "$output" 2>/dev/null || true)
  if [ "$begin_count" -ne 0 ] || [ "$end_count" -ne 0 ]; then
    [ "$begin_count" -eq 1 ] && [ "$end_count" -eq 1 ] || return 1
    if grep -Fq 'rm -f $MODDIR/system.prop' "$output"; then
      return 1
    fi
    chmod 0600 "$output" || return 1
    otast_shell_file_valid "$output"
    return $?
  fi

  temp=${output}.new.$$
  state=0
  replaced=0
  : >"$temp" || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed=$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//') || { rm -f "$temp"; return 1; }
    case "$state" in
      0)
        if [ "$trimmed" = 'if [ -e "/data/adb/tricky_store/pif_auto_security_patch" ]; then' ] && [ "$replaced" -eq 0 ]; then
          cat >>"$temp" <<'EOF_AUTHORITY'
# --- otast pif refresh authority BEGIN ---
# PIF profile refresh remains PIF-owned. OTA-derived platform and TrickyStore
# security-patch authority remains OTAST-owned.
if [ -e "/data/adb/tricky_store/pif_auto_security_patch" ]; then
  sh "$MODDIR/security_patch.sh"
else
  :
fi
# --- otast pif refresh authority END ---
EOF_AUTHORITY
          state=1
          replaced=1
        else
          printf '%s\n' "$line" >>"$temp" || { rm -f "$temp"; return 1; }
        fi
        ;;
      1) [ "$trimmed" = 'sh "$MODDIR/security_patch.sh"' ] || { rm -f "$temp"; return 1; }; state=2 ;;
      2) [ "$trimmed" = else ] || { rm -f "$temp"; return 1; }; state=3 ;;
      3) [ "$trimmed" = 'rm -f $MODDIR/system.prop' ] || { rm -f "$temp"; return 1; }; state=4 ;;
      4) [ "$trimmed" = fi ] || { rm -f "$temp"; return 1; }; state=0 ;;
      *) rm -f "$temp"; return 1 ;;
    esac
  done <"$output"
  [ "$state" -eq 0 ] && [ "$replaced" -eq 1 ] || { rm -f "$temp"; return 1; }
  mv -f "$temp" "$output" || return 1
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}

otast_transform_pif_ota() {
  local source output shebang
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  IFS= read -r shebang <"$source" || return 1
  case "$shebang" in '#!'*) ;; *) return 1 ;; esac

  if sed -n '2p' "$source" | grep -Fxq '# otast managed: AutoPIF executable self-update gate'; then
    cat "$source" >"$output" || return 1
  else
    {
      printf '%s\n' "$shebang"
      printf '%s\n' '# otast managed: AutoPIF executable self-update gate'
      printf '%s\n' '# Moving inject_s executable updates require OTAST compatibility review.'
      printf '%s\n' "printf '%s\\n' '[+] AutoPIF executable self-update is review-gated by OTAST; using the installed reviewed engine.'"
      printf '%s\n' 'exit 0'
      printf '%s\n' '# Original reviewed upstream body retained below for audit; unreachable by design.'
      sed -n '2,$p' "$source"
    } >"$output" || return 1
  fi
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}

otast_transform_pif_security_patch() {
  local source output shebang
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  IFS= read -r shebang <"$source" || return 1
  case "$shebang" in '#!'*) ;; *) return 1 ;; esac

  if sed -n '2p' "$source" | grep -Fxq '# otast managed: PIF auto-security-patch compatibility adapter'; then
    cat "$source" >"$output" || return 1
  else
    {
      printf '%s\n' "$shebang"
      cat <<'EOF_ADAPTER'
# otast managed: PIF auto-security-patch compatibility adapter
# The preference marker remains PIF-owned; profile SECURITY_PATCH is never
# promoted into OTAST-owned platform or TrickyStore security-patch state.
AUTO_FLAG=/data/adb/tricky_store/pif_auto_security_patch
case ${1:-} in
  --enable)
    if touch "$AUTO_FLAG"; then
      printf '%s\n' '[+] PIF auto security-patch preference enabled; OTAST OTA authority remains effective.'
      exit 0
    fi
    printf '%s\n' '[!] Failed to enable PIF auto security-patch preference.' >&2
    exit 1
    ;;
  --disable)
    if rm -f "$AUTO_FLAG"; then
      printf '%s\n' '[+] PIF auto security-patch preference disabled; OTAST-managed system.prop was preserved.'
      exit 0
    fi
    printf '%s\n' '[!] Failed to disable PIF auto security-patch preference.' >&2
    exit 1
    ;;
  '')
    printf '%s\n' '[+] PIF profile refreshed; OTA-derived platform/TrickyStore patch authority remains managed by OTAST.'
    exit 0
    ;;
  *)
    printf 'Usage: %s [--enable|--disable]\n' "$0" >&2
    exit 64
    ;;
esac
# Original reviewed upstream body retained below for audit; unreachable by design.
EOF_ADAPTER
      sed -n '2,$p' "$source"
    } >"$output" || return 1
  fi
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}
