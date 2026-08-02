# Architecture

## Authority

`/data/adb/ota.prop` is the sole authority. The runtime validates its shape, Pixel 9a identity, Android SDK, security patch dates, fingerprint, boot image digest and the complete VBMeta digest/size/AVB contract before planning work. It separately compares the live runtime identity with the authority and stops on any mismatch.

## Discovery

Discovery is explicit. OTAST checks only the module IDs and paths declared in `compatibility/supported-targets.json`. It prefers a staged module under `modules_update` and also evaluates the active module where both exist. Removed, disabled, symlinked and unsafe trees are ignored or rejected according to context.

## Planning

Each planned path is classified before mutation:

- `CURRENT`: managed bytes, mode and authority are current; no operation is added.
- `NEW`: a reviewed path is not yet managed; original bytes or absence are recorded.
- `UPDATE`: an existing managed path is unchanged from the previous managed result but the authority or managed template changed.
- `DRIFT`: live bytes or mode differ from recorded managed state; planning stops.

Exact replacement requires an accepted upstream SHA-256 unless the live path is already tracked by a valid state record. Reviewed transformations additionally require exact anchors and byte-valid shell output. External contracts have fixed paths, content and modes.

## Transactions

Apply and Restore acquire a process lock, create a private transaction directory, write `IN_PROGRESS`, journal each path before mutation, preserve the previous state record, perform an atomic file replacement, verify bytes and mode, and finally write `COMMITTED`.

A failure rolls the journal back in reverse order. A transaction left `IN_PROGRESS` is recovered during `post-fs-data` before later operations are permitted.

## Persistent state

The first Apply stores the original bytes and mode under `/data/adb/otast/backups`. Later authority updates retain that original evidence. Restore succeeds only when the current target still equals the recorded managed result and the original backup hash remains valid.

## Boot behavior

`post-fs-data.sh` performs bounded interrupted-transaction recovery only. `service.sh` exits immediately. OTAST does not automatically Apply or poll target modules.

## Property ownership

`/data/adb/boot_hash` carries `ro.boot.vbmeta.digest`; it never carries `boot.img.sha256`. The managed VBMeta Fixer service is the single runtime owner for VBMeta digest, size and AVB versions. TA UTL v4.4 keeps all non-vbmeta behavior but its overlapping vbmeta block is removed. Live identity comparison covers the same complete VBMeta contract before planning.

## Legacy transition

Known `ota-sot` and `otasst` module, state and dispatcher paths are explicit blockers. OTAST does not adopt or delete them. A separate restore-first cleanup must prove their managed targets were returned to upstream originals before their traces are removed.
