#!/system/bin/sh

# PIF provider dispatch. This layer is sourced after PR #41's accepted
# architecture-v2/pif-migration-v2 state machine. Inject-S deliberately keeps
# those functions unchanged. Exact Fork-v18 evidence installs provider-specific
# overrides without selecting or switching providers automatically.

OTAST_PIF_PROVIDER=NONE
OTAST_PIF_PROVIDER_ACTIVE=NONE
OTAST_PIF_PROVIDER_STAGED=NONE
OTAST_PIF_PROVIDER_CONFLICT=NONE
OTAST_PIF_FORK_AUTOPIF_BLOB=a0c3433ad5f89f0f8753a875ca28fb370ded0cfc
OTAST_PIF_FORK_BOUNDARY_BEGIN='# --- otast fork trickystore ownership BEGIN ---'
OTAST_PIF_FORK_BOUNDARY_END='# --- otast fork trickystore ownership END ---'

_otast_pif_provider_id_for_dir() {
  local dir prop digest
  dir=$1
  [ -d "$dir" ] && [ ! -L "$dir" ] || { printf 'NONE\n'; return 0; }
  if [ -e "$dir/remove" ] || [ -L "$dir/remove" ] || [ -e "$dir/disable" ] || [ -L "$dir/disable" ]; then
    printf 'NONE\n'
    return 0
  fi
  prop=$dir/module.prop
  [ -f "$prop" ] && [ ! -L "$prop" ] || { printf 'UNKNOWN\n'; return 0; }
  otast_assert_no_symlink_path "$prop" >/dev/null 2>&1 || { printf 'UNKNOWN\n'; return 0; }
  digest=$(otast_sha256 "$prop" 2>/dev/null) || { printf 'UNKNOWN\n'; return 0; }
  case "$digest" in
    95c5869147960b3689c2effc84dfbc68bedde7b8e22ae29a55ea17a4092ee80a) printf 'KOWX_INJECT_S\n' ;;
    59c698ce888105f09c248b11ccea3f545806c25b8b54ec2cda69c1d286f8e64b) printf 'OSM0SIS_FORK_V18\n' ;;
    *) printf 'UNKNOWN\n' ;;
  esac
}

_otast_pif_provider_detect_quiet() {
  OTAST_PIF_PROVIDER_ACTIVE=$(_otast_pif_provider_id_for_dir "$ADB_ROOT/modules/playintegrityfix") || return 1
  OTAST_PIF_PROVIDER_STAGED=$(_otast_pif_provider_id_for_dir "$ADB_ROOT/modules_update/playintegrityfix") || return 1
  OTAST_PIF_PROVIDER_CONFLICT=NONE
  case "$OTAST_PIF_PROVIDER_ACTIVE:$OTAST_PIF_PROVIDER_STAGED" in
    NONE:NONE) OTAST_PIF_PROVIDER=NONE ;;
    UNKNOWN:*|*:UNKNOWN) OTAST_PIF_PROVIDER=UNKNOWN ;;
    NONE:KOWX_INJECT_S|KOWX_INJECT_S:NONE|KOWX_INJECT_S:KOWX_INJECT_S) OTAST_PIF_PROVIDER=KOWX_INJECT_S ;;
    NONE:OSM0SIS_FORK_V18|OSM0SIS_FORK_V18:NONE|OSM0SIS_FORK_V18:OSM0SIS_FORK_V18) OTAST_PIF_PROVIDER=OSM0SIS_FORK_V18 ;;
    *)
      OTAST_PIF_PROVIDER=MIXED
      OTAST_PIF_PROVIDER_CONFLICT=$OTAST_PIF_PROVIDER_ACTIVE,$OTAST_PIF_PROVIDER_STAGED
      ;;
  esac
  return 0
}

otast_validate_pif_provider() {
  _otast_pif_provider_detect_quiet || return 1
  case "$OTAST_PIF_PROVIDER" in
    NONE|KOWX_INJECT_S|OSM0SIS_FORK_V18) return 0 ;;
    UNKNOWN)
      otast_stop 'playintegrityfix is effective but does not match a reviewed PIF provider identity'
      return 1
      ;;
    MIXED)
      otast_stop "active/staged playintegrityfix trees resolve to different providers: $OTAST_PIF_PROVIDER_CONFLICT; complete or remove the provider transition before OTAST Apply"
      return 1
      ;;
    *)
      otast_stop 'PIF provider detection entered an invalid state'
      return 1
      ;;
  esac
}

