#!/usr/bin/env bash
# Release UX/front-end for the qualified physical-device lifecycle.
# GitHub Actions release.yml is the sole production publisher. This wrapper
# only prepares/uploads optional physical proof, then reruns that same workflow.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'STOP: cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
REPO_SLUG=${OTAST_GITHUB_REPO:-cbkii/otast}
WORKFLOW=release.yml
LIFECYCLE_SCRIPT="$SCRIPT_DIR/release-device-lifecycle.sh"

REQUESTED_VERSION=
USER_NO_PUBLISH=0
YES=0
SHOW_HELP=0
PASSTHROUGH_ARGS=()
ORIGINAL_ARGS=("$@")
WRAPPER_REEXECED=${OTAST_RELEASE_WRAPPER_REEXECED:-0}
NETWORK_TIMEOUT_SECONDS=${OTAST_RELEASE_NETWORK_TIMEOUT_SECONDS:-90}
GIT_TIMEOUT_SECONDS=${OTAST_RELEASE_GIT_TIMEOUT_SECONDS:-60}
WORKFLOW_TIMEOUT_SECONDS=${OTAST_RELEASE_WORKFLOW_TIMEOUT_SECONDS:-2400}
WARNINGS=0

info() {
    printf '[INFO] %s\n' "$*"
}

warn() {
    WARNINGS=$((WARNINGS + 1))
    printf '[WARN] %s\n' "$*" >&2
}

fatal() {
    printf 'STOP: %s\n' "$*" >&2
    return 1
}

usage() {
    cat <<'EOF_HELP'
Usage: release-device.sh [OPTIONS]

Optional resumable physical-Pixel qualification for the exact candidate built by
the authoritative GitHub Release workflow.

  otast release
      Resolve the automatic next/reusable candidate, prepare its proof-gated
      GitHub draft, qualify that exact ZIP, upload proof, then publish by rerunning
      the same Release workflow.

  otast release --version v1.1.0
      Qualify an explicit newer version; versionCode remains automatic.

Options:
  --version VERSION   Explicit release version; blank/omitted = automatic next.
  --yes               Approve reboot and final publication prompts.
  --no-reboot         Never reboot automatically; print the required boundary.
  --no-publish        Upload PASS physical proof but leave the release as draft.
  --status            Show private resumable state.
  --reset             Remove only this wizard's private state for the candidate.
  -h, --help          Show this help without device or network access.

Network/GitHub calls are bounded. A stalled request fails with an actionable STOP
instead of leaving the terminal apparently hung. A clean local main is refreshed
once before release identity is resolved, so the wrapper never nests an old
lifecycle into a second release wrapper during normal operation.

Normal releases do not need this command: Actions -> Release publishes directly
with physical proof disabled by default. This helper exists only for the optional
strict physical-proof path.
EOF_HELP
}

while (($#)); do
    case ${1:-} in
        --version)
            (($# >= 2)) || { fatal '--version requires a value'; exit 2; }
            REQUESTED_VERSION=$2
            shift 2
            ;;
        --no-publish)
            USER_NO_PUBLISH=1
            shift
            ;;
        --yes)
            YES=1
            PASSTHROUGH_ARGS+=(--yes)
            shift
            ;;
        --no-reboot|--status|--reset)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
        -h|--help)
            SHOW_HELP=1
            shift
            ;;
        *)
            fatal "unknown argument: ${1:-missing}"
            usage >&2
            exit 2
            ;;
    esac
done

if ((SHOW_HELP)); then
    usage
    exit 0
fi

[[ -f $LIFECYCLE_SCRIPT && ! -L $LIFECYCLE_SCRIPT ]] || {
    fatal "qualified physical release lifecycle is missing or unsafe: $LIFECYCLE_SCRIPT"
    exit 1
}

ensure_command() {
    local command package
    command=$1
    package=$2
    command -v "$command" >/dev/null 2>&1 && return 0
    if command -v pkg >/dev/null 2>&1; then
        info "Installing missing Termux package: $package"
        pkg install -y "$package" >/dev/null 2>&1 || true
    fi
    command -v "$command" >/dev/null 2>&1 || {
        fatal "required command is missing: $command (Termux package: $package)"
        return 1
    }
}

ensure_command git git || exit 1
ensure_command gh gh || exit 1
ensure_command python3 python || exit 1
ensure_command base64 coreutils || exit 1
ensure_command timeout coreutils || exit 1

