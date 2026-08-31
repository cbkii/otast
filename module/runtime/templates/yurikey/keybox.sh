#!/system/bin/sh
# otast managed
# Yurikey's unattended remote keybox updater is disabled while OTAST owns the stack.
# Keybox replacement is an explicit local transaction after cryptographic validation.
printf '%s\n' '[OTAST] Yurikey automatic keybox replacement is disabled; active Tricky Store OSS keybox was not changed.' >&2
exit 0
