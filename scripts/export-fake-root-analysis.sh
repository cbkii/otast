#!/usr/bin/env bash
# Export a verified, sanitized post-patch fake Magisk root for private analysis.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'STOP: cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1

python3 "$SCRIPT_DIR/otast_safety_guard.py" non-root "export fake root analysis" >/dev/null || exit $?

fake_root=
output=
proof_dir=

usage() {
    cat <<'EOF'
Usage: export-fake-root-analysis.sh [OPTIONS]

Options:
  --fake-root PATH|latest  Managed fake root. Default: latest.
  --output ZIP             Output ZIP path.
  --proof-dir DIR          Include the matching proof logs.
  -h, --help               Show this help.

Default output:
  ~/storage/downloads/otast-post-patch-fake-root-<UTC>.zip
EOF
}

latest_dir() {
    local parent candidate latest
    parent=$1
    latest=
    [[ -d $parent ]] || return 1
    for candidate in "$parent"/*; do
        [[ -d $candidate && ! -L $candidate ]] || continue
        if [[ -z $latest || $candidate -nt $latest ]]; then
            latest=$candidate
        fi
    done
    [[ -n $latest ]] || return 1
    printf '%s\n' "$latest"
}

while (($#)); do
    case $1 in
        --fake-root)
            (($# >= 2)) || { printf 'STOP: --fake-root requires a value.\n' >&2; exit 2; }
            fake_root=$2
            shift 2
            ;;
        --output)
            (($# >= 2)) || { printf 'STOP: --output requires a value.\n' >&2; exit 2; }
            output=$2
            shift 2
            ;;
        --proof-dir)
            (($# >= 2)) || { printf 'STOP: --proof-dir requires a value.\n' >&2; exit 2; }
            proof_dir=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'STOP: unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

root_base=${HOME:?}/.cache/otast/fake-roots
if [[ -z $fake_root || $fake_root == latest ]]; then
    fake_root=$(latest_dir "$root_base") || {
        printf 'STOP: no fake root exists under %s.\n' "$root_base" >&2
        exit 1
    }
else
    python3 "$SCRIPT_DIR/otast_safety_guard.py" fake-root "$fake_root" \
        --operation "fake-root export selection" >/dev/null || exit $?
    fake_root=$(cd -- "$fake_root" >/dev/null 2>&1 && pwd -P) || {
        printf 'STOP: fake root does not exist: %s\n' "$fake_root" >&2
        exit 1
    }
fi
case $fake_root in
    "$root_base"/*) ;;
    *) printf 'STOP: fake root is outside %s: %s\n' "$root_base" "$fake_root" >&2; exit 1 ;;
esac
python3 "$SCRIPT_DIR/otast_safety_guard.py" fake-root "$fake_root" \
    --operation "fake-root analysis export" >/dev/null || exit $?

if find "$fake_root" -type l -print -quit | grep -q .; then
    printf 'STOP: fake root contains a symlink; refusing ambiguous export.\n' >&2
    exit 1
fi

for forbidden in \
    'keybox*.xml' '*.pem' '*.key' '*.p12' '*.pfx' '*.jks' \
    '*.db' '*.sqlite' '*.sqlite3' 'magisk.db'; do
    match=$(find "$fake_root" -type f -iname "$forbidden" -print -quit 2>/dev/null)
    if [[ -n $match ]]; then
        printf 'STOP: forbidden private-material pattern found: %s\n' "$match" >&2
        exit 1
    fi
done

stamp=$(date -u +%Y%m%dT%H%M%SZ) || exit 1
output=${output:-${HOME:?}/storage/downloads/otast-post-patch-fake-root-$stamp.zip}
case $output in
    /*) ;;
    *) output=$PWD/$output ;;
esac
output_dir=$(dirname -- "$output")
mkdir -p -- "$output_dir" || exit 1
if [[ -e $output || -L $output ]]; then
    printf 'STOP: output already exists: %s\n' "$output" >&2
    exit 1
fi

temp_parent=${TMPDIR:-${HOME:?}/.cache}
mkdir -p -- "$temp_parent" || exit 1
workspace=$(mktemp -d "$temp_parent/otast-export.XXXXXX") || exit 1
cleanup() {
    [[ -n ${workspace:-} ]] && rm -rf -- "$workspace"
}
trap cleanup EXIT INT TERM
chmod 0700 "$workspace" 2>/dev/null || true
bundle=$workspace/otast-post-patch-fake-root-$stamp
mkdir -p "$bundle/logs" || exit 1

python3 "$SCRIPT_DIR/otast_safety_guard.py" fake-root "$fake_root" \
    --operation "fake-root export report" >/dev/null || exit $?
bash "$SCRIPT_DIR/validate-fake-magisk-root.sh" "$fake_root" report \
    >"$bundle/logs/report.log" 2>&1 || {
    cat "$bundle/logs/report.log" >&2
    printf 'STOP: fake-root report failed.\n' >&2
    exit 1
}
python3 "$SCRIPT_DIR/otast_safety_guard.py" fake-root "$fake_root" \
    --operation "fake-root export verify" >/dev/null || exit $?
bash "$SCRIPT_DIR/validate-fake-magisk-root.sh" "$fake_root" verify \
    >"$bundle/logs/verify.log" 2>&1 || {
    cat "$bundle/logs/verify.log" >&2
    printf 'STOP: fake root is not currently verified.\n' >&2
    exit 1
}

cp -a -- "$fake_root" "$bundle/fake-root" || exit 1
if [[ -n $proof_dir ]]; then
    proof_dir=$(cd -- "$proof_dir" >/dev/null 2>&1 && pwd -P) || {
        printf 'STOP: proof directory does not exist: %s\n' "$proof_dir" >&2
        exit 1
    }
    case $proof_dir in
        "${HOME:?}/.local/state/otast-proof"/*) ;;
        *) printf 'STOP: proof directory is outside the private proof root.\n' >&2; exit 1 ;;
    esac
    cp -a -- "$proof_dir" "$bundle/proof" || exit 1
fi

git -C "$REPO_ROOT" status --short --branch >"$bundle/git-status.txt" 2>&1 || true
git -C "$REPO_ROOT" diff --binary >"$bundle/repository-working.diff" 2>/dev/null || true
git -C "$REPO_ROOT" diff --cached --binary >"$bundle/repository-staged.diff" 2>/dev/null || true
git_head=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null) || git_head=UNCOMMITTED
printf '%s\n' "$git_head" >"$bundle/repository-head.txt"

(
    cd -- "$fake_root" || exit 1
    find . -type f -print | LC_ALL=C sort | while IFS= read -r path; do
        sha256sum "$path" || exit 1
    done
) >"$bundle/fake-root-files.sha256" || exit 1

(
    cd -- "$fake_root" || exit 1
    find . -mindepth 1 -exec stat -c '%F\t%a\t%u\t%g\t%s\t%n' {} + | LC_ALL=C sort
) >"$bundle/fake-root-tree.tsv" || exit 1

candidate_sha=$(python3 - "$fake_root/candidate-module.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["module_sha256"])
PY
) || exit 1

authority_sha=$(sha256sum "$fake_root/data/adb/ota.prop" 2>/dev/null)
authority_sha=${authority_sha%% *}

cat >"$bundle/ANALYSIS-SUMMARY.txt" <<EOF
RESULT=PASS
GENERATED_UTC=$stamp
FAKE_ROOT_NAME=${fake_root##*/}
FAKE_ROOT=$fake_root
MODULE_SHA256=$candidate_sha
AUTHORITY_SHA256=$authority_sha
GIT_HEAD=$git_head
STATE=MANAGED_AND_VERIFIED_BEFORE_RESTORE
LIVE_DEVICE_MODIFIED=NO
STRICT_EXCLUSIONS=NOT_INSPECTED_BY_CAPTURE_CONTRACT
EOF

