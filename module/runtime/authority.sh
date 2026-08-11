#!/system/bin/sh

# Parse /data/adb/ota.prop and prove that the live runtime identity matches it.

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
OTAST_EXT_BUILD_RELEASE=''
OTAST_EXT_BUILD_INCREMENTAL=''
OTAST_EXT_BUILD_TYPE=''
OTAST_EXT_BUILD_TAGS=''
OTAST_EXT_PRODUCT_NAME=''
OTAST_EXT_PRODUCT_FIRST_API_LEVEL=''
OTAST_EXT_SOC_MODEL=''
OTAST_EXT_SOC_MANUFACTURER=''
OTAST_PIF_SPOOF_BUILD='true'
OTAST_PIF_SPOOF_PROPS='true'
OTAST_PIF_SPOOF_PROVIDER='true'
OTAST_PIF_SPOOF_SIGNATURE='true'
OTAST_PIF_SPOOF_VENDING_BUILD='true'
OTAST_PIF_SPOOF_VENDING_SDK='true'
OTAST_PIF_DEBUG='false'

otast_authority_value() {
  local key
  key=$1
  awk -F= -v wanted="$key" '
    $1 == wanted {
      sub(/^[^=]*=/, "")
      print
      found=1
      exit
    }
    END { if (!found) exit 1 }
  ' "$OTAST_AUTHORITY"
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

otast_validate_authority_file() {
  local size bool
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

  if ! awk -F= '
    function valid_key(k) { return k ~ /^[A-Za-z0-9_.-]+$/ }
    /^[[:space:]]*$/ { next }
    /^#/ { next }
    index($0, "=") == 0 { exit 20 }
    {
      key=$1
      if (!valid_key(key)) exit 21
      if (seen[key]++) exit 22
      value=$0
      sub(/^[^=]*=/, "", value)
      if (value ~ /^[[:space:]]/ || value ~ /[[:space:]]$/) exit 23
      entries++
    }
    END { if (entries == 0) exit 24 }
  ' "$OTAST_AUTHORITY"; then
    otast_stop 'authority file has malformed, duplicate or ambiguous entries'
    return 1
  fi

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

  OTAST_EXT_BUILD_RELEASE=$(otast_authority_optional ro.build.version.release "") || return 1
  OTAST_EXT_BUILD_INCREMENTAL=$(otast_authority_optional ro.build.version.incremental "") || return 1
  OTAST_EXT_BUILD_TYPE=$(otast_authority_optional ro.build.type "") || return 1
  OTAST_EXT_BUILD_TAGS=$(otast_authority_optional ro.build.tags "") || return 1
  OTAST_EXT_PRODUCT_NAME=$(otast_authority_optional ro.product.name "") || return 1
  OTAST_EXT_PRODUCT_FIRST_API_LEVEL=$(otast_authority_optional ro.product.first_api_level "") || return 1
  OTAST_EXT_SOC_MODEL=$(otast_authority_optional ro.soc.model "") || return 1
  OTAST_EXT_SOC_MANUFACTURER=$(otast_authority_optional ro.soc.manufacturer "") || return 1

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
  case "$OTAST_VBMETA_SIZE" in ''|*[!0-9]*) otast_stop 'invalid vbmeta size'; return 1 ;; esac
  [ "$OTAST_VBMETA_SIZE" -gt 0 ] 2>/dev/null || { otast_stop 'invalid vbmeta size'; return 1; }
  case "$OTAST_VBMETA_AVB_VERSION" in [0-9]*.[0-9]*) ;; *) otast_stop 'invalid vbmeta AVB version'; return 1 ;; esac
  case "$OTAST_BOOT_AVB_VERSION" in [0-9]*.[0-9]*) ;; *) otast_stop 'invalid boot AVB version'; return 1 ;; esac

  OTAST_PIF_SPOOF_BUILD=$(otast_authority_optional otast.pif.spoofBuild true) || return 1
  OTAST_PIF_SPOOF_PROPS=$(otast_authority_optional otast.pif.spoofProps true) || return 1
  OTAST_PIF_SPOOF_PROVIDER=$(otast_authority_optional otast.pif.spoofProvider true) || return 1
  OTAST_PIF_SPOOF_SIGNATURE=$(otast_authority_optional otast.pif.spoofSignature true) || return 1
  OTAST_PIF_SPOOF_VENDING_BUILD=$(otast_authority_optional otast.pif.spoofVendingBuild true) || return 1
  OTAST_PIF_SPOOF_VENDING_SDK=$(otast_authority_optional otast.pif.spoofVendingSdk true) || return 1
  OTAST_PIF_DEBUG=$(otast_authority_optional otast.pif.DEBUG false) || return 1
  for bool in \
    "$OTAST_PIF_SPOOF_BUILD" \
    "$OTAST_PIF_SPOOF_PROPS" \
    "$OTAST_PIF_SPOOF_PROVIDER" \
    "$OTAST_PIF_SPOOF_SIGNATURE" \
    "$OTAST_PIF_SPOOF_VENDING_BUILD" \
    "$OTAST_PIF_SPOOF_VENDING_SDK" \
    "$OTAST_PIF_DEBUG"; do
    case "$bool" in true|false) ;; *) otast_stop "invalid PIF boolean: $bool"; return 1 ;; esac
  done

  OTAST_AUTHORITY_SHA256=$(otast_sha256 "$OTAST_AUTHORITY") || return 1
  return 0
}