REAL_GIT=$(command -v git)
REAL_GH=$(command -v gh)
TIMEOUT_CMD=$(command -v timeout)

case $NETWORK_TIMEOUT_SECONDS in ''|*[!0-9]*) fatal 'OTAST_RELEASE_NETWORK_TIMEOUT_SECONDS must be an integer'; exit 2 ;; esac
case $GIT_TIMEOUT_SECONDS in ''|*[!0-9]*) fatal 'OTAST_RELEASE_GIT_TIMEOUT_SECONDS must be an integer'; exit 2 ;; esac
case $WORKFLOW_TIMEOUT_SECONDS in ''|*[!0-9]*) fatal 'OTAST_RELEASE_WORKFLOW_TIMEOUT_SECONDS must be an integer'; exit 2 ;; esac
((NETWORK_TIMEOUT_SECONDS >= 5)) || { fatal 'network timeout must be at least 5 seconds'; exit 2; }
((GIT_TIMEOUT_SECONDS >= 5)) || { fatal 'git timeout must be at least 5 seconds'; exit 2; }
((WORKFLOW_TIMEOUT_SECONDS >= 60)) || { fatal 'workflow timeout must be at least 60 seconds'; exit 2; }

run_bounded() {
    local description seconds rc
    description=$1
    seconds=$2
    shift 2
    "$TIMEOUT_CMD" --kill-after=5s "${seconds}s" "$@"
    rc=$?
    case $rc in
        124|137)
            warn "$description timed out after ${seconds}s"
            ;;
    esac
    return "$rc"
}

ensure_github_credentials() {
    local token rc

    # Explicit environment credentials are already authoritative for gh.
    if [[ -n ${GH_TOKEN:-} || -n ${GITHUB_TOKEN:-} ]]; then
        return 0
    fi

    # `gh auth token` reads the locally stored credential and does not need a
    # successful GitHub API round trip. This is the correct startup gate after a
    # reboot; actual API/network availability is checked by each bounded
    # operation below instead of being conflated with authentication state.
    token=$(run_bounded 'read GitHub CLI credential' 10 \
        "$REAL_GH" auth token --hostname github.com 2>/dev/null)
    rc=$?
    if ((rc == 0)) && [[ -n $token ]]; then
        token=
        return 0
    fi
    token=

    # Keep auth status only as best-effort diagnostics. It may contact GitHub
    # and has produced transient false failures immediately after Android boot.
    run_bounded 'GitHub authentication diagnostic' 10 \
        "$REAL_GH" auth status --hostname github.com >/dev/null 2>&1 || true
    fatal 'GitHub CLI has no usable local credential. Run: gh auth login --hostname github.com'
    return 1
}

ensure_github_credentials || exit 1

refresh_local_main_once() {
    local before after branch
    "$REAL_GIT" -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

    if ! "$REAL_GIT" -C "$REPO_ROOT" diff --quiet || ! "$REAL_GIT" -C "$REPO_ROOT" diff --cached --quiet; then
        warn 'local checkout is dirty; leaving it untouched. Release assets still target GitHub main.'
        return 0
    fi
    branch=$("$REAL_GIT" -C "$REPO_ROOT" branch --show-current 2>/dev/null) || branch=
    if [[ $branch != main ]]; then
        warn "local branch is ${branch:-detached}; leaving it untouched. Release assets still target GitHub main."
        return 0
    fi

    info 'Refreshing local main before release preparation.'
    if ! run_bounded 'fetch origin/main' "$GIT_TIMEOUT_SECONDS" "$REAL_GIT" -C "$REPO_ROOT" fetch --quiet origin main; then
        warn 'could not refresh local main; continuing with the current wrapper and GitHub-main release metadata.'
        return 0
    fi

    before=$("$REAL_GIT" -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null) || before=
    if ! run_bounded 'fast-forward local main' 20 "$REAL_GIT" -C "$REPO_ROOT" merge --ff-only --quiet origin/main; then
        warn 'local main could not fast-forward cleanly; leaving checkout unchanged.'
        return 0
    fi
    after=$("$REAL_GIT" -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null) || after=$before

    if [[ -n $before && -n $after && $before != "$after" && $WRAPPER_REEXECED != 1 ]]; then
        info 'Local main advanced; restarting once with the updated release wrapper.'
        exec env OTAST_RELEASE_WRAPPER_REEXECED=1 bash "$REPO_ROOT/scripts/release-device.sh" "${ORIGINAL_ARGS[@]}"
    fi
}

