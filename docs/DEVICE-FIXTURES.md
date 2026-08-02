# Private device fixtures

Device fixtures are never repository content.

## Capture

```bash
bash scripts/capture-device-fixture.sh --label tegu-current
```

The collector verifies root, `tegu` and SDK 36, then archives only an explicit allow-list:

- `ota.prop`, `boot_hash`, the TA guard and TrickyStore patch contract;
- active and staged PIF, TrickyStore, Yurikey, TA UTL and VBMeta Fixer trees.

It does not enumerate unrelated module trees. Tar extraction is bounded and validated before sanitization.

## Sanitization

The sanitizer excludes databases, keyboxes, private-key material, logs, credentials and unsupported special files. `/data/adb/...` symlink targets are rewritten to remain inside the fake tree. Absolute links outside `/data/adb` and escaping relative links are rejected.

The sanitized fixture is stored beneath:

```text
$HOME/.local/share/otast/device-fixtures/<label>
```

Disposable clones are restricted to:

```text
$HOME/.cache/otast/fake-roots/<name>
```

Neither location should be committed or uploaded.
