#!/system/bin/sh

# Shared OTAST helpers. Runtime is Magisk BusyBox ash; functions use ash local scope.

OTAST_TAB=$(printf '\t')

otast_log() {
  local level
  level=$1
  shift
  printf '[OTAST][%s] %s\n' "$level" "$*" >&2
}

otast_stop() {
  otast_log STOP "$*"
  return 1
}

OTAST_CAPABILITIES_REQUIRED=""
OTAST_CAPABILITIES_OPTIONAL=""

otast_require_capability() {
  local cap="$1"
  local reason="$2"
  OTAST_CAPABILITIES_REQUIRED="${OTAST_CAPABILITIES_REQUIRED}${cap}:${reason}|"
}

otast_optional_capability() {
  local cap="$1"
  local reason="$2"
  OTAST_CAPABILITIES_OPTIONAL="${OTAST_CAPABILITIES_OPTIONAL}${cap}:${reason}|"
}

otast_check_capabilities() {
  local list item cap reason avail failed
  failed=0

  # Required capabilities
  list="$OTAST_CAPABILITIES_REQUIRED"
  while [ -n "$list" ]; do
    item="${list%%|*}"
    list="${list#*|}"
    [ -z "$item" ] && continue
    cap="${item%%:*}"
    reason="${item#*:}"
    if command -v "$cap" >/dev/null 2>&1; then
      printf 'capability %s REQUIRED MATCH (%s)\n' "$cap" "$reason"
    else
      printf 'capability %s REQUIRED MISSING (%s)\n' "$cap" "$reason"
      otast_stop "Missing required capability: $cap ($reason)"
      failed=1
    fi
  done

  # Optional capabilities
  list="$OTAST_CAPABILITIES_OPTIONAL"
  while [ -n "$list" ]; do
    item="${list%%|*}"
    list="${list#*|}"
    [ -z "$item" ] && continue
    cap="${item%%:*}"
    reason="${item#*:}"
    if command -v "$cap" >/dev/null 2>&1; then
      printf 'capability %s OPTIONAL MATCH (%s)\n' "$cap" "$reason"
    else
      printf 'capability %s OPTIONAL MISSING (%s)\n' "$cap" "$reason"
    fi
  done

  return "$failed"
}

otast_command_exists() {
  command -v "$1" >/dev/null 2>&1
}

otast_sha256() {
  local file hash
  file=$1
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  if otast_command_exists sha256sum; then
    hash=$(sha256sum "$file" 2>/dev/null) || return 1
  elif otast_command_exists toybox; then
    hash=$(toybox sha256sum "$file" 2>/dev/null) || return 1
  elif otast_command_exists busybox; then
    hash=$(busybox sha256sum "$file" 2>/dev/null) || return 1
  else
    return 1
  fi
  hash=${hash%%[[:space:]]*}
  case "$hash" in *[!0-9a-f]*|'') return 1 ;; esac
  [ "${#hash}" -eq 64 ] || return 1
  printf '%s\n' "$hash"
}

otast_live_hash() {
  local path
  path=$1
  if [ ! -e "$path" ]; then
    printf 'MISSING\n'
    return 0
  fi
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  otast_sha256 "$path"
}

otast_file_mode() {
  local path mode
  path=$1
  [ -e "$path" ] && [ ! -L "$path" ] || return 1
  mode=''
  if otast_command_exists stat; then
    mode=$(stat -c '%a' "$path" 2>/dev/null) || mode=''
  fi
  if [ -z "$mode" ] && otast_command_exists toybox; then
    mode=$(toybox stat -c '%a' "$path" 2>/dev/null) || mode=''
  fi
  if [ -z "$mode" ] && otast_command_exists busybox; then
    mode=$(busybox stat -c '%a' "$path" 2>/dev/null) || mode=''
  fi
  case "$mode" in
    [0-7][0-7][0-7]) printf '0%s\n' "$mode" ;;
    [0-7][0-7][0-7][0-7]) printf '%s\n' "$mode" ;;
    *) return 1 ;;
  esac
}

otast_mode_valid() {
  case $1 in 0[0-7][0-7][0-7]) return 0 ;; *) return 1 ;; esac
}

otast_id_valid() {
  local value
  value=${1:-}
  case "$value" in
    ''|*[!A-Za-z0-9._-]*) return 1 ;;
    *) return 0 ;;
  esac
}

otast_safe_id() {
  local value
  value=${1:-}
  otast_id_valid "$value" || return 1
  printf '%s\n' "$value"
}

otast_assert_under_adb_root() {
  local path
  path=$1
  case "$path" in "$ADB_ROOT"|"$ADB_ROOT"/*) ;; *) otast_stop "path escapes ADB_ROOT: $path"; return 1 ;; esac
  case "$path" in *'/../'*|*/..|*'/./'*|*/.) otast_stop "non-canonical path: $path"; return 1 ;; esac
  return 0
}