# Refresh before resolving/printing release identity. This prevents the old
# lifecycle from becoming the component that updates main and re-enters a second
# wrapper after release preparation has already begun.
refresh_local_main_once

TMP_BASE=${TMPDIR:-${HOME:?}/.cache/otast/tmp}
mkdir -p -- "$TMP_BASE" || exit 1
WORK=$(mktemp -d "$TMP_BASE/release-wrapper.XXXXXX") || exit 1
SHIM_DIR=$WORK/shim
mkdir -p -- "$SHIM_DIR" || exit 1
cleanup() {
    [[ -n ${WORK:-} && -d ${WORK:-} ]] && rm -rf -- "$WORK"
}
trap cleanup EXIT INT TERM

fetch_remote_file() {
    local path output encoded
    path=$1
    output=$2
    if "$REAL_GIT" -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 &&
       "$REAL_GIT" -C "$REPO_ROOT" show "origin/main:$path" >"$output" 2>/dev/null; then
        return 0
    fi
    encoded=$(run_bounded "read GitHub main $path" "$NETWORK_TIMEOUT_SECONDS" \
        "$REAL_GH" api "repos/$REPO_SLUG/contents/$path?ref=main" --jq .content 2>/dev/null) || return $?
    printf '%s' "$encoded" | tr -d '\n' | base64 -d >"$output"
}

fetch_remote_file update.json "$WORK/update.json" || {
    fatal 'cannot read stable update.json from GitHub main'
    exit 1
}
fetch_remote_file module/module.prop "$WORK/module.prop" || {
    fatal 'cannot read module.prop from GitHub main'
    exit 1
}

resolved=$(PYTHONPATH="$REPO_ROOT" python3 - "$WORK/update.json" "$WORK/module.prop" "$REQUESTED_VERSION" <<'PY'
import sys
from pathlib import Path
from tools.otastctl.build import module_metadata
from tools.otastctl.release import load_update_metadata, resolve_release_identity
from tools.otastctl.util import stable_json

stable = load_update_metadata(Path(sys.argv[1]))
current = module_metadata(Path(sys.argv[2]))
print(stable_json(resolve_release_identity(stable, current, requested_version=sys.argv[3])), end="")
PY
) || {
    fatal 'release version resolution failed'
    exit 1
}
VERSION=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' <<<"$resolved") || exit 1
VERSION_CODE=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["version_code"])' <<<"$resolved") || exit 1
STABLE_VERSION=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["stable_version"])' <<<"$resolved") || exit 1
printf '[INFO] Release identity: stable=%s candidate=%s versionCode=%s\n' "$STABLE_VERSION" "$VERSION" "$VERSION_CODE"

AUTO_PUBLISH=${OTAST_RELEASE_WRAPPER_AUTOPUBLISH:-}
if [[ -z $AUTO_PUBLISH ]]; then
    if ((USER_NO_PUBLISH)); then AUTO_PUBLISH=0; else AUTO_PUBLISH=1; fi
fi
case $AUTO_PUBLISH in 0|1) ;; *) fatal "invalid OTAST_RELEASE_WRAPPER_AUTOPUBLISH: $AUTO_PUBLISH"; exit 2 ;; esac

proof_name="otast-${VERSION}-device-proof.json"
release_state() {
    run_bounded "read GitHub release $VERSION" "$NETWORK_TIMEOUT_SECONDS" \
        "$REAL_GH" release view "$VERSION" -R "$REPO_SLUG" --json isDraft,assets 2>/dev/null
}

release_has_proof() {
    local value
    value=$1
    PROOF_NAME="$proof_name" python3 -c '
import json,os,sys
value=json.load(sys.stdin)
print("yes" if any(a.get("name")==os.environ["PROOF_NAME"] for a in value.get("assets", [])) else "no")
' <<<"$value"
}

