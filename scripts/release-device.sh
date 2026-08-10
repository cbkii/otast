#!/usr/bin/env bash
# Resumable physical-device release qualification and publication for OTAST.
# Re-run the same command after each requested reboot; phase state is persisted privately.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'STOP: cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1

REPO_SLUG=${OTAST_GITHUB_REPO:-cbkii/otast}
WORKFLOW=release.yml
YES=0
NO_REBOOT=0
NO_PUBLISH=0
SHOW_STATUS=0
RESET=0
VERSION=

usage() {
    cat <<'EOF'
Usage: release-device.sh [OPTIONS]

One resumable command for the physical v1 release lifecycle. Re-run this same
command after each requested reboot; it resumes from private state automatically.

Options:
  --version VERSION   Release version. Default: module/module.prop version.
  --yes               Confirm reboot/publication prompts automatically.
  --no-reboot         Never reboot automatically; print the required boundary.
  --no-publish        Stop after uploading a PASS device proof to the draft.
  --status            Show current private release state and exit.
  --reset             Remove only this wizard's private state for VERSION.
  -h, --help          Show this help.

The command can create the GitHub draft through Actions, download and verify the
exact draft ZIP, install it through Magisk, prove Apply/reboot/Verify/no-op/Restore
across real reboot boundaries, upload a sanitized proof asset, then ask GitHub
Actions to publish that exact already-validated draft without rebuilding it.
EOF
}

fatal() {
    printf 'STOP: %s\n' "$*" >&2
    return 1
}

info() {
    printf '[INFO] %s\n' "$*"
}

phase_banner() {
    printf '\n==================================================\n'
    printf 'OTAST RELEASE: %s\n' "$1"
    printf '==================================================\n'
}

while (($#)); do
    case $1 in
        --version)
            (($# >= 2)) || { printf 'STOP: --version requires a value.\n' >&2; exit 2; }
            VERSION=$2
            shift 2
            ;;
        --yes) YES=1; shift ;;
        --no-reboot) NO_REBOOT=1; shift ;;
        --no-publish) NO_PUBLISH=1; shift ;;
        --status) SHOW_STATUS=1; shift ;;
        --reset) RESET=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'STOP: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z $VERSION ]]; then
    VERSION=$(sed -n 's/^version=//p' "$REPO_ROOT/module/module.prop" | sed -n '1p')
fi
if [[ ! $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.]+)?$ ]]; then
    printf 'STOP: invalid release version: %s\n' "$VERSION" >&2
    exit 2
fi

STATE_BASE=${HOME:?}/.local/state/otast-release
STATE_DIR=$STATE_BASE/$VERSION
STATE_FILE=$STATE_DIR/state.env
ASSET_DIR=$STATE_DIR/assets
LOG_DIR=$STATE_DIR/logs
PROOF_FILE=$STATE_DIR/otast-${VERSION}-device-proof.json
ZIP_NAME=otast-${VERSION}.zip
SHA_NAME=$ZIP_NAME.sha256
ZIP_PATH=$ASSET_DIR/$ZIP_NAME
SHA_PATH=$ASSET_DIR/$SHA_NAME

if ((RESET)); then
    if [[ -L $STATE_DIR ]]; then
        fatal "release state root is a symlink: $STATE_DIR"
        exit $?
    fi
    if [[ -d $STATE_DIR ]]; then
        rm -rf -- "$STATE_DIR" || { fatal "cannot remove release state: $STATE_DIR"; exit $?; }
    fi
    printf 'Reset private release state for %s.\n' "$VERSION"
    exit 0
fi

mkdir -p -- "$STATE_DIR" "$ASSET_DIR" "$LOG_DIR" || exit 1
chmod 0700 -- "$STATE_BASE" "$STATE_DIR" "$ASSET_DIR" "$LOG_DIR" 2>/dev/null || true

PHASE=START
COMMIT_SHA=
MODULE_SHA256=
BOOT_BEFORE=
BASELINE_RESULT=NOT_REQUIRED
DRAFT_TARGET=

