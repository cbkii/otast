#!/system/bin/sh

# Effective PIF/runtime ownership policy. Sourced after pif.sh, policy.sh and
# profiles.sh so these definitions intentionally replace the v1 implementations
# while preserving their migration/Restore helpers and the transaction engine.

OTAST_PIF_ARCHITECTURE=canonical-mirror-v2
OTAST_PIF_CANONICAL_PATH=''
OTAST_PIF_CANONICAL_ROLE=UNAVAILABLE
OTAST_PIF_CANONICAL_HASH=''
OTAST_PIF_PENDING_RETIREMENTS=0
OTAST_PIF_RETIRED_COUNT=0

_otast_pif_profile_state() {
  local path
  path=$1
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    printf 'ABSENT\n'
  elif otast_validate_pif_profile_file "$path" >/dev/null 2>&1; then
    printf 'PRESENT\n'
  else
    printf 'UNSAFE\n'
  fi
}

_otast_pif_select_canonical() {
  local global active staged
  global=$ADB_ROOT/pif.prop
  active=$ADB_ROOT/modules/playintegrityfix/pif.prop
  staged=$ADB_ROOT/modules_update/playintegrityfix/pif.prop
  OTAST_PIF_CANONICAL_PATH=''
  OTAST_PIF_CANONICAL_ROLE=UNAVAILABLE
  OTAST_PIF_CANONICAL_HASH=''
  if [ -f "$global" ] && [ ! -L "$global" ]; then
    OTAST_PIF_CANONICAL_PATH=$global; OTAST_PIF_CANONICAL_ROLE=GLOBAL_CUSTOM
  elif [ -f "$active" ] && [ ! -L "$active" ]; then
    OTAST_PIF_CANONICAL_PATH=$active; OTAST_PIF_CANONICAL_ROLE=ACTIVE_FALLBACK
  elif [ -f "$staged" ] && [ ! -L "$staged" ]; then
    OTAST_PIF_CANONICAL_PATH=$staged; OTAST_PIF_CANONICAL_ROLE=STAGED_FALLBACK
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
    otast_validate_pif_profile_file "$global" || return 1
  fi
  for module in "$ADB_ROOT/modules/playintegrityfix" "$ADB_ROOT/modules_update/playintegrityfix"; do
    [ -e "$module" ] || [ -L "$module" ] || continue
    [ -d "$module" ] && [ ! -L "$module" ] || {
      otast_stop "PIF module directory is unsafe: $module"; return 1;
    }
    otast_validate_pif_profile_file "$module/pif.prop" || return 1
    found=1
  done
  if [ "$found" -eq 1 ]; then
    _otast_pif_select_canonical || {
      otast_stop 'PIF is installed but no valid canonical profile is available'; return 1;
    }
  else
    OTAST_PIF_CANONICAL_PATH=''; OTAST_PIF_CANONICAL_ROLE=UNAVAILABLE; OTAST_PIF_CANONICAL_HASH=''
  fi
}

_otast_pif_profile_relation() {
  local path hash
  path=$1
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then printf 'ABSENT\n'; return 0; fi
  if [ ! -f "$path" ] || [ -L "$path" ]; then printf 'UNSAFE\n'; return 0; fi
  if [ "$path" = "$OTAST_PIF_CANONICAL_PATH" ]; then printf 'SOURCE\n'; return 0; fi
  hash=$(otast_sha256 "$path" 2>/dev/null) || { printf 'UNSAFE\n'; return 0; }
  if [ -n "$OTAST_PIF_CANONICAL_HASH" ] && [ "$hash" = "$OTAST_PIF_CANONICAL_HASH" ]; then
    printf 'MIRROR_CURRENT\n'
  else
    printf 'MIRROR_UPDATE_REQUIRED\n'
  fi
}

otast_verify_pif_profile_coherence() {
  local dir relation
  otast_validate_pif_profiles_current || return 1
  [ -n "$OTAST_PIF_CANONICAL_PATH" ] || return 0
  for dir in $(otast_effective_module_dirs playintegrityfix); do
    relation=$(_otast_pif_profile_relation "$dir/pif.prop") || return 1
    case "$relation" in
      SOURCE|MIRROR_CURRENT) ;;
      MIRROR_UPDATE_REQUIRED)
        otast_stop "PIF fallback profile is not synchronized with canonical profile: $dir/pif.prop; run explicit Apply"; return 1 ;;
      *) otast_stop "PIF fallback profile is unavailable or unsafe: $dir/pif.prop"; return 1 ;;
    esac
  done
}

