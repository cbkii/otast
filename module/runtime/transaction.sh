#!/system/bin/sh

# Transaction planner, persistent original-state records, rollback and recovery.

OTAST_PLAN=''
OTAST_PLAN_COUNT=0
OTAST_LOCK_DIR=''
OTAST_TX_DIR=''
OTAST_PREFLIGHT_ACTION=''
OTAST_LOCK_HELD=0
OTAST_LOCK_DEPTH=0

_otast_state_path() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_id=$(otast_safe_id "$1") || return 1
  printf '%s/records/%s.state\n' "$OTAST_STATE_ROOT" "$_otast_id"
}

_otast_state_get() {
  local _otast_file _otast_key _otast_line _otast_value _otast_found
  _otast_file=$1
  _otast_key=$2
  [ -f "$_otast_file" ] && [ ! -L "$_otast_file" ] || return 1
  _otast_found=0
  _otast_value=''
  while IFS= read -r _otast_line || [ -n "$_otast_line" ]; do
    case "$_otast_line" in
      "$_otast_key="*)
        [ "$_otast_found" -eq 0 ] || return 1
        _otast_value=${_otast_line#*=}
        _otast_found=1
        ;;
    esac
  done <"$_otast_file"
  [ "$_otast_found" -eq 1 ] || return 1
  printf '%s\n' "$_otast_value"
}

