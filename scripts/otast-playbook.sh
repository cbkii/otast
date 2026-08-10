#!/usr/bin/env bash
# Sourceable and executable command hub for the OTAST development playbook.
# This file delegates to repository scripts. It does not implement OTAST runtime logic.

_otast_pb_script_dir() {
    local source_path dir

    source_path=${BASH_SOURCE[0]}
    dir=$(cd -- "$(dirname -- "$source_path")" >/dev/null 2>&1 && pwd -P) || {
        printf 'STOP: cannot resolve OTAST playbook directory.\n' >&2
        return 1
    }
    printf '%s\n' "$dir"
}

_otast_pb_repo_root() {
    local script_dir candidate

    if [[ -n ${OTAST_REPO_ROOT:-} ]]; then
        candidate=$OTAST_REPO_ROOT
    else
        script_dir=$(_otast_pb_script_dir) || return 1
        candidate=$script_dir/..
    fi

    candidate=$(cd -- "$candidate" >/dev/null 2>&1 && pwd -P) || {
        printf 'STOP: OTAST repository does not exist: %s\n' "$candidate" >&2
        return 1
    }

    if [[ ! -f $candidate/pyproject.toml ||
          ! -f $candidate/scripts/test.sh ||
          ! -d $candidate/tools/otastctl ]]; then
        printf 'STOP: path is not an OTAST repository: %s\n' "$candidate" >&2
        return 1
    fi

    printf '%s\n' "$candidate"
}

_otast_pb_require_non_root() {
    local script_dir operation

    operation=${1:-OTAST operation}
    script_dir=$(_otast_pb_script_dir) || return 1
    python3 "$script_dir/otast_safety_guard.py" non-root "$operation" >/dev/null
}

_otast_pb_with_gh_token() {
    local token rc

    if [[ -n ${GH_TOKEN:-} || -n ${GITHUB_TOKEN:-} ]]; then
        "$@"
        return $?
    fi

    command -v gh >/dev/null 2>&1 || {
        _otast_pb_stop 'GitHub CLI is required. Install it with: pkg install gh'
        return 1
    }
    gh auth status --hostname github.com >/dev/null 2>&1 || {
        _otast_pb_stop 'GitHub CLI is not authenticated. Run: gh auth login --hostname github.com'
        return 1
    }
    token=$(gh auth token --hostname github.com 2>/dev/null) || {
        _otast_pb_stop 'cannot retrieve the active GitHub CLI token'
        return 1
    }
    [[ -n $token ]] || {
        _otast_pb_stop 'GitHub CLI returned an empty token'
        return 1
    }

    GH_TOKEN=$token "$@"
    rc=$?
    token=
    return "$rc"
}

_otast_pb_assert_fake_root() {
    local script_dir root operation

    root=$1
    operation=${2:-fake-root operation}
    script_dir=$(_otast_pb_script_dir) || return 1
    python3 "$script_dir/otast_safety_guard.py" fake-root "$root" \
        --operation "$operation" >/dev/null
}

_otast_pb_init_colors() {
    if [[ -t 1 && -z ${NO_COLOR:-} && ${TERM:-dumb} != dumb ]]; then
        OTAST_PB_RESET=$'\033[0m'
        OTAST_PB_BOLD=$'\033[1m'
        OTAST_PB_RED=$'\033[31m'
        OTAST_PB_CYAN=$'\033[36m'
    else
        OTAST_PB_RESET=
        OTAST_PB_BOLD=
        OTAST_PB_RED=
        OTAST_PB_CYAN=
    fi
}

_otast_pb_heading() {
    printf '\n%s%s%s\n' "$OTAST_PB_BOLD" "$1" "$OTAST_PB_RESET"
}

_otast_pb_stop() {
    printf '%sSTOP:%s %s\n' "$OTAST_PB_RED" "$OTAST_PB_RESET" "$*" >&2
    return 1
}

