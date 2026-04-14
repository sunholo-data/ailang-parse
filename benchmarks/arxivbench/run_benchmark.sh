#!/usr/bin/env bash
# arxivbench — structural fidelity benchmark for scientific-paper parsers.
#
# Usage:
#   bash benchmarks/arxivbench/run_benchmark.sh                   # AILANG only
#   bash benchmarks/arxivbench/run_benchmark.sh --all             # all installed adapters
#   bash benchmarks/arxivbench/run_benchmark.sh --adapter pandoc  # specific adapter
#   bash benchmarks/arxivbench/run_benchmark.sh --paper perelman_ricci
#
# Prerequisites:
#   - uv (https://github.com/astral-sh/uv)
#   - AILANG runtime (https://ailang.sunholo.com/install.sh)
#   - Optional:
#       pandoc                                   -> source-based baseline
#       uv pip install docling markitdown llama-parse unstructured
#                                                -> PDF-OCR baselines

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_DIR"

echo "=== arxivbench ==="
echo "Structural fidelity of LaTeX/arXiv parsers."
echo ""

if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

uv run benchmarks/arxivbench/eval_arxivbench.py "$@"

echo ""
echo "=== Done ==="
echo "Full results: benchmarks/arxivbench/results/latest.json"
echo "Methodology:  benchmarks/arxivbench/README.md"