otast_report_pif_provider() {
  _otast_pif_provider_detect_quiet || return 1
  printf 'pif_provider=%s\n' "$OTAST_PIF_PROVIDER"
  printf 'pif_provider_active=%s\n' "$OTAST_PIF_PROVIDER_ACTIVE"
  printf 'pif_provider_staged=%s\n' "$OTAST_PIF_PROVIDER_STAGED"
  printf 'pif_provider_conflict=%s\n' "$OTAST_PIF_PROVIDER_CONFLICT"
  case "$OTAST_PIF_PROVIDER" in
    KOWX_INJECT_S) printf '%s\n' 'pif_provider_preference=SUPPORTED_PREFERRED' ;;
    OSM0SIS_FORK_V18) printf '%s\n' 'pif_provider_preference=SUPPORTED_CANDIDATE_PHYSICAL_QUALIFICATION_REQUIRED' ;;
    *) printf '%s\n' 'pif_provider_preference=UNAVAILABLE' ;;
  esac
}

_otast_git_blob_sha1() {
  local path size
  path=$1
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  size=$(wc -c <"$path" 2>/dev/null) || return 1
  case "$size" in ''|*[!0-9]*) return 1 ;; esac
  { printf 'blob %s\0' "$size"; cat "$path"; } | sha1sum | sed 's/[[:space:]].*$//'
}

_otast_pif_managed_live_matches() {
  local id path state managed managed_mode live live_mode
  id=$1
  path=$2
  state=$(_otast_state_path "$id") || return 1
  [ -f "$state" ] && [ ! -L "$state" ] || return 1
  otast_assert_no_symlink_path "$state" || return 1
  _otast_validate_record "$state" "$id" "$path" || return 1
  managed=$(_otast_state_get "$state" managed_hash) || return 1
  managed_mode=$(_otast_state_get "$state" managed_mode) || return 1
  live=$(otast_live_hash "$path") || return 1
  [ "$live" != MISSING ] || return 1
  live_mode=$(otast_file_mode "$path") || return 1
  [ "$live" = "$managed" ] && [ "$live_mode" = "$managed_mode" ]
}

otast_validate_pif_fork_prop_file() {
  local path size line clean key value seen entries fingerprint patch
  path=$1
  [ -f "$path" ] && [ ! -L "$path" ] || {
    otast_stop "Fork profile is not a safe regular file: $path"
    return 1
  }
  otast_assert_no_symlink_path "$path" || return 1
  size=$(wc -c <"$path" 2>/dev/null) || return 1
  case "$size" in ''|*[!0-9]*) return 1 ;; esac
  [ "$size" -gt 0 ] && [ "$size" -le 131072 ] || {
    otast_stop "Fork profile size is outside the supported range: $path"
    return 1
  }
  if LC_ALL=C grep -q "$(printf '\r')" "$path" 2>/dev/null || od -An -v -tx1 "$path" 2>/dev/null | grep -Eq '(^|[[:space:]])00([[:space:]]|$)'; then
    otast_stop "Fork profile contains unsupported control bytes: $path"
    return 1
  fi

  seen='|'
  entries=0
  fingerprint=''
  patch=''
  while IFS= read -r line || [ -n "$line" ]; do
    clean=$(printf '%s' "$line" | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//') || return 1
    case "$clean" in
      '') continue ;;
      *=*) ;;
      *) otast_stop "Fork profile contains a malformed line: $path"; return 1 ;;
    esac
    key=${clean%%=*}
    value=${clean#*=}
    case "$key" in
      ''|*[!A-Za-z0-9_.*-]*) otast_stop "Fork profile contains an invalid key: $path"; return 1 ;;
    esac
    case "$seen" in *"|$key|"*) otast_stop "Fork profile contains a duplicate key ($key): $path"; return 1 ;; esac
    seen="${seen}${key}|"
    entries=$((entries + 1))
    case "$key" in
      FINGERPRINT)
        [ -n "$value" ] || { otast_stop "Fork profile fingerprint is empty: $path"; return 1; }
        fingerprint=$value
        ;;
      SECURITY_PATCH)
        otast_valid_date "$value" || { otast_stop "Fork profile security patch is invalid: $path"; return 1; }
        patch=$value
        ;;
      spoofBuild|spoofProps|spoofProvider|spoofSignature|spoofVendingFinger|spoofVendingSdk)
        case "$value" in 0|1) ;; *) otast_stop "Fork profile switch $key is invalid: $path"; return 1 ;; esac
        ;;
      verboseLogs)
        case "$value" in 0|1|2|3|100) ;; *) otast_stop "Fork profile verboseLogs is invalid: $path"; return 1 ;; esac
        ;;
    esac
  done <"$path"
  [ "$entries" -gt 0 ] && [ -n "$fingerprint" ] && [ -n "$patch" ] || {
    otast_stop "Fork profile is missing required FINGERPRINT or SECURITY_PATCH: $path"
    return 1
  }
  return 0
}

