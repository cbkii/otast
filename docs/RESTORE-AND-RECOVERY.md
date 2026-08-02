# Restore and recovery

## Restore

Restore is explicit. For every managed path, OTAST proves that live bytes and mode still equal the recorded managed result. It then verifies the persistent original backup and restores it atomically.

If a target module, user or another tool changed a managed path after Apply, Restore stops. Diagnose the drift before deciding whether to recover the target manually or return it to the recorded managed bytes.

## Interrupted transactions

Every transaction is marked `IN_PROGRESS` before the first target mutation and journals the previous bytes and state record. `post-fs-data.sh` runs bounded `boot-recover`, which rolls an unfinished journal back in reverse order.

A failed recovery is an unsafe-to-continue condition. Preserve `/data/adb/otast/transactions` and do not delete state or retry Apply blindly.

## Uninstall

The Magisk uninstall script attempts Restore first. If Restore is blocked, it records `UNINSTALL_RESTORE_FAILED` under the OTAST state root and returns failure instead of silently deleting recovery evidence.
