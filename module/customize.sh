#!/system/bin/sh

# Sourced by the Magisk installer. Do not call exit from this file.

ui_print '- OTAST v1.0.0-rc.3'
ui_print '- Validating Pixel 9a Android 16 authority and runtime package'

_otast_install_failed=0
_otast_device=$(getprop ro.product.device 2>/dev/null)
_otast_sdk=$(getprop ro.build.version.sdk 2>/dev/null)
if [ "$_otast_device" != tegu ]; then
  ui_print "! Unsupported device: ${_otast_device:-unknown}; expected tegu"
  _otast_install_failed=1
fi
if [ "$_otast_sdk" != 36 ]; then
  ui_print "! Unsupported SDK: ${_otast_sdk:-unknown}; expected 36"
  _otast_install_failed=1
fi
if [ ! -f /data/adb/ota.prop ] || [ -L /data/adb/ota.prop ]; then
  ui_print '! Missing or unsafe authority: /data/adb/ota.prop'
  _otast_install_failed=1
fi
for _otast_required in action.sh post-fs-data.sh service.sh uninstall.sh runtime/entry.sh runtime/common.sh runtime/authority.sh runtime/transaction.sh runtime/profiles.sh runtime/pif.sh runtime/ta.sh runtime/report.sh; do
  if [ ! -f "$MODPATH/$_otast_required" ] || [ -L "$MODPATH/$_otast_required" ]; then
    ui_print "! Missing or unsafe package file: $_otast_required"
    _otast_install_failed=1
  fi
done
if [ "$_otast_install_failed" -ne 0 ]; then
  abort 'OTAST installer validation failed; no runtime changes were applied.'
fi

set_perm_recursive "$MODPATH" 0 0 0755 0644
for _otast_exec in customize.sh action.sh post-fs-data.sh service.sh uninstall.sh runtime/entry.sh; do
  set_perm "$MODPATH/$_otast_exec" 0 0 0755
done

if ! ADB_ROOT=/data/adb OTAST_AUTHORITY=/data/adb/ota.prop sh "$MODPATH/runtime/entry.sh" preflight >/dev/null 2>"$TMPDIR/otast-preflight.log"; then
  ui_print '! OTAST preflight failed:'
  while IFS= read -r _otast_line; do ui_print "! $_otast_line"; done <"$TMPDIR/otast-preflight.log"
  abort 'OTAST was not installed because authority or target compatibility is unsafe.'
fi
ui_print '- Preflight passed; install the module and reboot'
