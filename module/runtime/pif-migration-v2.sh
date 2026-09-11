#!/system/bin/sh

# PIF topology and state migration for canonical-mirror v2. This file is
# intentionally sourced after architecture-v2.sh so migration-safe topology
# resolution and state-transition helpers are the effective implementations.

OTAST_PIF_PENDING_PROMOTIONS=0
OTAST_PIF_PROVISIONAL_PLAN=0

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

_otast_pif_module_dir_for_role() {
  case $1 in
    active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix" ;;
    staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix" ;;
    *) return 1 ;;
  esac
}

_otast_pif_module_effective() {
  local dir
  dir=$1
  [ -d "$dir" ] && [ ! -L "$dir" ] || return 1
  if [ -e "$dir/remove" ] || [ -L "$dir/remove" ] || [ -e "$dir/disable" ] || [ -L "$dir/disable" ]; then
    return 1
  fi
  return 0
}

# Canonical selection must use the same effective-module semantics as planning.
# Disabled/removed module trees can never become an identity source.
_otast_pif_select_canonical() {
  local global active_dir staged_dir active staged
  global=$ADB_ROOT/pif.prop
  active_dir=$ADB_ROOT/modules/playintegrityfix
  staged_dir=$ADB_ROOT/modules_update/playintegrityfix
  active=$active_dir/pif.prop
  staged=$staged_dir/pif.prop
  OTAST_PIF_CANONICAL_PATH=''
  OTAST_PIF_CANONICAL_ROLE=UNAVAILABLE
  OTAST_PIF_CANONICAL_HASH=''

  if [ -f "$global" ] && [ ! -L "$global" ]; then
    OTAST_PIF_CANONICAL_PATH=$global
    OTAST_PIF_CANONICAL_ROLE=GLOBAL_CUSTOM
  elif _otast_pif_module_effective "$active_dir" && [ -f "$active" ] && [ ! -L "$active" ]; then
    OTAST_PIF_CANONICAL_PATH=$active
    OTAST_PIF_CANONICAL_ROLE=ACTIVE_FALLBACK
  elif _otast_pif_module_effective "$staged_dir" && [ -f "$staged" ] && [ ! -L "$staged" ]; then
    OTAST_PIF_CANONICAL_PATH=$staged
    OTAST_PIF_CANONICAL_ROLE=STAGED_FALLBACK
  else
    return 1
  fi
  OTAST_PIF_CANONICAL_HASH=$(otast_sha256 "$OTAST_PIF_CANONICAL_PATH") || return 1
}

otast_validate_pif_profiles_current() {
  local global module found
  global=$ADB_ROOT/pif.prop
  found=0

  if [ -e "$global" ] || [ -L "$global" ]; then
    otast_assert_no_symlink_path "$global" || return 1
    otast_validate_pif_profile_file "$global" || return 1
  fi

  for module in "$ADB_ROOT/modules/playintegrityfix" "$ADB_ROOT/modules_update/playintegrityfix"; do
    [ -e "$module" ] || [ -L "$module" ] || continue
    [ -d "$module" ] && [ ! -L "$module" ] || {
      otast_stop "PIF module directory is unsafe: $module"
      return 1
    }
    otast_assert_no_symlink_path "$module/pif.prop" || return 1
    _otast_pif_module_effective "$module" || continue
    otast_validate_pif_profile_file "$module/pif.prop" || return 1
    found=1
  done

  if [ "$found" -eq 1 ]; then
    _otast_pif_select_canonical || {
      otast_stop 'PIF is installed but no valid canonical profile is available'
      return 1
    }
  else
    OTAST_PIF_CANONICAL_PATH=''
    OTAST_PIF_CANONICAL_ROLE=UNAVAILABLE
    OTAST_PIF_CANONICAL_HASH=''
  fi
}

_otast_pif_state_backup_valid() {
  local state original_exists original_hash backup
  state=$1
  original_exists=$(_otast_state_get "$state" original_exists) || return 1
  original_hash=$(_otast_state_get "$state" original_hash) || return 1
  backup=$(_otast_state_get "$state" backup) || return 1
  otast_assert_no_symlink_path "$backup" || return 1
  [ -f "$backup" ] && [ ! -L "$backup" ] || return 1
  if [ "$original_exists" = 1 ]; then
    [ "$(otast_sha256 "$backup")" = "$original_hash" ] || return 1
  else
    [ "$original_exists" = 0 ] && [ ! -s "$backup" ] || return 1
  fi
}

