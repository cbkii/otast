# Changelog

All notable user-visible changes are recorded here.

## v1.0.1

- Make `cbkii/otast` the sole supported OTAST module source and keep predecessor-name handling only as fail-closed migration detection.
- Preserve bootloader/libavb VBMeta runtime values; retain OTA-derived `ro.boot.vbmeta.size` as artifact provenance rather than forcing it over runtime telemetry.
- Require live Pixel bootconfig VBMeta digest and AVB-version evidence to be present and match OTA authority before Preflight, Apply or Verify.
- Neutralize the reviewed Android VBMeta Fixer runtime writer instead of accepting its hard-coded AVB 1.0 and block-size-derived VBMeta values.
- Harden Yurikey: make its root Action read-only by default, disable all-packages TrickyStore target regeneration, retain zero-digest/property-writer protections, and prevent implicit Zygisk Next policy changes.
- Preserve current PIF identity/spoof options and TrickyStore security-patch selection by default; OTA takeover is now explicit opt-in.
- Validate official system/vendor security patches from static partition properties rather than potentially spoofed runtime properties.
- Accept reviewed PIF Inject head `b994391970b51a2dfefed0e1d420dd6b017756e8` and TA UTL head `cf167849aaa7696972a3c7826ec94294e9e47fce` without widening OTAST's managed runtime surface.
- Add read-only Preflight to the Magisk Action menu while keeping Report as the timeout/default action.
- Extend fake-root/runtime tests for preserve-mode PIF, Yurikey writer ownership, VBMeta provenance semantics and fail-closed bootloader evidence.
- Simplify release UX and automate version preparation (#7)
- Overhaul Magisk release workflow and branch builds (#6)
- Optimize host hashing and clean-room validation safely (#2)
- feat(ci): add manual release readiness report
- fix(release): follow latest main and self-heal common failures
- feat(release): add resumable physical-device release wizard
- fix(maintenance): refresh reviewed upstream targets
- guard analysis and testbook
- fix(release): finalise exact proof and v1.0.0
- fix(tooling): preserve executable Python entrypoints
- fix(ci): pin ShellCheck with BusyBox support
- TAutil target hash
- feat: add reliable Termux maintenance and target monitoring
- Initial public release candidate

## v1.0.0 — initial stable release

- Promote the fully qualified v1.0.0 release candidate to the first stable release without expanding the managed runtime surface.
- Bind device-derived and Restore-clone proof to the exact commit-specific release ZIP rather than a rebuilt candidate.
- Add authenticated Termux maintenance, target monitoring, bounded report cleanup and clearer review/error outcomes.
- Pin CI and release validation to ShellCheck v0.11.0 and preserve executable source entrypoint modes.

## v1.0.0-rc.3 — reboot-boundary and live-contract correction

- Separate immutable platform identity checks from runtime VBMeta outputs managed by OTAST.
- Allow Preflight and Apply to repair stale VBMeta size/version values produced by the pre-OTAST stack.
- Require the authoritative VBMeta digest, size and AVB versions only during post-reboot Verify.
- Report `REBOOT_REQUIRED` after a successful Apply.
- Add a fake-root `reboot` action that executes the managed VBMeta Fixer service with a private `resetprop` shim.
- Start exact-ZIP qualification from deliberately conflicting pre-OTAST VBMeta values and prove pre-reboot Verify fails before simulated reboot succeeds.

## v1.0.0-rc.2 — stack-consistency correction

- Correct `/data/adb/boot_hash` to carry the authoritative VBMeta digest rather than the boot image SHA-256.
- Preserve PIF Inject Action, post-fs-data, service, WebUI and updater lifecycle entrypoints byte-for-byte.
- Narrow PIF management to `autopif.sh`, `autopif_ota.sh`, `pif.prop` and the competing `security_patch.sh` writer.
- Merge authority values into PIF configuration without dropping unrelated options or comments.
- Convert PIF refresh re-entry into read-only reconciliation; explicit Apply remains required.
- Replace unsupported TA UTL guard-file assumptions with an exact v4.4 `prop.sh` transformation that neutralises only its overlapping VBMeta writer.
- Make the managed VBMeta Fixer service the sole writer for authoritative VBMeta digest, size and AVB versions.
- Verify live VBMeta digest, size and AVB versions after reboot, while allowing explicit Apply to correct stale pre-OTAST writers.
- Block normal operation while legacy `ota-sot` or `otasst` traces remain.
- Add exact-source and fake-root regressions for PIF lifecycle preservation, TA UTL preservation, generator conflicts and legacy-governor conflicts.

## v1.0.0-rc.1 — initial public release candidate

- Establish the independent `otast` Magisk module identity and `/data/adb/otast` state root.
- Treat `/data/adb/ota.prop` as the sole device authority.
- Add journaled Apply, Verify, Restore and interrupted-transaction recovery.
- Add reviewed target contracts for PIF Inject, TrickyStore, Yurikey, TA UTL and Android VBMeta Fixer.
- Add exact-hash compatibility gates and managed-drift rejection.
- Add deterministic Magisk ZIP and public source ZIP builders.
- Add synthetic exact-ZIP fake-Magisk-root qualification.
- Add private Pixel fixture capture, sanitization, cloning and validation tools.
- Add public privacy, repository, CI, monitoring and owner-gated release tooling.
