#!/system/bin/sh

# OTAST runtime identity policy.
#
# The installed OTA owns platform-visible system/vendor SPL and the conservative
# software boot-state contract. PIF is a separate attestation-profile domain:
# custom/fallback profile identity is PIF-owned and may intentionally differ.

OTAST_SECURITY_PATCH_POLICY=ota
OTAST_EXPECT_FLASH_LOCKED=1
OTAST_EXPECT_VBMETA_DEVICE_STATE=locked
OTAST_EXPECT_VERIFIED_BOOT_STATE=green
OTAST_EXPECT_VERITY_MODE=enforcing
OTAST_EXPECT_VENDOR_VBMETA_DEVICE_STATE=locked
OTAST_EXPECT_VENDOR_VERIFIED_BOOT_STATE=green

otast_enforce_runtime_policy() {
  if [ "${OTAST_TRICKY_PATCH_POLICY:-preserve}" != ota ]; then
    otast_log WARN 'legacy TrickyStore security-patch preserve policy overridden: OTA platform SPL is authoritative'
  fi
  OTAST_TRICKY_PATCH_POLICY=ota
  OTAST_SECURITY_PATCH_POLICY=ota
}

_otast_plan_self_runtime_system_prop() {
  local source path state live original target source_hash
  source=$1
  path=$2
  state=$(_otast_state_path otast-runtime-system-prop) || return 1

  otast_assert_no_symlink_path "$path" || return 1
  live=$(otast_live_hash "$path") || return 1

  # A Magisk module replacement removes files generated inside the old module
  # directory. The persistent OTAST transaction records live outside that
  # directory, so a previously managed system.prop can legitimately be MISSING
  # immediately after upgrade/reinstall. This narrowly repairs only OTAST's own
  # generated file when its original state also proves the path did not exist
  # before OTAST first managed it. Any non-missing byte/mode drift still reaches
  # the normal transaction classifier and remains a hard stop.
  if [ "$live" = MISSING ] && [ -f "$state" ] && [ ! -L "$state" ]; then
    if _otast_validate_record "$state" otast-runtime-system-prop "$path"; then
      original=$(_otast_state_get "$state" original_exists) || return 1
      target=$(_otast_state_get "$state" target) || return 1
      if [ "$original" = 0 ] && [ "$target" = otast ]; then
        source_hash=$(otast_sha256 "$source") || return 1
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
          otast-runtime-system-prop otast "$path" 0644 "$source" "$source_hash" external UPDATE >>"$OTAST_PLAN" || return 1
        OTAST_PLAN_COUNT=$((OTAST_PLAN_COUNT + 1))
        otast_log INFO 'OTAST module replacement detected; self-managed system.prop will be transactionally rehydrated'
        return 0
      fi
    fi
  fi

  otast_plan_add otast-runtime-system-prop otast "$path" 0644 "$source" external ''
}

otast_plan_runtime_system_prop() {
  local source path
  case "$MODDIR" in
    */runtime) path=${MODDIR%/runtime}/system.prop ;;
    *)
      otast_stop "unexpected OTAST runtime directory: $MODDIR"
      return 1
      ;;
  esac
  source=$(otast_plan_source_text otast-runtime-system-prop <<EOF_PROP
# OTAST-managed platform runtime identity. Generated from /data/adb/ota.prop.
ro.build.version.security_patch=$OTAST_SYSTEM_PATCH
ro.vendor.build.security_patch=$OTAST_VENDOR_PATCH
ro.boot.flash.locked=$OTAST_EXPECT_FLASH_LOCKED
ro.boot.vbmeta.device_state=$OTAST_EXPECT_VBMETA_DEVICE_STATE
ro.boot.verifiedbootstate=$OTAST_EXPECT_VERIFIED_BOOT_STATE
ro.boot.veritymode=$OTAST_EXPECT_VERITY_MODE
vendor.boot.vbmeta.device_state=$OTAST_EXPECT_VENDOR_VBMETA_DEVICE_STATE
vendor.boot.verifiedbootstate=$OTAST_EXPECT_VENDOR_VERIFIED_BOOT_STATE
EOF_PROP
) || return 1
  _otast_plan_self_runtime_system_prop "$source" "$path"
}

