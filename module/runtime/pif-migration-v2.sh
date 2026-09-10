#!/system/bin/sh

# Metadata-only bridge from legacy pif-prop-{active,staged} ownership to the
# canonical-mirror v2 state IDs. This runs only under the Apply lock, before the
# v2 mirror transaction is planned. It never changes live profile bytes.

_otast_pif_legacy_profile_id_for_role() {
  case $1 in
    active) printf 'pif-prop-active\n' ;;
    staged) printf 'pif-prop-staged\n' ;;
    *) return 1 ;;
  esac
}

_otast_pif_profile_path_for_role() {
  case $1 in
    active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/pif.prop" ;;
    staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/pif.prop" ;;
    *) return 1 ;;
  esac
}

_otast_pif_seed_one_mirror_from_legacy() {
  local role legacy_id mirror_id path legacy_state mirror_state
  local original_exists original_mode original_hash old_backup new_backup
  local managed_hash managed_mode live live_mode target strategy mirror_original mirror_backup
  role=$1
  legacy_id=$(_otast_pif_legacy_profile_id_for_role "$role") || return 1
  mirror_id=pif-mirror-$role
  path=$(_otast_pif_profile_path_for_role "$role") || return 1
  legacy_state=$(_otast_state_path "$legacy_id") || return 1
  mirror_state=$(_otast_state_path "$mirror_id") || return 1

  [ -e "$legacy_state" ] || return 0
  [ "$path" != "$OTAST_PIF_CANONICAL_PATH" ] || return 0

  otast_pif_validate_legacy_state_one "$legacy_id" || return 1
  managed_hash=$(_otast_state_get "$legacy_state" managed_hash) || return 1
  managed_mode=$(_otast_state_get "$legacy_state" managed_mode) || return 1
  live=$(otast_live_hash "$path") || return 1
  live_mode=0000
  [ "$live" = MISSING ] || live_mode=$(otast_file_mode "$path") || return 1
  [ "$live" = "$managed_hash" ] && [ "$live_mode" = "$managed_mode" ] || {
    otast_stop "legacy PIF profile drift blocks v2 mirror adoption: $path"
    return 1
  }

  original_exists=$(_otast_state_get "$legacy_state" original_exists) || return 1
  original_mode=$(_otast_state_get "$legacy_state" original_mode) || return 1
  original_hash=$(_otast_state_get "$legacy_state" original_hash) || return 1
  old_backup=$(_otast_state_get "$legacy_state" backup) || return 1
  new_backup=$OTAST_STATE_ROOT/backups/$mirror_id.original

  if [ -e "$mirror_state" ]; then
    [ -f "$mirror_state" ] && [ ! -L "$mirror_state" ] && \
      _otast_validate_record "$mirror_state" "$mirror_id" "$path" || {
        otast_stop "v2 PIF mirror state is malformed during legacy adoption: $mirror_state"
        return 1
      }
    mirror_original=$(_otast_state_get "$mirror_state" original_hash) || return 1
    mirror_backup=$(_otast_state_get "$mirror_state" backup) || return 1
    [ "$mirror_original" = "$original_hash" ] && [ "$mirror_backup" = "$new_backup" ] || {
      otast_stop "v2 PIF mirror original contract conflicts with legacy ownership: $path"
      return 1
    }
    if [ "$original_exists" = 1 ]; then
      [ -f "$new_backup" ] && [ ! -L "$new_backup" ] && \
        [ "$(otast_sha256 "$new_backup")" = "$original_hash" ] || {
          otast_stop "v2 PIF mirror original backup is missing or invalid: $new_backup"
          return 1
        }
    fi
    return 0
  fi

  otast_ensure_dir "$OTAST_STATE_ROOT/backups" || return 1
  if [ "$original_exists" = 1 ]; then
    [ -f "$old_backup" ] && [ ! -L "$old_backup" ] && \
      [ "$(otast_sha256 "$old_backup")" = "$original_hash" ] || {
        otast_stop "legacy PIF original backup is missing or invalid: $old_backup"
        return 1
      }
    if [ -e "$new_backup" ]; then
      [ -f "$new_backup" ] && [ ! -L "$new_backup" ] && \
        [ "$(otast_sha256 "$new_backup")" = "$original_hash" ] || {
          otast_stop "existing v2 PIF mirror backup conflicts with legacy original: $new_backup"
          return 1
        }
    else
      cat "$old_backup" >"$new_backup" || return 1
      chmod 0600 "$new_backup" || return 1
    fi
  else
    if [ -e "$new_backup" ]; then
      [ -f "$new_backup" ] && [ ! -L "$new_backup" ] && [ ! -s "$new_backup" ] || {
        otast_stop "existing v2 PIF mirror absence backup is invalid: $new_backup"
        return 1
      }
    else
      : >"$new_backup" || return 1
      chmod 0600 "$new_backup" || return 1
    fi
  fi

  target=$(_otast_state_get "$legacy_state" target) || return 1
  strategy=$(_otast_state_get "$legacy_state" strategy) || return 1
  [ "$target" = playintegrityfix ] && [ "$strategy" = external ] || {
    otast_stop "legacy PIF profile state has unexpected ownership while adopting mirror: $legacy_state"
    return 1
  }

  _otast_write_state "$mirror_id" playintegrityfix "$path" \
    "$original_exists" "$original_mode" "$original_hash" "$new_backup" \
    "$managed_hash" "$managed_mode" external || return 1
  otast_log INFO "adopted legacy PIF $role fallback into v2 mirror state without changing live bytes"
}

otast_pif_prepare_v2_mirror_state() {
  [ "${OTAST_LOCK_HELD:-0}" = 1 ] || {
    otast_stop 'PIF v2 mirror-state migration requires the OTAST Apply lock'
    return 1
  }
  [ "${OTAST_PIF_ARCHITECTURE:-}" = canonical-mirror-v2 ] || return 0
  [ -n "${OTAST_PIF_CANONICAL_PATH:-}" ] || return 0
  _otast_pif_seed_one_mirror_from_legacy active || return 1
  _otast_pif_seed_one_mirror_from_legacy staged || return 1
}
