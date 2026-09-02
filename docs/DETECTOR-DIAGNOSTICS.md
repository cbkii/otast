# Detector diagnostics

OTAST's detector tooling is **read-only attribution**, not an automatic root-hiding or policy-rewrite layer. Use it after a fresh detector run when a finding must be tied to a concrete mount, executable mapping, SELinux rule, or module configuration.

## Root-exposure doctor

Run the target detector first and leave its process alive. For Duck Detector:

```bash
python3 scripts/root-exposure-doctor.py \
  --package com.eltavine.duckdetector \
  --detector-mount-claim suspicious \
  --output "$HOME/otast-root-doctor.json" \
  | tee "$HOME/otast-root-doctor.stdout.json"
```

The doctor:

- prefers a working Binder-safe `sudo` root backend when available and otherwise falls back to `su`;
- bounds every external command;
- contains optional collection failures rather than discarding already-collected evidence;
- records exact bounded `/proc/<pid>/mounts` and `/proc/<pid>/mountinfo` snapshots for every discovered target process, including package child processes;
- records line-numbered mount entries containing direct root-stack tokens;
- captures executable `/data/adb`/Zygisk/LSPosed mappings;
- enumerates active Magisk modules and scans their `sepolicy.rule` files for known dirty-policy edges;
- records current Inline Hook Invalidate and Zygisk Next configuration relevant to the target process;
- runs OTAST Report as optional corroboration. A Report timeout is a diagnostic coverage limitation and does **not** terminate mount/maps/SELinux collection.

The output deliberately refuses Tricky Store keybox content. It also performs no `resetprop`, denylist edits, chmod concealment, module changes, or Zygisk Next configuration writes.

## Mount evidence

A detector headline such as `1 critical mount signal(s)` is not sufficient for configuration changes. The doctor records both full bounded process snapshots and `mount_token_matches` / `mountinfo_token_matches` with exact line numbers. Compare the target process with the included init/root-shell namespace baselines before deciding whether the signal is:

- an actual target-visible root-managed mount;
- a token in an otherwise ordinary mount entry;
- confined to another namespace; or
- inconsistent with the detector's own detailed mount methods.

Do not change mount/unmount policy until the exact offending entry is identified.

## SELinux attribution

The doctor tracks these currently relevant DirtySepolicy-style edges:

| Edge | Reviewed source attribution |
| --- | --- |
| `system_server -> system_server:process execmem` | Magisk core policy |
| `untrusted_app -> magisk:binder call` | Magisk core policy |
| `untrusted_app -> xposed_data:file read` | Vector / LSPosed family policy |
| `zygote -> adb_data_file:dir search` | Zygisk-loader-family pattern; active module-file match is required for device-specific attribution |

For active Magisk modules, `policy_edge_attribution[].module_file_matches` is the physical-device evidence. Known-source labels explain reviewed upstream provenance; they do not override the live file scan.

The first two Magisk edges are part of Magisk's own root/Zygisk policy, not OTAST policy. Vector's reviewed `sepolicy.rule` defines `xposed_data` and grants wildcard file/directory access. The final zygote/`adb_data_file` edge is common in Zygisk loaders, so exact attribution must come from the device's installed `sepolicy.rule` files.

## Inline Hook Invalidate

Reviewed Inline Hook Invalidate source reads:

```text
/data/adb/modules/inline_hook_invalidate/config.txt
```

The first line controls enabled/library/method; following lines are exact target process names. Its target list decides whether the post-specialize remap thread runs. It does **not** request the Zygisk `DLCLOSE_MODULE_LIBRARY` option for non-target processes.

Therefore removing an app from the IHI target list can stop IHI's remap activity for that app, but it does not guarantee that the IHI Zygisk library disappears from `/proc/<pid>/maps`. A zero-map design for non-targets requires an upstream/module-code change that safely requests `DLCLOSE_MODULE_LIBRARY` before starting any persistent module code. Do not use that option for configured targets while IHI's detached remap thread executes module code.

The upstream project itself warns that inline-hook invalidation can cause random malfunctions/crashes and should be used narrowly.

## Zygisk Next

Zygisk Next 1.5.0 is a standalone Zygisk implementation. Current public source does not expose enough loader internals to infer a safe no-injection configuration purely from repository code.

The known `denylist_enforce=2` policy is documented in the ecosystem as `just_umount` / **Unmount Only**. It should not be interpreted as a promise that `libzygisk.so` will be absent from a denylisted process.

The doctor records, without changing them:

- `/data/adb/zygisksu/denylist_enforce`;
- `/data/adb/zygisksu/memory_type`;
- `/data/adb/zygisksu/linker`;
- installed Zygisk Next `module.prop`;
- Duck matches from `magisk --denylist ls`;
- bounded `zygiskd --help` output.

Do not switch Zygisk Next enforcement/memory/linker modes just to remove a detector warning until the installed 1.5.0 CLI/config semantics are captured and the effect can be tested as a single controlled variable. The current stack has working Tricky Store attestation and Play Integrity behavior that must not be destabilized by speculative loader changes.
