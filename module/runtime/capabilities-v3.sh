#!/system/bin/sh

# Cross-module capability ownership policy. This layer is intentionally sourced
# after the target-specific compatibility helpers so it can tighten reviewed
# adapters without replacing PR #41's PIF state machine or transaction engine.

OTAST_CAPABILITY_ARCHITECTURE=exclusive-writer-v1
OTAST_TA_PROP_GUARD=$ADB_ROOT/disable_prop_handler
OTAST_TA_EARLY_GUARD_BEGIN='# --- otast target-only prop guard BEGIN ---'
OTAST_TA_EARLY_GUARD_END='# --- otast target-only prop guard END ---'

_otast_cap_effective_role_dir() {
  local id role dir
  id=$1
  role=$2
  case "$role" in
    active) dir=$ADB_ROOT/modules/$id ;;
    staged) dir=$ADB_ROOT/modules_update/$id ;;
    *) return 1 ;;
  esac
  [ -d "$dir" ] && [ ! -L "$dir" ] || return 1
  [ ! -e "$dir/remove" ] && [ ! -e "$dir/disable" ] || return 1
  printf '%s\n' "$dir"
}

_otast_cap_count_ta_role() {
  local role id count
  role=$1
  count=0
  for id in TA_utl .TA_utl; do
    _otast_cap_effective_role_dir "$id" "$role" >/dev/null 2>&1 || continue
    count=$((count + 1))
  done
  printf '%s\n' "$count"
}

otast_validate_capability_ownership() {
  local role count
  # TA_utl and .TA_utl are aliases for one compatibility adapter. Two copies in
  # the same effective role would be two property/target-list writers and are
  # therefore ambiguous even though OTAST can transform each known file.
  for role in active staged; do
    count=$(_otast_cap_count_ta_role "$role") || return 1
    if [ "$count" -gt 1 ]; then
      otast_stop "exclusive capability conflict: multiple TA UTL aliases are effective in $role role"
      return 1
    fi
  done
  return 0
}

# Current upstream TA UTL reads /data/adb/boot_hash and writes sensitive props
# before/around its late disable_prop_handler check. Move the existing supported
# guard to the earliest executable boundary while keeping the exact reviewed
# source shape otherwise intact. The planner remains exact-hash gated.
otast_transform_ta_prop() {
  local source output line inserted
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1

  if grep -Fxq "$OTAST_TA_EARLY_GUARD_BEGIN" "$source" 2>/dev/null && \
     grep -Fxq "$OTAST_TA_EARLY_GUARD_END" "$source" 2>/dev/null; then
    cat "$source" >"$output" || return 1
    chmod 0600 "$output" || return 1
    otast_shell_file_valid "$output"
    return $?
  fi

  : >"$output" || return 1
  inserted=0
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "$line" >>"$output" || { rm -f "$output"; return 1; }
    if [ "$inserted" -eq 0 ]; then
      case "$line" in
        '#!'*)
          cat >>"$output" <<EOF_GUARD
$OTAST_TA_EARLY_GUARD_BEGIN
# OTAST owns global sensitive-property and VBMeta-digest capability boundaries.
# Presence of disable_prop_handler turns TA UTL into target-list/UI-only mode.
if [ -f "/data/adb/disable_prop_handler" ]; then
    exit 0
fi
$OTAST_TA_EARLY_GUARD_END
EOF_GUARD
          inserted=1
          ;;
      esac
    fi
  done <"$source"
  [ "$inserted" -eq 1 ] || { rm -f "$output"; return 1; }
  chmod 0600 "$output" || return 1
  otast_shell_file_valid "$output"
}

# Override the v2 TA planner with a target-list-only compatibility adapter. The
# WebUI boot-hash writer remains exact-neutralized because upstream exposes no
# clean target-only switch for that independent save path.
otast_plan_ta_utl() {
  local id dir role id_tag candidate webui_found guard_source ta_found
  ta_found=0
  for id in TA_utl .TA_utl; do
    for dir in $(otast_effective_module_dirs "$id"); do
      ta_found=1
    done
  done

  if [ "$ta_found" -eq 1 ]; then
    guard_source=$(otast_plan_source_text ta-disable-prop-handler <<'EOF_GUARD_FILE'
# Managed by OTAST: disable TA UTL property/VBMeta handler; target-list UI remains available.
EOF_GUARD_FILE
) || return 1
    otast_plan_add ta-disable-prop-handler ta-utl "$OTAST_TA_PROP_GUARD" 0644 "$guard_source" external '' || return 1
  fi

  for id in TA_utl .TA_utl; do
    for dir in $(otast_effective_module_dirs "$id"); do
      role=$(_otast_role_for_dir "$dir") || return 1
      case "$id" in
        TA_utl) id_tag=canonical ;;
        .TA_utl) id_tag=hidden ;;
        *) otast_stop "unsupported TA UTL alias: $id"; return 1 ;;
      esac
      _otast_plan_transformed_file ta-prop-$role-$id_tag ta-utl "$dir/prop.sh" 0755 \
        otast_transform_ta_prop \
        'fffa4d98aafb444594480ccaecbdbc083fee8e860418f86cc55e2422dc7a647f' || return 1

      [ -d "$dir/webui/assets" ] && [ ! -L "$dir/webui/assets" ] || {
        otast_stop "required reviewed TA UTL WebUI assets path is missing or unsafe: $dir/webui/assets"
        return 1
      }
      webui_found=0
      for candidate in "$dir"/webui/assets/boot_hash-*.js; do
        [ -e "$candidate" ] || continue
        [ -f "$candidate" ] && [ ! -L "$candidate" ] || {
          otast_stop "TA UTL WebUI boot-hash asset is unsafe: $candidate"
          return 1
        }
        if [ "$candidate" != "$dir/webui/assets/boot_hash-C0kIcwCH.js" ]; then
          otast_stop "unreviewed TA UTL WebUI boot-hash asset: $candidate"
          return 1
        fi
        webui_found=$((webui_found + 1))
      done
      [ "$webui_found" -eq 1 ] || {
        otast_stop "required reviewed TA UTL WebUI boot-hash asset is missing or ambiguous: $dir/webui/assets"
        return 1
      }
      _otast_plan_transformed_file ta-webui-boot-hash-$role-$id_tag ta-utl "$dir/webui/assets/boot_hash-C0kIcwCH.js" 0644 \
        otast_transform_ta_webui_boot_hash \
        'bedb09d2538e28d636ea592a58d2a2234849351d49a95175d54c4de7ccf4d5cc' || return 1
    done
  done
}

