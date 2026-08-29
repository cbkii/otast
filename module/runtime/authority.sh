#!/system/bin/sh

# Parse /data/adb/ota.prop and prove that the live runtime identity matches it.
# OTA-derived vbmeta.size is retained as provenance only; runtime vbmeta.size is
# bootloader/libavb telemetry and is not overwritten by OTAST.

OTAST_AUTHORITY_SHA256=''
OTAST_DEVICE=''
OTAST_BUILD_ID=''
OTAST_SDK=''
OTAST_SYSTEM_PATCH=''
OTAST_VENDOR_PATCH=''
OTAST_FINGERPRINT=''
OTAST_MANUFACTURER=''
OTAST_MODEL=''
OTAST_BOOT_SHA256=''
OTAST_VBMETA_DIGEST=''
OTAST_VBMETA_SIZE=''
OTAST_VBMETA_AVB_VERSION=''
OTAST_BOOT_AVB_VERSION=''
OTAST_PIF_SPOOF_BUILD='preserve'
OTAST_PIF_SPOOF_PROPS='preserve'
OTAST_PIF_SPOOF_PROVIDER='preserve'
OTAST_PIF_SPOOF_SIGNATURE='preserve'
OTAST_PIF_SPOOF_VENDING_BUILD='preserve'
OTAST_PIF_SPOOF_VENDING_SDK='preserve'
OTAST_PIF_DEBUG='preserve'
OTAST_PIF_IDENTITY_POLICY='preserve'
OTAST_TRICKY_PATCH_POLICY='preserve'

otast_kv_value() {
  local path key line
  path=$1
  key=$2
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "$key="*) printf '%s\n' "${line#*=}"; return 0 ;;
    esac
  done <"$path"
  return 1
}

otast_authority_value() {
  otast_kv_value "$OTAST_AUTHORITY" "$1"
}

otast_authority_optional() {
  local key default value
  key=$1
  default=$2
  value=$(otast_authority_value "$key" 2>/dev/null) || value=$default
  printf '%s\n' "$value"
}

otast_valid_date() {
  local date month day
  date=$1
  case "$date" in
    [0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]) ;;
    *) return 1 ;;
  esac
  month=${date#????-}
  month=${month%-??}
  day=${date##*-}
  [ "$month" -ge 1 ] 2>/dev/null && [ "$month" -le 12 ] 2>/dev/null || return 1
  [ "$day" -ge 1 ] 2>/dev/null && [ "$day" -le 31 ] 2>/dev/null
}

otast_validate_authority_lines() {
  local line key value seen entries
  seen='|'
  entries=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '') continue ;;
      \#*) continue ;;
      *=*) ;;
      *) return 1 ;;
    esac
    key=${line%%=*}
    value=${line#*=}
    case "$key" in ''|*[!A-Za-z0-9_.-]*) return 1 ;; esac
    case "$seen" in *"|$key|"*) return 1 ;; esac
    seen="${seen}${key}|"
    if printf '%s' "$value" | grep -Eq '^[[:space:]]|[[:space:]]$'; then
      return 1
    fi
    entries=$((entries + 1))
  done <"$OTAST_AUTHORITY"
  [ "$entries" -gt 0 ]
}