otast_assert_no_symlink_path() {
  local path parent rel cursor old_ifs component
  path=$1
  otast_assert_under_adb_root "$path" || return 1
  parent=${path%/*}
  rel=${parent#"$ADB_ROOT"/}
  cursor=$ADB_ROOT
  if [ "$parent" != "$ADB_ROOT" ]; then
    old_ifs=$IFS
    IFS=/
    for component in $rel; do
      IFS=$old_ifs
      [ -n "$component" ] || { IFS=/; continue; }
      cursor=$cursor/$component
      if [ -L "$cursor" ]; then
        IFS=$old_ifs
        otast_stop "symlink parent rejected: $cursor"
        return 1
      fi
      if [ -e "$cursor" ] && [ ! -d "$cursor" ]; then
        IFS=$old_ifs
        otast_stop "non-directory parent rejected: $cursor"
        return 1
      fi
      IFS=/
    done
    IFS=$old_ifs
  fi
  if [ -L "$path" ]; then
    otast_stop "symlink target rejected: $path"
    return 1
  fi
  return 0
}

otast_ensure_dir() {
  local dir
  dir=$1
  otast_assert_under_adb_root "$dir" || return 1
  otast_assert_no_symlink_path "$dir/.otast-probe" || return 1
  mkdir -p "$dir" || return 1
  [ -d "$dir" ] && [ ! -L "$dir" ]
}

otast_make_temp_in() {
  local dir prefix attempt candidate
  dir=$1
  prefix=$2
  otast_id_valid "$prefix" || return 1
  attempt=0
  while [ "$attempt" -lt 50 ]; do
    candidate=$dir/.${prefix}.$$.$attempt
    if (umask 077; set -C; : >"$candidate") 2>/dev/null; then
      printf '%s\n' "$candidate"
      return 0
    fi
    attempt=$((attempt + 1))
  done
  return 1
}

otast_atomic_install() {
  local source target mode parent temp
  source=$1
  target=$2
  mode=$3
  [ -f "$source" ] && [ ! -L "$source" ] || return 1
  otast_mode_valid "$mode" || return 1
  otast_assert_no_symlink_path "$target" || return 1
  parent=${target%/*}
  otast_ensure_dir "$parent" || return 1
  temp=$(otast_make_temp_in "$parent" otast-write) || return 1
  if cat "$source" >"$temp" && chmod "$mode" "$temp" && mv -f "$temp" "$target"; then
    return 0
  fi
  rm -f "$temp" 2>/dev/null || :
  return 1
}

otast_hash_allowed() {
  local hash csv old_ifs allowed
  hash=$1
  csv=$2
  old_ifs=$IFS
  IFS=,
  for allowed in $csv; do
    IFS=$old_ifs
    [ "$hash" = "$allowed" ] && return 0
    IFS=,
  done
  IFS=$old_ifs
  return 1
}

otast_is_fake_root() {
  [ "$ADB_ROOT" != /data/adb ] && [ -f "$ADB_ROOT/.otast-fake-root" ] && [ ! -L "$ADB_ROOT/.otast-fake-root" ]
}

otast_effective_module_dirs() {
  local id tree dir
  id=$1
  otast_id_valid "$id" || return 1
  for tree in modules_update modules; do
    dir=$ADB_ROOT/$tree/$id
    [ -d "$dir" ] && [ ! -L "$dir" ] || continue
    [ ! -e "$dir/remove" ] || continue
    [ ! -e "$dir/disable" ] || continue
    printf '%s\n' "$dir"
  done
}


otast_require_no_legacy_governors() {
  local legacy_otasst legacy_ota_sot legacy_aaa path
  legacy_otasst='otasst'
  legacy_ota_sot='ota-sot'
  legacy_aaa='aaa_ota_sot'
  for path in \
    "$ADB_ROOT/modules/$legacy_otasst" \
    "$ADB_ROOT/modules_update/$legacy_otasst" \
    "$ADB_ROOT/modules/$legacy_ota_sot" \
    "$ADB_ROOT/modules_update/$legacy_ota_sot" \
    "$ADB_ROOT/modules/$legacy_aaa" \
    "$ADB_ROOT/modules_update/$legacy_aaa" \
    "$ADB_ROOT/$legacy_otasst" \
    "$ADB_ROOT/aaa-ota-sot-BAKs" \
    "$ADB_ROOT/post-fs-data.d/000-$legacy_otasst.sh" \
    "$ADB_ROOT/post-fs-data.d/000-$legacy_aaa.sh"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
      otast_stop "legacy OTA authority governor trace must be removed before OTAST operation: $path"
      return 1
    fi
  done
  return 0
}