# Current mirror ownership can recur many times. Archive each ownership era into
# its own immutable generation, including a private copy of its original backup.
_otast_pif_archive_state_generation() {
  local id category state path root attempt generation pending archive_backup archive_state
  local original_exists original_hash backup line
  id=$1
  category=$2
  state=$(_otast_state_path "$id") || return 1
  [ -e "$state" ] || return 0
  path=$(_otast_state_get "$state" path) || return 1
  otast_assert_no_symlink_path "$state" || return 1
  [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
    otast_stop "PIF state is malformed before generation retirement: $state"
    return 1
  }
  _otast_pif_state_backup_valid "$state" || {
    otast_stop "PIF state original backup is invalid before generation retirement: $state"
    return 1
  }
  original_exists=$(_otast_state_get "$state" original_exists) || return 1
  original_hash=$(_otast_state_get "$state" original_hash) || return 1
  backup=$(_otast_state_get "$state" backup) || return 1

  root=$OTAST_STATE_ROOT/retired/$category/$id
  otast_ensure_dir "$root" || return 1
  attempt=1
  generation=''
  while [ "$attempt" -le 9999 ]; do
    generation=$root/g$(printf '%06d' "$attempt")
    if [ ! -e "$generation" ] && [ ! -L "$generation" ]; then
      break
    fi
    attempt=$((attempt + 1))
  done
  [ "$attempt" -le 9999 ] || {
    otast_stop "no free PIF retirement generation remains for $id"
    return 1
  }

  pending=$root/.pending.$$.$attempt
  otast_assert_no_symlink_path "$pending" || return 1
  mkdir "$pending" || return 1
  chmod 0700 "$pending" || { rm -rf "$pending" 2>/dev/null || :; return 1; }
  archive_backup=$generation/original.backup
  archive_state=$generation/state

  if ! cat "$backup" >"$pending/original.backup" || ! chmod 0600 "$pending/original.backup"; then
    rm -rf "$pending" 2>/dev/null || :
    return 1
  fi
  if [ "$original_exists" = 1 ] && [ "$(otast_sha256 "$pending/original.backup")" != "$original_hash" ]; then
    rm -rf "$pending" 2>/dev/null || :
    otast_stop "PIF archived original backup hash changed while retiring $id"
    return 1
  fi

  : >"$pending/state" || { rm -rf "$pending" 2>/dev/null || :; return 1; }
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      backup=*) printf 'backup=%s\n' "$archive_backup" >>"$pending/state" || { rm -rf "$pending" 2>/dev/null || :; return 1; } ;;
      *) printf '%s\n' "$line" >>"$pending/state" || { rm -rf "$pending" 2>/dev/null || :; return 1; } ;;
    esac
  done <"$state"
  chmod 0600 "$pending/state" || { rm -rf "$pending" 2>/dev/null || :; return 1; }
  mv "$pending" "$generation" || { rm -rf "$pending" 2>/dev/null || :; return 1; }

  rm -f "$state" || return 1
  rm -f "$backup" || return 1
  OTAST_PIF_RETIRED_COUNT=$((OTAST_PIF_RETIRED_COUNT + 1))
  otast_log INFO "retired PIF state generation: $id -> $archive_state"
}

_otast_pif_role_state_id() {
  case "$1:$2" in
    mirror:active) printf 'pif-mirror-active\n' ;;
    mirror:staged) printf 'pif-mirror-staged\n' ;;
    security-patch:active) printf 'pif-security-patch-active\n' ;;
    security-patch:staged) printf 'pif-security-patch-staged\n' ;;
    *) return 1 ;;
  esac
}

_otast_pif_role_target_path() {
  case "$1:$2" in
    mirror:active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/pif.prop" ;;
    mirror:staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/pif.prop" ;;
    security-patch:active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/security_patch.sh" ;;
    security-patch:staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/security_patch.sh" ;;
    *) return 1 ;;
  esac
}