_otast_transform_pif_fork_autopif4() {
  local source output line trimmed state depth inserted begin end
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  begin=$(grep -Fxc "$OTAST_PIF_FORK_BOUNDARY_BEGIN" "$source" 2>/dev/null || true)
  end=$(grep -Fxc "$OTAST_PIF_FORK_BOUNDARY_END" "$source" 2>/dev/null || true)
  if [ "$begin" -ne 0 ] || [ "$end" -ne 0 ]; then
    [ "$begin" -eq 1 ] && [ "$end" -eq 1 ] || return 1
    grep -Fq 'TS_SECPAT=' "$source" 2>/dev/null && return 1
    cat "$source" >"$output" || return 1
    chmod 0600 "$output" || return 1
    otast_shell_file_valid "$output"
    return $?
  fi

  : >"$output" || return 1
  state=0
  depth=0
  inserted=0
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed=$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//') || { rm -f "$output"; return 1; }
    if [ "$state" -eq 0 ]; then
      if [ "$trimmed" = 'elif [ -d "$TS_DIR" ]; then' ]; then
        printf '%s\n' "$line" >>"$output" || { rm -f "$output"; return 1; }
        cat >>"$output" <<'EOF_BOUNDARY'
    # --- otast fork trickystore ownership BEGIN ---
    # Fork owns profile generation; OTAST owns TrickyStore security_patch.txt.
    item "OTAST owns TrickyStore security_patch.txt; Fork patch mutation suppressed";
    :;
    # --- otast fork trickystore ownership END ---
EOF_BOUNDARY
        state=1
        depth=0
        inserted=$((inserted + 1))
      else
        printf '%s\n' "$line" >>"$output" || { rm -f "$output"; return 1; }
      fi
      continue
    fi

    case "$trimmed" in
      if\ *\;\ then)
        depth=$((depth + 1))
        ;;
      'fi;')
        if [ "$depth" -gt 0 ]; then
          depth=$((depth - 1))
        else
          printf '%s\n' "$line" >>"$output" || { rm -f "$output"; return 1; }
          state=0
        fi
        ;;
    esac
  done <"$source"

  [ "$state" -eq 0 ] && [ "$inserted" -eq 1 ] || { rm -f "$output"; return 1; }
  grep -Fq 'TS_SECPAT=' "$output" 2>/dev/null && { rm -f "$output"; return 1; }
  grep -Fq 'warn "TEESimulator v4.x/Oh My KeyMint must be configured manually' "$output" 2>/dev/null || { rm -f "$output"; return 1; }
  grep -Fq 'sh /data/adb/modules/playintegrityfix/killpi.sh' "$output" 2>/dev/null || { rm -f "$output"; return 1; }
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}

_otast_plan_transformed_git_blob() {
  local id target path mode expected transform actual source
  id=$1
  target=$2
  path=$3
  mode=$4
  expected=$5
  transform=$6
  [ -f "$path" ] && [ ! -L "$path" ] || {
    otast_stop "reviewed provider target is missing or unsafe: $path"
    return 1
  }
  otast_assert_no_symlink_path "$path" || return 1
  actual=$(_otast_git_blob_sha1 "$path") || return 1
  if [ "$actual" != "$expected" ]; then
    _otast_pif_managed_live_matches "$id" "$path" || {
      otast_stop "unreviewed provider writer bytes: $path"
      return 1
    }
  fi
  source=$OTAST_TMP_ROOT/source.$$.${id}
  "$transform" "$path" "$source" || {
    rm -f "$source" 2>/dev/null || :
    otast_stop "provider transformation failed: $path"
    return 1
  }
  chmod 0600 "$source" || return 1
  otast_plan_add "$id" "$target" "$path" "$mode" "$source" external ''
}

_otast_pif_fork_profile_path_for_dir() {
  printf '%s/custom.pif.prop\n' "$1"
}