_otast_pb_resolve_latest_dir() {
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

_otast_pb_resolve_fixture() {
    local input fixture_root resolved

    input=${1:-latest}
    fixture_root=${HOME:?}/.local/share/otast/device-fixtures

    if [[ $input == latest ]]; then
        resolved=$(_otast_pb_resolve_latest_dir "$fixture_root") || {
            _otast_pb_stop "no captured fixture exists under $fixture_root"
            return 1
        }
    else
        resolved=$(cd -- "$input" >/dev/null 2>&1 && pwd -P) || {
            _otast_pb_stop "fixture does not exist: $input"
            return 1
        }
    fi

    case $resolved in
        "$fixture_root"/*) ;;
        *)
            _otast_pb_stop "fixture is outside the private fixture root: $resolved"
            return 1
            ;;
    esac

    printf '%s\n' "$resolved"
}

_otast_pb_resolve_fake_root() {
    local input root_base candidate resolved

    input=${1:-latest}
    root_base=${HOME:?}/.cache/otast/fake-roots

    if [[ $input == latest ]]; then
        candidate=$(_otast_pb_resolve_latest_dir "$root_base") || {
            _otast_pb_stop "no fake root exists under $root_base"
            return 1
        }
    elif [[ $input != /* && $input != */* ]]; then
        case $input in
            *[!A-Za-z0-9._-]*|'')
                _otast_pb_stop "unsafe fake-root name: $input"
                return 1
                ;;
        esac
        candidate=$root_base/$input
    else
        candidate=$input
    fi

    _otast_pb_assert_fake_root "$candidate" "fake-root selection" || return $?
    resolved=$(cd -- "$candidate" >/dev/null 2>&1 && pwd -P) || {
        _otast_pb_stop "fake root does not exist: $candidate"
        return 1
    }

    case $resolved in
        "$root_base"/*) ;;
        *)
            _otast_pb_stop "fake root is outside the disposable root: $resolved"
            return 1
            ;;
    esac

    printf '%s
' "$resolved"
}

_otast_pb_version() {
    local repo version code

    repo=$(_otast_pb_repo_root) || return 1
    version=$(sed -n 's/^version=//p' "$repo/module/module.prop" | sed -n '1p')
    code=$(sed -n 's/^versionCode=//p' "$repo/module/module.prop" | sed -n '1p')

    printf 'OTAST playbook v5.2\n'
    printf 'Module: %s (%s)\n' "${version:-unknown}" "${code:-unknown}"
    printf 'Repository: %s\n' "$repo"
}

_otast_pb_help_main() {
    cat <<__OTAST_HELP__
${OTAST_PB_BOLD}OTAST DEVELOPMENT PLAYBOOK${OTAST_PB_RESET}

${OTAST_PB_BOLD}NAME${OTAST_PB_RESET}
    otast - sourceable command hub for developing, testing and qualifying OTAST

${OTAST_PB_BOLD}SYNOPSIS${OTAST_PB_RESET}
    source scripts/otast-playbook.sh
    otast <command> [arguments]

    bash scripts/otast-playbook.sh <command> [arguments]

${OTAST_PB_BOLD}PRIMARY WORKFLOW${OTAST_PB_RESET}
    ${OTAST_PB_CYAN}maintain${OTAST_PB_RESET}     Doctor, authenticated monitor and tests in one command.
    ${OTAST_PB_CYAN}review${OTAST_PB_RESET}       Investigate one changed target and retain structured evidence.
    ${OTAST_PB_CYAN}accept${OTAST_PB_RESET}       Advance one proven no-impact monitor baseline safely.
    ${OTAST_PB_CYAN}prepush${OTAST_PB_RESET}      Run full monitor/tests/audit/device proof/qualification.
    ${OTAST_PB_CYAN}doctor${OTAST_PB_RESET}       Check Termux, gh authentication and repository prerequisites.
    ${OTAST_PB_CYAN}test${OTAST_PB_RESET}         Run quick, standard or full repository validation.
    ${OTAST_PB_CYAN}synthetic${OTAST_PB_RESET}    Execute the exact module lifecycle in a generated fake root.
    ${OTAST_PB_CYAN}capture${OTAST_PB_RESET}      Capture a private sanitized fixture from the owned Pixel.
    ${OTAST_PB_CYAN}refresh${OTAST_PB_RESET}      Regenerate a fake root from device, fixture or upstream package.
    ${OTAST_PB_CYAN}upstream${OTAST_PB_RESET}     List, fetch or safely materialize target release packages.
    ${OTAST_PB_CYAN}prove${OTAST_PB_RESET}        Prove the exact ZIP against a device-derived fake root.
    ${OTAST_PB_CYAN}export${OTAST_PB_RESET}       Create an uploadable post-patch fake-root analysis ZIP.
    ${OTAST_PB_CYAN}qualify${OTAST_PB_RESET}      Run the complete local release-candidate qualification.
    ${OTAST_PB_CYAN}release${OTAST_PB_RESET}      Resumable physical-device proof and exact-draft publication.

${OTAST_PB_BOLD}COMMANDS${OTAST_PB_RESET}
    help [COMMAND]                 Show this page or detailed command help.
    commands                       Show a compact command list.
    version                        Show playbook and module versions.
    doctor                         Run scripts/check-dev-environment.sh.
    status                         Show Git state, module version, fixtures and fake roots.
    test [quick|standard|full]     Run scripts/test.sh. Default: standard.
    audit [REPORT_DIR]             Run the complete public-initialization audit.
    authority [FILE]               Validate an ota.prop file.
    build [OUTPUT_DIR]             Build the deterministic Magisk ZIP.
    source [OUTPUT_ZIP]            Build the deterministic public-source ZIP.
    monitor [OUTPUT_DIR|OPTIONS]   Authenticated monitor; exit 10 means review required.
    maintain [OPTIONS]             Normal ongoing Termux maintenance workflow.
    review TARGET [OPTIONS]        Review exact old/new upstream commits safely.
    accept TARGET [OPTIONS]        Update only a proven monitor.expected_head.
    cleanup [OPTIONS]              Prune old transient report history safely.
    prepush                        Full pre-push proof and qualification.
    synthetic [OUTPUT_DIR]         Run the repository-generated fake-root lifecycle.
    capture [LABEL] [OUTPUT_ROOT]  Capture a private sanitized device fixture.
    fixtures                       List private captured fixtures.
    reset <FIXTURE|latest> [NAME]  Clone a fixture and install the exact candidate ZIP.
    refresh <MODE> [OPTIONS]       Rebuild a disposable root from device/fixture/upstream.
    upstream <COMMAND> [OPTIONS]   Inspect/fetch/materialize upstream target packages.
    action <NAME|ROOT|latest> <ACTION>
                                  Run report/preflight/apply/reboot/verify/restore.
    prove [FIXTURE|latest] [NAME]  Run the full device-derived reboot-boundary proof.
    export [ROOT|latest] [ZIP]     Export a verified post-patch analysis archive.
    qualify [OPTIONS]              Run the final local, non-publishing qualification.
    release [OPTIONS]              Create/prove/publish an exact draft; rerun after reboots.
    cd                             Change the current shell to the repository root.

${OTAST_PB_BOLD}SAFETY MODEL${OTAST_PB_RESET}
    - Development commands do not commit, push, tag, release or install modules.
    - release is the explicit exception: it installs only the exact draft asset and
      publishes only after the physical lifecycle proof passes.
    - capture/refresh device are read-only against live /data/adb.
    - upstream ZIPs and installer code are retained in private evidence and never executed.
    - fake roots receive only a static default-extraction model plus inert installer evidence.
    - device capture remains authoritative for installer-generated postimages.
    - action/prove apply, reboot and restore only disposable fake roots.
    - release is the only host command allowed to drive live OTAST runtime actions.
    - qualify stops on dirty/unbound release state unless explicitly run as development.

${OTAST_PB_BOLD}HELP EXAMPLES${OTAST_PB_RESET}
    otast maintain
    otast review yurikey
    otast help prepush

${OTAST_PB_BOLD}ENVIRONMENT${OTAST_PB_RESET}
    OTAST_REPO_ROOT  Override the repository root.
    NO_COLOR         Disable ANSI colors.
__OTAST_HELP__
}

_otast_pb_help_command() {
    local topic
    topic=${1:-}

    case $topic in
        doctor)
            cat <<'__HELP__'
OTAST DOCTOR

SYNOPSIS
    otast doctor

PURPOSE
    Verifies Python, Git, Bash, BusyBox, ShellCheck, GitHub CLI authentication,
    authenticated API allowance, target-registry structure and repository prerequisites.
    It never prints or stores the active GitHub token.

DELEGATES TO
    scripts/otast-maintenance.py doctor
__HELP__
            ;;
        test)
            cat <<'__HELP__'
OTAST TEST

SYNOPSIS
    otast test [quick|standard|full]

MODES
    quick       Fast source/unit checks for normal edit cycles.
    standard    Broader repository verification. This is the default.
    full        ShellCheck, complete tests, deterministic source packaging and
                extracted-source execution. Use before candidate qualification.

DELEGATES TO
    scripts/test.sh --quick|--standard|--full
__HELP__
            ;;
        synthetic)
            cat <<'__HELP__'
OTAST SYNTHETIC

SYNOPSIS
    otast synthetic [OUTPUT_DIR]

PURPOSE
    Builds the exact candidate ZIP and runs its complete lifecycle against the
    repository-generated synthetic Magisk root. This proves deterministic module
    behaviour without using a copy of the device's installed module stack.

DEFAULT OUTPUT
    reports/fake-magisk-root

DELEGATES TO
    scripts/fake-magisk-root.sh
__HELP__
            ;;
        capture)
            cat <<'__HELP__'
OTAST CAPTURE

SYNOPSIS
    otast capture [LABEL] [OUTPUT_ROOT]

PURPOSE
    Reads the explicit OTAST allow-list from the owned Pixel through su, records
    live identity properties, removes private material and publishes a sanitized
    fixture. It does not modify live /data/adb.

DEFAULT LABEL
    tegu-<UTC timestamp>

DEFAULT OUTPUT ROOT
    ~/.local/share/otast/device-fixtures

DELEGATES TO
    scripts/capture-device-fixture.sh
__HELP__
            ;;
        fixtures)
            cat <<'__HELP__'
OTAST FIXTURES

SYNOPSIS
    otast fixtures

PURPOSE
    Lists private device fixtures with their authority hash and whether the
    expected sanitized Magisk root exists.
__HELP__
            ;;
        reset)
            cat <<'__HELP__'
OTAST RESET

SYNOPSIS
    otast reset <FIXTURE|latest> [WORKING_NAME]

PURPOSE
    Copies a sanitized fixture into ~/.cache/otast/fake-roots and installs the
    exact newly built candidate ZIP. Existing roots with the same name are reset.

EXAMPLES
    otast reset latest
    otast reset ~/.local/share/otast/device-fixtures/tegu-clean tegu-debug

DELEGATES TO
    scripts/reset-fake-magisk-root.sh
__HELP__
            ;;
        refresh)
            cat <<'__HELP__'
OTAST REFRESH

SYNOPSIS
    otast refresh device [--label LABEL] [--name NAME] [--prove]
                         [--restore-clone]
    otast refresh fixture [FIXTURE|latest] [--name NAME]
    otast refresh upstream TARGET [--fixture FIXTURE|latest] [--name NAME]
                           [--tree modules|modules_update]
                           [--ref REF]
                           [--tag TAG] [--include-prerelease]
                           [--asset NAME|--asset-regex REGEX] [--no-compare]

MODES
    device      Capture the current sanitized target allow-list from live
                /data/adb, then create a fresh fake root containing the exact
                newly built OTAST candidate. --prove runs the complete lifecycle.

    fixture     Rebuild a disposable fake root from an existing immutable fixture.

    upstream    Rebuild from a fixture and fetch either one GitHub release asset
                or an exact source archive selected with --ref. Branch-monitored
                targets such as Yurikey must use --ref with the observed commit.
                The complete ZIP/source/installer evidence is retained and analysed.
                No upstream script or binary is executed. Installer code is copied
                to inert evidence outside data/adb/modules*. By default the staged
                model is compared with the device-captured active target.

RECOMMENDATION
    Use refresh device for authoritative installed-tree proof. Use refresh
    upstream for compatibility review and update simulation. No VM or proot
    environment is required because installer execution is deliberately omitted.

DELEGATES TO
    capture-device-fixture.sh, reset-fake-magisk-root.sh,
    prove-device-fake-root.sh and upstream-target-package.py
__HELP__
            ;;
        upstream)
            cat <<'__HELP__'
OTAST UPSTREAM

SYNOPSIS
    otast upstream ref TARGET [--ref REF]
    otast upstream fetch-ref TARGET [--ref REF] [--force]
    otast upstream assets TARGET [--tag TAG] [--include-prerelease]
    otast upstream fetch TARGET [--tag TAG] [--include-prerelease]
                          [--asset NAME|--asset-regex REGEX] [--force]
    otast upstream analyse TARGET PACKAGE [--force]
    otast upstream materialize TARGET PACKAGE <FAKE_ROOT|latest>
                               [--tree modules|modules_update]
    otast upstream compare TARGET <FAKE_ROOT|latest>
                           [--active-tree modules]
                           [--candidate-tree modules_update]
    otast upstream show PATH

PURPOSE
    ref          Resolve a branch, tag or commit to its exact Git commit SHA.
    fetch-ref    Download the repository source archive at that exact commit and
                 retain its complete tree, inventory and installer analysis.
    assets       Show release metadata and every published asset.
    fetch        Download exactly one release ZIP, retain its complete extracted
                 source tree, inventory and installer analysis in private cache.
    analyse      Apply the same retention/analysis contract to a local ZIP.
    materialize  Derive Magisk's default-extraction module tree in a disposable
                 root. customize.sh/install.sh/META-INF are excluded only from the
                 assumed installed tree and retained as inert sidecar evidence.
    compare      Compare the captured active module with the static staged model.
    show         Display candidate evidence metadata.

SOURCE SELECTION
    Use fetch/--tag/--asset for release-monitored targets. Use fetch-ref/--ref
    for branch-monitored targets or when the monitor reports an exact commit.

SAFETY AND ACCURACY
    No upstream shell script, native binary or installer is executed. The fake
    module tree is ordinary data under ~/.cache/otast/fake-roots and cannot affect
    live /data/adb. Static analysis records installer conflicts and unresolved
    dynamic behaviour; device capture remains the authoritative installed postimage.
__HELP__
            ;;
        action)
            cat <<'__HELP__'
OTAST ACTION

SYNOPSIS
    otast action <NAME|FAKE_ROOT|latest> <ACTION>

NAME RESOLUTION
    A bare name such as `review-yurikey-5330b77c0b79` resolves safely below
    ~/.cache/otast/fake-roots. Absolute paths must remain below the same root.

ACTIONS
    report        Human-readable authority/module/state report.
    preflight     Read-only plan and conflict classification.
    apply         Apply the transaction inside the fake root.
    reboot        Simulate the reboot-time VBMeta writer contract.
    verify        Verify managed files and runtime properties.
    restore       Restore proven originals transactionally.
    boot-recover  Exercise interrupted-transaction recovery.

IMPORTANT
    After a changing Apply, the expected sequence is:
        apply -> verify fails before reboot -> reboot -> verify passes

DELEGATES TO
    scripts/validate-fake-magisk-root.sh
__HELP__
            ;;
        prove)
            cat <<'__HELP__'
OTAST PROVE

SYNOPSIS
    otast prove [FIXTURE|latest] [NAME] [--restore-clone]

PURPOSE
    Resets a fresh device-derived fake root and proves report, preflight, Apply,
    the reboot boundary, post-reboot Verify, second-Apply idempotency and final
    Verify. --restore-clone repeats Apply/reboot/Verify in a separate clone and
    proves Restore without destroying the managed root intended for export.

OUTPUT
    ~/.local/state/otast-proof/<NAME>
    ~/.cache/otast/fake-roots/<NAME>

DELEGATES TO
    scripts/prove-device-fake-root.sh
__HELP__
            ;;
        export)
            cat <<'__HELP__'
OTAST EXPORT

SYNOPSIS
    otast export [FAKE_ROOT|latest] [OUTPUT_ZIP]

PURPOSE
    Verifies a managed fake root and creates a private uploadable analysis ZIP
    containing the sanitized fake root, hashes, tree inventory, repository
    metadata and verification logs.

DEFAULT OUTPUT
    ~/storage/downloads/otast-post-patch-fake-root-<UTC>.zip

DELEGATES TO
    scripts/export-fake-root-analysis.sh
__HELP__
            ;;
        release)
            cat <<'__HELP__'
OTAST RELEASE

SYNOPSIS
    otast release [--version VERSION] [--yes] [--no-reboot] [--no-publish]
    otast release --status
    otast release --reset [--version VERSION]

PURPOSE
    One resumable real-device release wizard. The same command is run after each
    reboot; private phase state determines what comes next. It creates the GitHub
    draft through Actions when needed, downloads and verifies the exact draft ZIP,
    restores any existing managed OTAST state to a clean baseline, installs the
    exact draft through Magisk, and proves:

        Report -> Preflight -> Apply -> reboot -> Verify
        -> second Apply (NO_CHANGES_REQUIRED) -> Verify -> Restore
        -> reboot -> final Report

    After PASS it uploads a sanitized proof asset and asks the Release workflow to
    publish that exact already-validated draft without rebuilding it.

REBOOT UX
    At every reboot boundary the command persists its phase first. After Android
    is fully booted, run exactly the same command again: `otast release`.

SAFETY
    Existing managed state must Verify as CURRENT before automatic baseline Restore.
    A changed first Apply, post-reboot CURRENT state, second-Apply no-op, successful
    Restore and a real boot-ID change are all mandatory. Any mismatch stops.

DELEGATES TO
    scripts/release-device.sh
__HELP__
            ;;
        qualify)
            cat <<'__HELP__'
OTAST QUALIFY

SYNOPSIS
    otast qualify [--fixture PATH|latest] [--output DIR]
                   [--skip-device] [--allow-dirty]

PURPOSE
    Runs the final local release-candidate gates: full repository tests, privacy,
    two byte-identical module builds, exact embedded commit binding, deterministic
    source package, synthetic lifecycle and optionally the device-derived proof
    plus analysis export.

POLICY
    The default requires an existing Git commit and a clean worktree/index.
    --allow-dirty is development-only evidence and is never publication proof.
    This command performs no Git or GitHub writes.

DELEGATES TO
    scripts/qualify-release-candidate.sh
__HELP__
            ;;
        audit)
            cat <<'__HELP__'
OTAST AUDIT

SYNOPSIS
    otast audit [REPORT_DIR]

PURPOSE
    Runs full tests, privacy scan, synthetic fake-root qualification, public
    source packaging and Magisk ZIP construction in one evidence directory.

DELEGATES TO
    scripts/public-init-audit.sh
__HELP__
            ;;
        authority)
            cat <<'__HELP__'
OTAST AUTHORITY

SYNOPSIS
    otast authority [FILE]

DEFAULT
    authority/reference-tegu-CP1A.260305.018.ota.prop

PURPOSE
    Strictly validates ota.prop syntax, required values and cross-field identity.
__HELP__
            ;;
        build)
            cat <<'__HELP__'
OTAST BUILD

SYNOPSIS
    otast build [OUTPUT_DIR]

PURPOSE
    Builds and validates the deterministic Magisk module ZIP. When HEAD exists,
    release.properties is bound to that exact commit.

DEFAULT OUTPUT
    dist
__HELP__
            ;;
        source)
            cat <<'__HELP__'
OTAST SOURCE

SYNOPSIS
    otast source [OUTPUT_ZIP]

PURPOSE
    Builds the deterministic, privacy-checked public repository ZIP.

DEFAULT OUTPUT
    dist/otast-public-ready.zip
__HELP__
            ;;
        monitor)
            cat <<'__HELP__'
OTAST MONITOR

SYNOPSIS
    otast monitor [OUTPUT_DIR]
    otast monitor [--output DIR] [--keep N] [--no-cleanup]

PURPOSE
    Uses authenticated `gh api` requests to compare current upstream branch heads
    with reviewed compatibility baselines. It checks authentication and API budget
    before lookup, writes JSON and Markdown reports, and prunes older monitor reports
    only after a completely supported run.

EXIT STATUS
    0   All targets supported.
    10  One or more targets changed; run `otast review TARGET`.
    20  Authentication, API, registry or monitor failure.
__HELP__
            ;;
        maintain)
            cat <<'__HELP__'
OTAST MAINTAIN

SYNOPSIS
    otast maintain [--quick|--full] [--audit] [--device-proof] [--keep N]

PURPOSE
    The normal memorable Termux workflow. It runs doctor, authenticated target
    monitoring and repository tests in the correct order. `--full` also runs the
    public-boundary audit. `--device-proof` adds the device-derived lifecycle proof.
    Old transient monitor/maintenance reports are removed only after success.

EXIT STATUS
    0   Maintenance completed.
    10  Target review is required; no baseline was changed.
    20  A required check failed.
__HELP__
            ;;
        review)
            cat <<'__HELP__'
OTAST REVIEW

SYNOPSIS
    otast review TARGET [--observed SHA] [--fixture PATH] [--name NAME]

PURPOSE
    Resolves the target's exact expected and observed commits, retains both immutable
    source archives, compares module bytes/modes, builds a staged disposable fake
    root, and runs Report and Preflight without executing upstream installers.

RESULTS
    NO_PACKAGE_IMPACT  `otast accept TARGET` is permitted.
    PACKAGE_CHANGED    Compatibility/runtime work is required; baseline is unchanged.
    VALIDATION_FAILED  Troubleshoot the generated review log before proceeding.
__HELP__
            ;;
        accept)
            cat <<'__HELP__'
OTAST ACCEPT

SYNOPSIS
    otast accept TARGET [--review PATH] [--keep N]

PURPOSE
    Reads a completed NO_PACKAGE_IMPACT review, updates only
    targets.<target>.monitor.expected_head, runs an authenticated confirmation
    monitor, and automatically restores the original registry if that target is not
    confirmed. Historical reviewed_sources provenance is deliberately unchanged.
__HELP__
            ;;
        cleanup)
            cat <<'__HELP__'
OTAST CLEANUP

SYNOPSIS
    otast cleanup [--category all|target-monitor|target-review|maintenance]
                  [--keep N] [--dry-run]

PURPOSE
    Removes only timestamped transient reports managed by the maintenance tool.
    It never removes device fixtures, fake roots, upstream evidence, qualification
    evidence, non-matching report directories, or directories containing .otast-keep.
__HELP__
            ;;
        prepush)
            cat <<'__HELP__'
OTAST PREPUSH

SYNOPSIS
    otast prepush

PURPOSE
    Runs full authenticated maintenance, public-boundary audit, device-derived proof,
    and clean exact-commit qualification. It performs no Git or GitHub writes.
    Run it after committing locally and before pushing.
__HELP__
            ;;
        status)
            cat <<'__HELP__'
OTAST STATUS

SYNOPSIS
    otast status

PURPOSE
    Shows repository branch/commit/dirty state, module metadata, latest fixture,
    latest fake root and latest proof directory. It performs no mutation.
__HELP__
            ;;
        help|'') _otast_pb_help_main ;;
        *)
            _otast_pb_stop "unknown help topic: $topic"
            printf 'Run: otast commands\n' >&2
            return 1
            ;;
    esac
}

_otast_pb_commands() {
    cat <<'__COMMANDS__'
help commands version doctor status maintain monitor review accept cleanup prepush
 test audit authority build source synthetic capture fixtures reset refresh upstream
 action prove export qualify release cd
__COMMANDS__
}

_otast_pb_status() {
    local repo fixture fake proof version code head branch dirty

    repo=$(_otast_pb_repo_root) || return 1
    version=$(sed -n 's/^version=//p' "$repo/module/module.prop" | sed -n '1p')
    code=$(sed -n 's/^versionCode=//p' "$repo/module/module.prop" | sed -n '1p')
    head=$(git -C "$repo" rev-parse --short=12 HEAD 2>/dev/null) || head=UNCOMMITTED
    branch=$(git -C "$repo" branch --show-current 2>/dev/null) || branch=
    [[ -n $branch ]] || branch=DETACHED_OR_UNINITIALIZED
    if git -C "$repo" diff --quiet --ignore-submodules -- 2>/dev/null &&
       git -C "$repo" diff --cached --quiet --ignore-submodules -- 2>/dev/null; then
        dirty=CLEAN
    else
        dirty=DIRTY
    fi

    fixture=$(_otast_pb_resolve_latest_dir "${HOME:?}/.local/share/otast/device-fixtures" 2>/dev/null) || fixture=NONE
    fake=$(_otast_pb_resolve_latest_dir "${HOME:?}/.cache/otast/fake-roots" 2>/dev/null) || fake=NONE
    proof=$(_otast_pb_resolve_latest_dir "${HOME:?}/.local/state/otast-proof" 2>/dev/null) || proof=NONE

    _otast_pb_heading 'Repository'
    printf 'Path:        %s\n' "$repo"
    printf 'Module:      %s (%s)\n' "${version:-unknown}" "${code:-unknown}"
    printf 'Branch:      %s\n' "$branch"
    printf 'HEAD:        %s\n' "$head"
    printf 'Worktree:    %s\n' "$dirty"

    _otast_pb_heading 'Private evidence'
    printf 'Fixture:     %s\n' "$fixture"
    printf 'Fake root:   %s\n' "$fake"
    printf 'Proof:       %s\n' "$proof"
}

_otast_pb_fixtures() {
    local root item authority hash count

    root=${HOME:?}/.local/share/otast/device-fixtures
    count=0
    printf '%-32s  %-10s  %s\n' 'LABEL' 'AUTHORITY' 'PATH'

    if [[ ! -d $root ]]; then
        printf '%s\n' '(no fixture root)'
        return 0
    fi

    for item in "$root"/*; do
        [[ -d $item && ! -L $item ]] || continue
        authority=$item/data/adb/ota.prop
        if [[ -f $authority && ! -L $authority ]]; then
            hash=$(sha256sum "$authority" 2>/dev/null)
            hash=${hash%% *}
            hash=${hash:0:10}
        else
            hash=MISSING
        fi
        printf '%-32s  %-10s  %s\n' "${item##*/}" "$hash" "$item"
        count=$((count + 1))
    done

    if ((count == 0)); then
        printf '%s\n' '(none)'
    fi
}