load_state() {
    [[ -e $STATE_FILE ]] || return 0
    [[ -f $STATE_FILE && ! -L $STATE_FILE ]] || { fatal "release state is unsafe: $STATE_FILE"; return 1; }
    # This file is generated only by save_state below in a private 0700 directory.
    # shellcheck disable=SC1090
    source "$STATE_FILE" || { fatal 'cannot read release state'; return 1; }
    case ${PHASE:-} in
        START|BASELINE_REBOOT|INSTALL_REBOOT|APPLY_REBOOT|RESTORE_REBOOT|PROOF_READY|PUBLISHING|COMPLETE) ;;
        *) fatal "unknown release phase in state: ${PHASE:-missing}"; return 1 ;;
    esac
    if [[ -n ${COMMIT_SHA:-} && ! $COMMIT_SHA =~ ^[0-9a-f]{40}$|^[0-9a-f]{64}$ ]]; then
        fatal 'state commit SHA is malformed'
        return 1
    fi
    if [[ -n ${MODULE_SHA256:-} && ! $MODULE_SHA256 =~ ^[0-9a-f]{64}$ ]]; then
        fatal 'state module SHA-256 is malformed'
        return 1
    fi
    if [[ -n ${DRAFT_TARGET:-} && ! $DRAFT_TARGET =~ ^[0-9a-f]{40}$|^[0-9a-f]{64}$ ]]; then
        fatal 'state draft target is malformed'
        return 1
    fi
    case ${BASELINE_RESULT:-NOT_REQUIRED} in PASS|NOT_REQUIRED) ;; *) fatal 'state baseline result is malformed'; return 1 ;; esac
    if [[ -n ${BOOT_BEFORE:-} && ! $BOOT_BEFORE =~ ^[0-9A-Fa-f-]{16,64}$ ]]; then
        fatal 'state boot ID is malformed'
        return 1
    fi
    return 0
}

save_state() {
    local tmp
    tmp=$STATE_FILE.tmp.$$
    umask 077
    {
        printf 'PHASE=%q\n' "$PHASE"
        printf 'COMMIT_SHA=%q\n' "$COMMIT_SHA"
        printf 'MODULE_SHA256=%q\n' "$MODULE_SHA256"
        printf 'BOOT_BEFORE=%q\n' "$BOOT_BEFORE"
        printf 'BASELINE_RESULT=%q\n' "$BASELINE_RESULT"
        printf 'DRAFT_TARGET=%q\n' "$DRAFT_TARGET"
    } >"$tmp" || return 1
    chmod 0600 -- "$tmp" || return 1
    mv -f -- "$tmp" "$STATE_FILE"
}

load_state || exit $?

if ((SHOW_STATUS)); then
    printf 'Version:      %s\n' "$VERSION"
    printf 'Phase:        %s\n' "$PHASE"
    printf 'Commit:       %s\n' "${COMMIT_SHA:-unknown}"
    printf 'Module SHA:   %s\n' "${MODULE_SHA256:-unknown}"
    printf 'State:        %s\n' "$STATE_FILE"
    exit 0
fi

for command in gh git python3 unzip sha256sum getprop su grep sed cat sleep date mkdir chmod mv rm; do
    command -v "$command" >/dev/null 2>&1 || { fatal "required command is missing: $command"; exit $?; }
done

gh auth status --hostname github.com >/dev/null 2>&1 || {
    fatal 'GitHub CLI is not authenticated. Run: gh auth login --hostname github.com'
    exit $?
}

if ! su -c 'id -u' 2>/dev/null | grep -qx '0'; then
    fatal 'Magisk root is unavailable to Termux'
    exit $?
fi
if ! su -c 'magisk -V' >/dev/null 2>&1; then
    fatal 'Magisk CLI is unavailable through root; cannot install the exact draft ZIP'
    exit $?
fi

DEVICE=$(getprop ro.product.device 2>/dev/null)
SDK=$(getprop ro.build.version.sdk 2>/dev/null)
if [[ $DEVICE != tegu || $SDK != 36 ]]; then
    fatal "physical release proof requires tegu / SDK 36; observed device=$DEVICE sdk=$SDK"
    exit $?
fi

current_boot_id() {
    cat /proc/sys/kernel/random/boot_id 2>/dev/null
}

run_live() {
    local action log rc
    action=$1
    log=$2
    info "Live OTAST: $action"
    su -c "sh /data/adb/modules/otast/runtime/entry.sh $action" >"$log" 2>&1
    rc=$?
    cat "$log"
    return "$rc"
}

has_managed_state() {
    su -c 'for f in /data/adb/otast/records/*.state; do [ -f "$f" ] && exit 0; done; exit 1' >/dev/null 2>&1
}

