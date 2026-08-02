# Fake Magisk root

OTAST has two fake-root paths.

## Synthetic exact-ZIP qualification

```bash
bash scripts/fake-magisk-root.sh
```

This builds the deterministic Magisk ZIP, validates it, safely extracts that exact ZIP under a temporary fake `data/adb/modules/otast`, and executes the runtime with BusyBox `ash` where available.

The gate covers:

- active and staged target selection;
- authority/live-identity matching;
- exact writer and external-contract planning;
- minimal-impact PIF transforms while preserving upstream Action, boot and service entrypoints;
- TA UTL v4.4 narrow VBMeta-writer removal and VBMeta Fixer ownership;
- full vbmeta digest, size and AVB-version authority checks;
- legacy governor and automatic PIF security-patch conflict rejection;
- Apply, Verify and no-op Apply;
- authority update;
- transaction interruption and boot recovery;
- unknown-hash and symlink rejection;
- Verify, Apply and Restore drift rejection;
- complete Restore and original-byte recovery;
- strict-exclusion sentinel preservation.

## Device-derived clone

First remove any legacy `ota-sot`/`otasst` governor with the standalone cleanup utility. Capture then refuses unresolved legacy module, state or dispatcher traces. Create a private sanitized fixture and disposable clone:

```bash
bash scripts/capture-device-fixture.sh --label tegu-current
bash scripts/reset-fake-magisk-root.sh \
  "$HOME/.local/share/otast/device-fixtures/tegu-current" \
  tegu-current
```

The reset command installs the exact newly built module ZIP into the clone. Validate or mutate the clone without touching live `/data/adb`:

```bash
bash scripts/validate-fake-magisk-root.sh \
  "$HOME/.cache/otast/fake-roots/tegu-current" \
  preflight
```

## Boundary

A fake root does not emulate Android init, the Magisk daemon, mount namespaces, SELinux enforcement, Binder, HALs, the bootloader, TEE or Titan M2. Physical-device validation remains required for release acceptance after runtime, installer or boot changes.
