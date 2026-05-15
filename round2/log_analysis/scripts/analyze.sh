#!/usr/bin/env bash
# One-shot: parse a submission log, detect leaks, refresh the comparison table.
#
# Usage:
#   scripts/log_analysis/analyze.sh <submission_id>           # analyze one submission
#   scripts/log_analysis/analyze.sh all                       # analyze every submission with a log
#   scripts/log_analysis/analyze.sh <submission_id> --refresh # force re-parse
#
# Outputs written:
#   docs/round2_log_analysis/parsed/<sub>.json       (cached parser output)
#   docs/round2_log_analysis/leaks/<sub>.md          (leak report)
#   docs/round2_log_analysis/submissions_table.md    (comparison table)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOGS_ROOT="/tmp/prosperity_logs"

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <submission_id>|all [--refresh]" >&2
    exit 1
fi

target="$1"
shift || true
extra_args=("$@")

run_one() {
    local sub="$1"
    if [[ ! -d "$LOGS_ROOT/$sub" ]]; then
        echo "[$sub] no log directory, skipping" >&2
        return
    fi
    if ! ls "$LOGS_ROOT/$sub"/*.log >/dev/null 2>&1; then
        echo "[$sub] no .log file, skipping" >&2
        return
    fi
    echo "[$sub] parsing + detecting leaks..." >&2
    python3 "$SCRIPT_DIR/detect_leaks.py" "$sub" ${extra_args[@]+"${extra_args[@]}"} >/dev/null
}

if [[ "$target" == "all" ]]; then
    subs=$(ls -1 "$LOGS_ROOT" | sort -n)
    for s in $subs; do
        [[ "$s" =~ ^[0-9]+$ ]] || continue
        run_one "$s" || echo "[$s] FAILED" >&2
    done
    echo "refreshing comparison table for all submissions..." >&2
    python3 "$SCRIPT_DIR/compare_submissions.py" all ${extra_args[@]+"${extra_args[@]}"}
else
    run_one "$target"
    echo "refreshing comparison table..." >&2
    python3 "$SCRIPT_DIR/compare_submissions.py" all ${extra_args[@]+"${extra_args[@]}"}
fi

echo "done. See:" >&2
echo "  $REPO_ROOT/docs/round2_log_analysis/submissions_table.md" >&2
if [[ "$target" != "all" ]]; then
    echo "  $REPO_ROOT/docs/round2_log_analysis/leaks/$target.md" >&2
fi
