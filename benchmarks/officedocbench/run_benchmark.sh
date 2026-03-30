#!/usr/bin/env bash
# OfficeDocBench — run the benchmark suite
#
# Usage:
#   bash benchmarks/officedocbench/run_benchmark.sh              # AILANG Parse only (from golden)
#   bash benchmarks/officedocbench/run_benchmark.sh --all        # All installed adapters
#   bash benchmarks/officedocbench/run_benchmark.sh --live       # Re-parse files (requires AILANG)
#   bash benchmarks/officedocbench/run_benchmark.sh --json       # JSON output
#
# Prerequisites:
#   - Python 3.10+ with uv (https://github.com/astral-sh/uv)
#   - For --all: pip install unstructured docling llama-parse markitdown
#   - For --live: AILANG runtime installed (https://ailang.sunholo.com/install.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_DIR"

echo "=== OfficeDocBench ==="
echo "The first benchmark for Office structural document parsing."
echo ""

# Check Python / uv
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Run the evaluation
uv run benchmarks/officedocbench/eval_officedocbench.py "$@"

echo ""
echo "=== Done ==="
echo "Full results: benchmarks/officedocbench/results/"
echo "Methodology:  benchmarks/officedocbench/README.md"