mark_private_state_complete() {
    local state tmp line wrote_phase
    state=${HOME:?}/.local/state/otast-release/$VERSION/state.env
    [[ -f $state && ! -L $state ]] || return 0
    tmp=$state.wrapper.$$
    wrote_phase=0
    : >"$tmp" || return 1
    while IFS= read -r line || [[ -n $line ]]; do
        case $line in
            PHASE=*)
                if ((wrote_phase == 0)); then
                    printf 'PHASE=COMPLETE\n' >>"$tmp" || return 1
                    wrote_phase=1
                fi
                ;;
            *) printf '%s\n' "$line" >>"$tmp" || return 1 ;;
        esac
    done <"$state"
    ((wrote_phase == 1)) || printf 'PHASE=COMPLETE\n' >>"$tmp" || return 1
    chmod 0600 -- "$tmp" 2>/dev/null || true
    mv -f -- "$tmp" "$state"
}

publication_prompt() {
    local answer
    if ((YES)); then
        return 0
    fi
    if [[ ! -t 0 ]]; then
        printf 'PASS physical proof is present. Re-run with --yes to publish %s.\n' "$VERSION"
        return 1
    fi
    printf 'Publish the physically proven %s release now? [y/N] ' "$VERSION"
    if ! IFS= read -r -t 30 answer; then
        printf '\nPublication not requested.\n'
        return 1
    fi
    case $answer in
        y|Y|yes|YES) return 0 ;;
        *) printf 'Publication not requested.\n'; return 1 ;;
    esac
}

find_publication_run() {
    local dispatch_at runs
    dispatch_at=$1
    runs=$(run_bounded 'list Release workflow runs' "$NETWORK_TIMEOUT_SECONDS" \
        "$REAL_GH" run list -R "$REPO_SLUG" --workflow "$WORKFLOW" --branch main \
        --event workflow_dispatch --limit 30 --json databaseId,displayTitle,createdAt 2>/dev/null) || return $?
    EXPECTED="Release $VERSION" SINCE="$dispatch_at" python3 -c '
import json,os,sys
items=[r for r in json.load(sys.stdin) if r.get("displayTitle")==os.environ["EXPECTED"] and (r.get("createdAt") or "") >= os.environ["SINCE"]]
items.sort(key=lambda r:r.get("createdAt", ""), reverse=True)
print(items[0]["databaseId"] if items else "")
' <<<"$runs"
}

watch_publication_run() {
    local run_id deadline now status_json status conclusion next_progress
    run_id=$1
    deadline=$(( $(date +%s) + WORKFLOW_TIMEOUT_SECONDS ))
    next_progress=0
    while :; do
        now=$(date +%s)
        if ((now >= deadline)); then
            fatal "publication workflow $run_id did not complete within ${WORKFLOW_TIMEOUT_SECONDS}s"
            return 1
        fi
        status_json=$(run_bounded "read workflow $run_id status" "$NETWORK_TIMEOUT_SECONDS" \
            "$REAL_GH" run view "$run_id" -R "$REPO_SLUG" --json status,conclusion 2>/dev/null) || {
            sleep 5
            continue
        }
        status=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("status") or "")' <<<"$status_json") || status=
        conclusion=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("conclusion") or "")' <<<"$status_json") || conclusion=
        if [[ $status == completed ]]; then
            if [[ $conclusion == success ]]; then
                return 0
            fi
            run_bounded "read failed workflow $run_id logs" "$NETWORK_TIMEOUT_SECONDS" \
                "$REAL_GH" run view "$run_id" -R "$REPO_SLUG" --log-failed 2>/dev/null || true
            fatal "publication workflow failed: ${conclusion:-unknown}"
            return 1
        fi
        if ((now >= next_progress)); then
            info "Waiting for publication workflow $run_id (${status:-pending})."
            next_progress=$((now + 60))
        fi
        sleep 5
    done
}

dispatch_publication() {
    local dispatch_at run_id attempt
    publication_prompt || return 0
    info "Dispatching authoritative Release workflow for physically proven $VERSION"
    dispatch_at=$(date -u +%Y-%m-%dT%H:%M:%SZ) || return 1
    if ! run_bounded 'dispatch publication workflow' "$NETWORK_TIMEOUT_SECONDS" \
        "$REAL_GH" workflow run "$WORKFLOW" -R "$REPO_SLUG" --ref main \
        -f "version=$VERSION" -f full_validation=false -f physical_proof=true; then
        fatal 'cannot dispatch publication workflow. Physical proof remains preserved.'
        return 1
    fi

    run_id=
    for ((attempt=1; attempt<=30; attempt+=1)); do
        run_id=$(find_publication_run "$dispatch_at") || run_id=
        [[ -n $run_id ]] && break
        ((attempt % 5 == 0)) && info 'Waiting for the dispatched publication run to appear.'
        sleep 4
    done
    [[ -n $run_id ]] || {
        fatal 'workflow was dispatched but its run could not be identified. Physical proof remains preserved.'
        return 1
    }

    watch_publication_run "$run_id" || {
        fatal 'publication workflow did not complete successfully. Physical proof remains preserved; rerun otast release to retry the same candidate.'
        return 1
    }
    mark_private_state_complete || warn 'publication succeeded but private state could not be marked COMPLETE'
    printf '\nRELEASE COMPLETE: %s\n' "$VERSION"
    return 0
}

