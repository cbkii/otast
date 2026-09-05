#!/system/bin/sh

# Runtime mirror of compatibility/platforms/android-16.json.
# Keep this file deliberately small and BusyBox ash-compatible; host validation
# proves that its constants agree with the machine-readable platform profile.
OTAST_PLATFORM_ID='android-16'
OTAST_PLATFORM_ANDROID_RELEASE='16'
OTAST_PLATFORM_SDK='36'
OTAST_PLATFORM_MANUFACTURER='Google'
OTAST_PLATFORM_MODEL_PREFIX='Pixel '
OTAST_PLATFORM_FINGERPRINT_VENDOR='google'
OTAST_PLATFORM_FINGERPRINT_SUFFIX=':user/release-keys'

otast_platform_validate_product() {
  local device manufacturer model sdk fingerprint prefix
  device=$1
  manufacturer=$2
  model=$3
  sdk=$4
  fingerprint=${5:-}

  case "$device" in
    ''|*[!a-z0-9_]*) return 1 ;;
  esac
  [ "$manufacturer" = "$OTAST_PLATFORM_MANUFACTURER" ] || return 1
  case "$model" in
    "$OTAST_PLATFORM_MODEL_PREFIX"*) ;;
    *) return 1 ;;
  esac
  [ "$sdk" = "$OTAST_PLATFORM_SDK" ] || return 1
  [ -n "$fingerprint" ] || return 1

  prefix="$OTAST_PLATFORM_FINGERPRINT_VENDOR/$device/$device:$OTAST_PLATFORM_ANDROID_RELEASE/"
  case "$fingerprint" in
    "$prefix"*"$OTAST_PLATFORM_FINGERPRINT_SUFFIX") ;;
    *) return 1 ;;
  esac
  return 0
}
