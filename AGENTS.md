# Repository engineering rules

- `/data/adb/ota.prop` is the sole authority.
- Inspect state before mutation.
- Apply and Restore are explicit transactions.
- Unknown target hashes and drift fail closed.
- Runtime shell must remain Magisk BusyBox `ash` compatible.
- Host scripts must follow `scripts/lib/common.sh` failure and summary conventions.
- Never add raw device evidence, credentials, keyboxes, private keys, local reports or generated release files.
- Never broaden target discovery beyond the explicit module IDs and paths in the compatibility manifest.
- Do not weaken strict-exclusion tests or replace exact hashing with fuzzy matching.