_otast_fork_role_state_id() {
  case "$1:$2" in
    autopif4:active) printf 'pif-fork-autopif4-active\n' ;;
    autopif4:staged) printf 'pif-fork-autopif4-staged\n' ;;
    system-prop:active) printf 'pif-fork-system-prop-active\n' ;;
    system-prop:staged) printf 'pif-fork-system-prop-staged\n' ;;
    *) return 1 ;;
  esac
}

_otast_fork_role_target_path() {
  case "$1:$2" in
    autopif4:active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/autopif4.sh" ;;
    autopif4:staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/autopif4.sh" ;;
    system-prop:active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/system.prop" ;;
    system-prop:staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/system.prop" ;;
    *) return 1 ;;
  esac
}

_otast_fork_promotion_candidate() {
  local kind staged_id staged_path staged_state staged_dir active_id active_path active_state
  local managed managed_mode live live_mode
  kind=$1
  staged_id=$(_otast_fork_role_state_id "$kind" staged) || return 1
  staged_path=$(_otast_fork_role_target_path "$kind" staged) || return 1
  staged_state=$(_otast_state_path "$staged_id") || return 1
  [ -e "$staged_state" ] || return 1

  staged_dir=$ADB_ROOT/modules_update/playintegrityfix
  if [ -e "$staged_dir" ] || [ -L "$staged_dir" ]; then
    return 1
  fi
  _otast_pif_module_effective "$ADB_ROOT/modules/playintegrityfix" || {
    otast_stop "staged Fork state exists without an effective active module; cannot prove promotion: $staged_id"
    return 2
  }
  active_id=$(_otast_fork_role_state_id "$kind" active) || return 2
  active_path=$(_otast_fork_role_target_path "$kind" active) || return 2
  active_state=$(_otast_state_path "$active_id") || return 2
  otast_assert_no_symlink_path "$active_path" || return 2
  [ -f "$staged_state" ] && [ ! -L "$staged_state" ] && _otast_validate_record "$staged_state" "$staged_id" "$staged_path" || {
    otast_stop "staged Fork state is malformed while checking promotion: $staged_state"
    return 2
  }
  _otast_pif_state_backup_valid "$staged_state" || {
    otast_stop "staged Fork original backup is invalid while checking promotion: $staged_id"
    return 2
  }
  managed=$(_otast_state_get "$staged_state" managed_hash) || return 2
  managed_mode=$(_otast_state_get "$staged_state" managed_mode) || return 2
  live=$(otast_live_hash "$active_path") || return 2
  live_mode=0000
  [ "$live" = MISSING ] || live_mode=$(otast_file_mode "$active_path") || return 2
  if [ "$live" != "$managed" ] || [ "$live_mode" != "$managed_mode" ]; then
    otast_stop "staged Fork state disappeared without a provable Magisk promotion: $staged_id"
    return 2
  fi
  if [ -e "$active_state" ]; then
    [ -f "$active_state" ] && [ ! -L "$active_state" ] && _otast_validate_record "$active_state" "$active_id" "$active_path" || {
      otast_stop "active Fork state is malformed while checking promotion: $active_state"
      return 2
    }
    _otast_pif_state_backup_valid "$active_state" || {
      otast_stop "active Fork original backup is invalid while checking promotion: $active_id"
      return 2
    }
  fi
  return 0
}

_otast_fork_commit_one_promotion() {
  local kind staged_id staged_state active_id active_path active_state
  kind=$1
  _otast_fork_promotion_candidate "$kind"
  case $? in
    0) ;;
    1) return 0 ;;
    *) return 1 ;;
  esac
  staged_id=$(_otast_fork_role_state_id "$kind" staged) || return 1
  staged_state=$(_otast_state_path "$staged_id") || return 1
  active_id=$(_otast_fork_role_state_id "$kind" active) || return 1
  active_path=$(_otast_fork_role_target_path "$kind" active) || return 1
  active_state=$(_otast_state_path "$active_id") || return 1

  if [ -e "$active_state" ]; then
    _otast_pif_archive_state_generation "$active_id" pif-fork-role-promotion-v1 || return 1
  elif [ -e "$OTAST_STATE_ROOT/backups/$active_id.original" ] || [ -L "$OTAST_STATE_ROOT/backups/$active_id.original" ]; then
    otast_stop "orphaned active Fork backup blocks promotion: $active_id"
    return 1
  fi
  _otast_pif_copy_state_original_to_id "$staged_state" "$active_id" "$active_path" || return 1
  _otast_pif_archive_state_generation "$staged_id" pif-fork-role-promotion-v1 || return 1
  otast_log INFO "adopted Magisk staged-to-active Fork promotion for $kind"
}

