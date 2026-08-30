#!/system/bin/sh

# Sourced by the Magisk installer. Do not call exit from this file.

_otast_version=$(sed -n 's/^version=//p' "$MODPATH/module.prop" 2>/dev/null | sed -n '1p')
ui_print "- OTAST ${_otast_version:-unknown}"
ui_print '- Validating Google Pixel Android 16 authority and runtime package'

_otast_install_failed=0
_otast_device=$(getprop ro.product.device 2>/dev/null)
_otast_manufacturer=$(getprop ro.product.manufacturer 2>/dev/null)
_otast_model=$(getprop ro.product.model 2>/dev/null)
_otast_sdk=$(getprop ro.build.version.sdk 2>/dev/null)

case "$_otast_device" in
  ''|*[!a-z0-9_]*)
    ui_print "! Unsupported or malformed Pixel device identity: ${_otast_device:-unknown}"
    _otast_install_failed=1
    ;;
esac
if [ "$_otast_manufacturer" != Google ]; then
  ui_print "! Unsupported manufacturer: ${_otast_manufacturer:-unknown}; expected Google"
  _otast_install_failed=1
fi
case "$_otast_model" in
  'Pixel '*) ;;
  *)
    ui_print "! Unsupported model: ${_otast_model:-unknown}; expected Google Pixel"
    _otast_install_failed=1
    ;;
esac
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

ui_print ''
ui_print '*******************************'
ui_print '*         SUCCESS !!          *'
ui_print '*******************************'
ui_print '- OTAST installation validation passed.'
ui_print ''
ui_print '- Next steps:'
ui_print '  1. Reboot the device.'
ui_print '  2. Open Magisk > Modules > OTAST > Action.'
ui_print '  3. Select Preflight (read-only).'
ui_print '  4. If Preflight passes, run Action again and select Apply.'
ui_print '  5. If Apply reports REBOOT_REQUIRED, reboot again.'
ui_print '  6. Run Action > Verify (read-only) after that reboot.'
ui_print '- Do not run Apply before the first reboot.'
