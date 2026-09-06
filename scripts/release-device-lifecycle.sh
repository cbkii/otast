#!/usr/bin/env bash
# Flexible, resumable physical-device release workflow for OTAST.
# The operator runs the same command after each requested reboot.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'STOP: cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
ORIGINAL_ARGS=("$@")

REPO_SLUG=${OTAST_GITHUB_REPO:-cbkii/otast}
WORKFLOW=release.yml
YES=0
NO_REBOOT=0
NO_PUBLISH=0
SHOW_STATUS=0
RESET=0
VERSION=
WARNINGS=0
REEXECED=${OTAST_RELEASE_REEXECED:-0}

warn() { WARNINGS=$((WARNINGS + 1)); printf '[WARN] %s\n' "$*" >&2; }
info() { printf '[INFO] %s\n' "$*"; }
fatal() { printf 'STOP: %s\n' "$*" >&2; return 1; }
phase_banner() { printf '\n==================================================\nOTAST RELEASE: %s\n==================================================\n' "$1"; }

usage() {
    cat <<'EOF_HELP'
Usage: release-device.sh [OPTIONS]

One resumable release command for the registry-declared physical Pixel lifecycle.
The release source is latest GitHub main when the draft is prepared. The exact ZIP
SHA-256 and canonical runtime digest remain locked across every reboot boundary.

Run the same command after every requested reboot:

  otast release

Options:
  --version VERSION   Release version. Default: latest main module.prop version.
  --yes               Approve reboot/publication prompts automatically.
  --no-reboot         Never reboot automatically; print the required boundary.
  --no-publish        Stop after uploading a PASS device proof to the draft.
  --status            Show private resumable state and exit.
  --reset             Remove only this wizard's private state for VERSION.
  -h, --help          Show this help.

Before the evidence phase, place sanitized detector/acceptance inputs in the paths
printed by the wizard. The collector is read-only and never exports keybox/private
key material or changes Magisk/Zygisk/Vector/IHI/denylist/SELinux configuration.
EOF_HELP
}

while (($#)); do
    case $1 in
        --version) (($# >= 2)) || { fatal '--version requires a value'; exit 2; }; VERSION=$2; shift 2 ;;
        --yes) YES=1; shift ;;
        --no-reboot) NO_REBOOT=1; shift ;;
        --no-publish) NO_PUBLISH=1; shift ;;
        --status) SHOW_STATUS=1; shift ;;
        --reset) RESET=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fatal "unknown argument: $1"; usage >&2; exit 2 ;;
    esac
done

retry() {
    local attempts delay description rc attempt
    attempts=$1; delay=$2; description=$3; shift 3; rc=1
    for ((attempt=1; attempt<=attempts; attempt+=1)); do
        "$@"; rc=$?
        ((rc == 0)) && return 0
        if ((attempt < attempts)); then warn "$description failed (attempt $attempt/$attempts, status $rc); retrying in ${delay}s"; sleep "$delay"; fi
    done
    return "$rc"
}

ensure_host_command() {
    local command package
    command=$1; package=$2
    command -v "$command" >/dev/null 2>&1 && return 0
    if command -v pkg >/dev/null 2>&1; then
        info "Installing missing Termux package: $package"
        retry 2 3 "pkg install $package" pkg install -y "$package" >/dev/null 2>&1 || true
    fi
    command -v "$command" >/dev/null 2>&1 || { fatal "required command is missing: $command (Termux package: $package)"; return 1; }
}

ensure_host_tools() {
    ensure_host_command gh gh || return 1
    ensure_host_command git git || return 1
    ensure_host_command python3 python || return 1
    ensure_host_command unzip unzip || return 1
    ensure_host_command sha256sum coreutils || return 1
    ensure_host_command base64 coreutils || return 1
    for command in getprop su grep sed cat sleep date mkdir chmod mv rm awk; do
        command -v "$command" >/dev/null 2>&1 || { fatal "required platform command is missing: $command"; return 1; }
    done
}

refresh_local_main_best_effort() {
    local before after branch
    git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
    if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
        warn 'local checkout is dirty; leaving it untouched. Release still targets GitHub main.'; return 0
    fi
    retry 3 3 'fetch origin/main' git -C "$REPO_ROOT" fetch --quiet origin main || { warn 'could not refresh local main; Release workflow will still use GitHub main.'; return 0; }
    branch=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null)
    [[ $branch == main ]] || { warn "local branch is ${branch:-detached}; not switching it. Release still targets GitHub main."; return 0; }
    before=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null) || before=
    git -C "$REPO_ROOT" merge --ff-only --quiet origin/main || { warn 'local main could not fast-forward cleanly; leaving checkout unchanged.'; return 0; }
    after=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null) || after=$before
    if [[ -n $before && $before != "$after" && $REEXECED != 1 ]]; then
        info 'Local main advanced; restarting once with the updated release script.'
        exec env OTAST_RELEASE_REEXECED=1 bash "$REPO_ROOT/scripts/release-device.sh" "${ORIGINAL_ARGS[@]}"
    fi
}

remote_main_sha() { retry 3 3 'resolve GitHub main' gh api "repos/$REPO_SLUG/commits/main" --jq .sha 2>/dev/null; }
latest_main_version() {
    local encoded value
    encoded=$(retry 3 3 'read latest main module.prop' gh api "repos/$REPO_SLUG/contents/module/module.prop?ref=main" --jq .content 2>/dev/null) || return 1
    value=$(printf '%s' "$encoded" | tr -d '\n' | base64 -d 2>/dev/null | sed -n 's/^version=//p' | sed -n '1p')
    [[ -n $value ]] || return 1; printf '%s\n' "$value"
}

ensure_host_tools || exit $?
gh auth token --hostname github.com >/dev/null 2>&1 || { fatal 'GitHub CLI has no usable local token. Run: gh auth login --hostname github.com'; exit $?; }
refresh_local_main_best_effort

if [[ -z $VERSION ]]; then
    VERSION=$(latest_main_version 2>/dev/null) || VERSION=
    if [[ -z $VERSION ]]; then VERSION=$(sed -n 's/^version=//p' "$REPO_ROOT/module/module.prop" | sed -n '1p'); warn "could not read version from GitHub main; using local module version: ${VERSION:-unknown}"; fi