otast_live_value() {
  local key
  key=$1
  if [ -n "${OTAST_LIVE_PROP_FILE:-}" ]; then
    [ -f "$OTAST_LIVE_PROP_FILE" ] && [ ! -L "$OTAST_LIVE_PROP_FILE" ] || return 1
    awk -F= -v wanted="$key" '
      $1 == wanted {
        sub(/^[^=]*=/, "")
        print
        found=1
        exit
      }
      END { if (!found) exit 1 }
    ' "$OTAST_LIVE_PROP_FILE"
    return $?
  fi
  getprop "$key" 2>/dev/null
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

otast_compare_live_identity() {
  _otast_compare_live_pairs 'live platform identity differs from authority' \
    'ro.product.device:OTAST_DEVICE' \
    'ro.build.id:OTAST_BUILD_ID' \
    'ro.build.version.sdk:OTAST_SDK' \
    'ro.build.version.security_patch:OTAST_SYSTEM_PATCH' \
    'ro.vendor.build.security_patch:OTAST_VENDOR_PATCH' \
    'ro.build.fingerprint:OTAST_FINGERPRINT'
}

otast_compare_live_extended_identity() {
  local mismatch=''
  local pair key var expected live result

  for pair in \
    'ro.build.version.release:OTAST_EXT_BUILD_RELEASE' \
    'ro.build.version.incremental:OTAST_EXT_BUILD_INCREMENTAL' \
    'ro.build.type:OTAST_EXT_BUILD_TYPE' \
    'ro.build.tags:OTAST_EXT_BUILD_TAGS' \
    'ro.product.name:OTAST_EXT_PRODUCT_NAME' \
    'ro.product.first_api_level:OTAST_EXT_PRODUCT_FIRST_API_LEVEL' \
    'ro.soc.model:OTAST_EXT_SOC_MODEL' \
    'ro.soc.manufacturer:OTAST_EXT_SOC_MANUFACTURER'; do

    key=${pair%%:*}
    var=${pair#*:}
    eval "expected=\${$var}"

    if [ -z "$expected" ]; then
      printf 'extended_identity %s NOT_CONFIGURED\n' "$key"
      continue
    fi

    live=$(otast_live_value "$key" 2>/dev/null) || live=''

    if [ -z "$live" ]; then
      printf 'extended_identity %s UNAVAILABLE expected=%s\n' "$key" "$expected"
      mismatch="${mismatch}${key}:live=UNAVAILABLE,authority=$expected;"
    elif [ "$live" != "$expected" ]; then
      printf 'extended_identity %s MISMATCH live=%s expected=%s\n' "$key" "$live" "$expected"
      mismatch="${mismatch}${key}:live=$live,authority=$expected;"
    else
      printf 'extended_identity %s MATCH\n' "$key"
    fi
  done

  if [ -n "$mismatch" ]; then
    otast_stop "live extended platform identity differs from configured authority: $mismatch"
    return 1
  fi
  return 0
}

otast_compare_live_managed_vbmeta() {
  _otast_compare_live_pairs 'live managed VBMeta contract differs from authority; reboot after Apply before Verify' \
    'ro.boot.vbmeta.digest:OTAST_VBMETA_DIGEST' \
    'ro.boot.vbmeta.size:OTAST_VBMETA_SIZE' \
    'ro.boot.vbmeta.avb_version:OTAST_VBMETA_AVB_VERSION' \
    'ro.boot.avb_version:OTAST_BOOT_AVB_VERSION'
}
