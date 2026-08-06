#!/usr/bin/env bash
# Complete local OTAST release-candidate qualification. Performs no Git/GitHub writes.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'STOP: cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1

python3 "$SCRIPT_DIR/otast_safety_guard.py" non-root "qualify release candidate" >/dev/null || exit $?

fixture=latest
output=
skip_device=0
allow_dirty=0

usage() {
    cat <<'EOF'
Usage: qualify-release-candidate.sh [OPTIONS]

Options:
  --fixture PATH|latest  Device fixture for the copied-root proof. Default: latest.
  --output DIR           Qualification evidence directory.
  --skip-device          Skip the device-derived proof and analysis export.
  --allow-dirty          Development-only qualification of an uncommitted tree.
  -h, --help             Show this help.

Default policy requires an existing Git commit and a clean worktree/index.
This script never commits, pushes, tags, releases or installs the Magisk module.
EOF
}

while (($#)); do
    case $1 in
        --fixture)
            (($# >= 2)) || { printf 'STOP: --fixture requires a value.\n' >&2; exit 2; }
            fixture=$2
            shift 2
            ;;
        --output)
            (($# >= 2)) || { printf 'STOP: --output requires a value.\n' >&2; exit 2; }
            output=$2
            shift 2
            ;;
        --skip-device)
            skip_device=1
            shift
            ;;
        --allow-dirty)
            allow_dirty=1
            shift
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

stamp=$(date -u +%Y%m%dT%H%M%SZ) || exit 1
output=${output:-${HOME:?}/.local/state/otast-qualification/$stamp}
case $output in
    /*) ;;
    *) output=$REPO_ROOT/$output ;;
esac
if [[ -e $output || -L $output ]]; then
    printf 'STOP: qualification directory already exists: %s\n' "$output" >&2
    exit 1
fi
mkdir -p -- "$output" || exit 1
chmod 0700 -- "$(dirname -- "$output")" "$output" 2>/dev/null || true

head=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null) || head=
status=$(git -C "$REPO_ROOT" status --porcelain=v1 2>/dev/null) || status=GIT_STATUS_FAILED

publication_eligible=YES
if [[ -z $head ]]; then
    if ((allow_dirty == 0)); then
        printf 'STOP: create the local commit before final qualification.\n' >&2
        exit 1
    fi
    head=UNCOMMITTED
    publication_eligible=NO
fi
if [[ -n $status ]]; then
    if ((allow_dirty == 0)); then
        printf '%s\n' "$status" >&2
        printf 'STOP: worktree/index is not clean.\n' >&2
        exit 1
    fi
    publication_eligible=NO
fi

printf '%s\n' "$status" >"$output/git-status.txt"
printf '%s\n' "$head" >"$output/git-head.txt"

run_gate() {
    local name log rc
    name=$1
    shift
    log=$output/$name.log
    printf '\n===== %s =====\n' "$name"
    "$@" >"$log" 2>&1
    rc=$?
    cat "$log"
    if ((rc != 0)); then
        printf 'STOP: qualification gate failed: %s\n' "$name" >&2
        return "$rc"
    fi
    return 0
}

run_gate 01-full-test bash "$SCRIPT_DIR/test.sh" --full || exit $?
run_gate 02-privacy bash -c 'cd "$1" && python3 -m tools.otastctl --repo-root "$1" privacy-scan --json' _ "$REPO_ROOT" || exit $?

mkdir -p "$output/build-a" "$output/build-b" || exit 1
run_gate 03-build-a bash "$SCRIPT_DIR/build-release.sh" "$output/build-a" || exit $?
run_gate 04-build-b bash "$SCRIPT_DIR/build-release.sh" "$output/build-b" || exit $?

zip_a=$(find "$output/build-a" -maxdepth 1 -type f -name 'otast-*.zip' -print | LC_ALL=C sort | sed -n '1p')
zip_b=$(find "$output/build-b" -maxdepth 1 -type f -name 'otast-*.zip' -print | LC_ALL=C sort | sed -n '1p')
if [[ -z $zip_a || -z $zip_b ]]; then
    printf 'STOP: deterministic build did not produce both module ZIPs.\n' >&2
    exit 1
fi
if ! cmp -s -- "$zip_a" "$zip_b"; then
    printf 'STOP: independent module builds are not byte-identical.\n' >&2
    exit 1
fi
module_sha=$(sha256sum "$zip_a")
module_sha=${module_sha%% *}
printf '%s  %s\n' "$module_sha" "${zip_a##*/}" >"$output/module.sha256"

embedded_commit=$(unzip -p "$zip_a" release.properties 2>/dev/null | sed -n 's/^commit_sha=//p' | sed -n '1p')
if [[ $publication_eligible == YES && $embedded_commit != "$head" ]]; then
    printf 'STOP: module ZIP is not bound to the exact local commit.\n' >&2
    printf 'Expected: %s\nEmbedded: %s\n' "$head" "${embedded_commit:-missing}" >&2
    exit 1
fi
if [[ $publication_eligible == NO ]]; then
    printf 'Development qualification: commit binding is not publication evidence.\n' >"$output/commit-binding-warning.txt"
fi

source_zip=$output/otast-public-ready.zip
run_gate 05-source-package bash "$SCRIPT_DIR/package-public-repo.sh" "$source_zip" || exit $?
run_gate 06-source-validate bash -c 'cd "$1" && python3 -m tools.otastctl --repo-root "$1" validate-source "$2"' _ "$REPO_ROOT" "$source_zip" || exit $?
run_gate 07-synthetic bash "$SCRIPT_DIR/fake-magisk-root.sh" "$output/synthetic" || exit $?

device_result=SKIPPED
proof_dir=
analysis_zip=
if ((skip_device == 0)); then
    proof_name=tegu-qualified-$stamp
    proof_dir=${HOME:?}/.local/state/otast-proof/$proof_name
    prove_args=(
        --fixture "$fixture"
        --name "$proof_name"
        --evidence "$proof_dir"
        --module-zip "$zip_a"
        --restore-clone
    )
    run_gate 08-device-proof bash "$SCRIPT_DIR/prove-device-fake-root.sh" "${prove_args[@]}" || exit $?

    proof_env=$proof_dir/proof.env
    [[ -f $proof_env && ! -L $proof_env ]] || {
        printf 'STOP: device proof did not publish proof.env.\n' >&2
        exit 1
    }
    # shellcheck disable=SC1090
    source "$proof_env" || exit 1
    [[ ${OTAST_MODULE_SHA256:-} == "$module_sha" ]] || {
        printf 'STOP: device proof module hash differs from deterministic build.\n' >&2
        printf 'Build: %s\nProof: %s\n' "$module_sha" "${OTAST_MODULE_SHA256:-missing}" >&2
        exit 1
    }

    analysis_zip=$output/otast-post-patch-fake-root-$stamp.zip
    run_gate 09-analysis-export bash "$SCRIPT_DIR/export-fake-root-analysis.sh" \
        --fake-root "$OTAST_FAKE_ROOT" --proof-dir "$proof_dir" --output "$analysis_zip" || exit $?
    device_result=PASS
fi

cat >"$output/QUALIFICATION.txt" <<EOF
RESULT=PASS
PUBLICATION_ELIGIBLE=$publication_eligible
GIT_HEAD=$head
EMBEDDED_COMMIT=${embedded_commit:-missing}
MODULE_ZIP=$zip_a
MODULE_SHA256=$module_sha
SOURCE_ZIP=$source_zip
DEVICE_DERIVED_PROOF=$device_result
PROOF_DIR=$proof_dir
ANALYSIS_ZIP=$analysis_zip
GIT_WRITES=NONE
GITHUB_WRITES=NONE
GENERATED_UTC=$stamp
EOF

printf '\n==================================================\n'
printf 'QUALIFICATION:          PASS\n'
printf 'FULL TEST:             PASS\n'
printf 'PRIVACY:               PASS\n'
printf 'DETERMINISTIC MODULE:  PASS\n'
printf 'SOURCE PACKAGE:        PASS\n'
printf 'SYNTHETIC LIFECYCLE:   PASS\n'
printf 'DEVICE-DERIVED PROOF:  %s\n' "$device_result"
printf 'PUBLICATION ELIGIBLE:  %s\n' "$publication_eligible"
printf 'MODULE SHA-256:        %s\n' "$module_sha"
printf 'EVIDENCE:              %s\n' "$output"
printf 'GIT/GITHUB WRITES:     NONE\n'
printf '==================================================\n'
