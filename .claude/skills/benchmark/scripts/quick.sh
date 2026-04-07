#!/usr/bin/env bash
# Fast docparse-only OfficeDocBench run.
# Use during iteration when you only care about whether AILANG Parse regressed.
# NOTE: only updates the docparse entry in summary.json — other adapters keep
# their previous values, so the snapshot remains internally consistent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

SUMMARY="benchmarks/officedocbench/results/summary.json"
PREV=".claude/skills/benchmark/.previous-summary.json"

if [[ -f "$SUMMARY" ]]; then
  cp "$SUMMARY" "$PREV"
fi

echo "→ Running OfficeDocBench (docparse only, ~10s)…"
uv run benchmarks/officedocbench/eval_officedocbench.py --adapter docparse

# --adapter docparse alone won't refresh summary.json (it gates summary writing
# on --all). Re-aggregate from existing per-adapter results to keep everything
# in sync.
"$(dirname "${BASH_SOURCE[0]}")/refresh-summary.sh" --skip-postcheck

"$(dirname "${BASH_SOURCE[0]}")/_postcheck.sh"
