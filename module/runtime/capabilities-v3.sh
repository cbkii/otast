#!/system/bin/sh

# Cross-module capability ownership policy. This layer is intentionally sourced
# after the target-specific compatibility helpers so it can tighten reviewed
# adapters without replacing PR #41's PIF state machine or transaction engine.

OTAST_CAPABILITY_ARCHITECTURE=exclusive-writer-v1
OTAST_TA_PROP_GUARD=$ADB_ROOT/disable_prop_handler
OTAST_CAPABILITY_LAST_CONFLICT=''

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

_otast_cap_module_effective() {
  local id
  id=$1
  _otast_cap_effective_role_dir "$id" active >/dev/null 2>&1 && return 0
  _otast_cap_effective_role_dir "$id" staged >/dev/null 2>&1 && return 0
  return 1
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

# Runtime-inspected direct writers. Strict-exclusion/non-target module identities
# are deliberately absent: their trees remain path-protected and are inspected
# only by host/qualification tooling, never made runtime write targets.
_otast_cap_writer_integrations() {
  printf '%s\n' otast playintegrityfix trickystore vector rezygisk
}

_otast_cap_integration_module_ids() {
  case "$1" in
    otast) return 0 ;;
    playintegrityfix) printf '%s\n' playintegrityfix ;;
    trickystore) printf '%s\n' tricky_store ;;
    vector) printf '%s\n' vector ;;
    rezygisk) printf '%s\n' rezygisk ;;
    *) return 1 ;;
  esac
}

_otast_cap_integration_writes() {
  case "$1" in
    otast) printf '%s\n' platform_system_spl platform_vendor_spl trickystore_patch vbmeta_digest ;;
    playintegrityfix) printf '%s\n' pif_profile global_sensitive_props ;;
    trickystore) printf '%s\n' key_attestation ;;
    vector) printf '%s\n' lsposed_environment ;;
    rezygisk) printf '%s\n' zygisk_provider ;;
    *) return 1 ;;
  esac
}

_otast_cap_exclusive_ids() {
  printf '%s\n' \
    installed_ota_static_identity \
    raw_boot_avb_evidence \
    global_sensitive_props \
    pif_profile \
    platform_system_spl \
    platform_vendor_spl \
    trickystore_patch \
    key_attestation \
    vbmeta_digest \
    package_provenance \
    zygisk_provider
}

_otast_cap_is_exclusive() {
  case "$1" in
    installed_ota_static_identity|raw_boot_avb_evidence|global_sensitive_props|pif_profile|platform_system_spl|platform_vendor_spl|trickystore_patch|key_attestation|vbmeta_digest|package_provenance|zygisk_provider) return 0 ;;
    *) return 1 ;;
  esac
}

_otast_cap_integration_enabled() {
  local integration id
  integration=$1
  [ "$integration" = otast ] && return 0
  for id in $(_otast_cap_integration_module_ids "$integration"); do
    _otast_cap_module_effective "$id" && return 0
  done
  return 1
}

_otast_cap_effective_module_id_count() {
  local integration id count
  integration=$1
  count=0
  for id in $(_otast_cap_integration_module_ids "$integration"); do
    _otast_cap_module_effective "$id" || continue
    count=$((count + 1))
  done
  printf '%s\n' "$count"
}

_otast_cap_integration_claims() {
  local integration capability claimed
  integration=$1
  capability=$2
  for claimed in $(_otast_cap_integration_writes "$integration"); do
    [ "$claimed" = "$capability" ] && return 0
  done
  return 1
}

_otast_cap_record_conflict() {
  OTAST_CAPABILITY_LAST_CONFLICT=$1
  if [ "${OTAST_CAPABILITY_REPORT_ONLY:-0}" = 1 ]; then
    return 0
  fi
  otast_stop "$OTAST_CAPABILITY_LAST_CONFLICT"
  return 1
}

_otast_cap_writer_list() {
  local capability integration result
  capability=$1
  result=''
  for integration in $(_otast_cap_writer_integrations); do
    _otast_cap_integration_enabled "$integration" || continue
    _otast_cap_integration_claims "$integration" "$capability" || continue
    if [ -n "$result" ]; then result=$result,$integration; else result=$integration; fi
  done
  printf '%s\n' "${result:-NONE}"
}