otast_plan_pif_runtime_system_props() {
  local dir role path source
  for dir in $(otast_effective_module_dirs playintegrityfix); do
    role=$(_otast_role_for_dir "$dir") || return 1
    path=$dir/system.prop
    source=$OTAST_TMP_ROOT/source.$$.pif-runtime-system-prop-$role

    if [ -e "$path" ]; then
      [ -f "$path" ] && [ ! -L "$path" ] || {
        otast_stop "PIF system.prop is not a safe regular file: $path"
        return 1
      }
      cat "$path" >"$source" || return 1
    else
      : >"$source" || return 1
    fi
    chmod 0600 "$source" || return 1

    # This file is a global Magisk property surface. It must always expose the
    # installed OTA SPL, regardless of process-local PIF profile metadata.
    otast_prop_set_line "$source" ro.build.version.security_patch "$OTAST_SYSTEM_PATCH" || return 1
    otast_prop_set_line "$source" ro.vendor.build.security_patch "$OTAST_VENDOR_PATCH" || return 1
    chmod 0600 "$source" || return 1

    otast_plan_add "pif-runtime-system-prop-$role" playintegrityfix "$path" 0644 "$source" external '' || return 1
  done
  return 0
}

otast_plan_strict_runtime_identity() {
  otast_plan_runtime_system_prop || return 1
  otast_plan_pif_runtime_system_props || return 1
  return 0
}

otast_compare_live_strict_runtime_identity() {
  # Fake roots model Android post-reboot values in tools/otastctl/fake_root.py.
  # Production verification at /data/adb must prove the property service sees
  # the intended values after the required reboot.
  _otast_compare_live_pairs 'live OTA security-patch contract differs from authority; reboot after Apply before Verify' \
    'ro.build.version.security_patch:OTAST_SYSTEM_PATCH' \
    'ro.vendor.build.security_patch:OTAST_VENDOR_PATCH' || return 1

  _otast_compare_live_pairs 'live software boot-state contract differs from OTAST policy; reboot after Apply before Verify' \
    'ro.boot.flash.locked:OTAST_EXPECT_FLASH_LOCKED' \
    'ro.boot.vbmeta.device_state:OTAST_EXPECT_VBMETA_DEVICE_STATE' \
    'ro.boot.verifiedbootstate:OTAST_EXPECT_VERIFIED_BOOT_STATE' \
    'ro.boot.veritymode:OTAST_EXPECT_VERITY_MODE' || return 1

  return 0
}

otast_pif_file_value() {
  local path key
  path=$1
  key=$2
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  otast_kv_value "$path" "$key"
}

otast_pif_custom_profile_state() {
  local path
  path=$ADB_ROOT/pif.prop
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    printf 'ABSENT\n'
    return 0
  fi
  if otast_validate_pif_profile_file "$path" >/dev/null 2>&1; then
    printf 'PRESENT\n'
  else
    printf 'UNSAFE\n'
  fi
}

otast_pif_active_fallback_path() {
  local path
  path=$ADB_ROOT/modules/playintegrityfix/pif.prop
  [ -s "$path" ] && [ -f "$path" ] && [ ! -L "$path" ] || return 1
  printf '%s\n' "$path"
}

otast_pif_fallback_profile_state() {
  local module path
  module=$ADB_ROOT/modules/playintegrityfix
  path=$module/pif.prop
  if [ ! -e "$module" ] && [ ! -L "$module" ]; then
    printf 'ABSENT\n'
    return 0
  fi
  if [ ! -d "$module" ] || [ -L "$module" ]; then
    printf 'UNSAFE\n'
    return 0
  fi
  if otast_validate_pif_profile_file "$path" >/dev/null 2>&1; then
    printf 'PRESENT\n'
  else
    printf 'UNSAFE\n'
  fi
}

otast_pif_effective_profile_path() {
  local path
  if [ "$(otast_pif_custom_profile_state)" = PRESENT ]; then
    printf '%s\n' "$ADB_ROOT/pif.prop"
    return 0
  fi
  path=$(otast_pif_active_fallback_path 2>/dev/null) || return 1
  otast_validate_pif_profile_file "$path" >/dev/null 2>&1 || return 1
  printf '%s\n' "$path"
}

otast_pif_autopif_engine_state() {
  local path
  path=$ADB_ROOT/modules/playintegrityfix/autopif.sh
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    printf 'UNAVAILABLE\n'
  elif [ -f "$path" ] && [ ! -L "$path" ] && grep -Fq "$OTAST_PIF_REFRESH_AUTHORITY_BEGIN" "$path" 2>/dev/null; then
    printf 'MANAGED_REVIEWED\n'
  elif [ -f "$path" ] && [ ! -L "$path" ]; then
    printf 'REVIEWED_APPLY_REQUIRED\n'
  else
    printf 'UNSAFE\n'
  fi
}