request_reboot() {
    local answer
    BOOT_BEFORE=$(current_boot_id) || { fatal 'cannot read current boot ID'; return 1; }
    save_state || { fatal 'cannot persist reboot boundary'; return 1; }
    printf '\nRequired reboot boundary reached.\n'
    printf 'After Android is fully booted, run the SAME command again:\n'
    printf '  otast release\n\n'
    if ((NO_REBOOT)); then
        return 10
    fi
    if ((YES)); then
        answer=y
    elif [[ -t 0 ]]; then
        printf 'Reboot now? [Y/n] '
        if IFS= read -r -t 30 answer; then
            :
        else
            printf '\nNo response; reboot was not requested.\n'
            return 10
        fi
        answer=${answer:-y}
    else
        return 10
    fi
    case $answer in
        y|Y|yes|YES)
            info 'Requesting reboot through Magisk root'
            su -c reboot >/dev/null 2>&1
            return 10
            ;;
        *) return 10 ;;
    esac
}

require_new_boot() {
    local now
    now=$(current_boot_id) || { fatal 'cannot read current boot ID'; return 1; }
    if [[ -z $BOOT_BEFORE || $now == "$BOOT_BEFORE" ]]; then
        printf 'A real reboot is still required before this phase can continue.\n'
        request_reboot
        return $?
    fi
    BOOT_BEFORE=
    save_state || return 1
    return 0
}

workflow_run_id() {
    local title head json
    title=$1
    head=$2
    json=$(gh run list -R "$REPO_SLUG" --workflow "$WORKFLOW" --branch main \
        --event workflow_dispatch --limit 20 \
        --json databaseId,displayTitle,headSha,status,conclusion,createdAt 2>/dev/null) || return 1
    EXPECTED_TITLE=$title EXPECTED_HEAD=$head python3 -c '
import json, os, sys
runs=json.load(sys.stdin)
items=[r for r in runs if r.get("displayTitle")==os.environ["EXPECTED_TITLE"] and r.get("headSha")==os.environ["EXPECTED_HEAD"]]
items.sort(key=lambda r:r.get("createdAt", ""), reverse=True)
print(items[0]["databaseId"] if items else "")
' <<<"$json"
}

watch_run() {
    local run_id status conclusion attempt json
    run_id=$1
    for ((attempt=1; attempt<=240; attempt+=1)); do
        json=$(gh run view "$run_id" -R "$REPO_SLUG" --json status,conclusion 2>/dev/null) || {
            if ((attempt % 6 == 0)); then printf '[WARN] cannot read workflow state yet (%s/240)\n' "$attempt" >&2; fi
            sleep 10
            continue
        }
        status=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("status", ""))' <<<"$json")
        conclusion=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("conclusion") or "")' <<<"$json")
        if [[ $status == completed ]]; then
            if [[ $conclusion == success ]]; then
                return 0
            fi
            gh run view "$run_id" -R "$REPO_SLUG" --log-failed 2>/dev/null || true
            fatal "GitHub Release workflow concluded: ${conclusion:-unknown}"
            return 1
        fi
        if ((attempt % 6 == 0)); then info "Waiting for GitHub Release workflow ($status)"; fi
        sleep 10
    done
    fatal 'GitHub Release workflow did not complete within 40 minutes'
    return 1
}

dispatch_release_workflow() {
    local operation head title run_id attempt
    operation=$1
    head=$(gh api "repos/$REPO_SLUG/commits/main" --jq .sha 2>/dev/null) || {
        fatal 'cannot resolve current GitHub main commit'
        return 1
    }
    title="Release $operation $VERSION"
    info "Dispatching GitHub Actions: $title"
    gh workflow run "$WORKFLOW" -R "$REPO_SLUG" --ref main \
        -f "operation=$operation" -f "version=$VERSION" >/dev/null || {
        fatal 'cannot dispatch Release workflow'
        return 1
    }
    run_id=
    for ((attempt=1; attempt<=30; attempt+=1)); do
        run_id=$(workflow_run_id "$title" "$head") || run_id=
        [[ -n $run_id ]] && break
        sleep 4
    done
    [[ -n $run_id ]] || { fatal 'dispatched Release workflow did not appear'; return 1; }
    info "Watching workflow run $run_id"
    watch_run "$run_id"
}

release_json() {
    gh release view "$VERSION" -R "$REPO_SLUG" \
        --json isDraft,tagName,targetCommitish,assets 2>/dev/null
}

