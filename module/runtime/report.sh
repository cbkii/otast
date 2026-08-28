#!/system/bin/sh

otast_report() {
  local _otast_dir _otast_found _otast_id _otast_boot_size _otast_boot_digest _otast_boot_avb
  _otast_boot_size=$(otast_bootconfig_value androidboot.vbmeta.size 2>/dev/null) || _otast_boot_size='UNAVAILABLE'
  _otast_boot_digest=$(otast_bootconfig_value androidboot.vbmeta.digest 2>/dev/null) || _otast_boot_digest='UNAVAILABLE'
  _otast_boot_avb=$(otast_bootconfig_value androidboot.vbmeta.avb_version 2>/dev/null) || _otast_boot_avb='UNAVAILABLE'

  printf 'authority=%s\n' "$OTAST_AUTHORITY"
  printf 'authority_sha256=%s\n' "$OTAST_AUTHORITY_SHA256"
  printf 'device=%s\n' "$OTAST_DEVICE"
  printf 'build_id=%s\n' "$OTAST_BUILD_ID"
  printf 'sdk=%s\n' "$OTAST_SDK"
  printf 'system_patch=%s\n' "$OTAST_SYSTEM_PATCH"
  printf 'vendor_patch=%s\n' "$OTAST_VENDOR_PATCH"
  printf 'pif_identity_policy=%s\n' "$OTAST_PIF_IDENTITY_POLICY"
  printf 'trickystore_security_patch_policy=%s\n' "$OTAST_TRICKY_PATCH_POLICY"
  printf 'ota_vbmeta_digest=%s\n' "$OTAST_VBMETA_DIGEST"
  printf 'bootloader_vbmeta_digest=%s\n' "$_otast_boot_digest"
  printf 'ota_vbmeta_avb_version=%s\n' "$OTAST_VBMETA_AVB_VERSION"
  printf 'bootloader_vbmeta_avb_version=%s\n' "$_otast_boot_avb"
  printf 'ota_vbmeta_size_artifact_evidence=%s\n' "$OTAST_VBMETA_SIZE"
  printf 'bootloader_vbmeta_size_runtime=%s\n' "$_otast_boot_size"
  if [ "$_otast_boot_size" != UNAVAILABLE ] && [ "$_otast_boot_size" != "$OTAST_VBMETA_SIZE" ]; then
    printf '%s\n' 'vbmeta_size_note=artifact-derived and runtime libavb size use different semantics; mismatch is informational and is never resetprop-corrected'
  fi
  printf 'state_root=%s\n' "$OTAST_STATE_ROOT"
  for _otast_id in playintegrityfix tricky_store Yurikey TA_utl .TA_utl vbmeta-fixer; do
    _otast_found=0
    for _otast_dir in $(otast_effective_module_dirs "$_otast_id"); do
      printf 'module=%s path=%s\n' "$_otast_id" "$_otast_dir"
      _otast_found=1
    done
    [ "$_otast_found" -eq 1 ] || printf 'module=%s path=ABSENT_OR_DISABLED\n' "$_otast_id"
  done
  otast_verify_managed
}