_otast_pb_test() {
    local repo mode

    repo=$(_otast_pb_repo_root) || return 1
    mode=${1:-standard}
    case $mode in
        quick|standard|full) ;;
        *) _otast_pb_stop 'test mode must be quick, standard or full'; return 1 ;;
    esac
    bash "$repo/scripts/test.sh" "--$mode"
}

_otast_pb_capture() {
    local repo label output_root
    local -a args

    repo=$(_otast_pb_repo_root) || return 1
    label=${1:-}
    output_root=${2:-}
    args=()
    [[ -n $label ]] && args+=(--label "$label")
    [[ -n $output_root ]] && args+=(--output-root "$output_root")
    bash "$repo/scripts/capture-device-fixture.sh" "${args[@]}"
}

_otast_pb_reset() {
    local repo fixture name

    repo=$(_otast_pb_repo_root) || return 1
    fixture=$(_otast_pb_resolve_fixture "${1:-}") || return 1
    name=${2:-current}
    bash "$repo/scripts/reset-fake-magisk-root.sh" "$fixture" "$name"
}

_otast_pb_upstream() {
    local repo subcommand target root package

    repo=$(_otast_pb_repo_root) || return 1
    subcommand=${1:-}
    [[ -n $subcommand ]] || {
        _otast_pb_help_command upstream
        return 2
    }
    shift

    case $subcommand in
        ref|fetch-ref|assets|fetch|analyse)
            target=${1:-}
            [[ -n $target ]] || { _otast_pb_stop "upstream $subcommand requires TARGET"; return 2; }
            shift
            _otast_pb_with_gh_token                 python3 "$repo/scripts/upstream-target-package.py" "$subcommand" "$target" "$@"
            ;;
        materialize)
            target=${1:-}
            [[ -n $target ]] || { _otast_pb_stop 'upstream materialize requires TARGET'; return 2; }
            shift
            package=${1:-}
            [[ -n $package ]] || { _otast_pb_stop 'upstream materialize requires PACKAGE'; return 2; }
            shift
            root=$(_otast_pb_resolve_fake_root "${1:-latest}") || return 1
            (($# > 0)) && shift
            python3 "$repo/scripts/upstream-target-package.py" materialize \
                "$target" "$package" "$root" "$@"
            ;;
        compare)
            target=${1:-}
            [[ -n $target ]] || { _otast_pb_stop 'upstream compare requires TARGET'; return 2; }
            shift
            root=$(_otast_pb_resolve_fake_root "${1:-latest}") || return 1
            (($# > 0)) && shift
            python3 "$repo/scripts/upstream-target-package.py" compare \
                "$target" "$root" "$@"
            ;;
        show)
            [[ -n ${1:-} ]] || { _otast_pb_stop 'upstream show requires PATH'; return 2; }
            python3 "$repo/scripts/upstream-target-package.py" show "$1"
            ;;
        *)
            _otast_pb_stop "unknown upstream command: $subcommand"
            return 2
            ;;
    esac
}

