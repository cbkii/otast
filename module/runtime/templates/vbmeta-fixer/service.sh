#!/system/bin/sh

# OTAST neutralizes the upstream runtime VBMeta writer. The bootloader-provided
# androidboot/ro.boot values remain authoritative at runtime; OTAST validates
# identity and prevents competing Yurikey/TA writers from overwriting them.
exit 0