# If GitHub already has physical proof for this exact candidate, do not re-enter
# qualification. The authoritative workflow can resume publication/update sync.
info "Checking GitHub state for $VERSION."
existing=$(release_state)
release_state_rc=$?
if ((release_state_rc == 124 || release_state_rc == 137)); then
    fatal "GitHub release-state lookup timed out for $VERSION"
    exit 1
fi
if ((release_state_rc == 0)) && [[ -n $existing ]]; then
    has_proof=$(release_has_proof "$existing") || has_proof=no
    is_draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$existing") || is_draft=unknown
    if [[ $has_proof == yes ]]; then
        if [[ $AUTO_PUBLISH == 1 ]]; then
            dispatch_publication
            exit $?
        fi
        printf 'Release %s already has physical proof (draft=%s); publication not requested.\n' "$VERSION" "$is_draft"
        exit 0
    fi
fi

# The retained lifecycle still speaks its original operation=draft/publish API.
# Translate those internal calls into the single authoritative workflow contract.
# All gh calls made by the lifecycle pass through this bounded shim.
cat >"$SHIM_DIR/gh" <<'SHIM'
#!/usr/bin/env bash
real=${OTAST_REAL_GH:-}
state=${OTAST_SHIM_STATE:-}
timeout_cmd=${OTAST_TIMEOUT_CMD:-}
timeout_seconds=${OTAST_GH_TIMEOUT_SECONDS:-90}

[[ -n $real && -x $real ]] || { printf '[OTAST][STOP] real gh path is unavailable\n' >&2; exit 2; }
[[ -n $state ]] || { printf '[OTAST][STOP] gh shim state path is unavailable\n' >&2; exit 2; }
if [[ -z $timeout_cmd ]]; then
    timeout_cmd=$(command -v timeout 2>/dev/null) || timeout_cmd=
fi
[[ -n $timeout_cmd && -x $timeout_cmd ]] || { printf '[OTAST][STOP] timeout command is unavailable\n' >&2; exit 2; }
case $timeout_seconds in ''|*[!0-9]*) timeout_seconds=90 ;; esac

run_real() {
    local rc
    "$timeout_cmd" --kill-after=5s "${timeout_seconds}s" "$real" "$@"
    rc=$?
    case $rc in
        124|137) printf '[OTAST][WARN] GitHub command timed out after %ss: gh %s\n' "$timeout_seconds" "$*" >&2 ;;
    esac
    return "$rc"
}

