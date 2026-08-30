#!/usr/bin/env bash
# Release UX/front-end for the qualified physical-device lifecycle.
# GitHub Actions release.yml is the sole production publisher. This wrapper
# only prepares/uploads optional physical proof, then reruns that same workflow.

set -u

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
ORIGINAL_ARGS=("$@")

while (($#)); do
    case $1 in
        --version)
            (($# >= 2)) || { printf 'STOP: --version requires a value.\n' >&2; exit 2; }
            REQUESTED_VERSION=$2
            shift 2
            ;;
        --no-publish) USER_NO_PUBLISH=1; shift ;;
        --yes) YES=1; shift ;;
        -h|--help) SHOW_HELP=1; shift ;;
        *) shift ;;
    esac
done

if ((SHOW_HELP)); then
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

Normal releases do not need this command: Actions -> Release publishes directly
with physical proof disabled by default. This helper exists only for the optional
strict physical-proof path.
EOF_HELP
    exit 0
fi

[[ -f $LIFECYCLE_SCRIPT && ! -L $LIFECYCLE_SCRIPT ]] || {
    printf 'STOP: qualified physical release lifecycle is missing or unsafe: %s\n' "$LIFECYCLE_SCRIPT" >&2
    exit 1
}

ensure_command() {
    local command=$1 package=$2
    command -v "$command" >/dev/null 2>&1 && return 0
    if command -v pkg >/dev/null 2>&1; then
        pkg install -y "$package" >/dev/null 2>&1 || true
    fi
    command -v "$command" >/dev/null 2>&1 || {
        printf 'STOP: required command is missing: %s\n' "$command" >&2
        return 1
    }
}

ensure_command git git || exit 1
ensure_command gh gh || exit 1
ensure_command python3 python || exit 1
ensure_command base64 coreutils || exit 1

gh auth status --hostname github.com >/dev/null 2>&1 || {
    printf 'STOP: GitHub CLI is not authenticated. Run: gh auth login --hostname github.com\n' >&2
    exit 1
}
REAL_GH=$(command -v gh)

TMP_BASE=${TMPDIR:-${HOME:?}/.cache/otast/tmp}
mkdir -p -- "$TMP_BASE" || exit 1
WORK=$(mktemp -d "$TMP_BASE/release-wrapper.XXXXXX") || exit 1
SHIM_DIR=$WORK/shim
SHIM_STATE=$WORK/last-operation
mkdir -p -- "$SHIM_DIR" || exit 1
cleanup() {
    rm -rf -- "$WORK"
}
trap cleanup EXIT INT TERM

fetch_remote_file() {
    local path=$1 output=$2 encoded
    if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git -C "$REPO_ROOT" fetch --quiet origin main >/dev/null 2>&1 || true
        if git -C "$REPO_ROOT" show "origin/main:$path" >"$output" 2>/dev/null; then
            return 0
        fi
    fi
    encoded=$("$REAL_GH" api "repos/$REPO_SLUG/contents/$path?ref=main" --jq .content 2>/dev/null) || return 1
    printf '%s' "$encoded" | tr -d '\n' | base64 -d >"$output"
}

