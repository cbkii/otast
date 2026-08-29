#!/system/bin/sh

# OTAST owns TrickyStore target-list policy. Yurikey must not delete or
# repopulate target.txt with every installed package.
printf '%s\n' 'OTAST: Yurikey automatic TrickyStore target regeneration is disabled.' >&2
exit 0
