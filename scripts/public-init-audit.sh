#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P) || exit 1
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P) || exit 1
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh" || exit 1

report_dir=${1:-"$REPO_ROOT/reports/public-init"}
case $report_dir in /*) ;; *) report_dir=$REPO_ROOT/$report_dir ;; esac
mkdir -p -- "$report_dir" || otast_script_fatal "Cannot create report directory: $report_dir"

if ! bash "$SCRIPT_DIR/test.sh" --full >"$report_dir/full-test.log" 2>&1; then
    cat "$report_dir/full-test.log" >&2
    otast_script_error 'Full test pass failed'
fi
if ((OTAST_SCRIPT_ERRORS == 0)); then
    if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" privacy-scan --json >"$report_dir/privacy.json"; then
        otast_script_error 'Privacy scan failed'
    fi
fi
if ((OTAST_SCRIPT_ERRORS == 0)); then
    if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" fake-root --output "$report_dir/fake-root" >"$report_dir/fake-root-summary.json"; then
        otast_script_error 'Independent fake-root qualification failed'
    fi
fi
if ((OTAST_SCRIPT_ERRORS == 0)); then
    if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" package-source --output "$report_dir/otast-public-ready.zip"; then
        otast_script_error 'Public source packaging failed'
    fi
fi
if ((OTAST_SCRIPT_ERRORS == 0)); then
    if ! otast_python -m tools.otastctl --repo-root "$REPO_ROOT" build --output "$report_dir/release"; then
        otast_script_error 'Magisk release package build failed'
    fi
fi
if ((OTAST_SCRIPT_ERRORS == 0)); then
    version=$(awk -F= '$1=="version" {print $2; exit}' "$REPO_ROOT/module/module.prop") || version=
    source_zip_sha256=$(sha256sum "$report_dir/otast-public-ready.zip" 2>/dev/null | awk 'NR==1 {print $1}') || source_zip_sha256=
    module_zip=$(find "$report_dir/release" -maxdepth 1 -type f -name 'otast-*.zip' -print | sort | head -n 1) || module_zip=
    module_zip_sha256=
    if [[ -n $module_zip ]]; then
        module_zip_sha256=$(sha256sum "$module_zip" 2>/dev/null | awk 'NR==1 {print $1}') || module_zip_sha256=
    fi
    generated_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) || generated_utc=
    if [[ -z $version || -z $source_zip_sha256 || -z $module_zip_sha256 || -z $generated_utc ]]; then
        otast_script_error 'Cannot resolve one or more audit-summary fields'
    else
        {
            printf 'OTAST public initialization audit\n'
            printf 'result=PASS\n'
            printf 'version=%s\n' "$version"
            printf 'source_zip_sha256=%s\n' "$source_zip_sha256"
            printf 'module_zip_sha256=%s\n' "$module_zip_sha256"
            printf 'generated_utc=%s\n' "$generated_utc"
        } >"$report_dir/AUDIT.txt" || otast_script_error 'Cannot write audit summary'
    fi
fi
if ((OTAST_SCRIPT_ERRORS == 0)); then
    otast_script_info "Audit evidence: $report_dir"
    otast_script_info "Public ZIP: $report_dir/otast-public-ready.zip"
fi
otast_script_summary