# Detect once after the accepted PR #41 layers are loaded. Only exact Fork v18
# overrides those functions; Inject-S therefore retains the accepted state machine.
_otast_pif_provider_detect_quiet || return 1
if [ "$OTAST_PIF_PROVIDER" = OSM0SIS_FORK_V18 ]; then
  OTAST_PIF_ARCHITECTURE=fork-owned-profile-v1

  _otast_pif_select_canonical() {
    local active staged
    active=$(_otast_pif_fork_profile_path_for_dir "$ADB_ROOT/modules/playintegrityfix")
    staged=$(_otast_pif_fork_profile_path_for_dir "$ADB_ROOT/modules_update/playintegrityfix")
    OTAST_PIF_CANONICAL_PATH=''
    OTAST_PIF_CANONICAL_ROLE=UNAVAILABLE
    OTAST_PIF_CANONICAL_HASH=''
    if _otast_pif_module_effective "$ADB_ROOT/modules/playintegrityfix" && [ -f "$active" ] && [ ! -L "$active" ]; then
      OTAST_PIF_CANONICAL_PATH=$active
      OTAST_PIF_CANONICAL_ROLE=ACTIVE_CUSTOM
    elif _otast_pif_module_effective "$ADB_ROOT/modules_update/playintegrityfix" && [ -f "$staged" ] && [ ! -L "$staged" ]; then
      OTAST_PIF_CANONICAL_PATH=$staged
      OTAST_PIF_CANONICAL_ROLE=STAGED_CUSTOM
    else
      return 1
    fi
    OTAST_PIF_CANONICAL_HASH=$(otast_sha256 "$OTAST_PIF_CANONICAL_PATH") || return 1
  }

  otast_validate_pif_profiles_current() {
    local dir prop json found
    otast_validate_pif_provider || return 1
    found=0
    for dir in $(otast_effective_module_dirs playintegrityfix); do
      prop=$(_otast_pif_fork_profile_path_for_dir "$dir")
      json=$dir/custom.pif.json
      if [ ! -e "$prop" ] && [ ! -L "$prop" ]; then
        if [ -e "$json" ] || [ -L "$json" ]; then
          otast_stop "Fork v18 JSON-only profile is detected at $json; migrate it with upstream migrate.sh -p before OTAST Apply"
        else
          otast_stop "Fork v18 has no supported custom.pif.prop authority: $dir"
        fi
        return 1
      fi
      otast_validate_pif_fork_prop_file "$prop" || return 1
      if [ -e "$json" ] || [ -L "$json" ]; then
        [ -f "$json" ] && [ ! -L "$json" ] || { otast_stop "Fork JSON profile path is unsafe: $json"; return 1; }
        otast_assert_no_symlink_path "$json" || return 1
        otast_log INFO "Fork custom.pif.prop is authoritative ahead of sibling custom.pif.json: $dir"
      fi
      found=1
    done
    if [ "$found" -eq 1 ]; then
      _otast_pif_select_canonical || {
        otast_stop 'Fork v18 is installed but no canonical custom.pif.prop is available'
        return 1
      }
    else
      OTAST_PIF_CANONICAL_PATH=''
      OTAST_PIF_CANONICAL_ROLE=UNAVAILABLE
      OTAST_PIF_CANONICAL_HASH=''
    fi
  }

  _otast_pif_profile_relation() {
    local path hash
    path=$1
    if [ ! -e "$path" ] && [ ! -L "$path" ]; then printf 'ABSENT\n'; return 0; fi
    [ -f "$path" ] && [ ! -L "$path" ] || { printf 'UNSAFE\n'; return 0; }
    [ "$path" = "$OTAST_PIF_CANONICAL_PATH" ] && { printf 'SOURCE\n'; return 0; }
    hash=$(otast_sha256 "$path" 2>/dev/null) || { printf 'UNSAFE\n'; return 0; }
    if [ -n "$OTAST_PIF_CANONICAL_HASH" ] && [ "$hash" = "$OTAST_PIF_CANONICAL_HASH" ]; then
      printf 'PROVIDER_OWNED_EQUAL\n'
    else
      printf 'PROVIDER_OWNED_DIFFERENT\n'
    fi
  }

  otast_verify_pif_profile_coherence() {
    otast_validate_pif_profiles_current
  }

  otast_plan_pif() {
    local dir role source system_prop
    otast_validate_pif_profiles_current || return 1
    for dir in $(otast_effective_module_dirs playintegrityfix); do
      role=$(_otast_role_for_dir "$dir") || return 1
      _otast_plan_transformed_git_blob pif-fork-autopif4-$role playintegrityfix "$dir/autopif4.sh" 0755 \
        "$OTAST_PIF_FORK_AUTOPIF_BLOB" _otast_transform_pif_fork_autopif4 || return 1

      system_prop=$dir/system.prop
      if [ -e "$system_prop" ] || [ -L "$system_prop" ]; then
        [ -f "$system_prop" ] && [ ! -L "$system_prop" ] || {
          otast_stop "stale Fork system.prop path is unsafe: $system_prop"
          return 1
        }
        source=$(otast_plan_source_text pif-fork-system-prop-$role <<'EOF_EMPTY_PROP'
# OTAST: stale provider system.prop neutralized; platform SPL authority is OTAST-owned.
EOF_EMPTY_PROP
) || return 1
        otast_plan_add pif-fork-system-prop-$role playintegrityfix "$system_prop" 0644 "$source" external '' || return 1
      fi
    done
  }

  otast_pif_inspect_role_transitions() {
    local kind rc
    OTAST_PIF_PENDING_PROMOTIONS=0
    for kind in autopif4 system-prop; do
      _otast_fork_promotion_candidate "$kind"
      rc=$?
      case "$rc" in
        0) OTAST_PIF_PENDING_PROMOTIONS=$((OTAST_PIF_PENDING_PROMOTIONS + 1)) ;;
        1) ;;
        *) return 1 ;;
      esac
    done
    return 0
  }

  otast_pif_commit_role_transitions() {
    [ "${OTAST_LOCK_HELD:-0}" = 1 ] || {
      otast_stop 'Fork provider transition commit requires the OTAST Apply/Restore lock'
      return 1
    }
    otast_pif_inspect_role_transitions || return 1
    _otast_fork_commit_one_promotion autopif4 || return 1
    _otast_fork_commit_one_promotion system-prop || return 1
    OTAST_PIF_PENDING_PROMOTIONS=0
  }

  otast_pif_prepare_v2_mirror_state() {
    [ "${OTAST_LOCK_HELD:-0}" = 1 ] || {
      otast_stop 'Fork provider state preparation requires the OTAST Apply lock'
      return 1
    }
    return 0
  }

  otast_pif_inspect_legacy_profile_state() {
    local id state
    OTAST_PIF_PENDING_RETIREMENTS=0
    otast_pif_inspect_role_transitions || return 1
    for id in \
      pif-global-prop pif-prop-active pif-prop-staged \
      pif-mirror-active pif-mirror-staged pif-security-patch-active pif-security-patch-staged \
      pif-autopif-active pif-autopif-staged pif-autopif-ota-active pif-autopif-ota-staged \
      pif-runtime-system-prop-active pif-runtime-system-prop-staged; do
      state=$(_otast_state_path "$id") || return 1
      [ -e "$state" ] || continue
      [ -f "$state" ] && [ ! -L "$state" ] || {
        otast_stop "prior PIF ownership state is unsafe during Fork transition: $state"
        return 1
      }
      OTAST_PIF_PENDING_RETIREMENTS=$((OTAST_PIF_PENDING_RETIREMENTS + 1))
    done
    return 0
  }

  otast_pif_retire_legacy_profile_state() {
    local id state
    [ "${OTAST_LOCK_HELD:-0}" = 1 ] || {
      otast_stop 'Fork provider ownership retirement requires the OTAST lock'
      return 1
    }
    otast_pif_inspect_legacy_profile_state || return 1
    OTAST_PIF_RETIRED_COUNT=0
    for id in \
      pif-global-prop pif-prop-active pif-prop-staged \
      pif-mirror-active pif-mirror-staged pif-security-patch-active pif-security-patch-staged \
      pif-autopif-active pif-autopif-staged pif-autopif-ota-active pif-autopif-ota-staged \
      pif-runtime-system-prop-active pif-runtime-system-prop-staged; do
      state=$(_otast_state_path "$id") || return 1
      [ -e "$state" ] || continue
      _otast_pif_archive_state_generation "$id" pif-provider-transition-v1 || return 1
    done
    OTAST_PIF_PENDING_RETIREMENTS=0
    [ "$OTAST_PIF_RETIRED_COUNT" -eq 0 ] || \
      otast_log INFO "retired $OTAST_PIF_RETIRED_COUNT Inject-S ownership generation(s) after exact Fork-v18 provider transition"
  }
fi
