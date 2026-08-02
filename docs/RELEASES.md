# Releases

## Local candidate

```bash
bash scripts/test.sh --full
bash scripts/build-release.sh
```

The module ZIP is deterministic: fixed member order, timestamp, compression and modes. `release.properties` binds the package to the current version and, when Git history exists, the exact source commit.

## Public source package

```bash
bash scripts/package-public-repo.sh
```

The source ZIP contains one top-level `otast/` directory and excludes Git history, reports, release outputs and Python caches.

## GitHub workflow

The release workflow defaults to validation only. Publishing is an explicit owner-only dispatch. It runs the full gate, verifies that the requested version equals `module.prop`, builds the exact ZIP and checksum, and creates the corresponding GitHub release without mutating source metadata.

Release acceptance still requires physical Pixel validation for runtime-, installer- or boot-sensitive changes.