_otast_pif_deprecated_path() {
  case $1 in
    pif-autopif-active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/autopif.sh" ;;
    pif-autopif-staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/autopif.sh" ;;
    pif-autopif-ota-active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/autopif_ota.sh" ;;
    pif-autopif-ota-staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/autopif_ota.sh" ;;
    pif-runtime-system-prop-active) printf '%s\n' "$ADB_ROOT/modules/playintegrityfix/system.prop" ;;
    pif-runtime-system-prop-staged) printf '%s\n' "$ADB_ROOT/modules_update/playintegrityfix/system.prop" ;;
    *) return 1 ;;
  esac
}

_otast_pif_retire_record() {
  local id category state dir dst a b
  id=$1; category=$2
  state=$(_otast_state_path "$id") || return 1
  [ -e "$state" ] || return 0
  dir=$OTAST_STATE_ROOT/retired/$category
  otast_ensure_dir "$dir" || return 1
  dst=$dir/$id.state
  if [ -e "$dst" ]; then
    [ -f "$dst" ] && [ ! -L "$dst" ] || { otast_stop "retired PIF state is unsafe: $dst"; return 1; }
    a=$(otast_sha256 "$state") || return 1; b=$(otast_sha256 "$dst") || return 1
    [ "$a" = "$b" ] || { otast_stop "retired PIF state conflicts with active state: $id"; return 1; }
    rm -f "$state" || return 1
  else
    mv "$state" "$dst" || return 1; chmod 0600 "$dst" || return 1
  fi
  OTAST_PIF_RETIRED_COUNT=$((OTAST_PIF_RETIRED_COUNT + 1))
}

_otast_pif_restore_deprecated_writer() {
  local id path state original_exists original_mode original_hash backup managed_hash live live_mode temp
  id=$1; path=$(_otast_pif_deprecated_path "$id") || return 1
  state=$(_otast_state_path "$id") || return 1
  [ -e "$state" ] || return 0
  [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
    otast_stop "deprecated PIF writer state is malformed or mismatched: $state"; return 1;
  }
  original_exists=$(_otast_state_get "$state" original_exists) || return 1
  original_mode=$(_otast_state_get "$state" original_mode) || return 1
  original_hash=$(_otast_state_get "$state" original_hash) || return 1
  backup=$(_otast_state_get "$state" backup) || return 1
  managed_hash=$(_otast_state_get "$state" managed_hash) || return 1
  live=$(otast_live_hash "$path") || return 1; live_mode=0000
  [ "$live" = MISSING ] || live_mode=$(otast_file_mode "$path") || return 1
  if [ "$original_exists" = 1 ]; then
    [ -f "$backup" ] && [ ! -L "$backup" ] && [ "$(otast_sha256 "$backup")" = "$original_hash" ] || {
      otast_stop "deprecated PIF writer original backup is missing or invalid: $id"; return 1;
    }
    if [ "$live" = "$managed_hash" ]; then
      temp=${path}.otast-retire.$$
      cat "$backup" >"$temp" || { rm -f "$temp"; return 1; }
      chmod "$original_mode" "$temp" || { rm -f "$temp"; return 1; }
      mv -f "$temp" "$path" || { rm -f "$temp"; return 1; }
    elif [ "$live" != "$original_hash" ] || [ "$live_mode" != "$original_mode" ]; then
      otast_stop "deprecated PIF writer drift blocks ownership retirement: $path"; return 1
    fi
  else
    if [ "$live" = "$managed_hash" ]; then rm -f "$path" || return 1
    elif [ "$live" != MISSING ]; then otast_stop "deprecated generated PIF writer drift blocks ownership retirement: $path"; return 1
    fi
  fi
  _otast_pif_retire_record "$id" pif-writer-ownership-v2
}

