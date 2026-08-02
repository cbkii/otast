#!/system/bin/sh

# The upstream action also mutates persistent properties and developer settings.
# Those operations conflict with /data/adb/ota.prop as the sole authority.
printf '%s\n' 'OTAST: Yurikey property/developer-setting cleanup is disabled.' >&2
exit 0
