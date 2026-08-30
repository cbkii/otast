# Changelog

All notable user-visible changes are recorded here.

## v1.0.2

- Simplify Release into one authoritative workflow (#14)
- Fix Magisk Action volume-key menu (#13)

## v1.0.1

- Merge pull request #12 from cbkii/fix/release-preflight-auto-patch
- tests: prove exact PIF auto-patch marker preservation
- tests: qualify enabled PIF auto-patch state
- tests: cover enabled PIF auto-patch compatibility
- docs: define safe handling for enabled PIF auto patch
- docs: allow existing PIF auto-patch flag under OTAST ownership
- fix: absorb enabled PIF auto-patch state during Apply
- Merge pull request #11 from cbkii/fix/yurikey-vbmeta-hardening
- docs(release): link physical proof runbook
- docs(release): align guide with optional physical proof
- docs(release): document physical Pixel proof workflow
- Harden manual Release workflow and make physical proof optional (#8)
- Simplify release UX and automate version preparation (#7)
- Overhaul Magisk release workflow and branch builds (#6)
- Optimize host hashing and clean-room validation safely (#2)
- feat(ci): add manual release readiness report
- fix(release): follow latest main and self-heal common failures
- feat(release): add resumable physical-device release wizard

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