_otast_pif_source_mirror_state() {
  OTAST_PIF_SOURCE_MIRROR_ID=''
  OTAST_PIF_SOURCE_MIRROR_PATH=''
  case "$OTAST_PIF_CANONICAL_ROLE" in
    ACTIVE_FALLBACK)
      OTAST_PIF_SOURCE_MIRROR_ID=pif-mirror-active
      OTAST_PIF_SOURCE_MIRROR_PATH=$ADB_ROOT/modules/playintegrityfix/pif.prop
      ;;
    STAGED_FALLBACK)
      OTAST_PIF_SOURCE_MIRROR_ID=pif-mirror-staged
      OTAST_PIF_SOURCE_MIRROR_PATH=$ADB_ROOT/modules_update/playintegrityfix/pif.prop
      ;;
    *) return 1 ;;
  esac
}

otast_pif_inspect_legacy_profile_state() {
  local id state path
  OTAST_PIF_PENDING_RETIREMENTS=0
  for id in pif-global-prop pif-prop-active pif-prop-staged; do
    state=$(_otast_state_path "$id") || return 1; [ -e "$state" ] || continue
    otast_pif_validate_legacy_state_one "$id" || return 1
    OTAST_PIF_PENDING_RETIREMENTS=$((OTAST_PIF_PENDING_RETIREMENTS + 1))
  done
  for id in pif-autopif-active pif-autopif-staged pif-autopif-ota-active pif-autopif-ota-staged pif-runtime-system-prop-active pif-runtime-system-prop-staged; do
    state=$(_otast_state_path "$id") || return 1; [ -e "$state" ] || continue
    path=$(_otast_pif_deprecated_path "$id") || return 1
    [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
      otast_stop "deprecated PIF writer state is malformed or mismatched: $state"; return 1;
    }
    OTAST_PIF_PENDING_RETIREMENTS=$((OTAST_PIF_PENDING_RETIREMENTS + 1))
  done
  _otast_pif_source_mirror_state 2>/dev/null || return 0
  id=$OTAST_PIF_SOURCE_MIRROR_ID; path=$OTAST_PIF_SOURCE_MIRROR_PATH; state=$(_otast_state_path "$id") || return 1
  [ -e "$state" ] || return 0
  [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
    otast_stop "canonical PIF source has invalid mirror ownership state: $state"; return 1;
  }
  OTAST_PIF_PENDING_RETIREMENTS=$((OTAST_PIF_PENDING_RETIREMENTS + 1))
}

otast_pif_retire_legacy_profile_state() {
  local id state path managed live
  otast_pif_inspect_legacy_profile_state || return 1
  OTAST_PIF_RETIRED_COUNT=0
  for id in pif-global-prop pif-prop-active pif-prop-staged; do
    state=$(_otast_state_path "$id") || return 1; [ -e "$state" ] || continue
    _otast_pif_retire_record "$id" pif-profile-ownership-v1 || return 1
  done
  for id in pif-autopif-active pif-autopif-staged pif-autopif-ota-active pif-autopif-ota-staged pif-runtime-system-prop-active pif-runtime-system-prop-staged; do
    _otast_pif_restore_deprecated_writer "$id" || return 1
  done
  if _otast_pif_source_mirror_state 2>/dev/null; then
    id=$OTAST_PIF_SOURCE_MIRROR_ID; path=$OTAST_PIF_SOURCE_MIRROR_PATH; state=$(_otast_state_path "$id") || return 1
    if [ -e "$state" ]; then
      managed=$(_otast_state_get "$state" managed_hash) || return 1; live=$(otast_live_hash "$path") || return 1
      [ "$live" = "$managed" ] || { otast_stop "PIF mirror drift blocks promotion to canonical source: $path"; return 1; }
      _otast_pif_retire_record "$id" pif-mirror-source-v1 || return 1
    fi
  fi
  OTAST_PIF_PENDING_RETIREMENTS=0
  [ "$OTAST_PIF_RETIRED_COUNT" -eq 0 ] || otast_log INFO "retired $OTAST_PIF_RETIRED_COUNT superseded PIF ownership record(s)"
}