otast_verify_capability_ownership() {
  local id dir found
  otast_validate_capability_ownership || return 1
  found=0
  for id in TA_utl .TA_utl; do
    for dir in $(otast_effective_module_dirs "$id"); do found=1; done
  done
  if [ "$found" -eq 1 ]; then
    [ -f "$OTAST_TA_PROP_GUARD" ] && [ ! -L "$OTAST_TA_PROP_GUARD" ] || {
      otast_stop 'TA UTL compatibility adapter is not in target-list-only mode; explicit Apply is required'
      return 1
    }
  fi
  return 0
}

_otast_cap_module_state() {
  local id active staged
  id=$1
  active=0; staged=0
  _otast_cap_effective_role_dir "$id" active >/dev/null 2>&1 && active=1
  _otast_cap_effective_role_dir "$id" staged >/dev/null 2>&1 && staged=1
  case "$active:$staged" in
    0:0) printf 'ABSENT\n' ;;
    1:0) printf 'ACTIVE\n' ;;
    0:1) printf 'STAGED\n' ;;
    1:1) printf 'ACTIVE_AND_STAGED\n' ;;
  esac
}

otast_report_capability_ownership() {
  local pif ta_state yuri_state vbmeta_state tricky_state
  pif=$(_otast_cap_module_state playintegrityfix)
  tricky_state=$(_otast_cap_module_state tricky_store)
  if [ "$(_otast_cap_count_ta_role active)" -gt 0 ] || [ "$(_otast_cap_count_ta_role staged)" -gt 0 ]; then ta_state=COMPATIBILITY_ADAPTER; else ta_state=ABSENT; fi
  yuri_state=$(_otast_cap_module_state Yurikey)
  vbmeta_state=$(_otast_cap_module_state vbmeta-fixer)

  printf 'capability_architecture=%s\n' "$OTAST_CAPABILITY_ARCHITECTURE"
  printf '%s\n' 'capability_installed_ota_static_identity_owner=STOCK_OS_PLUS_OTA_AUTHORITY'
  printf '%s\n' 'capability_raw_boot_avb_evidence_owner=BOOTLOADER_LIBAVB_READ_ONLY'
  if [ "$pif" = ABSENT ]; then
    printf '%s\n' 'capability_pif_profile_owner=NONE'
    printf '%s\n' 'capability_global_sensitive_props_owner=NONE'
  else
    printf '%s\n' 'capability_pif_profile_owner=PLAYINTEGRITYFIX_PROVIDER'
    printf '%s\n' 'capability_global_sensitive_props_owner=PLAYINTEGRITYFIX_PROVIDER'
  fi
  printf '%s\n' 'capability_platform_system_spl_owner=OTAST'
  printf '%s\n' 'capability_platform_vendor_spl_owner=OTAST'
  printf '%s\n' 'capability_vbmeta_digest_owner=OTAST_BOOT_HASH_CONTRACT'
  if [ "$tricky_state" = ABSENT ]; then
    printf '%s\n' 'capability_trickystore_patch_owner=NONE'
    printf '%s\n' 'capability_key_attestation_owner=NONE'
  else
    printf '%s\n' 'capability_trickystore_patch_owner=OTAST'
    printf '%s\n' 'capability_key_attestation_owner=TRICKYSTORE_OSS'
  fi
  printf 'capability_ta_utl_state=%s\n' "$ta_state"
  printf 'capability_yurikey_state=%s\n' "$yuri_state"
  printf 'capability_vbmeta_fixer_state=%s\n' "$vbmeta_state"
  printf '%s\n' 'capability_package_provenance_owner=EXTERNAL_NON_TARGET_UNINSPECTED'
  printf '%s\n' 'capability_zygisk_provider_owner=DEFERRED_TO_PROVIDER_QUALIFICATION_LAYER'
}