_otast_pb_refresh() {
    local repo mode label name fixture target package tree json root compare_rc
    local prove=0 restore_clone=0 include_prerelease=0 no_compare=0
    local tag=''
    local ref=''
    local asset=''
    local asset_regex=''
    local -a fetch_args prove_args

    repo=$(_otast_pb_repo_root) || return 1
    mode=${1:-}
    [[ -n $mode ]] || { _otast_pb_help_command refresh; return 2; }
    shift

    case $mode in
        device)
            label=
            name=
            while (($#)); do
                case $1 in
                    --label)
                        (($# >= 2)) || { _otast_pb_stop '--label requires a value'; return 2; }
                        label=$2
                        shift 2
                        ;;
                    --name)
                        (($# >= 2)) || { _otast_pb_stop '--name requires a value'; return 2; }
                        name=$2
                        shift 2
                        ;;
                    --prove) prove=1; shift ;;
                    --restore-clone) restore_clone=1; shift ;;
                    -h|--help) _otast_pb_help_command refresh; return 0 ;;
                    *) _otast_pb_stop "unknown refresh device argument: $1"; return 2 ;;
                esac
            done
            [[ -n $label ]] || label="tegu-$(date -u +%Y%m%dT%H%M%SZ)"
            [[ -n $name ]] || name=$label
            bash "$repo/scripts/capture-device-fixture.sh" --label "$label" || return $?
            fixture="${HOME:?}/.local/share/otast/device-fixtures/$label"
            if ((prove)); then
                prove_args=(--fixture "$fixture" --name "$name")
                ((restore_clone)) && prove_args+=(--restore-clone)
                bash "$repo/scripts/prove-device-fake-root.sh" "${prove_args[@]}"
            else
                bash "$repo/scripts/reset-fake-magisk-root.sh" "$fixture" "$name"
            fi
            ;;
        fixture)
            fixture=${1:-latest}
            if [[ $fixture != --* ]]; then
                shift
            else
                fixture=latest
            fi
            name=
            while (($#)); do
                case $1 in
                    --name)
                        (($# >= 2)) || { _otast_pb_stop '--name requires a value'; return 2; }
                        name=$2
                        shift 2
                        ;;
                    -h|--help) _otast_pb_help_command refresh; return 0 ;;
                    *) _otast_pb_stop "unknown refresh fixture argument: $1"; return 2 ;;
                esac
            done
            fixture=$(_otast_pb_resolve_fixture "$fixture") || return 1
            [[ -n $name ]] || name="refresh-$(date -u +%Y%m%dT%H%M%SZ)"
            bash "$repo/scripts/reset-fake-magisk-root.sh" "$fixture" "$name"
            ;;
        upstream)
            target=${1:-}
            [[ -n $target ]] || { _otast_pb_stop 'refresh upstream requires TARGET'; return 2; }
            shift
            fixture=latest
            name=
            tree=modules_update
            while (($#)); do
                case $1 in
                    --fixture)
                        (($# >= 2)) || { _otast_pb_stop '--fixture requires a value'; return 2; }
                        fixture=$2
                        shift 2
                        ;;
                    --name)
                        (($# >= 2)) || { _otast_pb_stop '--name requires a value'; return 2; }
                        name=$2
                        shift 2
                        ;;
                    --tree)
                        (($# >= 2)) || { _otast_pb_stop '--tree requires a value'; return 2; }
                        tree=$2
                        shift 2
                        ;;
                    --ref)
                        (($# >= 2)) || { _otast_pb_stop '--ref requires a value'; return 2; }
                        ref=$2
                        shift 2
                        ;;
                    --tag)
                        (($# >= 2)) || { _otast_pb_stop '--tag requires a value'; return 2; }
                        tag=$2
                        shift 2
                        ;;
                    --include-prerelease) include_prerelease=1; shift ;;
                    --asset)
                        (($# >= 2)) || { _otast_pb_stop '--asset requires a value'; return 2; }
                        asset=$2
                        shift 2
                        ;;
                    --asset-regex)
                        (($# >= 2)) || { _otast_pb_stop '--asset-regex requires a value'; return 2; }
                        asset_regex=$2
                        shift 2
                        ;;
                    --no-compare) no_compare=1; shift ;;
                    -h|--help) _otast_pb_help_command refresh; return 0 ;;
                    *) _otast_pb_stop "unknown refresh upstream argument: $1"; return 2 ;;
                esac
            done
            case $tree in
                modules|modules_update) ;;
                *) _otast_pb_stop '--tree must be modules or modules_update'; return 2 ;;
            esac
            if [[ -n $ref ]] && { [[ -n $tag ]] || ((include_prerelease)) || [[ -n $asset ]] || [[ -n $asset_regex ]]; }; then
                _otast_pb_stop '--ref cannot be combined with release selectors (--tag, --include-prerelease, --asset, --asset-regex)'
                return 2
            fi
            fixture=$(_otast_pb_resolve_fixture "$fixture") || return 1
            [[ -n $name ]] || name="upstream-${target}-$(date -u +%Y%m%dT%H%M%SZ)"
            bash "$repo/scripts/reset-fake-magisk-root.sh" "$fixture" "$name" || return $?

            if [[ -n $ref ]]; then
                fetch_args=(fetch-ref "$target" --ref "$ref")
            else
                fetch_args=(fetch "$target")
                [[ -n $tag ]] && fetch_args+=(--tag "$tag")
                ((include_prerelease)) && fetch_args+=(--include-prerelease)
                [[ -n $asset ]] && fetch_args+=(--asset "$asset")
                [[ -n $asset_regex ]] && fetch_args+=(--asset-regex "$asset_regex")
            fi
            json=$(_otast_pb_with_gh_token                 python3 "$repo/scripts/upstream-target-package.py" "${fetch_args[@]}")
            compare_rc=$?
            if ((compare_rc != 0)); then
                return "$compare_rc"
            fi
            printf '%s\n' "$json"
            package=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["package"])' <<<"$json") || return 1
            root=$(_otast_pb_resolve_fake_root "${HOME:?}/.cache/otast/fake-roots/$name") || return 1

            python3 "$repo/scripts/upstream-target-package.py" materialize \
                "$target" "$package" "$root" --tree "$tree" || return $?

            if ((no_compare == 0)) && [[ $tree == modules_update ]]; then
                printf '\n===== active device capture vs static candidate =====\n'
                python3 "$repo/scripts/upstream-target-package.py" compare \
                    "$target" "$root"
                compare_rc=$?
                if ((compare_rc != 0)); then
                    printf '[WARN] comparison was unavailable; materialization remains usable for static review.\n' >&2
                fi
            fi

            printf '\nNext classification commands:\n'
            printf '  otast upstream show %q\n' "$(dirname -- "$package")"
            printf '  otast action %q report\n' "$root"
            printf '  otast action %q preflight\n' "$root"
            ;;
        *)
            _otast_pb_stop 'refresh mode must be device, fixture or upstream'
            return 2
            ;;
    esac
}

