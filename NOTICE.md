# Notices

OTAST is Copyright © 2026 cbkii and is distributed under GPL-3.0-only.

OTAST contains original transactional runtime and host tooling plus compatibility metadata and adapted replacement scripts derived from reviewed upstream projects. OTAST does not redistribute private keys, keyboxes, device captures, credentials or proprietary factory-image binaries.

## Reviewed upstream projects

- PlayIntegrityFix / PIF Inject by KOWX712 — GPL-3.0-only. OTAST preserves upstream lifecycle entrypoints and applies narrow, reviewed transformations only to identity generation/configuration and the competing security-patch writer.
- Yurikey by Yurii0307 — GPL-3.0-only. OTAST replaces only reviewed authority-writing surfaces; unrelated functionality remains upstream-owned.
- Android-VBMeta-Fixer by Zenlua — MIT. The managed service replacement preserves bounded companion-app registration while removing competing identity writers. See `third_party/licenses/Android-VBMeta-Fixer-MIT.txt`.
- TrickyStore by 5ec1cff — upstream-owned. OTAST writes only the documented external security-patch contract and does not redistribute or patch its source tree.
- Tricky-Addon-Update-Target-List by KOWX712 — upstream-owned. OTAST transforms only the reviewed v4.4 `prop.sh` VBMeta block and preserves all other behavior and files.

Commit references and accepted SHA-256 values are recorded in `compatibility/supported-targets.json`.
