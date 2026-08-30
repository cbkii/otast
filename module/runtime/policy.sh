#!/system/bin/sh

# OTAST runtime identity policy.
#
# OTA-derived SPL is authoritative. PIF identity selection may remain preserved,
# but it must not introduce a different security patch into runtime properties,
# PIF configuration, or TrickyStore attestation metadata.
#
# Software-readable boot state is also centralized here so unrelated modules do
# not compete over the same Pixel lock-state properties. This does not forge TEE
# RootOfTrust; hardware/local attestation remains a separate targeted concern.

OTAST_SECURITY_PATCH_POLICY=ota
OTAST_EXPECT_FLASH_LOCKED=1
OTAST_EXPECT_VBMETA_DEVICE_STATE=locked
OTAST_EXPECT_VERIFIED_BOOT_STATE=green
OTAST_EXPECT_VERITY_MODE=enforcing
OTAST_EXPECT_VENDOR_VBMETA_DEVICE_STATE=locked
OTAST_EXPECT_VENDOR_VERIFIED_BOOT_STATE=green

otast_enforce_runtime_policy() {
  if [ "${OTAST_TRICKY_PATCH_POLICY:-preserve}" != ota ]; then
    otast_log WARN 'legacy TrickyStore security-patch preserve policy overridden: OTA SPL is authoritative'
  fi
  OTAST_TRICKY_PATCH_POLICY=ota
  OTAST_SECURITY_PATCH_POLICY=ota
}

# Override the compatibility transform from pif.sh: preserve all unrelated PIF
# identity/options while always reconciling SECURITY_PATCH to ota.prop.
otast_transform_pif_prop() {
  local source output
  source=$1
  output=$2
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  cat "$source" >"$output" || return 1

  if [ "$OTAST_PIF_IDENTITY_POLICY" = ota ]; then
    otast_prop_set_line "$output" FINGERPRINT "$OTAST_FINGERPRINT" || return 1
    otast_prop_set_line "$output" MANUFACTURER "$OTAST_MANUFACTURER" || return 1
    otast_prop_set_line "$output" MODEL "$OTAST_MODEL" || return 1
    otast_prop_set_line "$output" PRODUCT "${OTAST_DEVICE}_beta" || return 1
    otast_prop_set_line "$output" DEVICE "$OTAST_DEVICE" || return 1
    otast_prop_set_line "$output" PRODUCT_LIST "\"${OTAST_DEVICE}_beta\"" || return 1
  fi

  # SPL is source identity, not an attestation-profile preference.
  otast_prop_set_line "$output" SECURITY_PATCH "$OTAST_SYSTEM_PATCH" || return 1

  otast_prop_apply_policy "$output" spoofBuild "$OTAST_PIF_SPOOF_BUILD" || return 1
  otast_prop_apply_policy "$output" spoofProps "$OTAST_PIF_SPOOF_PROPS" || return 1
  otast_prop_apply_policy "$output" spoofProvider "$OTAST_PIF_SPOOF_PROVIDER" || return 1
  otast_prop_apply_policy "$output" spoofSignature "$OTAST_PIF_SPOOF_SIGNATURE" || return 1
  otast_prop_apply_policy "$output" spoofVendingBuild "$OTAST_PIF_SPOOF_VENDING_BUILD" || return 1
  otast_prop_apply_policy "$output" spoofVendingSdk "$OTAST_PIF_SPOOF_VENDING_SDK" || return 1
  otast_prop_apply_policy "$output" DEBUG "$OTAST_PIF_DEBUG" || return 1
  chmod 0600 "$output" || return 1
}

otast_plan_runtime_system_prop() {
  local source path
  path=$MODDIR/../system.prop
  source=$(otast_plan_source_text otast-runtime-system-prop <<EOF_PROP
# OTAST-managed runtime identity. Generated from /data/adb/ota.prop.
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
  otast_plan_add otast-runtime-system-prop otast "$path" 0644 "$source" external ''
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
  # Fake roots do not model Android's post-reboot property service. Production
  # verification at /data/adb must prove the values actually became visible.
  [ "$ADB_ROOT" = /data/adb ] || return 0

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
    vendor.boot.vbmeta.device_state \
    vendor.boot.verifiedbootstate; do
    printf 'live_%s=%s\n' "$value" "$(otast_live_value "$value" 2>/dev/null || printf 'UNAVAILABLE')"
  done
}