_otast_pb_action() {
    local repo root action

    repo=$(_otast_pb_repo_root) || return 1
    root=$(_otast_pb_resolve_fake_root "${1:-}") || return 1
    action=${2:-report}
    _otast_pb_assert_fake_root "$root" "fake-root action: $action" || return $?
    bash "$repo/scripts/validate-fake-magisk-root.sh" "$root" "$action"
}

_otast_pb_dispatch() {
    local command repo output fixture root
    local -a prove_args

    _otast_pb_init_colors
    command=${1:-help}
    (($# > 0)) && shift

    case $command in
        help|-h|--help|man|commands|version|--version|-V|status|fixtures|fixture-list|cd)
            ;;
        doctor|env|maintain|upkeep|monitor|review|review-target|accept|accept-target|cleanup|clean-reports|prepush|ready|test|audit|authority|build|package-module|source|package-source|synthetic|fake-synthetic|capture|fixture-capture|reset|fixture-reset|refresh|upstream|target|action|fake-action|prove|proof|export|archive|qualify|finalise|finalize|release|release-v1)
            _otast_pb_require_non_root "otast $command" || return $?
            ;;
    esac

    case $command in
        help|-h|--help|man)
            _otast_pb_help_command "${1:-}"
            ;;
        commands)
            _otast_pb_commands
            ;;
        version|--version|-V)
            _otast_pb_version
            ;;
        doctor|env)
            repo=$(_otast_pb_repo_root) || return 1
            python3 "$repo/scripts/otast-maintenance.py" doctor
            ;;
        status)
            _otast_pb_status
            ;;
        test)
            _otast_pb_test "${1:-standard}"
            ;;
        audit)
            repo=$(_otast_pb_repo_root) || return 1
            output=${1:-reports/public-init}
            bash "$repo/scripts/public-init-audit.sh" "$output"
            ;;
        authority)
            repo=$(_otast_pb_repo_root) || return 1
            output=${1:-$repo/authority/reference-tegu-CP1A.260305.018.ota.prop}
            (cd -- "$repo" && python3 -m tools.otastctl --repo-root "$repo" authority-validate "$output")
            ;;
        build|package-module)
            repo=$(_otast_pb_repo_root) || return 1
            bash "$repo/scripts/build-release.sh" "${1:-$repo/dist}"
            ;;
        source|package-source)
            repo=$(_otast_pb_repo_root) || return 1
            bash "$repo/scripts/package-public-repo.sh" "${1:-$repo/dist/otast-public-ready.zip}"
            ;;
        monitor)
            repo=$(_otast_pb_repo_root) || return 1
            if [[ -n ${1:-} && ${1:-} != --* ]]; then
                python3 "$repo/scripts/otast-maintenance.py" monitor --output "$1" "${@:2}"
            else
                python3 "$repo/scripts/otast-maintenance.py" monitor "$@"
            fi
            ;;
        maintain|upkeep)
            repo=$(_otast_pb_repo_root) || return 1
            python3 "$repo/scripts/otast-maintenance.py" maintain "$@"
            ;;
        review|review-target)
            repo=$(_otast_pb_repo_root) || return 1
            [[ -n ${1:-} ]] || { _otast_pb_stop 'review requires TARGET'; return 2; }
            python3 "$repo/scripts/otast-maintenance.py" review "$@"
            ;;
        accept|accept-target)
            repo=$(_otast_pb_repo_root) || return 1
            [[ -n ${1:-} ]] || { _otast_pb_stop 'accept requires TARGET'; return 2; }
            python3 "$repo/scripts/otast-maintenance.py" accept "$@"
            ;;
        cleanup|clean-reports)
            repo=$(_otast_pb_repo_root) || return 1
            python3 "$repo/scripts/otast-maintenance.py" cleanup "$@"
            ;;
        prepush|ready)
            repo=$(_otast_pb_repo_root) || return 1
            python3 "$repo/scripts/otast-maintenance.py" maintain --audit --device-proof || return $?
            bash "$repo/scripts/qualify-release-candidate.sh"
            ;;
        synthetic|fake-synthetic)
            repo=$(_otast_pb_repo_root) || return 1
            bash "$repo/scripts/fake-magisk-root.sh" "${1:-$repo/reports/fake-magisk-root}"
            ;;
        capture|fixture-capture)
            _otast_pb_capture "${1:-}" "${2:-}"
            ;;
        fixtures|fixture-list)
            _otast_pb_fixtures
            ;;
        reset|fixture-reset)
            _otast_pb_reset "${1:-}" "${2:-}"
            ;;
        refresh)
            _otast_pb_refresh "$@"
            ;;
        upstream|target)
            _otast_pb_upstream "$@"
            ;;
        action|fake-action)
            _otast_pb_action "${1:-}" "${2:-report}"
            ;;
        prove|proof)
            repo=$(_otast_pb_repo_root) || return 1
            if [[ ${1:-} == --* || -z ${1:-} ]]; then
                fixture=$(_otast_pb_resolve_fixture latest) || return 1
            else
                fixture=$(_otast_pb_resolve_fixture "$1") || return 1
                shift
            fi
            prove_args=(--fixture "$fixture")
            if [[ -n ${1:-} && ${1:-} != --* ]]; then
                prove_args+=(--name "$1")
                shift
            fi
            prove_args+=("$@")
            bash "$repo/scripts/prove-device-fake-root.sh" "${prove_args[@]}"
            ;;
        export|archive)
            repo=$(_otast_pb_repo_root) || return 1
            root=$(_otast_pb_resolve_fake_root "${1:-latest}") || return 1
            _otast_pb_assert_fake_root "$root" "fake-root export" || return $?
            if (($# >= 2)); then
                bash "$repo/scripts/export-fake-root-analysis.sh" --fake-root "$root" --output "$2"
            else
                bash "$repo/scripts/export-fake-root-analysis.sh" --fake-root "$root"
            fi
            ;;
        qualify|finalise|finalize)
            repo=$(_otast_pb_repo_root) || return 1
            bash "$repo/scripts/qualify-release-candidate.sh" "$@"
            ;;
        release|release-v1)
            repo=$(_otast_pb_repo_root) || return 1
            bash "$repo/scripts/release-device.sh" "$@"
            ;;
        cd)
            repo=$(_otast_pb_repo_root) || return 1
            if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
                printf '%s\n' "$repo"
            else
                cd -- "$repo" || return 1
                printf 'Changed directory to %s\n' "$repo"
            fi
            ;;
        *)
            _otast_pb_stop "unknown command: $command"
            printf 'Run: otast help\n' >&2
            return 2
            ;;
    esac
}

# Public sourceable entrypoint.
otast() {
    _otast_pb_dispatch "$@"
}

# Execute when called as a script; define functions only when sourced.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    _otast_pb_dispatch "$@"
fi
