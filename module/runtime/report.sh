#!/system/bin/sh

otast_report() {
  local _otast_dir _otast_found _otast_id
  printf 'authority=%s\n' "$OTAST_AUTHORITY"
  printf 'authority_sha256=%s\n' "$OTAST_AUTHORITY_SHA256"
  printf 'device=%s\n' "$OTAST_DEVICE"
  printf 'build_id=%s\n' "$OTAST_BUILD_ID"
  printf 'sdk=%s\n' "$OTAST_SDK"
  printf 'system_patch=%s\n' "$OTAST_SYSTEM_PATCH"
  printf 'vendor_patch=%s\n' "$OTAST_VENDOR_PATCH"
  printf 'state_root=%s\n' "$OTAST_STATE_ROOT"
  for _otast_id in playintegrityfix tricky_store Yurikey TA_utl .TA_utl vbmeta-fixer; do
    _otast_found=0
    for _otast_dir in $(otast_effective_module_dirs "$_otast_id"); do
      printf 'module=%s path=%s\n' "$_otast_id" "$_otast_dir"
      _otast_found=1
    done
    [ "$_otast_found" -eq 1 ] || printf 'module=%s path=ABSENT\n' "$_otast_id"
  done
  otast_verify_managed
}