cat >"$bundle/EXPORT-POLICY.txt" <<'EOF'
This archive was exported from a previously sanitized OTAST fake root.
The exporter rejects symlinks, keybox files, private-key formats and databases.
It may still contain device identity and installed-module metadata. Keep it private.
EOF

python3 - "$bundle" "$output" <<'PY'
from __future__ import annotations

import os
import stat
import sys
import zipfile
from pathlib import Path

source = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
base = source.parent

with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(base).as_posix()):
        relative = path.relative_to(base).as_posix()
        if path.is_symlink():
            raise SystemExit(f"symlink rejected during ZIP creation: {relative}")
        info = zipfile.ZipInfo(relative + ("/" if path.is_dir() else ""))
        info.date_time = (2020, 1, 1, 0, 0, 0)
        mode = path.stat().st_mode
        info.external_attr = (mode & 0xFFFF) << 16
        info.create_system = 3
        if path.is_dir():
            archive.writestr(info, b"")
        elif stat.S_ISREG(mode):
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        else:
            raise SystemExit(f"special file rejected during ZIP creation: {relative}")
PY
rc=$?
if ((rc != 0)); then
    rm -f -- "$output"
    exit "$rc"
fi

python3 -m zipfile -t "$output" >/dev/null || {
    rm -f -- "$output"
    printf 'STOP: generated ZIP failed integrity validation.\n' >&2
    exit 1
}

(
    cd -- "$output_dir" || exit 1
    sha256sum "$(basename -- "$output")" >"$(basename -- "$output").sha256"
) || exit 1

printf '\n==================================================\n'
printf 'ANALYSIS EXPORT:      PASS\n'
printf 'POST-PATCH VERIFY:    PASS\n'
printf 'LIVE DEVICE MODIFIED: NO\n'
printf 'ARCHIVE:              %s\n' "$output"
printf 'CHECKSUM:             %s.sha256\n' "$output"
printf '==================================================\n'