ensure_draft() {
    local json draft tag target
    json=$(release_json) || json=
    if [[ -z $json ]]; then
        dispatch_release_workflow draft || return $?
        json=$(release_json) || { fatal 'draft release was not created'; return 1; }
    fi
    draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$json")
    tag=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tagName"])' <<<"$json")
    target=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["targetCommitish"])' <<<"$json")
    [[ $tag == "$VERSION" ]] || { fatal "release tag mismatch: $tag"; return 1; }
    if [[ $draft != true ]]; then
        PHASE=COMPLETE
        COMMIT_SHA=$target
        save_state || return 1
        printf 'Release %s is already published.\n' "$VERSION"
        return 20
    fi
    case $target in
        [0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;
        *) fatal "draft target is not an immutable commit SHA: $target"; return 1 ;;
    esac
    [[ ${#target} -eq 40 || ${#target} -eq 64 ]] || { fatal 'draft target commit SHA has wrong length'; return 1; }
    [[ $target =~ ^[0-9a-f]{40}$|^[0-9a-f]{64}$ ]] || { fatal "draft target is not an immutable full commit SHA: $target"; return 1; }
    DRAFT_TARGET=$target
    return 0
}

download_and_verify_draft() {
    local zip_sha embedded_commit embedded_version
    rm -f -- "$ZIP_PATH" "$SHA_PATH"
    gh release download "$VERSION" -R "$REPO_SLUG" \
        --pattern "$ZIP_NAME" --pattern "$SHA_NAME" \
        --dir "$ASSET_DIR" --clobber >/dev/null || {
        fatal 'cannot download exact draft release assets'
        return 1
    }
    [[ -f $ZIP_PATH && ! -L $ZIP_PATH && -f $SHA_PATH && ! -L $SHA_PATH ]] || {
        fatal 'draft release assets are missing or unsafe'
        return 1
    }
    (cd -- "$ASSET_DIR" && sha256sum -c "$SHA_NAME") || {
        fatal 'draft ZIP does not match its SHA-256 sidecar'
        return 1
    }
    zip_sha=$(sha256sum "$ZIP_PATH") || return 1
    zip_sha=${zip_sha%% *}
    embedded_version=$(unzip -p "$ZIP_PATH" module.prop 2>/dev/null | sed -n 's/^version=//p' | sed -n '1p')
    embedded_commit=$(unzip -p "$ZIP_PATH" release.properties 2>/dev/null | sed -n 's/^commit_sha=//p' | sed -n '1p')
    [[ $embedded_version == "$VERSION" ]] || { fatal "draft ZIP version mismatch: $embedded_version"; return 1; }
    [[ $embedded_commit == "$DRAFT_TARGET" ]] || {
        fatal "draft ZIP commit mismatch: asset=$embedded_commit release=$DRAFT_TARGET"
        return 1
    }
    MODULE_SHA256=$zip_sha
    COMMIT_SHA=$embedded_commit
    save_state || return 1
}

verify_installed_draft() {
    local module_prop release_props installed_version installed_commit
    module_prop=$(su -c 'cat /data/adb/modules/otast/module.prop' 2>/dev/null) || {
        fatal 'active OTAST module is missing after reboot'
        return 1
    }
    release_props=$(su -c 'cat /data/adb/modules/otast/release.properties' 2>/dev/null) || {
        fatal 'active OTAST release.properties is missing after reboot'
        return 1
    }
    installed_version=$(sed -n 's/^version=//p' <<<"$module_prop" | sed -n '1p')
    installed_commit=$(sed -n 's/^commit_sha=//p' <<<"$release_props" | sed -n '1p')
    [[ $installed_version == "$VERSION" ]] || { fatal "installed version mismatch: $installed_version"; return 1; }
    [[ $installed_commit == "$COMMIT_SHA" ]] || { fatal "installed commit mismatch: $installed_commit"; return 1; }
    if su -c 'test -e /data/adb/modules/otast/disable' >/dev/null 2>&1; then
        fatal 'OTAST module is disabled after installation'
        return 1
    fi
}

install_exact_draft() {
    local root_zip rc
    root_zip=/data/local/tmp/otast-release-${VERSION#v}.zip
    phase_banner 'INSTALL EXACT DRAFT ZIP'
    su -c "cat > '$root_zip'" <"$ZIP_PATH" || { fatal 'cannot stage draft ZIP for Magisk'; return 1; }
    su -c "chmod 0600 '$root_zip' && magisk --install-module '$root_zip'" >"$LOG_DIR/install.log" 2>&1
    rc=$?
    cat "$LOG_DIR/install.log"
    su -c "rm -f '$root_zip'" >/dev/null 2>&1 || true
    ((rc == 0)) || { fatal "Magisk module installation failed with status $rc"; return "$rc"; }
    PHASE=INSTALL_REBOOT
    request_reboot
}

write_proof() {
    GENERATED_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ) || return 1
    VERSION_VALUE=$VERSION COMMIT_VALUE=$COMMIT_SHA SHA_VALUE=$MODULE_SHA256 \
    BASELINE_VALUE=$BASELINE_RESULT GENERATED_VALUE=$GENERATED_UTC PROOF_PATH=$PROOF_FILE \
    python3 - <<'PY'
import json, os
from pathlib import Path
value = {
    "schema_version": 1,
    "result": "PASS",
    "version": os.environ["VERSION_VALUE"],
    "commit_sha": os.environ["COMMIT_VALUE"],
    "module_sha256": os.environ["SHA_VALUE"],
    "device": "tegu",
    "sdk": 36,
    "phases": {
        "baseline": os.environ["BASELINE_VALUE"],
        "install_reboot": "PASS",
        "apply_reboot": "PASS",
        "verify_noop_restore": "PASS",
        "restore_reboot_report": "PASS",
    },
    "generated_utc": os.environ["GENERATED_VALUE"],
}
path = Path(os.environ["PROOF_PATH"])
tmp = path.with_name(path.name + ".tmp")
tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
tmp.chmod(0o600)
tmp.replace(path)
PY
}

publish_proven_draft() {
    phase_banner 'UPLOAD PROOF + PUBLISH EXACT DRAFT'
    python3 "$SCRIPT_DIR/validate-device-release-proof.py" \
        --proof "$PROOF_FILE" --module-zip "$ZIP_PATH" \
        --version "$VERSION" --commit "$COMMIT_SHA" || return $?
    gh release upload "$VERSION" "$PROOF_FILE" -R "$REPO_SLUG" --clobber || {
        fatal 'cannot upload sanitized device proof to draft release'
        return 1
    }
    if ((NO_PUBLISH)); then
        printf 'PASS proof uploaded. Draft intentionally left unpublished (--no-publish).\n'
        return 0
    fi
    if ((YES == 0)); then
        local answer
        if [[ ! -t 0 ]]; then
            printf 'PASS proof uploaded. Re-run with --yes to request publication.\n'
            return 0
        fi
        printf 'Publish the validated %s draft now? [y/N] ' "$VERSION"
        if ! IFS= read -r -t 30 answer; then
            printf '\nPublication not requested.\n'
            return 0
        fi
        case $answer in y|Y|yes|YES) ;; *) printf 'Publication not requested.\n'; return 0 ;; esac
    fi
    PHASE=PUBLISHING
    save_state || return 1
    dispatch_release_workflow publish || return $?
    local json draft
    json=$(release_json) || { fatal 'published release cannot be read'; return 1; }
    draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$json")
    [[ $draft == false ]] || { fatal 'Release workflow completed but release is still draft'; return 1; }
    PHASE=COMPLETE
    save_state || return 1
    printf '\nRELEASE COMPLETE: %s\n' "$VERSION"
    printf 'Published exact module SHA-256: %s\n' "$MODULE_SHA256"
}