otast_validate_authority_file() {
  local size policy
  [ -f "$OTAST_AUTHORITY" ] && [ ! -L "$OTAST_AUTHORITY" ] || {
    otast_stop "authority file missing or unsafe: $OTAST_AUTHORITY"
    return 1
  }
  size=$(wc -c <"$OTAST_AUTHORITY" 2>/dev/null) || return 1
  case "$size" in ''|*[!0-9]*) return 1 ;; esac
  [ "$size" -gt 0 ] && [ "$size" -le 524288 ] || {
    otast_stop 'authority file size is outside the supported range'
    return 1
  }
  if LC_ALL=C grep -q "$(printf '\r')" "$OTAST_AUTHORITY" 2>/dev/null; then
    otast_stop 'authority file contains CR characters'
    return 1
  fi
  if od -An -v -tx1 "$OTAST_AUTHORITY" 2>/dev/null | grep -Eq '(^|[[:space:]])00([[:space:]]|$)'; then
    otast_stop 'authority file contains NUL bytes'
    return 1
  fi
  otast_validate_authority_lines || {
    otast_stop 'authority file has malformed, duplicate or ambiguous entries'
    return 1
  }

  OTAST_DEVICE=$(otast_authority_value ro.product.device) || return 1
  OTAST_BUILD_ID=$(otast_authority_value ro.build.id) || return 1
  OTAST_SDK=$(otast_authority_value ro.build.version.sdk) || return 1
  OTAST_SYSTEM_PATCH=$(otast_authority_value ro.build.version.security_patch) || return 1
  OTAST_VENDOR_PATCH=$(otast_authority_optional ro.vendor.build.security_patch "$OTAST_SYSTEM_PATCH") || return 1
  OTAST_FINGERPRINT=$(otast_authority_value ro.build.fingerprint) || return 1
  OTAST_MANUFACTURER=$(otast_authority_value ro.product.manufacturer) || return 1
  OTAST_MODEL=$(otast_authority_value ro.product.model) || return 1
  OTAST_BOOT_SHA256=$(otast_authority_value boot.img.sha256) || return 1
  OTAST_VBMETA_DIGEST=$(otast_authority_value ro.boot.vbmeta.digest) || return 1
  OTAST_VBMETA_SIZE=$(otast_authority_value ro.boot.vbmeta.size) || return 1
  OTAST_VBMETA_AVB_VERSION=$(otast_authority_value ro.boot.vbmeta.avb_version) || return 1
  OTAST_BOOT_AVB_VERSION=$(otast_authority_value ro.boot.avb_version) || return 1

  [ "$OTAST_DEVICE" = tegu ] || { otast_stop "unsupported authority device: $OTAST_DEVICE"; return 1; }
  [ "$OTAST_SDK" = 36 ] || { otast_stop "unsupported authority SDK: $OTAST_SDK"; return 1; }
  otast_valid_date "$OTAST_SYSTEM_PATCH" || { otast_stop "invalid system patch date: $OTAST_SYSTEM_PATCH"; return 1; }
  otast_valid_date "$OTAST_VENDOR_PATCH" || { otast_stop "invalid vendor patch date: $OTAST_VENDOR_PATCH"; return 1; }
  case "$OTAST_FINGERPRINT" in google/tegu/tegu:16/*:user/release-keys) ;; *) otast_stop 'authority fingerprint is not a Pixel 9a Android 16 release fingerprint'; return 1 ;; esac
  [ "$OTAST_MANUFACTURER" = Google ] && [ "$OTAST_MODEL" = 'Pixel 9a' ] || {
    otast_stop 'authority product identity is not Pixel 9a'
    return 1
  }
  case "$OTAST_BOOT_SHA256" in *[!0-9a-f]*|'') otast_stop 'invalid boot.img SHA-256'; return 1 ;; esac
  [ "${#OTAST_BOOT_SHA256}" -eq 64 ] || { otast_stop 'invalid boot.img SHA-256 length'; return 1; }
  case "$OTAST_VBMETA_DIGEST" in *[!0-9a-f]*|'') otast_stop 'invalid vbmeta digest'; return 1 ;; esac
  [ "${#OTAST_VBMETA_DIGEST}" -eq 64 ] || { otast_stop 'invalid vbmeta digest length'; return 1; }
  case "$OTAST_VBMETA_SIZE" in ''|*[!0-9]*) otast_stop 'invalid OTA-derived vbmeta size evidence'; return 1 ;; esac
  [ "$OTAST_VBMETA_SIZE" -gt 0 ] 2>/dev/null || { otast_stop 'invalid OTA-derived vbmeta size evidence'; return 1; }
  case "$OTAST_VBMETA_AVB_VERSION" in [0-9]*.[0-9]*) ;; *) otast_stop 'invalid vbmeta AVB version'; return 1 ;; esac
  case "$OTAST_BOOT_AVB_VERSION" in [0-9]*.[0-9]*) ;; *) otast_stop 'invalid boot AVB version'; return 1 ;; esac

  OTAST_PIF_IDENTITY_POLICY=$(otast_authority_optional otast.pif.identity preserve) || return 1
  OTAST_TRICKY_PATCH_POLICY=$(otast_authority_optional otast.trickystore.securityPatch preserve) || return 1
  case "$OTAST_PIF_IDENTITY_POLICY" in preserve|ota) ;; *) otast_stop "invalid PIF identity policy: $OTAST_PIF_IDENTITY_POLICY"; return 1 ;; esac
  case "$OTAST_TRICKY_PATCH_POLICY" in preserve|ota) ;; *) otast_stop "invalid TrickyStore security-patch policy: $OTAST_TRICKY_PATCH_POLICY"; return 1 ;; esac

  OTAST_PIF_SPOOF_BUILD=$(otast_authority_optional otast.pif.spoofBuild preserve) || return 1
  OTAST_PIF_SPOOF_PROPS=$(otast_authority_optional otast.pif.spoofProps preserve) || return 1
  OTAST_PIF_SPOOF_PROVIDER=$(otast_authority_optional otast.pif.spoofProvider preserve) || return 1
  OTAST_PIF_SPOOF_SIGNATURE=$(otast_authority_optional otast.pif.spoofSignature preserve) || return 1
  OTAST_PIF_SPOOF_VENDING_BUILD=$(otast_authority_optional otast.pif.spoofVendingBuild preserve) || return 1
  OTAST_PIF_SPOOF_VENDING_SDK=$(otast_authority_optional otast.pif.spoofVendingSdk preserve) || return 1
  OTAST_PIF_DEBUG=$(otast_authority_optional otast.pif.DEBUG preserve) || return 1
  for policy in \
    "$OTAST_PIF_SPOOF_BUILD" \
    "$OTAST_PIF_SPOOF_PROPS" \
    "$OTAST_PIF_SPOOF_PROVIDER" \
    "$OTAST_PIF_SPOOF_SIGNATURE" \
    "$OTAST_PIF_SPOOF_VENDING_BUILD" \
    "$OTAST_PIF_SPOOF_VENDING_SDK" \
    "$OTAST_PIF_DEBUG"; do
    case "$policy" in true|false|preserve) ;; *) otast_stop "invalid PIF policy: $policy"; return 1 ;; esac
  done
  OTAST_AUTHORITY_SHA256=$(otast_sha256 "$OTAST_AUTHORITY") || return 1
  return 0
}

otast_live_value() {
  local key
  key=$1
  if [ -n "${OTAST_LIVE_PROP_FILE:-}" ]; then
    otast_kv_value "$OTAST_LIVE_PROP_FILE" "$key"
    return $?
  fi
  getprop "$key" 2>/dev/null
}

otast_bootconfig_value() {
  local key line value
  key=$1
  [ -r /proc/bootconfig ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "$key = "*)
        value=${line#*=}
        value=$(printf '%s' "$value" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//') || return 1
        case "$value" in \"*\") value=${value#\"}; value=${value%\"} ;; esac
        printf '%s\n' "$value"
        return 0
        ;;
    esac
  done </proc/bootconfig
  return 1
}

_otast_compare_live_pairs() {
  local label mismatch pair key var expected live
  label=$1
  shift
  mismatch=''
  for pair in "$@"; do
    key=${pair%%:*}
    var=${pair#*:}
    eval "expected=\${$var}"
    live=$(otast_live_value "$key" 2>/dev/null) || live=''
    if [ "$live" != "$expected" ]; then
      mismatch="${mismatch}${key}:live=${live:-MISSING},authority=$expected;"
    fi
  done
  if [ -n "$mismatch" ]; then
    otast_stop "$label: $mismatch"
    return 1
  fi
  return 0
}

otast_static_prop_value() {
  local key path value
  key=$1
  shift
  if [ -n "${OTAST_LIVE_PROP_FILE:-}" ]; then
    otast_kv_value "$OTAST_LIVE_PROP_FILE" "$key"
    return $?
  fi
  for path in "$@"; do
    [ -f "$path" ] && [ ! -L "$path" ] || continue
    value=$(otast_kv_value "$path" "$key" 2>/dev/null) || continue
    printf '%s\n' "$value"
    return 0
  done
  return 1
}

otast_compare_live_identity() {
  local system_patch vendor_patch
  _otast_compare_live_pairs 'live platform identity differs from authority' \
    'ro.product.device:OTAST_DEVICE' \
    'ro.build.id:OTAST_BUILD_ID' \
    'ro.build.version.sdk:OTAST_SDK' \
    'ro.build.fingerprint:OTAST_FINGERPRINT' || return 1

  system_patch=$(otast_static_prop_value ro.build.version.security_patch \
    /system/build.prop /system/system/build.prop /product/build.prop 2>/dev/null) || {
      otast_stop 'cannot read static system security-patch property'
      return 1
    }
  vendor_patch=$(otast_static_prop_value ro.vendor.build.security_patch \
    /vendor/build.prop /odm/build.prop 2>/dev/null) || {
      otast_stop 'cannot read static vendor security-patch property'
      return 1
    }
  [ "$system_patch" = "$OTAST_SYSTEM_PATCH" ] || {
    otast_stop "static system security patch differs from authority: static=$system_patch authority=$OTAST_SYSTEM_PATCH"
    return 1
  }
  [ "$vendor_patch" = "$OTAST_VENDOR_PATCH" ] || {
    otast_stop "static vendor security patch differs from authority: static=$vendor_patch authority=$OTAST_VENDOR_PATCH"
    return 1
  }
  return 0
}

otast_compare_bootloader_vbmeta() {
  local digest avb mismatch
  [ -r /proc/bootconfig ] || return 0

  digest=$(otast_bootconfig_value androidboot.vbmeta.digest 2>/dev/null) || {
    otast_stop 'required bootloader VBMeta evidence is missing: androidboot.vbmeta.digest'
    return 1
  }
  [ -n "$digest" ] || {
    otast_stop 'required bootloader VBMeta evidence is empty: androidboot.vbmeta.digest'
    return 1
  }
  avb=$(otast_bootconfig_value androidboot.vbmeta.avb_version 2>/dev/null) || {
    otast_stop 'required bootloader VBMeta evidence is missing: androidboot.vbmeta.avb_version'
    return 1
  }
  [ -n "$avb" ] || {
    otast_stop 'required bootloader VBMeta evidence is empty: androidboot.vbmeta.avb_version'
    return 1
  }

  mismatch=''
  [ "$digest" = "$OTAST_VBMETA_DIGEST" ] || mismatch="${mismatch}androidboot.vbmeta.digest:bootloader=$digest,authority=$OTAST_VBMETA_DIGEST;"
  [ "$avb" = "$OTAST_VBMETA_AVB_VERSION" ] || mismatch="${mismatch}androidboot.vbmeta.avb_version:bootloader=$avb,authority=$OTAST_VBMETA_AVB_VERSION;"
  if [ -n "$mismatch" ]; then
    otast_stop "bootloader VBMeta evidence differs from OTA authority: $mismatch"
    return 1
  fi
  return 0
}

otast_compare_live_managed_vbmeta() {
  _otast_compare_live_pairs 'live managed VBMeta contract differs from authority; reboot after Apply before Verify' \
    'ro.boot.vbmeta.digest:OTAST_VBMETA_DIGEST' \
    'ro.boot.vbmeta.avb_version:OTAST_VBMETA_AVB_VERSION' \
    'ro.boot.avb_version:OTAST_BOOT_AVB_VERSION'
}
