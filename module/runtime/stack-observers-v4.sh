#!/system/bin/sh

# Read-only integrity-stack observers. This layer never mutates external module
# state. It exists to make qualification preconditions explicit without turning
# Zygisk, LSPosed, concealment or Play-Store relationship modules into OTAST
# ownership targets.

OTAST_STACK_ZYGISK_PROVIDER=UNRESOLVED
OTAST_STACK_ZYGISK_PROVIDER_COUNT=0
OTAST_STACK_DETACH_STATE=ABSENT
OTAST_STACK_DETACH_CRITICAL=NONE
OTAST_STACK_DETACH_HASH=UNAVAILABLE

_otast_stack_effective_role() {
  local id active staged
  id=$1
  active=0
  staged=0
  _otast_cap_effective_role_dir "$id" active >/dev/null 2>&1 && active=1
  _otast_cap_effective_role_dir "$id" staged >/dev/null 2>&1 && staged=1
  case "$active:$staged" in
    0:0) printf 'ABSENT\n' ;;
    1:0) printf 'ACTIVE\n' ;;
    0:1) printf 'STAGED\n' ;;
    1:1) printf 'ACTIVE_AND_STAGED\n' ;;
  esac
}

_otast_stack_module_prop_hash() {
  local id role dir prop
  id=$1
  role=$2
  dir=$(_otast_cap_effective_role_dir "$id" "$role") || { printf 'UNAVAILABLE\n'; return 0; }
  prop=$dir/module.prop
  [ -f "$prop" ] && [ ! -L "$prop" ] || { printf 'UNAVAILABLE\n'; return 0; }
  otast_assert_no_symlink_path "$prop" >/dev/null 2>&1 || { printf 'UNAVAILABLE\n'; return 0; }
  otast_sha256 "$prop" 2>/dev/null || printf 'UNAVAILABLE\n'
}

_otast_stack_collect_zygisk_provider() {
  local id count selected
  count=0
  selected=''
  for id in rezygisk zygisksu; do
    _otast_cap_module_effective "$id" || continue
    count=$((count + 1))
    selected=$id
  done
  OTAST_STACK_ZYGISK_PROVIDER_COUNT=$count
  case "$count" in
    0) OTAST_STACK_ZYGISK_PROVIDER=EXTERNAL_OR_BUILTIN_UNRESOLVED ;;
    1) OTAST_STACK_ZYGISK_PROVIDER=$selected ;;
    *) OTAST_STACK_ZYGISK_PROVIDER=CONFLICT ;;
  esac
}

_otast_stack_detach_list() {
  local path size
  path=$1
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  otast_assert_no_symlink_path "$path" || return 1
  size=$(wc -c <"$path" 2>/dev/null) || return 1
  case "$size" in ''|*[!0-9]*) return 1 ;; esac
  [ "$size" -le 1048576 ] || return 1
  [ "$size" -gt 0 ] || return 0
  od -An -v -tu1 "$path" 2>/dev/null | awk '
    {
      for (i = 1; i <= NF; i++) bytes[++n] = $i + 0
    }
    END {
      p = 1
      while (p <= n) {
        len = bytes[p]
        p++
        if (len <= 0 || p + len - 1 > n) exit 2
        name = ""
        for (j = 0; j < len; j += 2) {
          ch = bytes[p + j]
          if (ch < 32 || ch > 126) exit 2
          if (j + 1 < len && bytes[p + j + 1] != 0) exit 2
          name = name sprintf("%c", ch)
        }
        if (name !~ /^[A-Za-z0-9._]+$/) exit 2
        print name
        p += len
      }
      if (p != n + 1) exit 2
    }
  '
}