# If a prior invocation was interrupted around publication, verify current release first.
if [[ $PHASE == COMPLETE ]]; then
    printf 'Release %s is already complete.\n' "$VERSION"
    exit 0
fi
if [[ $PHASE == PUBLISHING ]]; then
    json=$(release_json) || { fatal 'cannot inspect release after publication request'; exit $?; }
    draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$json")
    if [[ $draft == false ]]; then
        PHASE=COMPLETE
        save_state || exit 1
        printf 'Release %s is already published.\n' "$VERSION"
        exit 0
    fi
    PHASE=PROOF_READY
    save_state || exit 1
fi

if [[ $PHASE == START ]]; then
    phase_banner 'PREPARE IMMUTABLE DRAFT'
    ensure_draft
    draft_rc=$?
    if ((draft_rc == 20)); then exit 0; fi
    ((draft_rc == 0)) || exit "$draft_rc"
    download_and_verify_draft || exit $?

    if has_managed_state; then
        phase_banner 'RESTORE EXISTING OTAST STATE TO CLEAN BASELINE'
        if ! su -c 'test -f /data/adb/modules/otast/runtime/entry.sh' >/dev/null 2>&1; then
            fatal 'existing managed OTAST state has no active runtime; manual recovery is required before release proof'
            exit $?
        fi
        run_live verify "$LOG_DIR/baseline-verify.log" || {
            fatal 'existing managed state is not CURRENT; do not auto-restore drifted state'
            exit $?
        }
        grep -q '^CURRENT[[:space:]]' "$LOG_DIR/baseline-verify.log" || {
    fatal 'existing managed state Verify returned success without CURRENT evidence'
    exit $?
}
        run_live restore "$LOG_DIR/baseline-restore.log" || exit $?
        BASELINE_RESULT=PASS
        PHASE=BASELINE_REBOOT
        request_reboot
        exit $?
    fi

    install_exact_draft
    exit $?
