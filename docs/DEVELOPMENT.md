# Development

## Termux

Use Termux private storage:

```bash
mkdir -p "$HOME/repos"
cd "$HOME/repos/otast"
bash scripts/bootstrap-termux.sh
```

Android shared storage does not provide reliable executable-bit and symlink behavior for a Git working tree.

## Test levels

```bash
bash scripts/test.sh --quick
bash scripts/test.sh --standard
bash scripts/test.sh --full
```

- `quick`: environment, syntax, privacy, deterministic build and unit/fake-root tests.
- `standard`: adds ShellCheck for maintained Bash and BusyBox sources.
- `full`: adds deterministic public-source packaging, clean extraction, unrelated-working-directory execution and clean Git initialization.

## Runtime changes

Runtime files use `#!/system/bin/sh` and must parse under BusyBox `ash`. Do not use Bash arrays, process substitution, `mapfile` or unbounded waits in module code.

## Compatibility changes

Record exact upstream repository, commit/ref, source kind, accepted writer hashes, modes and managed template hashes. Add a negative unknown-hash test and rerun the full exact-ZIP qualification.

## Android shared-storage extraction

The repository must ultimately live under Termux private storage. If Android shared storage flattened modes while transferring the ZIP, run:

```bash
bash scripts/restore-source-modes.sh
```

`bootstrap-termux.sh` runs this repair automatically before checking dependencies.