otast_validate_capability_ownership() {
  local role count integration capability writers writer_count module_count write_cap
  OTAST_CAPABILITY_LAST_CONFLICT=''

  # TA_utl and .TA_utl are aliases for one compatibility adapter. Two copies in
  # the same effective role are ambiguous even after writer neutralisation.
  for role in active staged; do
    count=$(_otast_cap_count_ta_role "$role") || return 1
    if [ "$count" -gt 1 ]; then
      _otast_cap_record_conflict "exclusive capability conflict: multiple TA UTL aliases are effective in $role role"
      return $?
    fi
  done

  # A single integration may expose compatibility aliases, but more than one
  # effective module ID is not accepted when that integration owns an exclusive
  # capability. Active+staged copies of the same module ID remain one writer.
  for integration in $(_otast_cap_writer_integrations); do
    [ "$integration" = otast ] && continue
    _otast_cap_integration_enabled "$integration" || continue
    module_count=$(_otast_cap_effective_module_id_count "$integration") || return 1
    [ "$module_count" -le 1 ] && continue
    for write_cap in $(_otast_cap_integration_writes "$integration"); do
      _otast_cap_is_exclusive "$write_cap" || continue
      _otast_cap_record_conflict "exclusive capability conflict: integration $integration has multiple effective module identities for $write_cap"
      return $?
    done
  done

  # Generic effective-writer arbitration. Every runtime-inspected exclusive
  # capability resolves to zero or one enabled direct integration; compatibility
  # adapters whose writers are neutralized are deliberately absent here.
  for capability in $(_otast_cap_exclusive_ids); do
    writers=$(_otast_cap_writer_list "$capability") || return 1
    [ "$writers" = NONE ] && continue
    writer_count=1
    case "$writers" in *,*) writer_count=2 ;; esac
    if [ "$writer_count" -gt 1 ]; then
      _otast_cap_record_conflict "exclusive capability conflict: $capability has multiple effective writers: $writers"
      return $?
    fi
  done
  return 0
}

# Override the v2 TA planner with a target-list-only compatibility adapter. The
# exact transform lives in ta.sh and combines an early disable_prop_handler
# boundary with defense-in-depth removal of the reviewed trailing VBMeta writer.
# The independent WebUI boot-hash writer remains exact-neutralized because
# upstream exposes no clean target-only switch for that save path.
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

_otast_cap_report_row() {
  local capability policy_owner selected state conflict
  capability=$1
  policy_owner=$2
  selected=$(_otast_cap_writer_list "$capability") || selected=UNKNOWN
  case "$capability" in
    installed_ota_static_identity|raw_boot_avb_evidence) state=EXTERNAL_AUTHORITY ;;
    package_provenance) state=EXTERNAL_NON_TARGET_OBSERVED ;;
    *) if [ "$selected" = NONE ]; then state=UNOWNED_OR_NOT_INSTALLED; else state=WRITER_EFFECTIVE; fi ;;
  esac
  conflict=NONE
  case "$selected" in *,*) conflict=$selected ;; esac
  printf 'capability_%s_policy_owner=%s\n' "$capability" "$policy_owner"
  printf 'capability_%s_selected_writer=%s\n' "$capability" "$selected"
  printf 'capability_%s_observers=OTAST\n' "$capability"
  printf 'capability_%s_conflicts=%s\n' "$capability" "$conflict"
  printf 'capability_%s_state=%s\n' "$capability" "$state"
  printf 'capability_%s_evidence=REGISTRY_PLUS_EFFECTIVE_MODULE_STATE\n' "$capability"
}

otast_report_capability_ownership() {
  local pif ta_state yuri_state vbmeta_state tricky_state
  pif=$(_otast_cap_module_state playintegrityfix)
  tricky_state=$(_otast_cap_module_state tricky_store)
  if [ "$(_otast_cap_count_ta_role active)" -gt 0 ] || [ "$(_otast_cap_count_ta_role staged)" -gt 0 ]; then ta_state=COMPATIBILITY_ADAPTER; else ta_state=ABSENT; fi
  yuri_state=$(_otast_cap_module_state Yurikey)
  vbmeta_state=$(_otast_cap_module_state vbmeta-fixer)

  printf 'capability_architecture=%s\n' "$OTAST_CAPABILITY_ARCHITECTURE"
  printf 'capability_last_conflict=%s\n' "${OTAST_CAPABILITY_LAST_CONFLICT:-NONE}"
  _otast_cap_report_row installed_ota_static_identity STOCK_OS_PLUS_OTA_AUTHORITY
  _otast_cap_report_row raw_boot_avb_evidence BOOTLOADER_LIBAVB_READ_ONLY
  _otast_cap_report_row pif_profile SELECTED_PIF_PROVIDER_PLUS_USER_PROFILE
  _otast_cap_report_row global_sensitive_props SELECTED_PIF_PROVIDER
  _otast_cap_report_row platform_system_spl OTAST
  _otast_cap_report_row platform_vendor_spl OTAST
  _otast_cap_report_row trickystore_patch OTAST
  _otast_cap_report_row key_attestation TRICKYSTORE_OSS
  _otast_cap_report_row vbmeta_digest OTAST_BOOT_HASH_CONTRACT
  _otast_cap_report_row package_provenance EXTERNAL_NON_TARGET_PROVIDER
  _otast_cap_report_row zygisk_provider ONE_EFFECTIVE_ZYGISK_PROVIDER

  # Backward-compatible summary keys retained for existing tooling.
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
  printf '%s\n' 'capability_package_provenance_owner=EXTERNAL_NON_TARGET_OBSERVED'
}