_otast_write_state() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_id=$1
  _otast_target=$2
  _otast_path=$3
  _otast_original_exists=$4
  _otast_original_mode=$5
  _otast_original_hash=$6
  _otast_backup=$7
  _otast_managed_hash=$8
  shift 8
  _otast_managed_mode=$1
  _otast_strategy=$2
  _otast_state=$(_otast_state_path "$_otast_id") || return 1
  _otast_parent=${_otast_state%/*}
  otast_ensure_dir "$_otast_parent" || return 1
  _otast_tmp=$(otast_make_temp_in "$_otast_parent" state) || return 1
  {
    printf 'version=1\n'
    printf 'id=%s\n' "$_otast_id"
    printf 'target=%s\n' "$_otast_target"
    printf 'path=%s\n' "$_otast_path"
    printf 'strategy=%s\n' "$_otast_strategy"
    printf 'original_exists=%s\n' "$_otast_original_exists"
    printf 'original_mode=%s\n' "$_otast_original_mode"
    printf 'original_hash=%s\n' "$_otast_original_hash"
    printf 'backup=%s\n' "$_otast_backup"
    printf 'managed_hash=%s\n' "$_otast_managed_hash"
    printf 'managed_mode=%s\n' "$_otast_managed_mode"
    printf 'authority_sha256=%s\n' "$OTAST_AUTHORITY_SHA256"
  } >"$_otast_tmp" || {
    rm -f "$_otast_tmp" 2>/dev/null || :
    return 1
  }
  chmod 0600 "$_otast_tmp" || {
    rm -f "$_otast_tmp" 2>/dev/null || :
    return 1
  }
  mv -f "$_otast_tmp" "$_otast_state"
}

otast_acquire_lock() {
  local attempt owner stale
  if [ "${OTAST_LOCK_HELD:-0}" = 1 ]; then
    OTAST_LOCK_DEPTH=$((OTAST_LOCK_DEPTH + 1))
    return 0
  fi
  OTAST_LOCK_DIR=$OTAST_STATE_ROOT/lock
  otast_ensure_dir "$OTAST_STATE_ROOT" || return 1
  attempt=0
  while [ "$attempt" -lt 2 ]; do
    if mkdir "$OTAST_LOCK_DIR" 2>/dev/null; then
      chmod 0700 "$OTAST_LOCK_DIR" || return 1
      printf '%s\n' "$$" >"$OTAST_LOCK_DIR/pid" || return 1
      chmod 0600 "$OTAST_LOCK_DIR/pid" || return 1
      OTAST_LOCK_HELD=1
      OTAST_LOCK_DEPTH=1
      return 0
    fi
    [ ! -L "$OTAST_LOCK_DIR" ] && [ -d "$OTAST_LOCK_DIR" ] || {
      otast_stop "unsafe OTAST lock path: $OTAST_LOCK_DIR"
      return 1
    }
    owner=$(cat "$OTAST_LOCK_DIR/pid" 2>/dev/null) || owner=''
    case "$owner" in
      ''|*[!0-9]*) ;;
      *)
        if kill -0 "$owner" 2>/dev/null; then
          otast_stop "another OTAST operation holds the lock (pid $owner)"
          return 1
        fi
        ;;
    esac
    stale=$OTAST_STATE_ROOT/lock.stale.$$.$attempt
    if mv "$OTAST_LOCK_DIR" "$stale" 2>/dev/null; then
      rm -rf "$stale" 2>/dev/null || {
        otast_stop "cannot remove stale lock evidence: $stale"
        return 1
      }
      otast_log WARN "reclaimed stale OTAST lock"
    else
      otast_stop "OTAST lock changed while checking it"
      return 1
    fi
    attempt=$((attempt + 1))
  done
  otast_stop "cannot acquire OTAST lock"
  return 1
}

otast_release_lock() {
  local owner
  [ "${OTAST_LOCK_HELD:-0}" = 1 ] || return 0
  if [ "${OTAST_LOCK_DEPTH:-1}" -gt 1 ] 2>/dev/null; then
    OTAST_LOCK_DEPTH=$((OTAST_LOCK_DEPTH - 1))
    return 0
  fi
  if [ -n "$OTAST_LOCK_DIR" ] && [ -d "$OTAST_LOCK_DIR" ] && [ ! -L "$OTAST_LOCK_DIR" ]; then
    owner=$(cat "$OTAST_LOCK_DIR/pid" 2>/dev/null) || owner=''
    if [ "$owner" = "$$" ]; then
      rm -rf "$OTAST_LOCK_DIR" 2>/dev/null || return 1
    else
      otast_stop "refusing to release a lock not owned by this process"
      return 1
    fi
  fi
  OTAST_LOCK_DIR=''
  OTAST_LOCK_HELD=0
  OTAST_LOCK_DEPTH=0
  return 0
}

otast_plan_begin() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  otast_ensure_dir "$OTAST_TMP_ROOT" || return 1
  OTAST_PLAN=$OTAST_TMP_ROOT/plan.$$
  : >"$OTAST_PLAN" || return 1
  chmod 0600 "$OTAST_PLAN" || return 1
  OTAST_PLAN_COUNT=0
}

otast_plan_cleanup() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  [ -n "$OTAST_PLAN" ] || return 0
  _otast_plan_prefix=$OTAST_TMP_ROOT/source.$$
  rm -f "$OTAST_PLAN" "$_otast_plan_prefix".* 2>/dev/null || :
  OTAST_PLAN=''
  OTAST_PLAN_COUNT=0
}

otast_plan_source_text() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_name=$(otast_safe_id "$1") || return 1
  _otast_source=$OTAST_TMP_ROOT/source.$$.${_otast_name}
  cat >"$_otast_source" || return 1
  chmod 0600 "$_otast_source" || return 1
  printf '%s\n' "$_otast_source"
}

otast_plan_source_file() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_name=$(otast_safe_id "$1") || return 1
  _otast_input=$2
  [ -f "$_otast_input" ] && [ ! -L "$_otast_input" ] || return 1
  _otast_source=$OTAST_TMP_ROOT/source.$$.${_otast_name}
  cat "$_otast_input" >"$_otast_source" || return 1
  chmod 0600 "$_otast_source" || return 1
  printf '%s\n' "$_otast_source"
}

_otast_normalize_record_mode() {
  case $1 in
    [0-7][0-7][0-7]) printf '0%s\n' "$1" ;;
    0[0-7][0-7][0-7]) printf '%s\n' "$1" ;;
    *) return 1 ;;
  esac
}

_otast_record_hash_valid() {
  case $1 in
    ''|*[!0-9a-f]*) return 1 ;;
  esac
  [ "${#1}" -eq 64 ]
}

_otast_validate_record() {
  local _otast_state _otast_expected_id _otast_expected_path _otast_line _otast_value
  local _otast_version _otast_id _otast_target _otast_path _otast_strategy
  local _otast_original_exists _otast_original_mode _otast_original_hash _otast_backup
  local _otast_managed_hash _otast_managed_mode _otast_authority
  local _otast_seen_version _otast_seen_id _otast_seen_target _otast_seen_path
  local _otast_seen_strategy _otast_seen_original_exists _otast_seen_original_mode
  local _otast_seen_original_hash _otast_seen_backup _otast_seen_managed_hash
  local _otast_seen_managed_mode _otast_seen_authority

  _otast_state=$1
  _otast_expected_id=$2
  _otast_expected_path=$3
  [ -f "$_otast_state" ] && [ ! -L "$_otast_state" ] || return 1

  _otast_seen_version=0
  _otast_seen_id=0
  _otast_seen_target=0
  _otast_seen_path=0
  _otast_seen_strategy=0
  _otast_seen_original_exists=0
  _otast_seen_original_mode=0
  _otast_seen_original_hash=0
  _otast_seen_backup=0
  _otast_seen_managed_hash=0
  _otast_seen_managed_mode=0
  _otast_seen_authority=0

  while IFS= read -r _otast_line || [ -n "$_otast_line" ]; do
    case "$_otast_line" in
      version=*)
        [ "$_otast_seen_version" -eq 0 ] || return 1
        _otast_version=${_otast_line#*=}
        _otast_seen_version=1
        ;;
      id=*)
        [ "$_otast_seen_id" -eq 0 ] || return 1
        _otast_id=${_otast_line#*=}
        _otast_seen_id=1
        ;;
      target=*)
        [ "$_otast_seen_target" -eq 0 ] || return 1
        _otast_target=${_otast_line#*=}
        _otast_seen_target=1
        ;;
      path=*)
        [ "$_otast_seen_path" -eq 0 ] || return 1
        _otast_path=${_otast_line#*=}
        _otast_seen_path=1
        ;;
      strategy=*)
        [ "$_otast_seen_strategy" -eq 0 ] || return 1
        _otast_strategy=${_otast_line#*=}
        _otast_seen_strategy=1
        ;;
      original_exists=*)
        [ "$_otast_seen_original_exists" -eq 0 ] || return 1
        _otast_original_exists=${_otast_line#*=}
        _otast_seen_original_exists=1
        ;;
      original_mode=*)
        [ "$_otast_seen_original_mode" -eq 0 ] || return 1
        _otast_original_mode=${_otast_line#*=}
        _otast_seen_original_mode=1
        ;;
      original_hash=*)
        [ "$_otast_seen_original_hash" -eq 0 ] || return 1
        _otast_original_hash=${_otast_line#*=}
        _otast_seen_original_hash=1
        ;;
      backup=*)
        [ "$_otast_seen_backup" -eq 0 ] || return 1
        _otast_backup=${_otast_line#*=}
        _otast_seen_backup=1
        ;;
      managed_hash=*)
        [ "$_otast_seen_managed_hash" -eq 0 ] || return 1
        _otast_managed_hash=${_otast_line#*=}
        _otast_seen_managed_hash=1
        ;;
      managed_mode=*)
        [ "$_otast_seen_managed_mode" -eq 0 ] || return 1
        _otast_managed_mode=${_otast_line#*=}
        _otast_seen_managed_mode=1
        ;;
      authority_sha256=*)
        [ "$_otast_seen_authority" -eq 0 ] || return 1
        _otast_authority=${_otast_line#*=}
        _otast_seen_authority=1
        ;;
      *) return 1 ;;
    esac
  done <"$_otast_state"

  for _otast_value in \
    "$_otast_seen_version" "$_otast_seen_id" "$_otast_seen_target" \
    "$_otast_seen_path" "$_otast_seen_strategy" "$_otast_seen_original_exists" \
    "$_otast_seen_original_mode" "$_otast_seen_original_hash" "$_otast_seen_backup" \
    "$_otast_seen_managed_hash" "$_otast_seen_managed_mode" "$_otast_seen_authority"; do
    [ "$_otast_value" -eq 1 ] || return 1
  done

  [ "$_otast_version" = 1 ] || return 1
  [ "$_otast_id" = "$_otast_expected_id" ] || return 1
  [ "$_otast_path" = "$_otast_expected_path" ] || return 1
  otast_id_valid "$_otast_id" || return 1
  otast_id_valid "$_otast_target" || return 1
  case "$_otast_strategy" in exact|external) ;; *) return 1 ;; esac
  case "$_otast_original_exists" in 0|1) ;; *) return 1 ;; esac

  _otast_managed_mode=$(_otast_normalize_record_mode "$_otast_managed_mode") || return 1
  _otast_record_hash_valid "$_otast_managed_hash" || return 1
  _otast_record_hash_valid "$_otast_authority" || return 1

  if [ "$_otast_original_exists" = 1 ]; then
    _otast_original_mode=$(_otast_normalize_record_mode "$_otast_original_mode") || return 1
    _otast_record_hash_valid "$_otast_original_hash" || return 1
  else
    [ "$_otast_original_mode" = 0000 ] || return 1
    [ "$_otast_original_hash" = MISSING ] || return 1
  fi

  [ "$_otast_backup" = "$OTAST_STATE_ROOT/backups/$_otast_id.original" ] || return 1
  otast_assert_under_adb_root "$_otast_path" || return 1
  return 0
}

_otast_classify_plan_item() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_id=$1
  _otast_path=$2
  _otast_mode=$3
  _otast_desired=$4
  _otast_strategy=$5
  _otast_allowed=$6
  OTAST_PREFLIGHT_ACTION=''
  _otast_state=$(_otast_state_path "$_otast_id") || return 1
  _otast_live=$(otast_live_hash "$_otast_path") || {
    otast_stop "target is not a safe regular file or missing path: $_otast_path"
    return 1
  }
  _otast_live_mode=0000
  [ "$_otast_live" = MISSING ] || _otast_live_mode=$(otast_file_mode "$_otast_path") || return 1

  if [ -e "$_otast_state" ]; then
    [ -f "$_otast_state" ] && [ ! -L "$_otast_state" ] || {
      otast_stop "managed state is unsafe: $_otast_state"
      return 1
    }
    _otast_validate_record "$_otast_state" "$_otast_id" "$_otast_path" || {
      otast_stop "managed state is malformed or mismatched: $_otast_state"
      return 1
    }
    _otast_managed=$(_otast_state_get "$_otast_state" managed_hash) || return 1
    _otast_managed_mode=$(_otast_state_get "$_otast_state" managed_mode) || return 1
    _otast_recorded_authority=$(_otast_state_get "$_otast_state" authority_sha256) || return 1
    if [ "$_otast_live" != "$_otast_managed" ] || [ "$_otast_live_mode" != "$_otast_managed_mode" ]; then
      otast_stop "managed target drift detected: $_otast_path"
      return 1
    fi
    if [ "$_otast_live" = "$_otast_desired" ] && [ "$_otast_live_mode" = "$_otast_mode" ] && [ "$_otast_recorded_authority" = "$OTAST_AUTHORITY_SHA256" ]; then
      OTAST_PREFLIGHT_ACTION=CURRENT
    else
      OTAST_PREFLIGHT_ACTION=UPDATE
    fi
    return 0
  fi

  case "$_otast_strategy" in
    exact)
      if [ "$_otast_live" = MISSING ]; then
        otast_stop "required exact-replacement file is missing: $_otast_path"
        return 1
      fi
      if ! otast_hash_allowed "$_otast_live" "$_otast_allowed"; then
        if [ "${OTAST_TEST_MODE:-0}" = 1 ] && otast_is_fake_root; then
          otast_log WARN "test fixture accepted for exact-replacement path: $_otast_path"
        else
          otast_stop "unsupported exact-replacement hash: $_otast_path ($_otast_live)"
          return 1
        fi
      fi
      ;;
    external)
      if [ "$_otast_live" != MISSING ] && [ "$_otast_live" = "$_otast_desired" ] && [ "$_otast_live_mode" = "$_otast_mode" ]; then
        OTAST_PREFLIGHT_ACTION=ADOPT
        return 0
      fi
      ;;
    *) return 1 ;;
  esac
  OTAST_PREFLIGHT_ACTION=NEW
  return 0
}

otast_plan_add() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_id=$(otast_safe_id "$1") || return 1
  _otast_target=$(otast_safe_id "$2") || return 1
  _otast_path=$3
  _otast_mode=$4
  _otast_source=$5
  _otast_strategy=$6
  _otast_allowed=$7
  otast_mode_valid "$_otast_mode" || return 1
  [ -f "$_otast_source" ] && [ ! -L "$_otast_source" ] || return 1
  otast_assert_no_symlink_path "$_otast_path" || return 1
  _otast_source_hash=$(otast_sha256 "$_otast_source") || return 1
  _otast_classify_plan_item "$_otast_id" "$_otast_path" "$_otast_mode" "$_otast_source_hash" "$_otast_strategy" "$_otast_allowed" || return 1
  if [ "$OTAST_PREFLIGHT_ACTION" = CURRENT ]; then
    return 0
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$_otast_id" "$_otast_target" "$_otast_path" "$_otast_mode" "$_otast_source" "$_otast_source_hash" "$_otast_strategy" "$OTAST_PREFLIGHT_ACTION" >>"$OTAST_PLAN" || return 1
  OTAST_PLAN_COUNT=$((OTAST_PLAN_COUNT + 1))
}

_otast_prepare_transaction() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_kind=$(otast_safe_id "$1") || return 1
  otast_ensure_dir "$OTAST_STATE_ROOT/transactions" || return 1
  _otast_attempt=0
  while [ "$_otast_attempt" -lt 50 ]; do
    OTAST_TX_DIR=$OTAST_STATE_ROOT/transactions/${_otast_kind}.$$.$_otast_attempt
    if mkdir "$OTAST_TX_DIR" 2>/dev/null; then
      chmod 0700 "$OTAST_TX_DIR" || return 1
      : >"$OTAST_TX_DIR/journal.tsv" || return 1
      chmod 0600 "$OTAST_TX_DIR/journal.tsv" || return 1
      printf 'IN_PROGRESS\n' >"$OTAST_TX_DIR/status" || return 1
      chmod 0600 "$OTAST_TX_DIR/status" || return 1
      return 0
    fi
    _otast_attempt=$((_otast_attempt + 1))
  done
  return 1
}

_otast_backup_before() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_id=$1
  _otast_path=$2
  _otast_before=$OTAST_TX_DIR/before.$_otast_id
  _otast_before_state=$OTAST_TX_DIR/state.$_otast_id
  _otast_state=$(_otast_state_path "$_otast_id") || return 1
  if [ -e "$_otast_path" ]; then
    [ -f "$_otast_path" ] && [ ! -L "$_otast_path" ] || return 1
    _otast_mode=$(otast_file_mode "$_otast_path") || return 1
    cat "$_otast_path" >"$_otast_before" || return 1
    chmod 0600 "$_otast_before" || return 1
    printf '1\t%s\n' "$_otast_mode" >"$OTAST_TX_DIR/before-meta.$_otast_id" || return 1
  else
    printf '0\t0000\n' >"$OTAST_TX_DIR/before-meta.$_otast_id" || return 1
  fi
  chmod 0600 "$OTAST_TX_DIR/before-meta.$_otast_id" || return 1
  if [ -f "$_otast_state" ] && [ ! -L "$_otast_state" ]; then
    cat "$_otast_state" >"$_otast_before_state" || return 1
    chmod 0600 "$_otast_before_state" || return 1
  fi
  printf '%s\t%s\n' "$_otast_id" "$_otast_path" >>"$OTAST_TX_DIR/journal.tsv" || return 1
}

_otast_persistent_original() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_id=$1
  _otast_path=$2
  _otast_state=$(_otast_state_path "$_otast_id") || return 1
  if [ -f "$_otast_state" ] && [ ! -L "$_otast_state" ]; then
    OTAST_ORIGINAL_EXISTS=$(_otast_state_get "$_otast_state" original_exists) || return 1
    OTAST_ORIGINAL_MODE=$(_otast_state_get "$_otast_state" original_mode) || return 1
    OTAST_ORIGINAL_HASH=$(_otast_state_get "$_otast_state" original_hash) || return 1
    OTAST_ORIGINAL_BACKUP=$(_otast_state_get "$_otast_state" backup) || return 1
    [ "$(_otast_state_get "$_otast_state" path)" = "$_otast_path" ] || return 1
    return 0
  fi
  otast_ensure_dir "$OTAST_STATE_ROOT/backups" || return 1
  OTAST_ORIGINAL_BACKUP=$OTAST_STATE_ROOT/backups/$_otast_id.original
  if [ -e "$_otast_path" ]; then
    [ -f "$_otast_path" ] && [ ! -L "$_otast_path" ] || return 1
    OTAST_ORIGINAL_EXISTS=1
    OTAST_ORIGINAL_MODE=$(otast_file_mode "$_otast_path") || return 1
    OTAST_ORIGINAL_HASH=$(otast_sha256 "$_otast_path") || return 1
    cat "$_otast_path" >"$OTAST_ORIGINAL_BACKUP" || return 1
    chmod 0600 "$OTAST_ORIGINAL_BACKUP" || return 1
  else
    OTAST_ORIGINAL_EXISTS=0
    OTAST_ORIGINAL_MODE=0000
    OTAST_ORIGINAL_HASH=MISSING
    : >"$OTAST_ORIGINAL_BACKUP" || return 1
    chmod 0600 "$OTAST_ORIGINAL_BACKUP" || return 1
  fi
}

_otast_apply_one() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_id=$1
  _otast_target=$2
  _otast_path=$3
  _otast_mode=$4
  _otast_source=$5
  _otast_source_hash=$6
  _otast_strategy=$7
  _otast_backup_before "$_otast_id" "$_otast_path" || return 1
  _otast_persistent_original "$_otast_id" "$_otast_path" || return 1
  otast_atomic_install "$_otast_source" "$_otast_path" "$_otast_mode" || return 1
  _otast_live=$(otast_sha256 "$_otast_path") || return 1
  _otast_live_mode=$(otast_file_mode "$_otast_path") || return 1
  [ "$_otast_live" = "$_otast_source_hash" ] && [ "$_otast_live_mode" = "$_otast_mode" ] || return 1
  _otast_write_state "$_otast_id" "$_otast_target" "$_otast_path" \
    "$OTAST_ORIGINAL_EXISTS" "$OTAST_ORIGINAL_MODE" "$OTAST_ORIGINAL_HASH" "$OTAST_ORIGINAL_BACKUP" \
    "$_otast_source_hash" "$_otast_mode" "$_otast_strategy" || return 1
  otast_log INFO "managed $_otast_target: $_otast_path"
}

_otast_reverse_journal() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_input=$1
  _otast_output=$2
  awk '{ lines[NR]=$0 } END { for (i=NR; i>=1; i--) print lines[i] }' "$_otast_input" >"$_otast_output"
}

_otast_rollback_transaction() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  [ -n "$OTAST_TX_DIR" ] && [ -f "$OTAST_TX_DIR/journal.tsv" ] || return 0
  _otast_reverse=$OTAST_TX_DIR/reverse.tsv
  _otast_reverse_journal "$OTAST_TX_DIR/journal.tsv" "$_otast_reverse" 2>/dev/null || return 1
  while IFS="$OTAST_TAB" read -r _otast_id _otast_path; do
    [ -n "$_otast_id" ] || continue
    otast_id_valid "$_otast_id" || return 1
    otast_assert_no_symlink_path "$_otast_path" || return 1
    _otast_meta=$OTAST_TX_DIR/before-meta.$_otast_id
    [ -f "$_otast_meta" ] || return 1
    _otast_exists=$(awk -F '\t' 'NR==1 {print $1}' "$_otast_meta" 2>/dev/null) || return 1
    _otast_mode=$(awk -F '\t' 'NR==1 {print $2}' "$_otast_meta" 2>/dev/null) || return 1
    if [ "$_otast_exists" = 1 ]; then
      otast_atomic_install "$OTAST_TX_DIR/before.$_otast_id" "$_otast_path" "$_otast_mode" || return 1
    elif [ "$_otast_exists" = 0 ]; then
      rm -f "$_otast_path" 2>/dev/null || return 1
    else
      return 1
    fi
    _otast_state=$(_otast_state_path "$_otast_id") || return 1
    if [ -f "$OTAST_TX_DIR/state.$_otast_id" ]; then
      otast_atomic_install "$OTAST_TX_DIR/state.$_otast_id" "$_otast_state" 0600 || return 1
    else
      rm -f "$_otast_state" 2>/dev/null || return 1
    fi
  done <"$_otast_reverse"
  printf 'ROLLED_BACK\n' >"$OTAST_TX_DIR/status" 2>/dev/null || :
  return 0
}

otast_apply_plan() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  [ -f "$OTAST_PLAN" ] || return 1
  if [ "$OTAST_PLAN_COUNT" -eq 0 ]; then
    otast_log INFO 'no target changes are required'
    return 0
  fi
  otast_acquire_lock || return 1
  _otast_prepare_transaction apply || {
    otast_release_lock
    return 1
  }
  _otast_failed=0
  while IFS="$OTAST_TAB" read -r _otast_id _otast_target _otast_path _otast_mode _otast_source _otast_source_hash _otast_strategy _otast_action; do
    [ -n "$_otast_id" ] || continue
    if ! _otast_apply_one "$_otast_id" "$_otast_target" "$_otast_path" "$_otast_mode" "$_otast_source" "$_otast_source_hash" "$_otast_strategy"; then
      otast_log ERROR "failed while applying operation: $_otast_id"
      _otast_failed=1
      break
    fi
  done <"$OTAST_PLAN"
  if [ "$_otast_failed" -ne 0 ]; then
    if _otast_rollback_transaction; then
      otast_log WARN 'failed transaction rolled back'
    else
      otast_log STOP "rollback failed; preserve evidence at $OTAST_TX_DIR"
    fi
    otast_release_lock
    return 1
  fi
  printf 'COMMITTED\n' >"$OTAST_TX_DIR/status" || {
    _otast_rollback_transaction
    otast_release_lock
    return 1
  }
  otast_release_lock
  return 0
}

otast_verify_managed() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_count _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  _otast_failed=0
  _otast_count=0
  if [ ! -d "$OTAST_STATE_ROOT/records" ]; then
    printf 'NO_MANAGED_STATE\n'
    return 0
  fi
  for _otast_state in "$OTAST_STATE_ROOT"/records/*.state; do
    [ -f "$_otast_state" ] || continue
    _otast_count=$((_otast_count + 1))
    _otast_id=$(_otast_state_get "$_otast_state" id) || { _otast_failed=1; continue; }
    _otast_path=$(_otast_state_get "$_otast_state" path) || { _otast_failed=1; continue; }
    if ! otast_id_valid "$_otast_id" || ! otast_assert_no_symlink_path "$_otast_path" || ! _otast_validate_record "$_otast_state" "$_otast_id" "$_otast_path"; then
      printf 'BROKEN_STATE	%s
' "$_otast_state"
      _otast_failed=1
      continue
    fi
    _otast_expected=$(_otast_state_get "$_otast_state" managed_hash) || { _otast_failed=1; continue; }
    _otast_mode=$(_otast_state_get "$_otast_state" managed_mode) || { _otast_failed=1; continue; }
    _otast_authority=$(_otast_state_get "$_otast_state" authority_sha256) || { _otast_failed=1; continue; }
    _otast_live=$(otast_live_hash "$_otast_path") || {
      printf 'BROKEN\t%s\t%s\n' "$_otast_id" "$_otast_path"
      _otast_failed=1
      continue
    }
    _otast_live_mode=$(otast_file_mode "$_otast_path" 2>/dev/null || printf 0000)
    if [ "$_otast_live" = "$_otast_expected" ] && [ "$_otast_live_mode" = "$_otast_mode" ] && [ "$_otast_authority" = "$OTAST_AUTHORITY_SHA256" ]; then
      printf 'CURRENT\t%s\t%s\n' "$_otast_id" "$_otast_path"
    else
      printf 'DRIFT\t%s\t%s\tlive=%s expected=%s mode=%s expected_mode=%s authority=%s current_authority=%s\n' \
        "$_otast_id" "$_otast_path" "$_otast_live" "$_otast_expected" "$_otast_live_mode" "$_otast_mode" "$_otast_authority" "$OTAST_AUTHORITY_SHA256"
      _otast_failed=1
    fi
  done
  if [ "$_otast_count" -eq 0 ]; then
    printf 'NO_MANAGED_STATE\n'
    return 0
  fi
  [ "$_otast_failed" -eq 0 ]
}

otast_restore_all() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  [ -d "$OTAST_STATE_ROOT/records" ] || {
    otast_log INFO 'nothing is managed'
    return 0
  }
  otast_acquire_lock || return 1
  _otast_prepare_transaction restore || {
    otast_release_lock
    return 1
  }
  _otast_failed=0
  for _otast_state in "$OTAST_STATE_ROOT"/records/*.state; do
    [ -f "$_otast_state" ] || continue
    _otast_id=$(_otast_state_get "$_otast_state" id) || { _otast_failed=1; break; }
    _otast_path=$(_otast_state_get "$_otast_state" path) || { _otast_failed=1; break; }
    if ! otast_id_valid "$_otast_id" || ! otast_assert_no_symlink_path "$_otast_path" || ! _otast_validate_record "$_otast_state" "$_otast_id" "$_otast_path"; then
      otast_log STOP "restore encountered malformed managed state: $_otast_state"
      _otast_failed=1
      break
    fi
    _otast_managed=$(_otast_state_get "$_otast_state" managed_hash) || { _otast_failed=1; break; }
    _otast_managed_mode=$(_otast_state_get "$_otast_state" managed_mode) || { _otast_failed=1; break; }
    _otast_original_exists=$(_otast_state_get "$_otast_state" original_exists) || { _otast_failed=1; break; }
    _otast_original_mode=$(_otast_state_get "$_otast_state" original_mode) || { _otast_failed=1; break; }
    _otast_backup=$(_otast_state_get "$_otast_state" backup) || { _otast_failed=1; break; }
    _otast_live=$(otast_live_hash "$_otast_path") || { _otast_failed=1; break; }
    _otast_live_mode=$(otast_file_mode "$_otast_path" 2>/dev/null || printf 0000)
    if [ "$_otast_live" != "$_otast_managed" ] || [ "$_otast_live_mode" != "$_otast_managed_mode" ]; then
      otast_log STOP "restore blocked by target drift: $_otast_path"
      _otast_failed=1
      break
    fi
    _otast_backup_before "$_otast_id" "$_otast_path" || { _otast_failed=1; break; }
    if [ "$_otast_original_exists" = 1 ]; then
      [ -f "$_otast_backup" ] && [ ! -L "$_otast_backup" ] || { _otast_failed=1; break; }
      _otast_backup_hash=$(otast_sha256 "$_otast_backup") || { _otast_failed=1; break; }
      _otast_recorded_original=$(_otast_state_get "$_otast_state" original_hash) || { _otast_failed=1; break; }
      [ "$_otast_backup_hash" = "$_otast_recorded_original" ] || { _otast_failed=1; break; }
      otast_atomic_install "$_otast_backup" "$_otast_path" "$_otast_original_mode" || { _otast_failed=1; break; }
    elif [ "$_otast_original_exists" = 0 ]; then
      rm -f "$_otast_path" || { _otast_failed=1; break; }
    else
      _otast_failed=1
      break
    fi
    rm -f "$_otast_state" || { _otast_failed=1; break; }
  done
  if [ "$_otast_failed" -ne 0 ]; then
    _otast_rollback_transaction || otast_log STOP "restore rollback failed; preserve $OTAST_TX_DIR"
    otast_release_lock
    return 1
  fi
  printf 'COMMITTED\n' >"$OTAST_TX_DIR/status" || {
    _otast_rollback_transaction
    otast_release_lock
    return 1
  }
  otast_release_lock
  return 0
}

otast_recover_transactions() {
  local _otast_action _otast_allowed _otast_attempt _otast_authority _otast_backup _otast_backup_hash _otast_before _otast_before_state _otast_desired _otast_exists _otast_expected _otast_failed _otast_file _otast_id _otast_input _otast_key _otast_kind _otast_live _otast_live_mode _otast_managed _otast_managed_hash _otast_managed_mode _otast_meta _otast_mode _otast_name _otast_original_exists _otast_original_hash _otast_original_mode _otast_output _otast_parent _otast_path _otast_plan_prefix _otast_recorded_authority _otast_recorded_hash _otast_recorded_mode _otast_recorded_original _otast_recovered _otast_reverse _otast_source _otast_source_hash _otast_state _otast_status _otast_strategy _otast_target _otast_tmp _otast_tx
  [ -d "$OTAST_STATE_ROOT/transactions" ] || return 0
  otast_acquire_lock || return 1
  _otast_recovered=0
  for _otast_tx in "$OTAST_STATE_ROOT"/transactions/*; do
    [ -d "$_otast_tx" ] && [ ! -L "$_otast_tx" ] || continue
    [ -f "$_otast_tx/status" ] && [ ! -L "$_otast_tx/status" ] || continue
    _otast_status=$(cat "$_otast_tx/status" 2>/dev/null) || continue
    case "$_otast_status" in COMMITTED|ROLLED_BACK) continue ;; IN_PROGRESS) ;; *) otast_release_lock; return 1 ;; esac
    [ -f "$_otast_tx/journal.tsv" ] && [ ! -L "$_otast_tx/journal.tsv" ] || {
      otast_release_lock
      return 1
    }
    OTAST_TX_DIR=$_otast_tx
    if _otast_rollback_transaction; then
      otast_log WARN "recovered interrupted transaction: $_otast_tx"
      _otast_recovered=$((_otast_recovered + 1))
    else
      otast_stop "cannot recover interrupted transaction: $_otast_tx"
      otast_release_lock
      return 1
    fi
  done
  otast_release_lock
  [ "$_otast_recovered" -eq 0 ] || otast_log INFO "recovered $_otast_recovered transaction(s)"
  return 0
}
