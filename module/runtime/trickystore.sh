#!/system/bin/sh

# Reviewed Tricky Store OSS v3.1.0 compatibility and read-only health checks.
# OTAST manages only the security-patch contract here. Keybox/target files are
# observed, never replaced implicitly.

OTAST_TRICKY_NAME='Tricky Store OSS'
OTAST_TRICKY_AUTHOR='beakthoven'
OTAST_TRICKY_VERSION='v3.1.0 (172-41383f5-release)'
OTAST_TRICKY_VERSION_CODE='172'
OTAST_TRICKY_KEYBOX_STATE='ABSENT'
OTAST_TRICKY_TARGET_COUNT='UNAVAILABLE'
OTAST_TRICKY_TEE_STATUS='UNAVAILABLE'

otast_trickystore_module_value() {
  local dir key
  dir=$1
  key=$2
  [ -f "$dir/module.prop" ] && [ ! -L "$dir/module.prop" ] || return 1
  otast_kv_value "$dir/module.prop" "$key"
}

otast_validate_trickystore_oss() {
  local dir id name author version version_code found
  found=0
  for dir in $(otast_effective_module_dirs tricky_store); do
    found=1
    id=$(otast_trickystore_module_value "$dir" id 2>/dev/null) || id=''
    name=$(otast_trickystore_module_value "$dir" name 2>/dev/null) || name=''
    author=$(otast_trickystore_module_value "$dir" author 2>/dev/null) || author=''
    version=$(otast_trickystore_module_value "$dir" version 2>/dev/null) || version=''
    version_code=$(otast_trickystore_module_value "$dir" versionCode 2>/dev/null) || version_code=''

    [ "$id" = tricky_store ] || {
      otast_stop "unsupported TrickyStore module id at $dir: ${id:-missing}"
      return 1
    }
    [ "$name" = "$OTAST_TRICKY_NAME" ] && [ "$author" = "$OTAST_TRICKY_AUTHOR" ] || {
      otast_stop "unsupported TrickyStore implementation at $dir: name=${name:-missing} author=${author:-missing}; expected Tricky Store OSS by beakthoven"
      return 1
    }
    [ "$version" = "$OTAST_TRICKY_VERSION" ] && [ "$version_code" = "$OTAST_TRICKY_VERSION_CODE" ] || {
      otast_stop "unreviewed Tricky Store OSS version at $dir: version=${version:-missing} versionCode=${version_code:-missing}; expected $OTAST_TRICKY_VERSION / $OTAST_TRICKY_VERSION_CODE"
      return 1
    }
  done
  [ "$found" -eq 1 ] || return 0
  return 0
}

otast_trickystore_keybox_state() {
  local path size
  path=$ADB_ROOT/tricky_store/keybox.xml
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    printf 'ABSENT\n'
    return 0
  fi
  [ -f "$path" ] && [ ! -L "$path" ] || {
    printf 'UNSAFE\n'
    return 0
  }
  size=$(wc -c <"$path" 2>/dev/null) || size=''
  case "$size" in ''|*[!0-9]*) printf 'UNREADABLE\n'; return 0 ;; esac
  [ "$size" -gt 0 ] || { printf 'EMPTY\n'; return 0; }

  if grep -q '<AndroidAttestation' "$path" 2>/dev/null &&
     grep -q '<Keybox[[:space:]>]' "$path" 2>/dev/null &&
     grep -q '<PrivateKey[[:space:]>]' "$path" 2>/dev/null &&
     grep -q '<CertificateChain[[:space:]>]' "$path" 2>/dev/null; then
    printf 'STRUCTURE_OK_UNPROVEN\n'
  else
    printf 'MALFORMED\n'
  fi
}

otast_trickystore_collect_health() {
  local path count
  OTAST_TRICKY_KEYBOX_STATE=$(otast_trickystore_keybox_state) || OTAST_TRICKY_KEYBOX_STATE='UNREADABLE'

  path=$ADB_ROOT/tricky_store/target.txt
  if [ -e "$path" ] || [ -L "$path" ]; then
    if [ -f "$path" ] && [ ! -L "$path" ]; then
      count=$(grep -Ev '^[[:space:]]*(#|$)' "$path" 2>/dev/null | wc -l 2>/dev/null) || count=''
      case "$count" in ''|*[!0-9]*) OTAST_TRICKY_TARGET_COUNT='UNAVAILABLE' ;; *) OTAST_TRICKY_TARGET_COUNT=$count ;; esac
    else
      OTAST_TRICKY_TARGET_COUNT='UNSAFE'
    fi
  else
    OTAST_TRICKY_TARGET_COUNT='ABSENT'
  fi

  path=$ADB_ROOT/tricky_store/tee_status
  if [ -f "$path" ] && [ ! -L "$path" ]; then
    OTAST_TRICKY_TEE_STATUS=$(sed -n '1p' "$path" 2>/dev/null) || OTAST_TRICKY_TEE_STATUS='UNAVAILABLE'
    [ -n "$OTAST_TRICKY_TEE_STATUS" ] || OTAST_TRICKY_TEE_STATUS='EMPTY'
  elif [ -e "$path" ] || [ -L "$path" ]; then
    OTAST_TRICKY_TEE_STATUS='UNSAFE'
  else
    OTAST_TRICKY_TEE_STATUS='ABSENT'
  fi

  case "$OTAST_TRICKY_KEYBOX_STATE" in
    EMPTY|MALFORMED|UNSAFE|UNREADABLE)
      otast_log WARN "Tricky Store OSS active keybox is $OTAST_TRICKY_KEYBOX_STATE; targeted local-attestation RootOfTrust rewriting cannot be relied on"
      ;;
  esac
  case "$OTAST_TRICKY_TARGET_COUNT" in
    UNSAFE) otast_stop 'Tricky Store OSS target.txt is not a safe regular file'; return 1 ;;
  esac
  return 0
}

otast_report_trickystore_health() {
  printf 'trickystore_implementation=%s\n' "$OTAST_TRICKY_NAME"
  printf 'trickystore_reviewed_version=%s\n' "$OTAST_TRICKY_VERSION"
  printf 'trickystore_keybox_state=%s\n' "$OTAST_TRICKY_KEYBOX_STATE"
  printf 'trickystore_target_count=%s\n' "$OTAST_TRICKY_TARGET_COUNT"
  printf 'trickystore_tee_status=%s\n' "$OTAST_TRICKY_TEE_STATUS"
}
