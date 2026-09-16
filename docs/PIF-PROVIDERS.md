<!-- GENERATED from compatibility/pif-providers.json; do not hand-edit. -->
# PIF provider contracts

Both reviewed implementations use module ID `playintegrityfix`; they are mutually exclusive providers, not co-installable targets.

Preferred provider: `kowx-inject-s`.

A provider preference change requires exact-stack physical Pixel qualification; repository support alone is insufficient.

| Provider | Status | Reviewed source | Profile precedence | Security-patch writer boundary |
|---|---|---|---|---|
| `kowx-inject-s` | `SUPPORTED_PREFERRED` | `KOWX712/PlayIntegrityFix@73552eec78f1e733573192333e9a7453b8de0662` | `/data/adb/pif.prop` → `/data/adb/modules/playintegrityfix/pif.prop` → `/data/adb/modules_update/playintegrityfix/pif.prop` | `module/security_patch.sh` / `SURGICAL_REVIEWED_BOUNDARY` |
| `osm0sis-fork-v18` | `SUPPORTED_CANDIDATE_PHYSICAL_QUALIFICATION_REQUIRED` | `osm0sis/PlayIntegrityFork@6d2307ff5037519982205e66bda1132d0d8cc4da` | `/data/adb/modules/playintegrityfix/custom.pif.prop` → `/data/adb/modules_update/playintegrityfix/custom.pif.prop` | `module/autopif4.sh` / `SURGICAL_REVIEWED_BOUNDARY` |

## Runtime policy

- Inject-S retains PR #41's canonical global/active/staged profile and immutable mirror-generation state machine.
- Fork v18 uses provider-owned `custom.pif.prop`; OTAST never mirrors or rewrites it.
- Fork's reviewed native loader uses `custom.pif.prop > custom.pif.json > pif.prop > pif.json`; a present custom prop is therefore authoritative even when a JSON file also exists.
- JSON-only Fork configuration fails closed in the OTAST runtime. Upstream supports JSON, but OTAST deliberately avoids an ad-hoc shell JSON parser; migrate to `custom.pif.prop` before Apply.
- Fork `autopif4.sh` remains the profile generator, but its direct TrickyStore `security_patch.txt` mutation is suppressed because that external contract belongs to OTAST. TEESimulator/OhMyKeyMint warning flow and the remaining profile/killpi lifecycle are preserved.
- Active/staged trees must resolve to the same reviewed provider implementation. A cross-provider staged transition fails closed; OTAST never switches providers automatically.

## Maintenance impact classes

Provider source movement is classified as docs/CI only, preserved non-writer surface, module identity, native dependency, target writer, new writer capability, removed writer capability, or ambiguous/unknown writer behavior. New, removed, or ambiguous writer behavior always requires explicit review and cannot advance compatibility automatically.