# `gh release delete --cleanup-tag` can delete a draft successfully and still
# return non-zero when tag cleanup fails (for example when a draft tag ref is
# absent). Normalize only this partial-success case: if the release is gone,
# deletion succeeded for the lifecycle's purpose.
if [[ ${1:-} == release && ${2:-} == delete ]]; then
    args=("$@")
    version=${3:-}
    repo=
    index=0
    while ((index < ${#args[@]})); do
        value=${args[index]}
        case $value in
            -R|--repo)
                if (($((index + 1)) < ${#args[@]})); then
                    repo=${args[index+1]}
                    index=$((index + 2))
                    continue
                fi
                ;;
        esac
        index=$((index + 1))
    done

    run_real "$@"
    rc=$?
    ((rc == 0)) && exit 0
    [[ -n $version ]] || exit "$rc"
    view=(release view "$version")
    [[ -z $repo ]] || view+=(--repo "$repo")
    if ! run_real "${view[@]}" >/dev/null 2>&1; then
        exit 0
    fi
    exit "$rc"
fi

if [[ ${1:-} == workflow && ${2:-} == run ]]; then
    args=("$@")
    out=()
    index=0
    operation=
    while ((index < ${#args[@]})); do
        value=${args[index]}
        if [[ $value == -f && $((index + 1)) -lt ${#args[@]} ]]; then
            pair=${args[index+1]}
            case $pair in
                operation=draft)
                    operation=draft
                    index=$((index + 2))
                    continue
                    ;;
                operation=publish)
                    operation=publish
                    index=$((index + 2))
                    continue
                    ;;
            esac
        fi
        out+=("$value")
        index=$((index + 1))
    done

    if [[ -n $operation ]]; then
        printf '%s\n' "$operation" >"$state"
        out+=("-f" "physical_proof=true")
        if [[ $operation == draft ]]; then
            out+=("-f" "full_validation=true")
        else
            out+=("-f" "full_validation=false")
        fi
    fi
    run_real "${out[@]}"
    exit $?
elif [[ ${1:-} == run && ${2:-} == list ]]; then
    output=$(run_real "$@") || exit $?
    operation=$(cat "$state" 2>/dev/null || true)
    OPERATION="$operation" python3 -c '
import json,os,sys
value=json.load(sys.stdin)
op=os.environ.get("OPERATION") or ""
if op:
    for item in value:
        title=item.get("displayTitle") or ""
        if title.startswith("Release ") and not title.startswith(f"Release {op} "):
            item["displayTitle"]=title.replace("Release ", f"Release {op} ", 1)
json.dump(value, sys.stdout)
' <<<"$output"
    exit $?
else
    run_real "$@"
    exit $?
fi
SHIM
chmod 0700 -- "$SHIM_DIR/gh" || exit 1

# The lifecycle also performs a best-effort local-main refresh. Keep that call
# bounded and prevent it from re-entering the wrapper: this wrapper already owns
# self-refresh and has resolved the candidate from current GitHub main.
cat >"$SHIM_DIR/git" <<'GIT_SHIM'
#!/usr/bin/env bash
real=${OTAST_REAL_GIT:-}
timeout_cmd=${OTAST_TIMEOUT_CMD:-}
timeout_seconds=${OTAST_GIT_TIMEOUT_SECONDS:-60}
[[ -n $real && -x $real ]] || exit 2
if [[ -z $timeout_cmd ]]; then timeout_cmd=$(command -v timeout 2>/dev/null) || timeout_cmd=; fi
[[ -n $timeout_cmd && -x $timeout_cmd ]] || exit 2
case $timeout_seconds in ''|*[!0-9]*) timeout_seconds=60 ;; esac
"$timeout_cmd" --kill-after=5s "${timeout_seconds}s" "$real" "$@"
rc=$?
case $rc in
    124|137) printf '[OTAST][WARN] git command timed out after %ss\n' "$timeout_seconds" >&2 ;;
esac
exit "$rc"
GIT_SHIM
chmod 0700 -- "$SHIM_DIR/git" || exit 1

lifecycle_args=("${PASSTHROUGH_ARGS[@]}")
# Qualification always stops after proof upload. This wrapper alone requests
# publication so a failed updater sync can be retried without repeating proof.
lifecycle_args+=(--version "$VERSION" --no-publish)

info 'Entering bounded, resumable physical-device qualification.'
PATH="$SHIM_DIR:$PATH" \
    OTAST_REAL_GH="$REAL_GH" \
    OTAST_REAL_GIT="$REAL_GIT" \
    OTAST_TIMEOUT_CMD="$TIMEOUT_CMD" \
    OTAST_SHIM_STATE="$WORK/last-operation" \
    OTAST_GH_TIMEOUT_SECONDS="$NETWORK_TIMEOUT_SECONDS" \
    OTAST_GIT_TIMEOUT_SECONDS="$GIT_TIMEOUT_SECONDS" \
    OTAST_RELEASE_REEXECED=1 \
    OTAST_RELEASE_WRAPPER_AUTOPUBLISH="$AUTO_PUBLISH" \
    bash "$LIFECYCLE_SCRIPT" "${lifecycle_args[@]}"
rc=$?
if ((rc != 0)); then
    exit "$rc"
fi
if [[ $AUTO_PUBLISH != 1 ]]; then
    exit 0
fi

existing=$(release_state)
release_state_rc=$?
if ((release_state_rc == 124 || release_state_rc == 137)); then
    fatal "GitHub release-state lookup timed out after physical qualification for $VERSION"
    exit 1
fi
((release_state_rc == 0)) || exit 0
has_proof=$(release_has_proof "$existing") || has_proof=no
[[ $has_proof == yes ]] || exit 0

dispatch_publication
exit $?
