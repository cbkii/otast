# OTAST development playbook

The playbook is a sourceable operator layer over the repository's existing
runtime, build, fake-root, capture and validation scripts. It does not move or
reimplement those contracts.

## Enable the command

```bash
source "$HOME/repos/otast/scripts/otast-playbook.sh"
source "$HOME/repos/otast/scripts/otast-playbook-completion.bash"

otast help
```

The kit installer can add guarded source lines to `~/.bashrc` with
`--shell-init`.

## Stable release — one command

The normal owner-facing v1 release interface is deliberately one resumable
command:

```bash
otast release
```

The command creates or reuses the exact GitHub draft, verifies and installs that
asset on the owned Pixel, drives the changing Apply across a real reboot, proves
post-reboot Verify, proves the second Apply is a no-op, Restores the original
managed files, proves the post-Restore reboot, uploads sanitized proof, and then
asks to publish that same draft without rebuilding it.

Whenever it requests a reboot, wait for Android to finish booting and run the
**same command again**:

```bash
otast release
```

No lifecycle subcommands need to be memorised. `otast release --status` shows the
private resumable phase without changing anything. See [`RELEASE.md`](RELEASE.md)
for the release contract and recovery options.

## Normal module-development cycle

```bash
otast doctor
otast status
otast test quick
otast synthetic
```

Before final qualification:

```bash
otast test full
otast refresh device --prove --restore-clone
otast export latest
otast qualify --fixture latest
```

## Fake-root refresh modes

### Current installed device stack

```bash
otast refresh device
```

This reads only the explicit sanitized OTAST target allow-list from live
`/data/adb`, publishes a private fixture, and builds a new disposable fake root
with the exact current OTAST candidate.

To run the full lifecycle immediately:

```bash
otast refresh device --prove --restore-clone
```

### Existing immutable fixture

```bash
otast refresh fixture latest --name tegu-debug
```

This touches neither live `/data/adb` nor the source fixture.

### New upstream target release

For a target monitored through GitHub Releases:

```bash
otast upstream assets playintegrityfix

otast refresh upstream playintegrityfix \
  --asset-regex 'inject.*\.zip$' \
  --name pif-update-review
```

### New upstream branch commit

The target monitor compares branch heads for targets such as Yurikey. A reported
branch commit must be reviewed at that exact commit rather than replaced with the
latest release asset.

```bash
otast upstream ref yurikey --ref 5330b77c0b797e580c582d43e91ceae5b450dce6

otast refresh upstream yurikey \
  --ref 5330b77c0b797e580c582d43e91ceae5b450dce6 \
  --fixture latest \
  --tree modules_update \
  --name yurikey-5330b77-review
```

`fetch-ref` downloads the GitHub source archive at the resolved immutable commit.
The complete repository tree is retained, while the unique `module.prop` root is
used to derive the inert static module model. Do not combine `--ref` with release
selectors such as `--tag`, `--asset`, or `--include-prerelease`.

The upstream workflow is intentionally split into evidence and runtime model.

## Upstream evidence strategy

### Why installer files are retained

Magisk sources `customize.sh` inside its installer environment. It can set
`SKIPUNZIP`, `REPLACE`, `REMOVE`, generate files, alter modes, inspect the device,
source helpers and write outside the module directory. Removing installer code
from evidence would hide compatibility conflicts.

OTAST therefore retains:

```text
~/.cache/otast/upstream-candidates/<target>/<release-tag-ref-or-local-hash>/
├── original-release.zip
├── candidate.json
├── inventory.json
├── installer-analysis.json
├── module-root.txt
└── source-tree/
    ├── customize.sh
    ├── install.sh
    ├── META-INF/
    └── complete remaining package tree
```

The exact asset filename is preserved instead of always being renamed to
`original-release.zip`.

### Why installer files are not executed

The normal on-device workflow does not need a VM or `proot`. Upstream installer
execution would add complexity without producing release-quality proof:

- a shell sandbox cannot faithfully reproduce Magisk/Android installer state;
- `proot` is path translation rather than kernel namespace, seccomp or network
  isolation;
- packaged native binaries and direct syscalls cannot be safely or faithfully
  modelled by shell command shims;
- the owned Pixel can provide the authoritative post-install tree through a
  read-only sanitized capture.

Consequently:

```text
customize.sh            RETAINED_NOT_EXECUTED
install.sh              RETAINED_NOT_EXECUTED
META-INF installer      RETAINED_NOT_EXECUTED
packaged native files   INVENTORIED_NOT_EXECUTED
network                 NOT_USED_BY_TOOL
root/su                  NOT_USED_BY_TOOL
```

### Static installer analysis

The analysis records line-level findings for:

- `SKIPUNZIP`, `REPLACE` and `REMOVE`;
- permission/context operations;
- file generation, movement and deletion;
- `/data/adb`, partition, property and block-device paths;
- `resetprop`, `settings`, `pm`, `cmd`, mounts and similar privileged commands;
- network commands;
- dynamic execution such as `eval`, variable sourcing and command substitution;
- packaged ELF/DEX/PE files and references to them;
- global `service.d` and `post-fs-data.d` installation.

The result is classified as:

```text
NO_CUSTOM_INSTALLER
STATIC_MODEL_PARTIAL
STATIC_MODEL_INCOMPLETE
```

A `BLOCK` finding does not mean the package is malicious. It means static default
extraction cannot claim to model all installer effects and device capture is
required before profile acceptance.

### Static fake-root materialization

```bash
otast upstream materialize playintegrityfix \
  ~/.cache/otast/upstream-candidates/playintegrityfix/<tag>/<asset>.zip \
  latest \
  --tree modules_update
```

The fake target tree contains Magisk's default-extracted module payload. Installer
entrypoints are excluded only from the assumed installed tree. They remain in the
private complete source tree and are copied as read-only shell evidence below:

```text
<fake-root>/.otast/upstream-evidence/<target>/<sha-prefix>/
```

The fake root is marked:

```text
qualification=STATIC_INSTALL_MODEL_ONLY
installer_executed=false
installer_code_retained=true
```

This static tree is useful for OTAST profile/hash/writer classification, staged
update precedence, fail-closed behavior and source review. It is not a substitute
for a real installed postimage.

### Compare active capture with staged candidate

```bash
otast upstream compare playintegrityfix latest
```

This writes a hash/mode/path comparison between:

```text
data/adb/modules/<target>          device-captured active tree
data/adb/modules_update/<target>   static upstream candidate
```

The report is explicitly labelled
`ACTIVE_DEVICE_CAPTURE_VS_STATIC_CANDIDATE_DELTA`; differences can come from a
new upstream version as well as installer behavior.

## Manual fake-root lifecycle

```bash
otast reset latest tegu-debug
otast action tegu-debug report
otast action tegu-debug preflight
otast action tegu-debug apply
otast action tegu-debug reboot
otast action tegu-debug verify
otast action tegu-debug restore
```

After a changing Apply, the expected boundary is:

```text
apply -> pre-reboot verify rejected -> reboot -> verify passes
```

## Device-derived proof

```bash
otast prove latest --restore-clone
```

This proves report, preflight, Apply, expected reboot boundary, post-reboot
Verify, second-Apply idempotency, final Verify and optional Restore in a separate
clone.

## Export and final qualification

```bash
otast export latest
otast qualify --fixture latest
```

The final qualifier runs full tests/ShellCheck, privacy, deterministic builds,
commit binding, source packaging, synthetic lifecycle, device-derived proof,
Restore proof and analysis export. The qualifier passes that exact already-built ZIP
through the primary and Restore-clone proofs; those stages never rebuild a second
candidate with different `release.properties` commit binding. It performs no Git or
GitHub writes.

## Safety guard

Operational commands must run as the normal Termux UID. Running the playbook,
upstream helper, proof, exporter or qualifier as root stops before work begins.
The device capture command itself also runs as the normal user and delegates only
its bounded read-only `/data/adb` collection step through `su`.

Before every fake-root action, the guard verifies:

- the root is a direct descendant of `~/.cache/otast/fake-roots`;
- no path component through `data/adb` is a symbolic link;
- the root, `data/adb` and marker belong to the invoking Termux UID;
- `.otast-fake-root` is a regular non-symlink file;
- fake `data/adb` does not resolve to live `/data/adb`.

Upstream output and evidence roots must remain below
`~/.cache/otast/upstream-candidates`. This is a containment rule, not merely a
shared-storage exclusion.

`installer-analysis.json` contains a `path_surfaces` section. It reports literal
`/data/adb` paths, module trees, global Magisk script paths, common path-variable
assignments, sourced helpers, native executable references and unresolved
variable-derived paths. The report is observational: no source literal or variable
is rewritten.

## Safety boundaries

- Live `/data/adb` is read only by the capture script.
- Upstream packages remain in Termux private storage.
- No upstream shell script or native binary is executed.
- Full installer/source code remains available for static review.
- Fake roots exist only below `~/.cache/otast/fake-roots`.
- Apply, simulated reboot and Restore run only against those marked roots.
- Device capture is the authority for actual Magisk installation outcomes.
- No playbook command commits, pushes, tags, publishes or installs OTAST live.

## Ongoing Termux maintenance

The preferred interface is now:

```bash
otast maintain
otast review TARGET
otast accept TARGET
otast prepush
```

These commands provide authenticated GitHub monitoring, structured target-review evidence, a guarded single-field baseline transition, persistent logs, distinct review/error statuses, and successful-run report cleanup. See [`docs/MAINTENANCE.md`](MAINTENANCE.md) for the complete procedure and troubleshooting contract.
