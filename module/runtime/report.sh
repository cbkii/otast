#!/system/bin/sh

otast_diagnose_writers() {
  local dir role
  # PIF
  for dir in $(otast_effective_module_dirs "playintegrityfix"); do
    role=$(_otast_role_for_dir "$dir")
    printf 'writer playintegrityfix %s autopif.sh OTAST_MANAGED\n' "$role"
    printf 'writer playintegrityfix %s autopif_ota.sh OTAST_MANAGED\n' "$role"
    printf 'writer playintegrityfix %s security_patch.sh OTAST_MANAGED\n' "$role"
    printf 'writer playintegrityfix %s pif.prop OTAST_MANAGED\n' "$role"
  done

  # TA_utl
  for dir in $(otast_effective_module_dirs "TA_utl"); do
    role=$(_otast_role_for_dir "$dir")
    printf 'writer TA_utl %s prop.sh OTAST_MANAGED\n' "$role"
  done
  for dir in $(otast_effective_module_dirs ".TA_utl"); do
    role=$(_otast_role_for_dir "$dir")
    printf 'writer .TA_utl %s prop.sh OTAST_MANAGED\n' "$role"
  done

  # Yurikey
  for dir in $(otast_effective_module_dirs "Yurikey"); do
    role=$(_otast_role_for_dir "$dir")
    printf 'writer Yurikey %s service.sh OTAST_MANAGED\n' "$role"
    printf 'writer Yurikey %s apply.sh OTAST_MANAGED\n' "$role"
    printf 'writer Yurikey %s clear-all.sh OTAST_MANAGED\n' "$role"
  done

  # VBMeta Fixer
  for dir in $(otast_effective_module_dirs "vbmeta-fixer"); do
    role=$(_otast_role_for_dir "$dir")
    printf 'writer vbmeta-fixer %s service.sh OTAST_MANAGED\n' "$role"
  done

  # Conflicts
  if [ -e "$ADB_ROOT/tricky_store/pif_auto_security_patch" ]; then
    printf 'conflict tricky_store active tricky_store/pif_auto_security_patch KNOWN_COMPETING_WRITER_ACTIVE\n'
  else
    printf 'conflict tricky_store active tricky_store/pif_auto_security_patch KNOWN_COMPETING_WRITER_DISABLED\n'
  fi
}

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
  otast_diagnose_writers
  otast_verify_managed
}