fetch_remote_file update.json "$WORK/update.json" || {
    printf 'STOP: cannot read stable update.json from GitHub main.\n' >&2
    exit 1
}
fetch_remote_file module/module.prop "$WORK/module.prop" || {
    printf 'STOP: cannot read module.prop from GitHub main.\n' >&2
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
    printf 'STOP: release version resolution failed.\n' >&2
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

proof_name="otast-${VERSION}-device-proof.json"
release_state() {
    "$REAL_GH" release view "$VERSION" -R "$REPO_SLUG" --json isDraft,assets 2>/dev/null
}

release_has_proof() {
    local value=$1
    PROOF_NAME="$proof_name" python3 -c '
import json,os,sys
value=json.load(sys.stdin)
print("yes" if any(a.get("name")==os.environ["PROOF_NAME"] for a in value.get("assets", [])) else "no")
' <<<"$value"
}

mark_private_state_complete() {
    local state=${HOME:?}/.local/state/otast-release/$VERSION/state.env tmp
    [[ -f $state && ! -L $state ]] || return 0
    tmp=$state.wrapper.$$
    awk 'BEGIN{done=0} /^PHASE=/{print "PHASE=COMPLETE"; done=1; next} {print} END{if(!done) print "PHASE=COMPLETE"}' "$state" >"$tmp" || return 1
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

dispatch_publication() {
    local dispatch_at run_id runs attempt
    publication_prompt || return 0
    printf '[INFO] Dispatching authoritative Release workflow for physically proven %s\n' "$VERSION"
    dispatch_at=$(date -u +%Y-%m-%dT%H:%M:%SZ) || return 1
    "$REAL_GH" workflow run "$WORKFLOW" -R "$REPO_SLUG" --ref main \
        -f "version=$VERSION" -f full_validation=false -f physical_proof=true || {
        printf 'STOP: cannot dispatch publication workflow. Physical proof remains preserved.\n' >&2
        return 1
    }

    run_id=
    for ((attempt=1; attempt<=30; attempt+=1)); do
        runs=$("$REAL_GH" run list -R "$REPO_SLUG" --workflow "$WORKFLOW" --branch main \
            --event workflow_dispatch --limit 30 --json databaseId,displayTitle,createdAt 2>/dev/null) || runs='[]'
        run_id=$(EXPECTED="Release $VERSION" SINCE="$dispatch_at" python3 -c '
import json,os,sys
items=[r for r in json.load(sys.stdin) if r.get("displayTitle")==os.environ["EXPECTED"] and (r.get("createdAt") or "") >= os.environ["SINCE"]]
items.sort(key=lambda r:r.get("createdAt", ""), reverse=True)
print(items[0]["databaseId"] if items else "")
' <<<"$runs")
        [[ -n $run_id ]] && break
        sleep 4
    done
    [[ -n $run_id ]] || {
        printf 'STOP: workflow was dispatched but its run could not be identified. Physical proof remains preserved.\n' >&2
        return 1
    }

    if ! "$REAL_GH" run watch "$run_id" -R "$REPO_SLUG" --exit-status; then
        "$REAL_GH" run view "$run_id" -R "$REPO_SLUG" --log-failed 2>/dev/null || true
        printf 'STOP: publication workflow failed. Physical proof remains preserved; rerun otast release to retry the same candidate.\n' >&2
        return 1
    fi
    mark_private_state_complete || true
    printf '\nRELEASE COMPLETE: %s\n' "$VERSION"
    return 0
}

# If GitHub already has physical proof for this exact candidate, do not re-enter
# qualification. The authoritative workflow can resume publication/update sync.
existing=$(release_state) || existing=
if [[ -n $existing ]]; then
    has_proof=$(release_has_proof "$existing") || has_proof=no
    is_draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$existing")
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
cat >"$SHIM_DIR/gh" <<'SHIM'
#!/usr/bin/env bash
set -u
real=${OTAST_REAL_GH:?}
state=${OTAST_SHIM_STATE:?}

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
    exec "$real" "${out[@]}"
elif [[ ${1:-} == run && ${2:-} == list ]]; then
    output=$("$real" "$@") || exit $?
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
else
    exec "$real" "$@"
fi
SHIM
chmod 0700 -- "$SHIM_DIR/gh" || exit 1

lifecycle_args=()
skip_next=0
for ((i=0; i<${#ORIGINAL_ARGS[@]}; i+=1)); do
    if ((skip_next)); then
        skip_next=0
        continue
    fi
    case ${ORIGINAL_ARGS[i]} in
        --version) skip_next=1 ;;
        --no-publish) ;;
        -h|--help) ;;
        *) lifecycle_args+=("${ORIGINAL_ARGS[i]}") ;;
    esac
done

# Qualification always stops after proof upload. This wrapper alone requests
# publication so a failed updater sync can be retried without repeating proof.
lifecycle_args+=(--version "$VERSION" --no-publish)

PATH="$SHIM_DIR:$PATH" OTAST_REAL_GH="$REAL_GH" OTAST_SHIM_STATE="$SHIM_STATE" \
    OTAST_RELEASE_WRAPPER_AUTOPUBLISH="$AUTO_PUBLISH" \
    bash "$LIFECYCLE_SCRIPT" "${lifecycle_args[@]}"
rc=$?
if ((rc != 0)); then
    exit "$rc"
fi
if [[ $AUTO_PUBLISH != 1 ]]; then
    exit 0
fi

existing=$(release_state) || exit 0
has_proof=$(release_has_proof "$existing") || has_proof=no
[[ $has_proof == yes ]] || exit 0

dispatch_publication
exit $?