# Suppress only the two competing write domains in PIF's security-patch helper.
# Marker enable/disable and profile selection/validation remain upstream flow.
otast_transform_pif_security_patch() {
  local source output line trimmed state depth begin end seen_domain seen_system seen_reset
  source=$1; output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  begin=$(grep -Fxc '# --- otast pif patch-domain boundary BEGIN ---' "$source" 2>/dev/null || true)
  end=$(grep -Fxc '# --- otast pif patch-domain boundary END ---' "$source" 2>/dev/null || true)
  if [ "$begin" -ne 0 ] || [ "$end" -ne 0 ]; then
    [ "$begin" -eq 1 ] && [ "$end" -eq 1 ] || return 1
    cat "$source" >"$output" || return 1; chmod 0600 "$output" || return 1; otast_shell_file_valid "$output"; return $?
  fi
  : >"$output" || return 1
  state=0; depth=0; seen_domain=0; seen_system=0; seen_reset=0
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed=$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//') || { rm -f "$output"; return 1; }
    case "$state" in
      0)
        case "$trimmed" in
          '--disable) rm -f "$AUTO_FLAG" "$MODDIR/system.prop"; exit;;')
            printf '%s\n' '    --disable) rm -f "$AUTO_FLAG"; rm -f "$MODDIR/system.prop"; exit;;' >>"$output" || return 1 ;;
          'if [ "$FILE_NAME" = "security_patch.txt" ]; then')
            cat >>"$output" <<'BOUNDARY'
# --- otast pif patch-domain boundary BEGIN ---
# Profile metadata remains PIF-owned; platform and TrickyStore patch state do not.
if [ "$FILE_NAME" = "security_patch.txt" ] || [ "$FILE_NAME" = "devconfig.toml" ]; then
    echo "[OTAST] PIF profile patch retained; competing TrickyStore writer suppressed"
fi
# --- otast pif patch-domain boundary END ---
BOUNDARY
            state=1; depth=1; seen_domain=1 ;;
          'cat << EOF > $MODDIR/system.prop')
            printf '%s\n' '# OTAST: profile-derived PIF system.prop write suppressed.' >>"$output" || return 1
            state=2; seen_system=1 ;;
          'PROPS="ro.build.version.security_patch ro.vendor.build.security_patch"')
            printf '%s\n' '# OTAST: profile-derived resetprop writes suppressed.' >>"$output" || return 1
            state=3; seen_reset=1 ;;
          'if resetprop --help | grep "compact" > /dev/null; then')
            printf '%s\n' '# OTAST: profile-derived resetprop writes suppressed.' >>"$output" || return 1
            state=4; depth=1; seen_reset=1 ;;
          *) printf '%s\n' "$line" >>"$output" || return 1 ;;
        esac ;;
      1)
        case "$trimmed" in
          if\ *|if\[* ) depth=$((depth + 1)) ;;
          fi) depth=$((depth - 1)); [ "$depth" -gt 0 ] || state=0 ;;
        esac ;;
      2) [ "$trimmed" = EOF ] && state=0 ;;
      3) : ;;
      4)
        case "$trimmed" in
          if\ *|if\[* ) depth=$((depth + 1)) ;;
          fi) depth=$((depth - 1)); [ "$depth" -gt 0 ] || state=0 ;;
        esac ;;
    esac
  done <"$source"
  [ "$seen_domain" -eq 1 ] && [ "$seen_system" -eq 1 ] && [ "$seen_reset" -eq 1 ] || { rm -f "$output"; return 1; }
  case "$state" in 0|3) ;; *) rm -f "$output"; return 1 ;; esac
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}

_otast_v2_plan_security_patch() {
  local role path id state allowed backup original live managed managed_mode live_mode source
  role=$1; path=$2; id=pif-security-patch-$role
  allowed='a21fa1444ad870ad2ba09cb2a45a0576361df6062369d13f05fbf0db78f29476,f24517231c21856c4603f14e9d1ad8d38af5e6753a8060837320e66337ed5012'
  state=$(_otast_state_path "$id") || return 1
  if [ ! -e "$state" ]; then
    _otast_plan_transformed_file "$id" playintegrityfix "$path" 0755 otast_transform_pif_security_patch "$allowed"; return $?
  fi
  [ -f "$state" ] && [ ! -L "$state" ] && _otast_validate_record "$state" "$id" "$path" || {
    otast_stop "managed PIF security-patch state is unsafe or mismatched: $state"; return 1;
  }
  managed=$(_otast_state_get "$state" managed_hash) || return 1; managed_mode=$(_otast_state_get "$state" managed_mode) || return 1
  live=$(otast_live_hash "$path") || return 1; live_mode=$(otast_file_mode "$path") || return 1
  [ "$live" = "$managed" ] && [ "$live_mode" = "$managed_mode" ] || { otast_stop "managed target drift detected: $path"; return 1; }
  backup=$(_otast_state_get "$state" backup) || return 1; original=$(_otast_state_get "$state" original_hash) || return 1
  [ -f "$backup" ] && [ ! -L "$backup" ] && [ "$(otast_sha256 "$backup")" = "$original" ] || { otast_stop "PIF security-patch original backup is invalid: $path"; return 1; }
  otast_hash_allowed "$original" "$allowed" || { otast_stop "PIF security-patch original is outside reviewed hashes: $path ($original)"; return 1; }
  source=$OTAST_TMP_ROOT/source.$$.${id}
  otast_transform_pif_security_patch "$backup" "$source" || { rm -f "$source" 2>/dev/null || :; return 1; }
  chmod 0600 "$source" || return 1
  otast_plan_add "$id" playintegrityfix "$path" 0755 "$source" exact "$allowed"
}