fi

if [[ $PHASE == BASELINE_REBOOT ]]; then
    phase_banner 'CONFIRM CLEAN BASELINE REBOOT'
    require_new_boot || exit $?
    if has_managed_state; then
        fatal 'managed state still exists after baseline Restore/reboot'
        exit $?
    fi
    ensure_draft
    draft_rc=$?
    if ((draft_rc == 20)); then exit 0; fi
    ((draft_rc == 0)) || exit "$draft_rc"
    download_and_verify_draft || exit $?
    install_exact_draft
    exit $?
fi

if [[ $PHASE == INSTALL_REBOOT ]]; then
    phase_banner 'POST-INSTALL REPORT → PREFLIGHT → APPLY'
    require_new_boot || exit $?
    verify_installed_draft || exit $?
    run_live report "$LOG_DIR/post-install-report.log" || exit $?
    run_live preflight "$LOG_DIR/preflight.log" || exit $?
    grep -q '^READY[[:space:]]' "$LOG_DIR/preflight.log" || {
        fatal 'Preflight did not report READY'
        exit $?
    }
    operations=$(sed -n 's/^READY[[:space:]]operations=\([0-9][0-9]*\).*/\1/p' "$LOG_DIR/preflight.log" | sed -n '1p')
    [[ -n $operations && $operations -gt 0 ]] || {
        fatal 'release proof requires a changing first Apply; Preflight planned no changes'
        exit $?
    }
    run_live apply "$LOG_DIR/first-apply.log" || exit $?
    grep -q '^REBOOT_REQUIRED[[:space:]]' "$LOG_DIR/first-apply.log" || {
        fatal 'first Apply did not produce REBOOT_REQUIRED'
        exit $?
    }
    PHASE=APPLY_REBOOT
    request_reboot
    exit $?
fi

if [[ $PHASE == APPLY_REBOOT ]]; then
    phase_banner 'VERIFY → SECOND APPLY NO-OP → VERIFY → RESTORE'
    require_new_boot || exit $?
    verify_installed_draft || exit $?
    run_live verify "$LOG_DIR/post-apply-verify.log" || exit $?
    grep -q '^CURRENT[[:space:]]' "$LOG_DIR/post-apply-verify.log" || {
        fatal 'post-reboot Verify did not report any CURRENT managed item'
        exit $?
    }
    run_live apply "$LOG_DIR/second-apply.log" || exit $?
    grep -q '^NO_CHANGES_REQUIRED[[:space:]]' "$LOG_DIR/second-apply.log" || {
        fatal 'second Apply was not a no-op'
        exit $?
    }
    run_live verify "$LOG_DIR/second-verify.log" || exit $?
    grep -q '^CURRENT[[:space:]]' "$LOG_DIR/second-verify.log" || {
        fatal 'second Verify did not report CURRENT managed state'
        exit $?
    }
    run_live restore "$LOG_DIR/restore.log" || exit $?
    PHASE=RESTORE_REBOOT
    request_reboot
    exit $?
fi

if [[ $PHASE == RESTORE_REBOOT ]]; then
    phase_banner 'FINAL POST-RESTORE REPORT'
    require_new_boot || exit $?
    verify_installed_draft || exit $?
    if has_managed_state; then
        fatal 'managed state remains after Restore/reboot'
        exit $?
    fi
    run_live report "$LOG_DIR/final-report.log" || exit $?
    write_proof || { fatal 'cannot write sanitized device proof'; exit $?; }
    PHASE=PROOF_READY
    save_state || exit 1
fi

if [[ $PHASE == PROOF_READY ]]; then
    ensure_draft
    draft_rc=$?
    if ((draft_rc == 20)); then exit 0; fi
    ((draft_rc == 0)) || exit "$draft_rc"
    [[ $DRAFT_TARGET == "$COMMIT_SHA" ]] || {
        fatal 'draft release target changed after device proof'
        exit $?
    }
    [[ -f $ZIP_PATH && ! -L $ZIP_PATH ]] || download_and_verify_draft || exit $?
    publish_proven_draft
    exit $?
fi

fatal "unhandled release phase: $PHASE"
exit $?