_otast_pif_promotion_candidate() {
  local kind staged_id staged_path staged_state staged_dir active_path active_dir
  local managed managed_mode live live_mode active_id active_state
  kind=$1
  staged_id=$(_otast_pif_role_state_id "$kind" staged) || return 1
  staged_path=$(_otast_pif_role_target_path "$kind" staged) || return 1
  staged_state=$(_otast_state_path "$staged_id") || return 1
  [ -e "$staged_state" ] || return 1

  staged_dir=$ADB_ROOT/modules_update/playintegrityfix
  if [ -e "$staged_dir" ] || [ -L "$staged_dir" ]; then
    return 1
  fi

  active_dir=$ADB_ROOT/modules/playintegrityfix
  _otast_pif_module_effective "$active_dir" || {
    otast_stop "staged PIF state exists without an effective active module; cannot prove promotion: $staged_id"
    return 2
  }
  active_path=$(_otast_pif_role_target_path "$kind" active) || return 2
  otast_assert_no_symlink_path "$active_path" || return 2
  [ -f "$staged_state" ] && [ ! -L "$staged_state" ] && _otast_validate_record "$staged_state" "$staged_id" "$staged_path" || {
    otast_stop "staged PIF state is malformed while checking promotion: $staged_state"
    return 2
  }
  _otast_pif_state_backup_valid "$staged_state" || {
    otast_stop "staged PIF original backup is invalid while checking promotion: $staged_id"
    return 2
  }
  managed=$(_otast_state_get "$staged_state" managed_hash) || return 2
  managed_mode=$(_otast_state_get "$staged_state" managed_mode) || return 2
  live=$(otast_live_hash "$active_path") || return 2
  live_mode=0000
  [ "$live" = MISSING ] || live_mode=$(otast_file_mode "$active_path") || return 2
  if [ "$live" != "$managed" ] || [ "$live_mode" != "$managed_mode" ]; then
    otast_stop "staged PIF state disappeared without a provable Magisk promotion: $staged_id"
    return 2
  fi

  active_id=$(_otast_pif_role_state_id "$kind" active) || return 2
  active_state=$(_otast_state_path "$active_id") || return 2
  if [ -e "$active_state" ]; then
    [ -f "$active_state" ] && [ ! -L "$active_state" ] && _otast_validate_record "$active_state" "$active_id" "$active_path" || {
      otast_stop "active PIF state is malformed while checking promotion: $active_state"
      return 2
    }
    _otast_pif_state_backup_valid "$active_state" || {
      otast_stop "active PIF original backup is invalid while checking promotion: $active_id"
      return 2
    }
  fi
  return 0
}

otast_pif_inspect_role_transitions() {
  local kind rc
  OTAST_PIF_PENDING_PROMOTIONS=0
  for kind in mirror security-patch; do
    _otast_pif_promotion_candidate "$kind"
    rc=$?
    case "$rc" in
      0) OTAST_PIF_PENDING_PROMOTIONS=$((OTAST_PIF_PENDING_PROMOTIONS + 1)) ;;
      1) ;;
      *) return 1 ;;
    esac
  done
  return 0
}

_otast_pif_copy_state_original_to_id() {
  local source_state destination_id destination_path target strategy original_exists original_mode original_hash
  local source_backup destination_backup managed_hash managed_mode
  source_state=$1
  destination_id=$2
  destination_path=$3
  target=$(_otast_state_get "$source_state" target) || return 1
  strategy=$(_otast_state_get "$source_state" strategy) || return 1
  original_exists=$(_otast_state_get "$source_state" original_exists) || return 1
  original_mode=$(_otast_state_get "$source_state" original_mode) || return 1
  original_hash=$(_otast_state_get "$source_state" original_hash) || return 1
  source_backup=$(_otast_state_get "$source_state" backup) || return 1
  managed_hash=$(_otast_state_get "$source_state" managed_hash) || return 1
  managed_mode=$(_otast_state_get "$source_state" managed_mode) || return 1
  destination_backup=$OTAST_STATE_ROOT/backups/$destination_id.original

  otast_ensure_dir "$OTAST_STATE_ROOT/backups" || return 1
  otast_assert_no_symlink_path "$destination_backup" || return 1
  if [ -e "$destination_backup" ]; then
    otast_stop "destination PIF promotion backup already exists without active ownership: $destination_backup"
    return 1
  fi
  cat "$source_backup" >"$destination_backup" || return 1
  chmod 0600 "$destination_backup" || return 1
  _otast_write_state "$destination_id" "$target" "$destination_path" \
    "$original_exists" "$original_mode" "$original_hash" "$destination_backup" \
    "$managed_hash" "$managed_mode" "$strategy"
}