otast_plan_pif() {
  local dir role source
  otast_validate_pif_profiles_current || return 1
  [ -n "$OTAST_PIF_CANONICAL_PATH" ] || return 0
  if [ -e "$ADB_ROOT/tricky_store/pif_auto_security_patch" ] || [ -L "$ADB_ROOT/tricky_store/pif_auto_security_patch" ]; then
    [ -f "$ADB_ROOT/tricky_store/pif_auto_security_patch" ] && [ ! -L "$ADB_ROOT/tricky_store/pif_auto_security_patch" ] || { otast_stop 'PIF automatic security-patch flag is not a safe regular file'; return 1; }
    otast_log WARN 'PIF auto-security-patch marker is enabled; marker is preserved while profile-derived platform/TrickyStore writes are suppressed'
  fi
  for dir in $(otast_effective_module_dirs playintegrityfix); do
    role=$(_otast_role_for_dir "$dir") || return 1
    _otast_v2_plan_security_patch "$role" "$dir/security_patch.sh" || return 1
    if [ "$dir/pif.prop" != "$OTAST_PIF_CANONICAL_PATH" ]; then
      source=$(otast_plan_source_file "pif-mirror-$role" "$OTAST_PIF_CANONICAL_PATH") || return 1
      otast_plan_add "pif-mirror-$role" playintegrityfix "$dir/pif.prop" 0644 "$source" external '' || return 1
    fi
  done
}

# OTAST owns installed platform SPL presentation only. Verified-boot state is
# evidence; it is not normalized to locked/green/enforcing by this layer.
otast_plan_strict_runtime_identity() {
  local source path
  case "$MODDIR" in */runtime) path=${MODDIR%/runtime}/system.prop ;; *) otast_stop "unexpected OTAST runtime directory: $MODDIR"; return 1 ;; esac
  source=$(otast_plan_source_text otast-runtime-system-prop <<EOF
# OTAST-managed installed-platform security-patch identity.
ro.build.version.security_patch=$OTAST_SYSTEM_PATCH
ro.vendor.build.security_patch=$OTAST_VENDOR_PATCH
EOF
) || return 1
  _otast_plan_self_runtime_system_prop "$source" "$path"
}

_otast_v2_boot_error_present() {
  case ${1:-} in ''|0|none|NONE|false|FALSE) return 1 ;; *) return 0 ;; esac
}

otast_verify_boot_presentation_consistency() {
  local state error part
  state=$(otast_live_value ro.boot.verifiedbootstate 2>/dev/null) || state=''
  error=$(otast_live_value ro.boot.verifiedbooterror 2>/dev/null) || error=''
  part=$(otast_live_value ro.boot.verifyerrorpart 2>/dev/null) || part=''
  if [ "$state" = green ] && { _otast_v2_boot_error_present "$error" || _otast_v2_boot_error_present "$part"; }; then
    otast_stop "contradictory verified-boot presentation: state=green while verification error evidence remains (error=${error:-MISSING}, part=${part:-MISSING})"
    return 1
  fi
}

otast_compare_live_strict_runtime_identity() {
  _otast_compare_live_pairs 'live OTA security-patch contract differs from authority; reboot after Apply before Verify' \
    'ro.build.version.security_patch:OTAST_SYSTEM_PATCH' 'ro.vendor.build.security_patch:OTAST_VENDOR_PATCH' || return 1
  otast_verify_boot_presentation_consistency || return 1
  otast_verify_pif_profile_coherence
}

