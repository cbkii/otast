#!/usr/bin/env bash
# Fast non-mutating validation for the OTAST playbook v5.1 helper files.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || {
    printf 'STOP: cannot resolve script directory.\n' >&2
    exit 1
}
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1

errors=0
check() {
    local description output rc
    description=$1
    shift
    printf '%-52s' "$description"
    output=$("$@" 2>&1)
    rc=$?
    if ((rc == 0)); then
        printf ' PASS\n'
    else
        printf ' FAIL\n'
        if [[ -n $output ]]; then
            printf '%s\n' "$output" | sed 's/^/    /' >&2
        fi
        errors=$((errors + 1))
    fi
}

check 'Main playbook Bash syntax' bash -n "$SCRIPT_DIR/otast-playbook.sh"
check 'Completion Bash syntax' bash -n "$SCRIPT_DIR/otast-playbook-completion.bash"
check 'Device proof Bash syntax' bash -n "$SCRIPT_DIR/prove-device-fake-root.sh"
check 'Analysis exporter Bash syntax' bash -n "$SCRIPT_DIR/export-fake-root-analysis.sh"
check 'Candidate qualifier Bash syntax' bash -n "$SCRIPT_DIR/qualify-release-candidate.sh"

if command -v shellcheck >/dev/null 2>&1; then
    check 'Playbook ShellCheck warnings' shellcheck --severity=warning --shell=bash "$SCRIPT_DIR/otast-playbook.sh"
    check 'Completion ShellCheck warnings' shellcheck --severity=warning --shell=bash "$SCRIPT_DIR/otast-playbook-completion.bash"
    check 'Self-test ShellCheck warnings' shellcheck --severity=warning --shell=bash "$SCRIPT_DIR/otast-playbook-self-test.sh"
    check 'Device proof ShellCheck warnings' shellcheck --severity=warning --shell=bash "$SCRIPT_DIR/prove-device-fake-root.sh"
    check 'Analysis exporter ShellCheck warnings' shellcheck --severity=warning --shell=bash "$SCRIPT_DIR/export-fake-root-analysis.sh"
    check 'Candidate qualifier ShellCheck warnings' shellcheck --severity=warning --shell=bash "$SCRIPT_DIR/qualify-release-candidate.sh"
else
    printf '%-52s SKIP (shellcheck unavailable)\n' 'Overlay ShellCheck warnings'
fi
check 'Python source syntax' python3 -c 'from pathlib import Path; import sys; [compile(Path(p).read_text(encoding="utf-8"), p, "exec") for p in sys.argv[1:]]'     "$SCRIPT_DIR/upstream-target-package.py"     "$SCRIPT_DIR/otast_safety_guard.py"     "$SCRIPT_DIR/otast-maintenance.py"     "$REPO_ROOT/tests/test_playbook.py"     "$REPO_ROOT/tests/test_maintenance.py"
check 'Executable help output' env NO_COLOR=1 OTAST_REPO_ROOT="$REPO_ROOT" bash "$SCRIPT_DIR/otast-playbook.sh" help
check 'Detailed proof help output' env NO_COLOR=1 OTAST_REPO_ROOT="$REPO_ROOT" bash "$SCRIPT_DIR/otast-playbook.sh" help prove
check 'Detailed refresh help output' env NO_COLOR=1 OTAST_REPO_ROOT="$REPO_ROOT" bash "$SCRIPT_DIR/otast-playbook.sh" help refresh
check 'Detailed upstream help output' env NO_COLOR=1 OTAST_REPO_ROOT="$REPO_ROOT" bash "$SCRIPT_DIR/otast-playbook.sh" help upstream
check 'Detailed maintenance help output' env NO_COLOR=1 OTAST_REPO_ROOT="$REPO_ROOT" bash "$SCRIPT_DIR/otast-playbook.sh" help maintain
check 'Detailed review help output' env NO_COLOR=1 OTAST_REPO_ROOT="$REPO_ROOT" bash "$SCRIPT_DIR/otast-playbook.sh" help review
check 'Maintenance CLI help output' env OTAST_REPO_ROOT="$REPO_ROOT" python3 "$SCRIPT_DIR/otast-maintenance.py" --help
check 'Command list output' env NO_COLOR=1 OTAST_REPO_ROOT="$REPO_ROOT" bash "$SCRIPT_DIR/otast-playbook.sh" commands
check 'Sourceable otast function' env NO_COLOR=1 OTAST_REPO_ROOT="$REPO_ROOT" bash -c 'source "$1" && declare -F otast >/dev/null && otast version >/dev/null' _ "$SCRIPT_DIR/otast-playbook.sh"
check 'Combined Python contract tests' env PYTHONDONTWRITEBYTECODE=1 bash -c 'cd "$1" && python3 -m unittest tests.test_maintenance tests.test_playbook -v' _ "$REPO_ROOT"

printf '\n==================================================\n'
if ((errors == 0)); then
    printf 'PLAYBOOK SELF-TEST: PASS\n'
else
    printf 'PLAYBOOK SELF-TEST: FAIL (%s checks)\n' "$errors"
fi
printf 'REPOSITORY:         %s\n' "$REPO_ROOT"
printf '==================================================\n'

((errors == 0))
