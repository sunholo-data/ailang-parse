#!/bin/bash
# Run gap analysis and benchmark, report results
# Usage: run_gap_check.sh [--gaps-only] [--bench-only]

set -e
cd "$(git rev-parse --show-toplevel)"

if [[ "$1" != "--bench-only" ]]; then
  echo "=== Gap Analysis ==="
  uv run benchmarks/office/eval_gaps.py --verbose 2>&1
  echo ""
fi

if [[ "$1" != "--gaps-only" ]]; then
  echo "=== OfficeDocBench (AILANG Parse only) ==="
  uv run benchmarks/officedocbench/eval_officedocbench.py 2>&1
  echo ""
fi
