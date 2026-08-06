#!/usr/bin/env bash
# Prove the exact candidate ZIP against a sanitized copy of the device Magisk root.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'STOP: cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1

python3 "$SCRIPT_DIR/otast_safety_guard.py" non-root "prove device fake root" >/dev/null || exit $?

fixture=
name=
evidence=
module_zip=
restore_clone=0

usage() {
    cat <<'EOF'
Usage: prove-device-fake-root.sh [OPTIONS]

Options:
  --fixture PATH|latest   Sanitized device fixture. Default: latest.
  --name NAME             Fake-root/proof name. Default: tegu-proof-<UTC>.
  --evidence DIR          Evidence directory. Default: ~/.local/state/otast-proof/NAME.
  --module-zip PATH       Prove this exact validated candidate ZIP without rebuilding it.
  --restore-clone         Prove Restore in a separate disposable clone.
  -h, --help              Show this help.

The managed fake root is preserved for analysis/export. Live /data/adb is never modified.
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
        --fixture)
            (($# >= 2)) || { printf 'STOP: --fixture requires a value.\n' >&2; exit 2; }
            fixture=$2
            shift 2
            ;;
        --name)
            (($# >= 2)) || { printf 'STOP: --name requires a value.\n' >&2; exit 2; }
            name=$2
            shift 2
            ;;
        --evidence)
            (($# >= 2)) || { printf 'STOP: --evidence requires a value.\n' >&2; exit 2; }
            evidence=$2
            shift 2
            ;;
        --module-zip)
            (($# >= 2)) || { printf 'STOP: --module-zip requires a value.\n' >&2; exit 2; }
            module_zip=$2
            shift 2
            ;;
        --restore-clone)
            restore_clone=1
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

if [[ -z $fixture || $fixture == latest ]]; then
    fixture=$(latest_dir "${HOME:?}/.local/share/otast/device-fixtures") || {
        printf 'STOP: no private device fixture exists. Run otast capture first.\n' >&2
        exit 1
    }
else
    fixture=$(cd -- "$fixture" >/dev/null 2>&1 && pwd -P) || {
        printf 'STOP: fixture does not exist: %s\n' "$fixture" >&2
        exit 1
    }
fi

fixture_root=${HOME:?}/.local/share/otast/device-fixtures
case $fixture in
    "$fixture_root"/*) ;;
    *) printf 'STOP: fixture is outside %s: %s\n' "$fixture_root" "$fixture" >&2; exit 1 ;;
esac

if [[ -n $module_zip ]]; then
    [[ -f $module_zip && ! -L $module_zip ]] || {
        printf 'STOP: candidate module ZIP is missing or unsafe: %s\n' "$module_zip" >&2
        exit 1
    }
    module_zip=$(cd -- "$(dirname -- "$module_zip")" >/dev/null 2>&1 && pwd -P)/$(basename -- "$module_zip") || exit 1
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ) || exit 1
name=${name:-tegu-proof-$stamp}
case $name in
    ''|*[!A-Za-z0-9._-]*) printf 'STOP: unsafe proof name: %s\n' "$name" >&2; exit 1 ;;
esac

evidence=${evidence:-${HOME:?}/.local/state/otast-proof/$name}
case $evidence in
    /*) ;;
    *) evidence=$REPO_ROOT/$evidence ;;
esac

if [[ -e $evidence || -L $evidence ]]; then
    printf 'STOP: evidence path already exists: %s\n' "$evidence" >&2
    exit 1
fi
mkdir -p -- "$evidence" || exit 1
chmod 0700 -- "$(dirname -- "$evidence")" "$evidence" 2>/dev/null || true

fake_root=${HOME:?}/.cache/otast/fake-roots/$name

run_action() {
    local root action log rc
    root=$1
    action=$2
    log=$3

    printf '\n===== %s =====\n' "$action"
    python3 "$SCRIPT_DIR/otast_safety_guard.py" fake-root "$root" \
        --operation "device proof action: $action" >/dev/null || return $?
    bash "$SCRIPT_DIR/validate-fake-magisk-root.sh" "$root" "$action" >"$log" 2>&1
    rc=$?
    cat "$log"
    return "$rc"
}

printf 'Fixture:  %s\n' "$fixture"
printf 'Name:     %s\n' "$name"
printf 'Evidence: %s\n' "$evidence"

reset_args=("$fixture" "$name")
[[ -z $module_zip ]] || reset_args+=("$module_zip")
bash "$SCRIPT_DIR/reset-fake-magisk-root.sh" "${reset_args[@]}" \
    >"$evidence/00-reset.log" 2>&1
rc=$?
cat "$evidence/00-reset.log"
if ((rc != 0)); then
    printf 'STOP: fake-root reset failed.\n' >&2
    exit "$rc"
fi
python3 "$SCRIPT_DIR/otast_safety_guard.py" fake-root "$fake_root" \
    --operation "device proof reset result" >/dev/null || exit $?

run_action "$fake_root" report "$evidence/01-report.log" || exit $?
run_action "$fake_root" preflight "$evidence/02-preflight.log" || exit $?
run_action "$fake_root" apply "$evidence/03-apply-first.log" || exit $?

if grep -Fq 'REBOOT_REQUIRED' "$evidence/03-apply-first.log"; then
    run_action "$fake_root" verify "$evidence/04-verify-before-reboot.log"
    verify_rc=$?
    if ((verify_rc == 0)); then
        printf 'STOP: Verify unexpectedly passed before the required reboot.\n' >&2
        exit 1
    fi
    if ! grep -Fq 'reboot after Apply before Verify' "$evidence/04-verify-before-reboot.log"; then
        printf 'STOP: pre-reboot Verify failed for an unexpected reason.\n' >&2
        exit 1
    fi
    run_action "$fake_root" reboot "$evidence/05-reboot.log" || exit $?
else
    if ! grep -Fq 'NO_CHANGES_REQUIRED' "$evidence/03-apply-first.log"; then
        printf 'STOP: first Apply reported neither REBOOT_REQUIRED nor NO_CHANGES_REQUIRED.\n' >&2
        exit 1
    fi
    printf 'No reboot simulation required; fixture was already current.\n' >"$evidence/04-verify-before-reboot.log"
    printf 'No reboot simulation required; fixture was already current.\n' >"$evidence/05-reboot.log"
fi

run_action "$fake_root" verify "$evidence/06-verify-after-reboot.log" || exit $?
run_action "$fake_root" apply "$evidence/07-apply-second.log" || exit $?
if ! grep -Fq 'NO_CHANGES_REQUIRED' "$evidence/07-apply-second.log"; then
    printf 'STOP: second Apply was not idempotent.\n' >&2
    exit 1
fi
run_action "$fake_root" verify "$evidence/08-verify-final.log" || exit $?

restore_result=NOT_REQUESTED
restore_root=
if ((restore_clone == 1)); then
    restore_name=${name}-restore
    restore_root=${HOME:?}/.cache/otast/fake-roots/$restore_name
    restore_reset_args=("$fixture" "$restore_name")
    [[ -z $module_zip ]] || restore_reset_args+=("$module_zip")
    bash "$SCRIPT_DIR/reset-fake-magisk-root.sh" "${restore_reset_args[@]}" \
        >"$evidence/20-restore-reset.log" 2>&1 || {
        cat "$evidence/20-restore-reset.log" >&2
        exit 1
    }
    python3 "$SCRIPT_DIR/otast_safety_guard.py" fake-root "$restore_root" \
        --operation "restore proof reset result" >/dev/null || exit $?
    run_action "$restore_root" preflight "$evidence/21-restore-preflight.log" || exit $?
    run_action "$restore_root" apply "$evidence/22-restore-apply.log" || exit $?
    if grep -Fq 'REBOOT_REQUIRED' "$evidence/22-restore-apply.log"; then
        run_action "$restore_root" reboot "$evidence/23-restore-reboot.log" || exit $?
    fi
    run_action "$restore_root" verify "$evidence/24-restore-managed-verify.log" || exit $?
    run_action "$restore_root" restore "$evidence/25-restore.log" || exit $?
    run_action "$restore_root" report "$evidence/26-restore-report.log" || exit $?
    restore_result=PASS
fi

candidate_sha=$(python3 - "$fake_root/candidate-module.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["module_sha256"])
PY
) || exit 1

git_head=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null) || git_head=UNCOMMITTED

cat >"$evidence/proof.env" <<EOF
OTAST_PROOF_NAME='$name'
OTAST_PROOF_DIR='$evidence'
OTAST_FIXTURE='$fixture'
OTAST_FAKE_ROOT='$fake_root'
OTAST_RESTORE_ROOT='$restore_root'
OTAST_MODULE_SHA256='$candidate_sha'
OTAST_MODULE_ZIP='$module_zip'
OTAST_GIT_HEAD='$git_head'
OTAST_RESTORE_RESULT='$restore_result'
OTAST_PROOF_UTC='$stamp'
EOF
chmod 0600 "$evidence/proof.env" || exit 1

cat >"$evidence/SUMMARY.txt" <<EOF
DEVICE_DERIVED_PROOF=PASS
PREFLIGHT=PASS
FIRST_APPLY=PASS
REBOOT_BOUNDARY=PASS
POST_REBOOT_VERIFY=PASS
SECOND_APPLY_NOOP=PASS
FINAL_VERIFY=PASS
RESTORE_CLONE=$restore_result
MODULE_SHA256=$candidate_sha
MODULE_ZIP=$module_zip
GIT_HEAD=$git_head
FIXTURE=$fixture
FAKE_ROOT=$fake_root
EVIDENCE=$evidence
LIVE_DEVICE_MODIFIED=NO
EOF

printf '\n==================================================\n'
printf 'DEVICE-DERIVED PROOF: PASS\n'
printf 'SECOND APPLY NO-OP:   PASS\n'
printf 'RESTORE CLONE:        %s\n' "$restore_result"
printf 'MODULE SHA-256:       %s\n' "$candidate_sha"
printf 'FAKE ROOT:            %s\n' "$fake_root"
printf 'EVIDENCE:             %s\n' "$evidence"
printf 'LIVE DEVICE MODIFIED: NO\n'
printf '==================================================\n'
