# Changelog

All notable user-visible changes are recorded here.

## v1.0.3

- compat: correct TA UTL v4.4 release asset digest
- release: do not retry deterministic compatibility blockers
- test: require deterministic compatibility failures to avoid redispatch
- release: distinguish pinned artifacts from branch drift
- test: cover pinned-artifact release gating
- release: gate pinned artifacts separately from branch drift
- Accept reviewed Yurikey remote key rotation (#35)
- docs: record accepted PIF native-equivalent baseline
- compat: accept PIF build-only native-equivalent head
- test: remove vacuous upgrade scenario booleans
- test: verify restore preserves original managed modes
- test: prove candidate-bound proof provenance
- fix: validate proof provenance from exact candidate ZIP
- fix: bind proof registry provenance to exact candidate ZIP
- test: match resolved git provenance path
- test: bind physical wrapper to GitHub-main provenance
- test: prove upgrade state and backup modes survive
- test: make upgrade qualification assertions explicit
- test: prove native reviews cannot be accepted
- fix: validate authority against selected repository
- test: exercise production PIF profile date validator
- test: pin target monitor cadence contract
- test: harden physical proof negative coverage
- fix: bind TA UTL release artifact provenance
- fix: contain platform paths and bind workflow artifacts
- fix: distinguish committed apply from state migration failure
- fix: collect native evidence for physical proof flow
- fix: make release monitor path valid and current
- fix: bind reusable proofs to current qualification
- fix: bind release properties to module identity
- fix: require complete linear upstream comparisons
- fix: bound and validate native evidence inventory
- fix: fail closed on incomplete device evidence
- fix: require runtime authority fingerprint
- fix: fail closed on unsafe PIF profile state
- fix: harden qualification provenance validation
- fix: bind authority parsing to selected repository
- fix: canonicalize runtime digest ZIP inputs
- fix: harden compatibility status rendering
- fix: reject incomplete target path evidence
- ci: use Node 24 upload-artifact pin
- test: cover PIF refresh reset and WebUI lifecycle
- test: qualify retired PIF profile ownership across upgrades
- fix: restore generated compatibility status link
- fix: retain managed target role for PIF registry
- fix: separate PIF profile ownership from platform authority
- test: preserve predecessor backups while allowing new managed surfaces
- test: run published predecessor upgrade when history is available
- test: qualify upgrade from published v1.0.2 runtime
- docs: link repository governance contract
- docs: define repository protection and review contract
- docs: align release summary with mandatory stable gates
- docs: make stable Pixel proof requirement explicit
- docs: document current stable release qualification gates
- test: bind runtime-equivalent proof reuse to both source commits
- test: match Dependabot action update configuration
- test: align public release contract with stable qualification gates
- test: assert transactional upgrade rehydration contract
- test: model transactional self-file rehydration on upgrade
- fix: transactionally rehydrate self-managed system.prop after upgrade
- test: enforce immutable action and release gate contracts
- release: gate stable publication on fresh monitor and physical proof
- ci: avoid secondary artifact failure after skipped build
- ci: pin branch-build actions to immutable SHAs
- test: cover predecessor-to-candidate fake-root upgrades
- test: make predecessor identity version-agnostic
- test: add deterministic fake-root upgrade qualification
- test: make maintenance classifier coverage hermetic
- test: align runtime contract assertions with current ownership model
- Add maintainable updates for pinned Actions
- Pin CI actions and retain exact release evidence
- Run daily pinned upstream target monitoring
- Bind native runtime evidence into physical qualification
- Align vendor SPL assertion with fail-closed wording
- Make source-compare test independent of local gh auth
- Add runtime equivalence and qualification registry tests
- Update physical proof tests for runtime-bound schema
- Expose runtime and qualification validation commands
- Generalize physical lifecycle and bind qualification evidence
- Expand device proof to runtime-bound evidence schema
- Add read-only physical qualification collector
- Validate qualification and runtime provenance in repository gate
- Make release manifest runtime-provenance aware
- Bind module builds to canonical runtime digest
- Add qualification registry and attribution contracts
- Add physical qualification evidence registry
- Add canonical runtime payload digest
- Bind physical release proof to compatibility release reference
- Align compatibility model with semantic acceptance
- Document semantic target maintenance workflow
- Document platform and observed-environment configuration boundaries
- Document managed target compatibility bases
- Document platform-profile compatibility architecture
- Document evidence-based Pixel compatibility model
- Test native runtime evidence boundaries
- Add read-only native runtime compatibility evidence collector
- Test semantic maintenance review contract
- Integrate semantic upstream impact into maintenance review
- Add compatibility architecture regression suite
- Align Pixel scope tests with qualification tiers
- Align runtime contracts with platform profiles
- Regenerate compatibility status
- Harden compatibility registry validation and impact precedence
- Tighten support qualification and artefact identity
- Expand platform authority regression coverage
- Document evidence-based compatibility architecture
- Add generated compatibility status
- Validate installer against reviewed platform profile
- Source reviewed platform contract in runtime entry
- Require platform profile and independent vendor SPL at runtime
- Validate compatibility registry in repository verification
- Bind host authority parsing to platform profiles
- Add PIF native dependency regression fixture
- Add generated compatibility documentation helper
- Add semantic upstream impact CLI
- Add BusyBox Android platform runtime mirror
- Add compatibility registry validation and impact classifier
- Refactor compatibility registry to schema v5
- Add Android 16 compatibility platform profile
- Harden detector diagnostics and release auth (#27)
- Bound release helper network calls and resume cleanly (#26)
- Relax brittle Yurikey source-hash gates (#25)
- Neutralize TA UTL WebUI direct VBMeta writer (#24)
- Add read-only root exposure doctor (#23)
- Fix stale release-draft recovery (#22)
- Make OTA security patch authoritative at runtime (#21)
- Generalize OTAST for Pixel device family (#15)

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