_otast_pif_report_value() {
  local key value
  key=$1; value=UNAVAILABLE
  [ -z "$OTAST_PIF_CANONICAL_PATH" ] || value=$(otast_kv_value "$OTAST_PIF_CANONICAL_PATH" "$key" 2>/dev/null) || value=UNAVAILABLE
  printf 'pif_profile_%s=%s\n' "$key" "$value"
}

otast_report_pif_profile() {
  local global active staged requested ownership
  global=$ADB_ROOT/pif.prop; active=$ADB_ROOT/modules/playintegrityfix/pif.prop; staged=$ADB_ROOT/modules_update/playintegrityfix/pif.prop
  otast_validate_pif_profiles_current >/dev/null 2>&1 || :
  printf 'pif_profile_architecture=%s\n' "$OTAST_PIF_ARCHITECTURE"
  printf '%s\n' 'pif_profile_precedence=GLOBAL_CUSTOM>ACTIVE_FALLBACK>STAGED_FALLBACK'
  printf 'pif_global_profile_state=%s\n' "$(_otast_pif_profile_state "$global")"
  printf 'pif_active_profile_state=%s\n' "$(_otast_pif_profile_state "$active")"
  printf 'pif_staged_profile_state=%s\n' "$(_otast_pif_profile_state "$staged")"
  printf 'pif_canonical_profile_path=%s\n' "${OTAST_PIF_CANONICAL_PATH:-UNAVAILABLE}"
  printf 'pif_canonical_profile_role=%s\n' "$OTAST_PIF_CANONICAL_ROLE"
  printf 'pif_active_profile_relation=%s\n' "$(_otast_pif_profile_relation "$active")"
  printf 'pif_staged_profile_relation=%s\n' "$(_otast_pif_profile_relation "$staged")"
  _otast_pif_report_value FINGERPRINT; _otast_pif_report_value MODEL; _otast_pif_report_value SECURITY_PATCH; _otast_pif_report_value spoofProps
  printf '%s\n' 'pif_autopif_lifecycle=UPSTREAM_PRESERVED'
  printf '%s\n' 'pif_autopif_self_update_policy=UPSTREAM_PRESERVED'
  printf '%s\n' 'pif_security_patch_writer_policy=OTAST_SURGICAL_PATCH_DOMAIN_BOUNDARY'
  if [ -f "$ADB_ROOT/tricky_store/pif_auto_security_patch" ] && [ ! -L "$ADB_ROOT/tricky_store/pif_auto_security_patch" ]; then requested=true; else requested=false; fi
  printf 'pif_auto_security_patch_requested=%s\n' "$requested"
  printf '%s\n' 'pif_auto_security_patch_effective_policy=MARKER_PRESERVED_WRITES_SUPPRESSED'
  if [ "${OTAST_PIF_PENDING_RETIREMENTS:-0}" -gt 0 ] 2>/dev/null; then ownership=MIGRATION_PENDING; else ownership=CANONICAL_SOURCE_PLUS_MANAGED_MIRRORS; fi
  printf 'pif_profile_ownership_state=%s\n' "$ownership"
}

_otast_report_bootconfig() {
  local key value
  key=$1; value=$(otast_bootconfig_value "$key" 2>/dev/null) || value=UNAVAILABLE
  printf 'raw_%s=%s\n' "$key" "$value"
}

otast_report_strict_runtime_identity() {
  local key
  printf 'security_patch_policy=%s\n' "$OTAST_SECURITY_PATCH_POLICY"
  for key in ro.build.version.security_patch ro.vendor.build.security_patch ro.boot.flash.locked ro.boot.vbmeta.device_state ro.boot.verifiedbootstate ro.boot.veritymode ro.boot.verifiedbooterror ro.boot.verifyerrorpart vendor.boot.vbmeta.device_state vendor.boot.verifiedbootstate; do
    printf 'live_%s=%s\n' "$key" "$(otast_live_value "$key" 2>/dev/null || printf UNAVAILABLE)"
  done
  for key in androidboot.flash.locked androidboot.vbmeta.device_state androidboot.verifiedbootstate androidboot.veritymode androidboot.vbmeta.digest androidboot.vbmeta.avb_version; do _otast_report_bootconfig "$key"; done
  otast_report_pif_profile
}