otast_report_pif_profile() {
  local custom_state fallback_state fallback_path path role value relation custom_hash fallback_hash requested ownership
  custom_state=$(otast_pif_custom_profile_state)
  fallback_state=$(otast_pif_fallback_profile_state)
  fallback_path=$(otast_pif_active_fallback_path 2>/dev/null) || fallback_path='UNAVAILABLE'

  printf 'pif_custom_profile_path=%s\n' "$ADB_ROOT/pif.prop"
  printf 'pif_custom_profile_state=%s\n' "$custom_state"
  printf 'pif_fallback_profile_path=%s\n' "$fallback_path"
  printf 'pif_fallback_profile_state=%s\n' "$fallback_state"

  path=$(otast_pif_effective_profile_path 2>/dev/null) || path='UNAVAILABLE'
  role=UNAVAILABLE
  if [ "$path" = "$ADB_ROOT/pif.prop" ]; then
    role=CUSTOM
  elif [ "$path" != UNAVAILABLE ]; then
    role=ACTIVE_FALLBACK
  fi
  printf 'pif_effective_profile_path=%s\n' "$path"
  printf 'pif_effective_profile_role=%s\n' "$role"

  if [ "$custom_state" = PRESENT ] && [ "$fallback_state" = PRESENT ]; then
    custom_hash=$(otast_sha256 "$ADB_ROOT/pif.prop" 2>/dev/null) || custom_hash=''
    fallback_hash=$(otast_sha256 "$fallback_path" 2>/dev/null) || fallback_hash=''
    if [ -n "$custom_hash" ] && [ "$custom_hash" = "$fallback_hash" ]; then
      relation=SAME
    else
      relation=DISTINCT_EXPECTED
    fi
  else
    relation=UNAVAILABLE
  fi
  printf 'pif_profiles_relation=%s\n' "$relation"

  if [ "$path" != UNAVAILABLE ]; then
    value=$(otast_pif_file_value "$path" FINGERPRINT 2>/dev/null) || value='UNAVAILABLE'
    printf 'pif_profile_fingerprint=%s\n' "$value"
    value=$(otast_pif_file_value "$path" MODEL 2>/dev/null) || value='UNAVAILABLE'
    printf 'pif_profile_model=%s\n' "$value"
    value=$(otast_pif_file_value "$path" SECURITY_PATCH 2>/dev/null) || value='UNAVAILABLE'
    printf 'pif_profile_security_patch=%s\n' "$value"
    value=$(otast_pif_file_value "$path" spoofProps 2>/dev/null) || value='UNAVAILABLE'
    printf 'pif_profile_spoofProps=%s\n' "$value"
    case "$value" in
      true|1) printf '%s\n' 'pif_profile_patch_scope=process-local DroidGuard property hook enabled; profile SPL may intentionally differ from platform SPL' ;;
      false|0) printf '%s\n' 'pif_profile_patch_scope=profile metadata retained; reviewed PIF property hook is disabled' ;;
      *) printf '%s\n' 'pif_profile_patch_scope=UNKNOWN' ;;
    esac
  else
    printf '%s\n' 'pif_profile_fingerprint=UNAVAILABLE'
    printf '%s\n' 'pif_profile_model=UNAVAILABLE'
    printf '%s\n' 'pif_profile_security_patch=UNAVAILABLE'
    printf '%s\n' 'pif_profile_spoofProps=UNAVAILABLE'
    printf '%s\n' 'pif_profile_patch_scope=UNKNOWN'
  fi

  printf 'pif_autopif_engine_state=%s\n' "$(otast_pif_autopif_engine_state)"
  printf '%s\n' 'pif_autopif_self_update_policy=OTAST_REVIEW_GATED'
  if [ -f "$ADB_ROOT/tricky_store/pif_auto_security_patch" ] && [ ! -L "$ADB_ROOT/tricky_store/pif_auto_security_patch" ]; then
    requested=true
  else
    requested=false
  fi
  printf 'pif_auto_security_patch_requested=%s\n' "$requested"
  printf '%s\n' 'pif_auto_security_patch_effective_policy=OTAST_OTA_AUTHORITY'
  if [ "${OTAST_PIF_PENDING_RETIREMENTS:-0}" -gt 0 ] 2>/dev/null; then
    ownership=PENDING_RETIREMENT
  else
    ownership=PIF_OWNED
  fi
  printf 'pif_profile_ownership_state=%s\n' "$ownership"
}

otast_report_strict_runtime_identity() {
  local value
  printf 'security_patch_policy=%s\n' "$OTAST_SECURITY_PATCH_POLICY"
  for value in \
    ro.build.version.security_patch \
    ro.vendor.build.security_patch \
    ro.boot.flash.locked \
    ro.boot.vbmeta.device_state \
    ro.boot.verifiedbootstate \
    ro.boot.veritymode \
    ro.boot.verifiedbooterror \
    ro.boot.verifyerrorpart \
    vendor.boot.vbmeta.device_state \
    vendor.boot.verifiedbootstate; do
    printf 'live_%s=%s\n' "$value" "$(otast_live_value "$value" 2>/dev/null || printf 'UNAVAILABLE')"
  done
  otast_report_pif_profile
}