_otast_pif_commit_one_promotion() {
  local kind staged_id staged_path staged_state active_id active_path active_state
  kind=$1
  _otast_pif_promotion_candidate "$kind"
  case $? in
    0) ;;
    1) return 0 ;;
    *) return 1 ;;
  esac
  staged_id=$(_otast_pif_role_state_id "$kind" staged) || return 1
  staged_path=$(_otast_pif_role_target_path "$kind" staged) || return 1
  staged_state=$(_otast_state_path "$staged_id") || return 1
  active_id=$(_otast_pif_role_state_id "$kind" active) || return 1
  active_path=$(_otast_pif_role_target_path "$kind" active) || return 1
  active_state=$(_otast_state_path "$active_id") || return 1

  if [ -e "$active_state" ]; then
    _otast_pif_archive_state_generation "$active_id" pif-role-promotion-v2 || return 1
  else
    # A stale backup without its state cannot safely be rebound to another era.
    if [ -e "$OTAST_STATE_ROOT/backups/$active_id.original" ] || [ -L "$OTAST_STATE_ROOT/backups/$active_id.original" ]; then
      otast_stop "orphaned active PIF backup blocks promotion: $active_id"
      return 1
    fi
  fi

  _otast_pif_copy_state_original_to_id "$staged_state" "$active_id" "$active_path" || return 1
  _otast_pif_archive_state_generation "$staged_id" pif-role-promotion-v2 || return 1
  otast_log INFO "adopted Magisk staged-to-active PIF promotion for $kind"
}