_otast_stack_collect_detach() {
  local module_state path list package critical found
  module_state=$(_otast_stack_effective_role zygisk-detach)
  path=$ADB_ROOT/zygisk-detach/detach.bin
  OTAST_STACK_DETACH_CRITICAL=NONE
  OTAST_STACK_DETACH_HASH=UNAVAILABLE

  if [ "$module_state" = ABSENT ]; then
    OTAST_STACK_DETACH_STATE=ABSENT
    return 0
  fi
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    OTAST_STACK_DETACH_STATE=PRESENT_EMPTY_OR_UNCONFIGURED
    return 0
  fi
  [ -f "$path" ] && [ ! -L "$path" ] || {
    OTAST_STACK_DETACH_STATE=UNSAFE
    return 1
  }
  otast_assert_no_symlink_path "$path" || { OTAST_STACK_DETACH_STATE=UNSAFE; return 1; }
  OTAST_STACK_DETACH_HASH=$(otast_sha256 "$path") || { OTAST_STACK_DETACH_STATE=UNSAFE; return 1; }
  list=$(_otast_stack_detach_list "$path") || {
    OTAST_STACK_DETACH_STATE=MALFORMED
    return 1
  }
  [ -n "$list" ] || { OTAST_STACK_DETACH_STATE=PRESENT_EMPTY_OR_UNCONFIGURED; return 0; }
  OTAST_STACK_DETACH_STATE=CONFIGURED
  critical=''
  found=0
  for package in $list; do
    case "$package" in
      com.google.android.gms|com.android.vending|com.google.android.apps.walletnfcrel)
        if [ -n "$critical" ]; then critical=$critical,$package; else critical=$package; fi
        found=1
        ;;
    esac
    if [ -n "${OTAST_PI_TEST_PACKAGE:-}" ] && [ "$package" = "$OTAST_PI_TEST_PACKAGE" ]; then
      case ",$critical," in
        *",$package,"*) ;;
        *) if [ -n "$critical" ]; then critical=$critical,$package; else critical=$package; fi ;;
      esac
      found=1
    fi
  done
  [ "$found" -eq 1 ] && OTAST_STACK_DETACH_CRITICAL=$critical
  return 0
}

otast_collect_stack_observers() {
  if [ -n "${OTAST_PI_TEST_PACKAGE:-}" ]; then
    case "$OTAST_PI_TEST_PACKAGE" in
      *[!A-Za-z0-9._]*|'' )
        otast_stop "OTAST_PI_TEST_PACKAGE contains unsafe characters: $OTAST_PI_TEST_PACKAGE"
        return 1
        ;;
    esac
  fi
  _otast_stack_collect_zygisk_provider || return 1
  _otast_stack_collect_detach || return 1
}

otast_validate_qualification_environment() {
  otast_collect_stack_observers || return 1
  if [ "$OTAST_STACK_ZYGISK_PROVIDER_COUNT" -gt 1 ]; then
    otast_stop 'qualification has multiple effective module-based Zygisk providers; exactly one provider is required'
    return 1
  fi
  if [ "$OTAST_STACK_ZYGISK_PROVIDER_COUNT" -eq 0 ]; then
    otast_stop 'qualification cannot resolve the effective Zygisk provider from module state; bind the actual built-in/external provider before physical acceptance'
    return 1
  fi
  case "$OTAST_STACK_DETACH_STATE" in
    UNSAFE|MALFORMED)
      otast_stop 'zygisk-detach configuration is unsafe or malformed; qualification is inconclusive'
      return 1
      ;;
  esac
  if [ "$OTAST_STACK_DETACH_CRITICAL" != NONE ]; then
    otast_stop "qualification-critical package(s) are detached from Play Store: $OTAST_STACK_DETACH_CRITICAL"
    return 1
  fi
  return 0
}

_otast_stack_report_module() {
  local id state active_hash staged_hash
  id=$1
  state=$(_otast_stack_effective_role "$id")
  active_hash=$(_otast_stack_module_prop_hash "$id" active)
  staged_hash=$(_otast_stack_module_prop_hash "$id" staged)
  printf 'stack_module_%s_state=%s\n' "$id" "$state"
  printf 'stack_module_%s_active_module_prop_sha256=%s\n' "$id" "$active_hash"
  printf 'stack_module_%s_staged_module_prop_sha256=%s\n' "$id" "$staged_hash"
}

otast_report_stack_observers() {
  otast_collect_stack_observers || return 1
  printf 'stack_zygisk_provider=%s\n' "$OTAST_STACK_ZYGISK_PROVIDER"
  printf 'stack_zygisk_provider_count=%s\n' "$OTAST_STACK_ZYGISK_PROVIDER_COUNT"
  _otast_stack_report_module rezygisk
  _otast_stack_report_module zygisksu
  _otast_stack_report_module vector
  _otast_stack_report_module treat_wheel
  _otast_stack_report_module zygisk-detach
  printf 'stack_zygisk_detach_state=%s\n' "$OTAST_STACK_DETACH_STATE"
  printf 'stack_zygisk_detach_config_sha256=%s\n' "$OTAST_STACK_DETACH_HASH"
  printf 'stack_zygisk_detach_critical_targets=%s\n' "$OTAST_STACK_DETACH_CRITICAL"
  printf 'stack_pi_test_package=%s\n' "${OTAST_PI_TEST_PACKAGE:-UNSET}"
}