fi
if [[ -z $VERSION || $VERSION == */* || $VERSION == *$'\n'* ]]; then fatal "invalid release version: ${VERSION:-missing}"; exit 2; fi

STATE_BASE=${HOME:?}/.local/state/otast-release
STATE_DIR=$STATE_BASE/$VERSION
STATE_FILE=$STATE_DIR/state.env
ASSET_DIR=$STATE_DIR/assets
LOG_DIR=$STATE_DIR/logs
PROOF_FILE=$STATE_DIR/otast-${VERSION}-device-proof.json
ROOT_DOCTOR_FILE=$STATE_DIR/root-exposure.json
ACCEPTANCE_FILE=$STATE_DIR/external-acceptance.json
DEVICE_EVIDENCE_FILE=$STATE_DIR/device-evidence.json
ZIP_NAME=otast-${VERSION}.zip
SHA_NAME=$ZIP_NAME.sha256
ZIP_PATH=$ASSET_DIR/$ZIP_NAME
SHA_PATH=$ASSET_DIR/$SHA_NAME
PROOF_NAME=otast-${VERSION}-device-proof.json

if ((RESET)); then
    [[ ! -L $STATE_DIR ]] || { fatal "release state root is a symlink: $STATE_DIR"; exit $?; }
    [[ ! -d $STATE_DIR ]] || rm -rf -- "$STATE_DIR" || { fatal "cannot remove release state: $STATE_DIR"; exit $?; }
    printf 'Reset private release state for %s.\n' "$VERSION"; exit 0
fi
mkdir -p -- "$STATE_DIR" "$ASSET_DIR" "$LOG_DIR" || exit 1
chmod 0700 -- "$STATE_BASE" "$STATE_DIR" "$ASSET_DIR" "$LOG_DIR" 2>/dev/null || true

PHASE=START
MODULE_SHA256=
RUNTIME_DIGEST=
BOOT_BEFORE=
BASELINE_RESULT=NOT_REQUIRED
SOURCE_SHA=
SETTLE_RETRIES=0
RESTORE_RETRIES=0
FIRST_APPLY_NOOP=0
REAPPLY_RESULT=
INSTALL_CONTEXT=FRESH_INSTALL
ABORT_REASON=
STATE_CORRUPT=0

load_state() {
    [[ -e $STATE_FILE ]] || return 0
    [[ -f $STATE_FILE && ! -L $STATE_FILE ]] || { warn "release state file is unsafe and will be assessed for recovery: $STATE_FILE"; STATE_CORRUPT=1; return 0; }
    # shellcheck disable=SC1090
    if ! source "$STATE_FILE"; then warn 'private release state could not be parsed and will be assessed for recovery'; STATE_CORRUPT=1; return 0; fi
    case ${PHASE:-} in
        START|BASELINE_REBOOT|INSTALL_REBOOT|APPLY_REBOOT|EVIDENCE_REQUIRED|RESTORE_REBOOT|REAPPLY_REBOOT|ABORT_RESTORE_REBOOT|PROOF_READY|PUBLISHING|COMPLETE) ;;
        *) warn "unknown private release phase: ${PHASE:-missing}"; STATE_CORRUPT=1 ;;
    esac
    case ${SETTLE_RETRIES:-0} in ''|*[!0-9]*) SETTLE_RETRIES=0; STATE_CORRUPT=1 ;; esac
    case ${RESTORE_RETRIES:-0} in ''|*[!0-9]*) RESTORE_RETRIES=0; STATE_CORRUPT=1 ;; esac
    case ${FIRST_APPLY_NOOP:-0} in 0|1) ;; *) FIRST_APPLY_NOOP=0; STATE_CORRUPT=1 ;; esac
}

save_state() {
    local tmp
    tmp=$STATE_FILE.tmp.$$
    umask 077
    {
        printf 'PHASE=%q\n' "$PHASE"
        printf 'MODULE_SHA256=%q\n' "$MODULE_SHA256"
        printf 'RUNTIME_DIGEST=%q\n' "$RUNTIME_DIGEST"
        printf 'BOOT_BEFORE=%q\n' "$BOOT_BEFORE"
        printf 'BASELINE_RESULT=%q\n' "$BASELINE_RESULT"
        printf 'SOURCE_SHA=%q\n' "$SOURCE_SHA"
        printf 'SETTLE_RETRIES=%q\n' "$SETTLE_RETRIES"
        printf 'RESTORE_RETRIES=%q\n' "$RESTORE_RETRIES"
        printf 'FIRST_APPLY_NOOP=%q\n' "$FIRST_APPLY_NOOP"
        printf 'REAPPLY_RESULT=%q\n' "$REAPPLY_RESULT"
        printf 'INSTALL_CONTEXT=%q\n' "$INSTALL_CONTEXT"
        printf 'ABORT_REASON=%q\n' "$ABORT_REASON"
    } >"$tmp" || return 1
    chmod 0600 -- "$tmp" || return 1
    mv -f -- "$tmp" "$STATE_FILE"
}

load_state
if ((SHOW_STATUS)); then
    printf 'Version:        %s\n' "$VERSION"
    printf 'Phase:          %s\n' "$PHASE"
    printf 'Module SHA:     %s\n' "${MODULE_SHA256:-unknown}"
    printf 'Runtime digest: %s\n' "${RUNTIME_DIGEST:-unknown}"
    printf 'Source:         %s\n' "${SOURCE_SHA:-latest-main/unknown}"
    printf 'Install path:   %s\n' "$INSTALL_CONTEXT"
    printf 'Evidence:       %s\n' "$DEVICE_EVIDENCE_FILE"
    printf 'State:          %s\n' "$STATE_FILE"
    exit 0
fi

wait_for_android_ready() { local attempt value; for ((attempt=1; attempt<=30; attempt+=1)); do value=$(getprop sys.boot_completed 2>/dev/null); [[ $value == 1 ]] && return 0; ((attempt % 5 == 0)) && info 'Waiting for Android boot completion...'; sleep 2; done; warn 'sys.boot_completed did not become 1 within 60 seconds; continuing with root readiness checks.'; return 0; }
wait_for_root() { local attempt; for ((attempt=1; attempt<=20; attempt+=1)); do if su -c 'id -u' 2>/dev/null | grep -qx '0' && su -c 'magisk -V' >/dev/null 2>&1; then return 0; fi; ((attempt % 5 == 0)) && info 'Waiting for Magisk root...'; sleep 3; done; fatal 'Magisk root/CLI did not become available after bounded waiting'; return 1; }

load_release_reference() {
    python3 - "$REPO_ROOT" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1])
r=json.loads((root/'compatibility/supported-targets.json').read_text())
s=r['support_model']; ref=s['release_reference']; dev=s['devices'][ref['device']]
p=r['platforms'][ref['platform_profile']]; profile=json.loads((root/p['profile']).read_text())
fixture=(root/ref['authority_fixture']).read_text()
props={}
for line in fixture.splitlines():
    if line and not line.startswith('#') and '=' in line:
        k,v=line.split('=',1); props[k]=v
print('\t'.join(str(x) for x in (
    ref['device'], ref.get('model', dev.get('model','')), props.get('ro.product.manufacturer',''),
    ref['build'], props.get('ro.build.fingerprint',''), ref['platform_profile'], profile['sdk']
)))
PY
}

wait_for_android_ready; wait_for_root || exit $?
IFS=$'\t' read -r EXPECTED_DEVICE EXPECTED_MODEL EXPECTED_MANUFACTURER EXPECTED_BUILD EXPECTED_FINGERPRINT EXPECTED_PROFILE EXPECTED_SDK < <(load_release_reference) || { fatal 'cannot resolve compatibility release reference'; exit $?; }
DEVICE=$(getprop ro.product.device 2>/dev/null)
MODEL=$(getprop ro.product.model 2>/dev/null)
MANUFACTURER=$(getprop ro.product.manufacturer 2>/dev/null)
BUILD_ID=$(getprop ro.build.id 2>/dev/null)
FINGERPRINT=$(getprop ro.build.fingerprint 2>/dev/null)
SDK=$(getprop ro.build.version.sdk 2>/dev/null)
if [[ $DEVICE != "$EXPECTED_DEVICE" || $MODEL != "$EXPECTED_MODEL" || $MANUFACTURER != "$EXPECTED_MANUFACTURER" || $BUILD_ID != "$EXPECTED_BUILD" || $FINGERPRINT != "$EXPECTED_FINGERPRINT" || $SDK != "$EXPECTED_SDK" ]]; then
    fatal "physical release proof does not match declared release reference ($EXPECTED_DEVICE/$EXPECTED_BUILD/$EXPECTED_PROFILE); observed device=$DEVICE model=$MODEL manufacturer=$MANUFACTURER build=$BUILD_ID sdk=$SDK"
    exit $?
fi

current_boot_id() { cat /proc/sys/kernel/random/boot_id 2>/dev/null; }
has_managed_state() { su -c 'for f in /data/adb/otast/records/*.state; do [ -f "$f" ] && exit 0; done; exit 1' >/dev/null 2>&1; }

recover_corrupt_private_state() {
    local broken
    ((STATE_CORRUPT)) || return 0
    if has_managed_state; then fatal 'private release state is corrupt while live OTAST managed state exists; automated reset would lose lifecycle position'; return 1; fi
    broken=$STATE_FILE.broken.$(date -u +%Y%m%dT%H%M%SZ)
    if [[ -e $STATE_FILE ]]; then mv -- "$STATE_FILE" "$broken" || return 1; warn "quarantined corrupt private state to $broken"; fi
    PHASE=START; MODULE_SHA256=; RUNTIME_DIGEST=; BOOT_BEFORE=; BASELINE_RESULT=NOT_REQUIRED; SOURCE_SHA=; SETTLE_RETRIES=0; RESTORE_RETRIES=0; FIRST_APPLY_NOOP=0; REAPPLY_RESULT=; INSTALL_CONTEXT=FRESH_INSTALL; ABORT_REASON=; STATE_CORRUPT=0
    save_state || return 1; info 'Recovered by restarting from a clean private release state.'
}
recover_corrupt_private_state || exit $?

run_live() { local action log rc; action=$1; log=$2; info "Live OTAST: $action"; su -c "sh /data/adb/modules/otast/runtime/entry.sh $action" >"$log" 2>&1; rc=$?; cat "$log"; return "$rc"; }
run_boot_recover_best_effort() { if su -c 'test -f /data/adb/modules/otast/runtime/entry.sh' >/dev/null 2>&1; then info 'Attempting OTAST boot-recover before retry.'; run_live boot-recover "$LOG_DIR/boot-recover-$(date -u +%H%M%S).log" || warn 'boot-recover did not complete cleanly'; fi; }

request_reboot() {
    local answer
    BOOT_BEFORE=$(current_boot_id) || { fatal 'cannot read current boot ID'; return 1; }
    save_state || { fatal 'cannot persist reboot boundary'; return 1; }
    printf '\nRequired reboot boundary reached.\nAfter Android is fully booted, run the SAME command again:\n  otast release\n\n'
    ((NO_REBOOT)) && return 10
    if ((YES)); then answer=y; elif [[ -t 0 ]]; then printf 'Reboot now? [Y/n] '; if IFS= read -r -t 30 answer; then answer=${answer:-y}; else printf '\nNo response; reboot was not requested.\n'; return 10; fi; else return 10; fi
    case $answer in y|Y|yes|YES) info 'Requesting reboot through root'; su -c reboot >/dev/null 2>&1 || warn 'reboot command returned non-zero; reboot manually if needed'; return 10 ;; *) return 10 ;; esac
}
require_new_boot() { local now; now=$(current_boot_id) || { fatal 'cannot read current boot ID'; return 1; }; if [[ -z $BOOT_BEFORE || $now == "$BOOT_BEFORE" ]]; then info 'A real reboot is still required for this phase.'; request_reboot; return $?; fi; BOOT_BEFORE=; save_state || return 1; wait_for_android_ready; wait_for_root || return 1; return 0; }

workflow_run_id() {
    local title head since json
    title=$1; head=$2; since=$3
    json=$(gh run list -R "$REPO_SLUG" --workflow "$WORKFLOW" --branch main --event workflow_dispatch --limit 30 --json databaseId,displayTitle,headSha,status,conclusion,createdAt 2>/dev/null) || return 1
    EXPECTED_TITLE=$title EXPECTED_HEAD=$head SINCE=$since python3 -c '
import json, os, sys
runs=json.load(sys.stdin); since=os.environ.get("SINCE") or ""; items=[r for r in runs if r.get("displayTitle")==os.environ["EXPECTED_TITLE"]]
if since: items=[r for r in items if (r.get("createdAt") or "") >= since]
if os.environ.get("EXPECTED_HEAD"):
    exact=[r for r in items if r.get("headSha")==os.environ["EXPECTED_HEAD"]]
    if exact: items=exact
items.sort(key=lambda r:r.get("createdAt", ""), reverse=True); print(items[0]["databaseId"] if items else "")' <<<"$json"
}
watch_run() {
    local run_id status conclusion attempt json failed_log
    run_id=$1
    for ((attempt=1; attempt<=240; attempt+=1)); do
        json=$(gh run view "$run_id" -R "$REPO_SLUG" --json status,conclusion 2>/dev/null) || {
            ((attempt % 6 == 0)) && warn "cannot read workflow state yet ($attempt/240)"
            sleep 10
            continue
        }
        status=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("status", ""))' <<<"$json")
        conclusion=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("conclusion") or "")' <<<"$json")
        if [[ $status == completed ]]; then
            [[ $conclusion == success ]] && return 0
            failed_log=$(gh run view "$run_id" -R "$REPO_SLUG" --log-failed 2>/dev/null || true)
            [[ -z $failed_log ]] || printf '%s\n' "$failed_log"
            if grep -Eq 'Fresh target/dependency .*status 10' <<<"$failed_log"; then
                warn 'GitHub Release workflow stopped for deterministic compatibility review; not retrying the identical workflow.'
                return 10
            fi
            warn "GitHub Release workflow concluded ${conclusion:-unknown}"
            return 1
        fi
        ((attempt % 6 == 0)) && info "Waiting for GitHub Release workflow ($status)"
        sleep 10
    done
    warn 'GitHub Release workflow did not complete within 40 minutes'
    return 1
}
dispatch_release_workflow() {
    local operation head title run_id attempt dispatch_try dispatch_at watch_rc
    operation=$1
    head=$(remote_main_sha 2>/dev/null) || head=
    title="Release $operation $VERSION"
    for ((dispatch_try=1; dispatch_try<=2; dispatch_try+=1)); do
        info "Dispatching GitHub Actions from latest main: $title"
        dispatch_at=$(date -u +%Y-%m-%dT%H:%M:%SZ) || return 1
        gh workflow run "$WORKFLOW" -R "$REPO_SLUG" --ref main -f "operation=$operation" -f "version=$VERSION" >/dev/null 2>&1 || {
            warn "cannot dispatch Release workflow (attempt $dispatch_try/2)"
            sleep 3
            continue
        }
        run_id=
        for ((attempt=1; attempt<=30; attempt+=1)); do
            run_id=$(workflow_run_id "$title" "$head" "$dispatch_at") || run_id=
            [[ -n $run_id ]] && break
            sleep 4
        done
        if [[ -n $run_id ]]; then
            info "Watching workflow run $run_id"
            watch_run "$run_id"
            watch_rc=$?
            ((watch_rc == 0)) && return 0
            ((watch_rc == 10)) && return 10
        fi
        warn "Release workflow attempt $dispatch_try did not complete successfully"
    done
    return 1
}

release_json() { gh release view "$VERSION" -R "$REPO_SLUG" --json isDraft,tagName,targetCommitish,assets 2>/dev/null; }
release_has_proof_asset() { local json; json=$1; PROOF_ASSET=$PROOF_NAME python3 -c 'import json,os,sys; value=json.load(sys.stdin); print("yes" if any(a.get("name")==os.environ["PROOF_ASSET"] for a in value.get("assets", [])) else "no")' <<<"$json"; }
delete_draft_best_effort() { info "Removing stale/incomplete draft $VERSION so latest main can be rebuilt."; gh release delete "$VERSION" -R "$REPO_SLUG" --cleanup-tag --yes >/dev/null 2>&1 && return 0; gh release delete "$VERSION" -R "$REPO_SLUG" --yes >/dev/null 2>&1 || return 1; gh api -X DELETE "repos/$REPO_SLUG/git/refs/tags/$VERSION" >/dev/null 2>&1 || true; return 0; }

ensure_draft() {
    local json draft tag target latest has_proof dispatch_rc
    json=$(release_json) || json=
    if [[ -n $json ]]; then
        draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$json"); tag=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tagName"])' <<<"$json"); target=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("targetCommitish") or "")' <<<"$json")
        [[ $tag == "$VERSION" ]] || { fatal "release tag mismatch: $tag"; return 1; }
        if [[ $draft != true ]]; then PHASE=COMPLETE; save_state || return 1; printf 'Release %s is already published.\n' "$VERSION"; return 20; fi
        has_proof=$(release_has_proof_asset "$json") || has_proof=no; latest=$(remote_main_sha 2>/dev/null) || latest=
        if [[ $PHASE == START && $has_proof != yes && -n $latest && -n $target && $target != "$latest" ]]; then warn 'Existing draft was built from an older main and has no valid current proof; rebuilding it automatically.'; delete_draft_best_effort || { fatal 'cannot replace stale draft release'; return 1; }; json=; else SOURCE_SHA=$target; return 0; fi
    fi
    if [[ -z $json ]]; then
        dispatch_release_workflow draft
        dispatch_rc=$?
        if ((dispatch_rc == 10)); then
            fatal 'release is blocked by a deterministic compatibility review; resolve the reported target before retrying this same command'
            return 10
        fi
        if ((dispatch_rc != 0)); then
            json=$(release_json) || json=
            [[ -n $json ]] || { fatal 'cannot create or find draft release after workflow failure'; return 1; }
        fi
        json=$(release_json) || { fatal 'draft release was not created'; return 1; }; draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$json"); [[ $draft == true ]] || { fatal 'new release is not a draft'; return 1; }; SOURCE_SHA=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("targetCommitish") or "")' <<<"$json")
    fi
    save_state || return 1; return 0
}

download_assets_once() { rm -f -- "$ZIP_PATH" "$SHA_PATH"; gh release download "$VERSION" -R "$REPO_SLUG" --pattern "$ZIP_NAME" --pattern "$SHA_NAME" --dir "$ASSET_DIR" --clobber >/dev/null 2>&1; }
download_and_verify_draft() {
    local zip_sha embedded_version embedded_source embedded_runtime
    retry 3 3 'download draft assets' download_assets_once || return 1
    [[ -f $ZIP_PATH && ! -L $ZIP_PATH && -f $SHA_PATH && ! -L $SHA_PATH ]] || return 1
    (cd -- "$ASSET_DIR" && sha256sum -c "$SHA_NAME") >/dev/null 2>&1 || return 1
    zip_sha=$(sha256sum "$ZIP_PATH") || return 1; zip_sha=${zip_sha%% *}
    embedded_version=$(unzip -p "$ZIP_PATH" module.prop 2>/dev/null | sed -n 's/^version=//p' | sed -n '1p')
    embedded_source=$(unzip -p "$ZIP_PATH" release.properties 2>/dev/null | sed -n 's/^commit_sha=//p' | sed -n '1p')
    embedded_runtime=$(unzip -p "$ZIP_PATH" release.properties 2>/dev/null | sed -n 's/^runtime_digest=//p' | sed -n '1p')
    [[ $embedded_version == "$VERSION" && $embedded_runtime =~ ^[0-9a-f]{64}$ ]] || { warn 'draft ZIP version/runtime provenance is invalid'; return 1; }
    if [[ -n $MODULE_SHA256 && $PHASE != START && $zip_sha != "$MODULE_SHA256" ]]; then warn "draft ZIP SHA changed during active proof: expected=$MODULE_SHA256 observed=$zip_sha"; return 1; fi
    if [[ -n $RUNTIME_DIGEST && $PHASE != START && $embedded_runtime != "$RUNTIME_DIGEST" ]]; then warn 'draft runtime digest changed during active proof'; return 1; fi
    MODULE_SHA256=$zip_sha; RUNTIME_DIGEST=$embedded_runtime; [[ -n $embedded_source ]] && SOURCE_SHA=$embedded_source; save_state || return 1
    info "Locked release asset SHA-256: $MODULE_SHA256"; info "Locked runtime digest: $RUNTIME_DIGEST"; return 0
}
prepare_draft_assets() {
    local rc dispatch_rc
    ensure_draft
    rc=$?
    ((rc == 20)) && return 20
    ((rc == 0)) || return "$rc"
    if download_and_verify_draft; then return 0; fi
    if [[ $PHASE == START ]]; then
        warn 'Draft assets are missing/corrupt before device proof; rebuilding draft from latest main once.'
        delete_draft_best_effort || return 1
        dispatch_release_workflow draft
        dispatch_rc=$?
        ((dispatch_rc == 0)) || return "$dispatch_rc"
        ensure_draft || return $?
        download_and_verify_draft || { fatal 'rebuilt draft assets still fail integrity checks'; return 1; }
        return 0
    fi
    fatal 'locked draft asset integrity failed during an active proof; refusing to substitute another ZIP'
    return 1
}

wait_for_module_runtime() { local attempt; for ((attempt=1; attempt<=30; attempt+=1)); do su -c 'test -f /data/adb/modules/otast/runtime/entry.sh' >/dev/null 2>&1 && return 0; sleep 2; done; return 1; }
verify_installed_draft() { local module_prop release_props installed_version installed_source installed_runtime; wait_for_module_runtime || return 1; module_prop=$(su -c 'cat /data/adb/modules/otast/module.prop' 2>/dev/null) || return 1; release_props=$(su -c 'cat /data/adb/modules/otast/release.properties' 2>/dev/null) || return 1; installed_version=$(sed -n 's/^version=//p' <<<"$module_prop" | sed -n '1p'); installed_source=$(sed -n 's/^commit_sha=//p' <<<"$release_props" | sed -n '1p'); installed_runtime=$(sed -n 's/^runtime_digest=//p' <<<"$release_props" | sed -n '1p'); [[ $installed_version == "$VERSION" && $installed_runtime == "$RUNTIME_DIGEST" ]] || return 1; [[ -n $installed_source ]] && SOURCE_SHA=$installed_source; su -c 'test -e /data/adb/modules/otast/disable' >/dev/null 2>&1 && return 1; save_state || return 1; return 0; }

install_exact_draft() { local root_zip rc attempt; root_zip=/data/local/tmp/otast-release-${VERSION#v}.zip; phase_banner 'INSTALL EXACT RELEASE ZIP'; rc=1; for ((attempt=1; attempt<=2; attempt+=1)); do rc=0; su -c "rm -f '$root_zip'" >/dev/null 2>&1 || true; su -c "cat > '$root_zip'" <"$ZIP_PATH" || rc=$?; if ((rc == 0)); then su -c "chmod 0600 '$root_zip' && magisk --install-module '$root_zip'" >"$LOG_DIR/install-$attempt.log" 2>&1; rc=$?; cat "$LOG_DIR/install-$attempt.log"; fi; su -c "rm -f '$root_zip'" >/dev/null 2>&1 || true; ((rc == 0)) && break; warn "Magisk module installation failed (attempt $attempt/2, status $rc)"; sleep 3; done; ((rc == 0)) || { fatal 'Magisk module installation failed after retry'; return 1; }; PHASE=INSTALL_REBOOT; request_reboot; }
verify_with_recovery() { local log=$1; run_live verify "$log" && return 0; warn 'Verify failed; attempting boot-recover and one retry.'; run_boot_recover_best_effort; sleep 2; run_live verify "$log.retry"; }
restore_with_recovery() { local log=$1; run_live restore "$log" && return 0; warn 'Restore failed; attempting boot-recover and one retry.'; run_boot_recover_best_effort; run_live restore "$log.retry"; }
apply_with_recovery() { local log=$1; run_live apply "$log" && return 0; warn 'Apply failed; recovering transaction state and retrying once.'; run_boot_recover_best_effort; run_live preflight "$LOG_DIR/preflight-retry.log" || return 1; run_live apply "$log.retry"; }
begin_safe_abort_restore() { local reason=$1; ABORT_REASON=$reason; warn "$reason"; if has_managed_state && su -c 'test -f /data/adb/modules/otast/runtime/entry.sh' >/dev/null 2>&1; then phase_banner 'SAFE UNWIND AFTER RELEASE FAILURE'; if restore_with_recovery "$LOG_DIR/abort-restore.log"; then PHASE=ABORT_RESTORE_REBOOT; request_reboot; return $?; fi; fi; fatal "$reason; automatic safe Restore was not possible"; return 1; }

collect_physical_evidence() {
    [[ -f $ROOT_DOCTOR_FILE && ! -L $ROOT_DOCTOR_FILE ]] || { printf '\nPhysical evidence is required before Restore.\nRun the current root-exposure doctor with Duck left running and save JSON to:\n  %s\n' "$ROOT_DOCTOR_FILE"; return 10; }
    [[ -f $ACCEPTANCE_FILE && ! -L $ACCEPTANCE_FILE ]] || { printf '\nCreate sanitized external acceptance JSON at:\n  %s\nRequired keys: tricky_store_health=PASS, local_attestation=PASS, play_integrity basic/device/strong=PASS, play_store_certification=CERTIFIED.\nDo not include keybox/private-key material.\n' "$ACCEPTANCE_FILE"; return 10; }
    python3 "$SCRIPT_DIR/collect-device-qualification.py" --root-doctor-json "$ROOT_DOCTOR_FILE" --acceptance-json "$ACCEPTANCE_FILE" --output "$DEVICE_EVIDENCE_FILE" >"$LOG_DIR/device-evidence.stdout.json" || return 1
    return 0
}

write_proof() {
    local generated apply_phase
    generated=$(date -u +%Y-%m-%dT%H:%M:%SZ) || return 1
    if [[ $FIRST_APPLY_NOOP == 1 ]]; then apply_phase=SKIPPED_NO_CHANGES; elif ((SETTLE_RETRIES > 0)); then apply_phase=PASS_AFTER_SETTLING_REBOOT; else apply_phase=PASS; fi
    VERSION_VALUE=$VERSION SOURCE_VALUE=$SOURCE_SHA ZIP_SHA_VALUE=$MODULE_SHA256 RUNTIME_VALUE=$RUNTIME_DIGEST BASELINE_VALUE=$BASELINE_RESULT APPLY_VALUE=$apply_phase REAPPLY_VALUE=$REAPPLY_RESULT GENERATED_VALUE=$generated PROOF_PATH=$PROOF_FILE DEVICE_EVIDENCE_PATH=$DEVICE_EVIDENCE_FILE ZIP_PATH_VALUE=$ZIP_PATH REPO_ROOT_VALUE=$REPO_ROOT \
    python3 - <<'PY'
import json, os, zipfile
from pathlib import Path
import sys
root=Path(os.environ['REPO_ROOT_VALUE']); sys.path.insert(0,str(root))
from tools.otastctl.qualification import registry_provenance
zip_path=Path(os.environ['ZIP_PATH_VALUE'])
with zipfile.ZipFile(zip_path) as z:
    module={k:v for k,v in (line.split('=',1) for line in z.read('module.prop').decode().splitlines() if '=' in line)}
evidence=json.loads(Path(os.environ['DEVICE_EVIDENCE_PATH']).read_text())
value={
  'schema_version':4,
  'result':'PASS',
  'evidence_kind':'DIRECT_PHYSICAL',
  'version':os.environ['VERSION_VALUE'],
  'version_code':int(module['versionCode']),
  'qualified_source_commit':os.environ['SOURCE_VALUE'],
  'current_source_commit':os.environ['SOURCE_VALUE'],
  'qualified_zip_sha256':os.environ['ZIP_SHA_VALUE'],
  'current_zip_sha256':os.environ['ZIP_SHA_VALUE'],
  'runtime_digest_algorithm':'otast-runtime-v1',
  'runtime_digest':os.environ['RUNTIME_VALUE'],
  'registry_provenance':registry_provenance(root),
  'device_evidence':evidence,
  'installation_context':os.environ.get('INSTALL_CONTEXT_VALUE','FRESH_INSTALL'),
  'phases':{
    'baseline':os.environ['BASELINE_VALUE'], 'install_reboot':'PASS', 'preflight':'PASS',
    'apply':os.environ['APPLY_VALUE'], 'post_apply_reboot':'SKIPPED_NO_CHANGES' if os.environ['APPLY_VALUE']=='SKIPPED_NO_CHANGES' else 'PASS',
    'verify':'PASS', 'second_apply_noop':'PASS', 'restore':'PASS', 'restore_reboot_report':'PASS',
    'reapply':os.environ['REAPPLY_VALUE'] or 'PASS'},
  'generated_utc':os.environ['GENERATED_VALUE']}
path=Path(os.environ['PROOF_PATH']); tmp=path.with_name(path.name+'.tmp'); tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n'); tmp.chmod(0o600); tmp.replace(path)
PY
}
validate_local_proof() { python3 "$SCRIPT_DIR/validate-device-release-proof.py" --proof "$PROOF_FILE" --module-zip "$ZIP_PATH" --version "$VERSION"; }

recover_proof_asset_if_available() { local json has_proof; json=$(release_json) || return 1; has_proof=$(release_has_proof_asset "$json") || return 1; [[ $has_proof == yes ]] || return 1; retry 3 3 'download existing device proof' gh release download "$VERSION" -R "$REPO_SLUG" --pattern "$PROOF_NAME" --dir "$STATE_DIR" --clobber >/dev/null 2>&1 || return 1; [[ -f $PROOF_FILE ]] || return 1; prepare_draft_assets || return 1; validate_local_proof || return 1; PHASE=PROOF_READY; save_state || return 1; info 'Recovered an already-valid runtime-bound device proof from the draft release.'; return 0; }
publish_proven_draft() { local json draft answer; phase_banner 'UPLOAD PROOF + PUBLISH VALIDATED DRAFT'; validate_local_proof || return $?; retry 3 3 'upload device proof' gh release upload "$VERSION" "$PROOF_FILE" -R "$REPO_SLUG" --clobber || { fatal 'cannot upload sanitized device proof after retries'; return 1; }; if ((NO_PUBLISH)); then printf 'PASS proof uploaded. Draft intentionally left unpublished (--no-publish).\n'; return 0; fi; if ((YES == 0)); then if [[ ! -t 0 ]]; then printf 'PASS proof uploaded. Re-run with --yes to request publication.\n'; return 0; fi; printf 'Publish the validated %s draft now? [y/N] ' "$VERSION"; if ! IFS= read -r -t 30 answer; then printf '\nPublication not requested.\n'; return 0; fi; case $answer in y|Y|yes|YES) ;; *) printf 'Publication not requested.\n'; return 0 ;; esac; fi; PHASE=PUBLISHING; save_state || return 1; dispatch_release_workflow publish || { warn 'publish workflow failed; checking whether GitHub published anyway.'; json=$(release_json) || json=; if [[ -n $json ]]; then draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$json"); [[ $draft == false ]] && PHASE=COMPLETE && save_state && return 0; fi; PHASE=PROOF_READY; save_state || true; fatal 'publication did not complete; proof/draft are preserved and a rerun will retry publication'; return 1; }; json=$(release_json) || { fatal 'published release cannot be read'; return 1; }; draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$json"); [[ $draft == false ]] || { fatal 'Release workflow completed but release is still draft'; return 1; }; PHASE=COMPLETE; save_state || return 1; printf '\nRELEASE COMPLETE: %s\nPublished exact module SHA-256: %s\nRuntime digest: %s\n' "$VERSION" "$MODULE_SHA256" "$RUNTIME_DIGEST"; }

if [[ $PHASE == COMPLETE ]]; then printf 'Release %s is already complete.\n' "$VERSION"; exit 0; fi
if [[ $PHASE == PUBLISHING ]]; then json=$(release_json) || json=; if [[ -n $json ]]; then draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$json"); if [[ $draft == false ]]; then PHASE=COMPLETE; save_state || exit 1; printf 'Release %s is already published.\n' "$VERSION"; exit 0; fi; fi; PHASE=PROOF_READY; save_state || exit 1; fi

if [[ $PHASE == START ]]; then
    phase_banner 'PREPARE LATEST MAIN DRAFT'
    if recover_proof_asset_if_available; then :; else prepare_draft_assets; draft_rc=$?; ((draft_rc == 20)) && exit 0; ((draft_rc == 0)) || exit "$draft_rc"; fi
    if [[ $PHASE == PROOF_READY ]]; then publish_proven_draft; exit $?; fi
    active_version=$(su -c 'sed -n "s/^version=//p" /data/adb/modules/otast/module.prop 2>/dev/null | head -n1' 2>/dev/null || true)
    stable_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$REPO_ROOT/update.json" 2>/dev/null || true)
    if [[ -n $active_version && $active_version == "$stable_version" ]]; then INSTALL_CONTEXT=UPGRADE_FROM_STABLE; elif [[ -n $active_version || $(has_managed_state; echo $?) == 0 ]]; then INSTALL_CONTEXT=EXISTING_MANAGED_STATE; else INSTALL_CONTEXT=FRESH_INSTALL; fi
    save_state || exit 1
    if has_managed_state; then
        phase_banner 'RESTORE EXISTING OTAST STATE TO CLEAN BASELINE'
        if ! su -c 'test -f /data/adb/modules/otast/runtime/entry.sh' >/dev/null 2>&1; then
            if su -c 'test -f /data/adb/modules_update/otast/runtime/entry.sh' >/dev/null 2>&1; then warn 'OTAST runtime is staged but not active; rebooting once to activate it before baseline verification.'; BASELINE_RESULT=NEEDS_VERIFY; PHASE=BASELINE_REBOOT; request_reboot; exit $?; fi
            fatal 'existing managed OTAST state has no active/staged runtime; automated Restore cannot be proven safe'; exit $?
        fi
        verify_with_recovery "$LOG_DIR/baseline-verify.log" || { fatal 'existing managed state could not be verified after boot-recovery; refusing to auto-restore drifted state'; exit $?; }
        grep -q '^CURRENT[[:space:]]' "$LOG_DIR/baseline-verify.log" "$LOG_DIR/baseline-verify.log.retry" 2>/dev/null || { fatal 'existing managed state Verify returned success without CURRENT evidence; refusing to conceal possible drift'; exit $?; }
        restore_with_recovery "$LOG_DIR/baseline-restore.log" || { fatal 'existing managed state could not be safely restored after recovery retry'; exit $?; }
        BASELINE_RESULT=PASS; PHASE=BASELINE_REBOOT; request_reboot; exit $?
    fi
    install_exact_draft; exit $?
fi

if [[ $PHASE == BASELINE_REBOOT ]]; then
    phase_banner 'CONFIRM/RECOVER CLEAN BASELINE REBOOT'; require_new_boot || exit $?
    if has_managed_state; then
        if [[ $BASELINE_RESULT == NEEDS_VERIFY ]]; then
            su -c 'test -f /data/adb/modules/otast/runtime/entry.sh' >/dev/null 2>&1 || { fatal 'staged OTAST runtime did not become active after reboot; existing managed state cannot be verified safely'; exit $?; }
            verify_with_recovery "$LOG_DIR/baseline-verify-after-activation.log" || { fatal 'existing managed state could not be verified after activating staged runtime'; exit $?; }
            grep -q '^CURRENT[[:space:]]' "$LOG_DIR/baseline-verify-after-activation.log" "$LOG_DIR/baseline-verify-after-activation.log.retry" 2>/dev/null || { fatal 'existing managed state is not proven CURRENT after activating staged runtime; refusing automatic Restore'; exit $?; }
            restore_with_recovery "$LOG_DIR/baseline-restore-after-activation.log" || { fatal 'verified existing managed state could not be restored after activating staged runtime'; exit $?; }
            BASELINE_RESULT=PASS; RESTORE_RETRIES=0; save_state || exit 1; request_reboot; exit $?
        fi
        if ((RESTORE_RETRIES < 1)) && su -c 'test -f /data/adb/modules/otast/runtime/entry.sh' >/dev/null 2>&1; then RESTORE_RETRIES=$((RESTORE_RETRIES + 1)); warn 'Managed records remain after Restore/reboot; retrying Restore once.'; restore_with_recovery "$LOG_DIR/baseline-restore-retry.log" || { fatal 'baseline Restore retry failed'; exit $?; }; save_state || exit 1; request_reboot; exit $?; fi
        fatal 'managed state remains after bounded baseline Restore recovery'; exit $?
    fi
    [[ $BASELINE_RESULT != NEEDS_VERIFY ]] || BASELINE_RESULT=PASS
    RESTORE_RETRIES=0; save_state || exit 1; prepare_draft_assets || exit $?; install_exact_draft; exit $?
fi

if [[ $PHASE == INSTALL_REBOOT ]]; then
    phase_banner 'POST-INSTALL REPORT → PREFLIGHT → APPLY'; require_new_boot || exit $?
    if ! verify_installed_draft; then if ((SETTLE_RETRIES < 1)); then SETTLE_RETRIES=$((SETTLE_RETRIES + 1)); warn 'Installed OTAST runtime is not active yet; requesting one additional settling reboot.'; save_state || exit 1; request_reboot; exit $?; fi; fatal 'installed OTAST module/runtime is still unavailable after an extra reboot'; exit $?; fi
    SETTLE_RETRIES=0; run_live report "$LOG_DIR/post-install-report.log" || warn 'initial Report returned non-zero; continuing to authoritative Preflight'
    run_live preflight "$LOG_DIR/preflight.log" || { run_boot_recover_best_effort; run_live preflight "$LOG_DIR/preflight.retry.log" || { begin_safe_abort_restore 'Preflight failed after recovery retry'; exit $?; }; }
    grep -q '^READY[[:space:]]' "$LOG_DIR/preflight.log" "$LOG_DIR/preflight.retry.log" 2>/dev/null || { begin_safe_abort_restore 'Preflight did not report READY after recovery retry'; exit $?; }
    apply_with_recovery "$LOG_DIR/first-apply.log" || { begin_safe_abort_restore 'first Apply failed after transaction recovery retry'; exit $?; }
    if grep -q '^REBOOT_REQUIRED[[:space:]]' "$LOG_DIR/first-apply.log" "$LOG_DIR/first-apply.log.retry" 2>/dev/null; then PHASE=APPLY_REBOOT; FIRST_APPLY_NOOP=0; SETTLE_RETRIES=0; request_reboot; exit $?; fi
    if grep -q '^NO_CHANGES_REQUIRED[[:space:]]' "$LOG_DIR/first-apply.log" "$LOG_DIR/first-apply.log.retry" 2>/dev/null; then info 'System was already current; no first-Apply reboot is required.'; FIRST_APPLY_NOOP=1; PHASE=APPLY_REBOOT; BOOT_BEFORE=; save_state || exit 1; else begin_safe_abort_restore 'first Apply returned an unrecognized terminal result'; exit $?; fi
fi

if [[ $PHASE == APPLY_REBOOT ]]; then
    phase_banner 'VERIFY → SECOND APPLY NO-OP → VERIFY'; [[ -z $BOOT_BEFORE ]] || require_new_boot || exit $?
    verify_installed_draft || { begin_safe_abort_restore 'installed release cannot be verified before no-op proof'; exit $?; }
    verify_with_recovery "$LOG_DIR/post-apply-verify.log" || { begin_safe_abort_restore 'post-Apply Verify failed after recovery retry'; exit $?; }
    [[ $FIRST_APPLY_NOOP == 1 ]] || grep -q '^CURRENT[[:space:]]' "$LOG_DIR/post-apply-verify.log" "$LOG_DIR/post-apply-verify.log.retry" 2>/dev/null || { begin_safe_abort_restore 'post-Apply Verify did not report CURRENT managed state'; exit $?; }
    apply_with_recovery "$LOG_DIR/second-apply.log" || { begin_safe_abort_restore 'second Apply failed after recovery retry'; exit $?; }
    if grep -q '^REBOOT_REQUIRED[[:space:]]' "$LOG_DIR/second-apply.log" "$LOG_DIR/second-apply.log.retry" 2>/dev/null; then if ((SETTLE_RETRIES < 2)); then SETTLE_RETRIES=$((SETTLE_RETRIES + 1)); warn "Second Apply changed files; allowing bounded settling reboot $SETTLE_RETRIES/2 before declaring a writer conflict."; save_state || exit 1; request_reboot; exit $?; fi; begin_safe_abort_restore 'persistent external writer conflict: second Apply kept changing files after settling reboots'; exit $?; fi
    grep -q '^NO_CHANGES_REQUIRED[[:space:]]' "$LOG_DIR/second-apply.log" "$LOG_DIR/second-apply.log.retry" 2>/dev/null || { begin_safe_abort_restore 'second Apply did not reach NO_CHANGES_REQUIRED'; exit $?; }
    verify_with_recovery "$LOG_DIR/second-verify.log" || { begin_safe_abort_restore 'second Verify failed after recovery retry'; exit $?; }
    [[ $FIRST_APPLY_NOOP == 1 ]] || grep -q '^CURRENT[[:space:]]' "$LOG_DIR/second-verify.log" "$LOG_DIR/second-verify.log.retry" 2>/dev/null || { begin_safe_abort_restore 'second Verify did not report CURRENT managed state'; exit $?; }
    PHASE=EVIDENCE_REQUIRED; save_state || exit 1
fi

if [[ $PHASE == EVIDENCE_REQUIRED ]]; then
    phase_banner 'READ-ONLY DEVICE / ATTESTATION / ROOT-EXPOSURE EVIDENCE'
    verify_with_recovery "$LOG_DIR/evidence-verify.log" || { begin_safe_abort_restore 'managed state is no longer CURRENT before evidence collection'; exit $?; }
    collect_physical_evidence; evidence_rc=$?
    if ((evidence_rc == 10)); then printf '\nLeave OTAST and the root stack unchanged, gather the requested evidence, then run `otast release` again.\n'; exit 10; fi
    ((evidence_rc == 0)) || { begin_safe_abort_restore 'physical evidence collection failed'; exit $?; }
    restore_with_recovery "$LOG_DIR/restore.log" || { begin_safe_abort_restore 'Restore failed after recovery retry'; exit $?; }
    PHASE=RESTORE_REBOOT; request_reboot; exit $?
fi

if [[ $PHASE == RESTORE_REBOOT ]]; then
    phase_banner 'POST-RESTORE REPORT → RE-APPLY'; require_new_boot || exit $?
    if has_managed_state; then
        if ((RESTORE_RETRIES < 1)) && su -c 'test -f /data/adb/modules/otast/runtime/entry.sh' >/dev/null 2>&1; then RESTORE_RETRIES=$((RESTORE_RETRIES + 1)); warn 'Managed records remain after Restore/reboot; running boot-recover + Restore once more.'; run_boot_recover_best_effort; restore_with_recovery "$LOG_DIR/final-restore-retry.log" || { fatal 'final Restore recovery failed'; exit $?; }; save_state || exit 1; request_reboot; exit $?; fi
        fatal 'managed state remains after bounded Restore recovery'; exit $?
    fi
    run_live report "$LOG_DIR/final-restored-report.log" || warn 'post-Restore Report returned non-zero after managed state was confirmed absent'
    run_live preflight "$LOG_DIR/reapply-preflight.log" || { fatal 're-Apply Preflight failed'; exit $?; }
    apply_with_recovery "$LOG_DIR/reapply.log" || { fatal 're-Apply failed after recovery retry'; exit $?; }
    if grep -q '^REBOOT_REQUIRED[[:space:]]' "$LOG_DIR/reapply.log" "$LOG_DIR/reapply.log.retry" 2>/dev/null; then REAPPLY_RESULT=PASS; PHASE=REAPPLY_REBOOT; request_reboot; exit $?; fi
    if grep -q '^NO_CHANGES_REQUIRED[[:space:]]' "$LOG_DIR/reapply.log" "$LOG_DIR/reapply.log.retry" 2>/dev/null; then REAPPLY_RESULT=SKIPPED_ALREADY_CURRENT; PHASE=REAPPLY_REBOOT; BOOT_BEFORE=; save_state || exit 1; else fatal 're-Apply returned an unrecognized result'; exit $?; fi
fi

if [[ $PHASE == REAPPLY_REBOOT ]]; then
    phase_banner 'FINAL RE-APPLY VERIFY → PROOF'; [[ -z $BOOT_BEFORE ]] || require_new_boot || exit $?
    verify_installed_draft || { fatal 'installed release identity/runtime digest is unavailable after re-Apply'; exit $?; }
    verify_with_recovery "$LOG_DIR/final-reapply-verify.log" || { fatal 'final post-re-Apply Verify failed'; exit $?; }
    grep -q '^CURRENT[[:space:]]' "$LOG_DIR/final-reapply-verify.log" "$LOG_DIR/final-reapply-verify.log.retry" 2>/dev/null || { fatal 'final post-re-Apply Verify did not report CURRENT'; exit $?; }
    INSTALL_CONTEXT_VALUE=$INSTALL_CONTEXT write_proof || { fatal 'cannot write sanitized runtime-bound device proof'; exit $?; }
    validate_local_proof || { fatal 'generated device proof failed local validation'; exit $?; }
    PHASE=PROOF_READY; save_state || exit 1
fi

if [[ $PHASE == ABORT_RESTORE_REBOOT ]]; then phase_banner 'CONFIRM SAFE RESTORE AFTER ABORT'; require_new_boot || exit $?; has_managed_state && { fatal "release aborted and managed state still remains after Restore: ${ABORT_REASON:-unknown reason}"; exit $?; }; run_live report "$LOG_DIR/abort-final-report.log" || true; fatal "release attempt was safely unwound and left unpublished: ${ABORT_REASON:-unknown reason}"; exit 1; fi

if [[ $PHASE == PROOF_READY ]]; then
    prepare_draft_assets || exit $?
    actual_sha=$(sha256sum "$ZIP_PATH") || exit 1; actual_sha=${actual_sha%% *}
    [[ $actual_sha == "$MODULE_SHA256" ]] || { fatal 'draft ZIP changed after physical proof; refusing publication of a different asset'; exit $?; }
    actual_runtime=$(unzip -p "$ZIP_PATH" release.properties 2>/dev/null | sed -n 's/^runtime_digest=//p' | head -n1)
    [[ $actual_runtime == "$RUNTIME_DIGEST" ]] || { fatal 'runtime digest changed after physical proof; physical qualification is stale'; exit $?; }
    publish_proven_draft; exit $?
fi

fatal "unhandled release phase: $PHASE"
exit $?
