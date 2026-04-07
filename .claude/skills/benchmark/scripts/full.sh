#!/usr/bin/env bash
# Full OfficeDocBench run across all 8 adapters.
# Regenerates summary.json + docs mirror, runs post-check.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

SUMMARY="benchmarks/officedocbench/results/summary.json"
PREV=".claude/skills/benchmark/.previous-summary.json"

# Snapshot the previous summary so post-check can diff
if [[ -f "$SUMMARY" ]]; then
  cp "$SUMMARY" "$PREV"
fi

echo "→ Running OfficeDocBench across all 8 adapters (this takes ~1 minute)…"
uv run benchmarks/officedocbench/eval_officedocbench.py --all

# Run the post-check (diff + sync reminders)
"$(dirname "${BASH_SOURCE[0]}")/_postcheck.sh"