otast_pif_commit_role_transitions() {
  [ "${OTAST_LOCK_HELD:-0}" = 1 ] || {
    otast_stop 'PIF role transition commit requires the OTAST Apply/Restore lock'
    return 1
  }
  otast_pif_inspect_role_transitions || return 1
  _otast_pif_commit_one_promotion mirror || return 1
  _otast_pif_commit_one_promotion security-patch || return 1
  OTAST_PIF_PENDING_PROMOTIONS=0
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
    [ -f "$mirror_state" ] && [ ! -L "$mirror_state" ] && _otast_validate_record "$mirror_state" "$mirror_id" "$path" || {
      otast_stop "v2 PIF mirror state is malformed during legacy adoption: $mirror_state"
      return 1
    }
    mirror_original=$(_otast_state_get "$mirror_state" original_hash) || return 1
    mirror_backup=$(_otast_state_get "$mirror_state" backup) || return 1
    [ "$mirror_original" = "$original_hash" ] && [ "$mirror_backup" = "$new_backup" ] || {
      otast_stop "v2 PIF mirror original contract conflicts with legacy ownership: $path"
      return 1
    }
    _otast_pif_state_backup_valid "$mirror_state" || {
      otast_stop "v2 PIF mirror original backup is missing or invalid: $new_backup"
      return 1
    }
    return 0
  fi

  otast_ensure_dir "$OTAST_STATE_ROOT/backups" || return 1
  otast_assert_no_symlink_path "$new_backup" || return 1
  if [ "$original_exists" = 1 ]; then
    [ -f "$old_backup" ] && [ ! -L "$old_backup" ] && [ "$(otast_sha256 "$old_backup")" = "$original_hash" ] || {
      otast_stop "legacy PIF original backup is missing or invalid: $old_backup"
      return 1
    }
    if [ -e "$new_backup" ]; then
      [ -f "$new_backup" ] && [ ! -L "$new_backup" ] && [ "$(otast_sha256 "$new_backup")" = "$original_hash" ] || {
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

# Safe direct retirement of v1 writers. Use the normal atomic writer/path guard;
# never follow a symlinked module ancestor from historical state.
_otast_pif_restore_deprecated_writer() {
  local id path state original_exists original_mode original_hash backup managed_hash live live_mode
  id=$1
  path=$(_otast_pif_deprecated_path "$id") || return 1
  otast_assert_no_symlink_path "$path" || return 1
  state=$(_otast_state_path "$id") || return 1
  [ -e "$state" ] || return 0
  [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
    otast_stop "deprecated PIF writer state is malformed or mismatched: $state"
    return 1
  }
  original_exists=$(_otast_state_get "$state" original_exists) || return 1
  original_mode=$(_otast_state_get "$state" original_mode) || return 1
  original_hash=$(_otast_state_get "$state" original_hash) || return 1
  backup=$(_otast_state_get "$state" backup) || return 1
  managed_hash=$(_otast_state_get "$state" managed_hash) || return 1
  live=$(otast_live_hash "$path") || return 1
  live_mode=0000
  [ "$live" = MISSING ] || live_mode=$(otast_file_mode "$path") || return 1
  if [ "$original_exists" = 1 ]; then
    [ -f "$backup" ] && [ ! -L "$backup" ] && [ "$(otast_sha256 "$backup")" = "$original_hash" ] || {
      otast_stop "deprecated PIF writer original backup is missing or invalid: $id"
      return 1
    }
    if [ "$live" = "$managed_hash" ]; then
      otast_atomic_install "$backup" "$path" "$original_mode" || return 1
    elif [ "$live" != "$original_hash" ] || [ "$live_mode" != "$original_mode" ]; then
      otast_stop "deprecated PIF writer drift blocks ownership retirement: $path"
      return 1
    fi
  else
    if [ "$live" = "$managed_hash" ]; then
      rm -f "$path" || return 1
    elif [ "$live" != MISSING ]; then
      otast_stop "deprecated generated PIF writer drift blocks ownership retirement: $path"
      return 1
    fi
  fi
  _otast_pif_retire_record "$id" pif-writer-ownership-v2
}

# Include role promotion in the same read-only migration accounting used by
# Report/Preflight/Verify. The effective canonical role must already be resolved.
otast_pif_inspect_legacy_profile_state() {
  local id state path
  OTAST_PIF_PENDING_RETIREMENTS=0
  otast_pif_inspect_role_transitions || return 1
  OTAST_PIF_PENDING_RETIREMENTS=$OTAST_PIF_PENDING_PROMOTIONS

  for id in pif-global-prop pif-prop-active pif-prop-staged; do
    state=$(_otast_state_path "$id") || return 1
    [ -e "$state" ] || continue
    otast_pif_validate_legacy_state_one "$id" || return 1
    OTAST_PIF_PENDING_RETIREMENTS=$((OTAST_PIF_PENDING_RETIREMENTS + 1))
  done
  for id in pif-autopif-active pif-autopif-staged pif-autopif-ota-active pif-autopif-ota-staged pif-runtime-system-prop-active pif-runtime-system-prop-staged; do
    state=$(_otast_state_path "$id") || return 1
    [ -e "$state" ] || continue
    path=$(_otast_pif_deprecated_path "$id") || return 1
    otast_assert_no_symlink_path "$path" || return 1
    [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
      otast_stop "deprecated PIF writer state is malformed or mismatched: $state"
      return 1
    }
    OTAST_PIF_PENDING_RETIREMENTS=$((OTAST_PIF_PENDING_RETIREMENTS + 1))
  done
  _otast_pif_source_mirror_state 2>/dev/null || return 0
  id=$OTAST_PIF_SOURCE_MIRROR_ID
  path=$OTAST_PIF_SOURCE_MIRROR_PATH
  state=$(_otast_state_path "$id") || return 1
  [ -e "$state" ] || return 0
  [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
    otast_stop "canonical PIF source has invalid mirror ownership state: $state"
    return 1
  }
  _otast_pif_state_backup_valid "$state" || {
    otast_stop "canonical PIF source mirror backup is invalid: $state"
    return 1
  }
  OTAST_PIF_PENDING_RETIREMENTS=$((OTAST_PIF_PENDING_RETIREMENTS + 1))
}

otast_pif_retire_legacy_profile_state() {
  local id state path managed live
  otast_pif_inspect_legacy_profile_state || return 1
  OTAST_PIF_RETIRED_COUNT=${OTAST_PIF_RETIRED_COUNT:-0}

  for id in pif-global-prop pif-prop-active pif-prop-staged; do
    state=$(_otast_state_path "$id") || return 1
    [ -e "$state" ] || continue
    _otast_pif_retire_record "$id" pif-profile-ownership-v1 || return 1
  done
  for id in pif-autopif-active pif-autopif-staged pif-autopif-ota-active pif-autopif-ota-staged pif-runtime-system-prop-active pif-runtime-system-prop-staged; do
    _otast_pif_restore_deprecated_writer "$id" || return 1
  done

  if _otast_pif_source_mirror_state 2>/dev/null; then
    id=$OTAST_PIF_SOURCE_MIRROR_ID
    path=$OTAST_PIF_SOURCE_MIRROR_PATH
    state=$(_otast_state_path "$id") || return 1
    if [ -e "$state" ]; then
      managed=$(_otast_state_get "$state" managed_hash) || return 1
      live=$(otast_live_hash "$path") || return 1
      [ "$live" = "$managed" ] || {
        otast_stop "PIF mirror drift blocks promotion to canonical source: $path"
        return 1
      }
      _otast_pif_archive_state_generation "$id" pif-mirror-source-v2 || return 1
    fi
  fi

  OTAST_PIF_PENDING_RETIREMENTS=$OTAST_PIF_PENDING_PROMOTIONS
  [ "$OTAST_PIF_RETIRED_COUNT" -eq 0 ] || otast_log INFO "retired $OTAST_PIF_RETIRED_COUNT superseded PIF ownership record(s)"
}

# During the provisional read-only plan, a staged security-patch state whose
# bytes have already been promoted to active is valid evidence, even if the old
# active state describes a different reviewed writer generation. The real plan
# is rebuilt after the promotion state has been committed.
_otast_v2_plan_security_patch() {
  local role path id state allowed backup original live managed managed_mode live_mode source
  role=$1
  path=$2
  id=pif-security-patch-$role
  allowed='a21fa1444ad870ad2ba09cb2a45a0576361df6062369d13f05fbf0db78f29476,f24517231c21856c4603f14e9d1ad8d38af5e6753a8060837320e66337ed5012'

  if [ "$role" = active ] && [ "${OTAST_PIF_PROVISIONAL_PLAN:-0}" = 1 ]; then
    _otast_pif_promotion_candidate security-patch
    case $? in
      0)
        state=$(_otast_state_path pif-security-patch-staged) || return 1
        original=$(_otast_state_get "$state" original_hash) || return 1
        otast_hash_allowed "$original" "$allowed" || {
          otast_stop "promoted PIF security-patch original is outside reviewed hashes: $original"
          return 1
        }
        return 0
        ;;
      1) ;;
      *) return 1 ;;
    esac
  fi

  state=$(_otast_state_path "$id") || return 1
  if [ ! -e "$state" ]; then
    _otast_plan_transformed_file "$id" playintegrityfix "$path" 0755 otast_transform_pif_security_patch "$allowed"
    return $?
  fi
  [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
    otast_stop "managed PIF security-patch state is unsafe or mismatched: $state"
    return 1
  }
  managed=$(_otast_state_get "$state" managed_hash) || return 1
  managed_mode=$(_otast_state_get "$state" managed_mode) || return 1
  live=$(otast_live_hash "$path") || return 1
  live_mode=$(otast_file_mode "$path") || return 1
  [ "$live" = "$managed" ] && [ "$live_mode" = "$managed_mode" ] || {
    otast_stop "managed target drift detected: $path"
    return 1
  }
  backup=$(_otast_state_get "$state" backup) || return 1
  original=$(_otast_state_get "$state" original_hash) || return 1
  [ -f "$backup" ] && [ ! -L "$backup" ] && [ "$(otast_sha256 "$backup")" = "$original" ] || {
    otast_stop "PIF security-patch original backup is invalid: $path"
    return 1
  }
  otast_hash_allowed "$original" "$allowed" || {
    otast_stop "PIF security-patch original is outside reviewed hashes: $path ($original)"
    return 1
  }
  source=$OTAST_TMP_ROOT/source.$$.${id}
  otast_transform_pif_security_patch "$backup" "$source" || {
    rm -f "$source" 2>/dev/null || :
    return 1
  }
  chmod 0600 "$source" || return 1
  otast_plan_add "$id" playintegrityfix "$path" 0755 "$source" exact "$allowed"
}
