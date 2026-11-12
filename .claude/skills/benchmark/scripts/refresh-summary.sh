#!/usr/bin/env bash
# Re-aggregate existing per-adapter results.json files into a fresh summary.json
# (and the docs mirror) without re-running any parsers.
#
# Useful when:
#   - You changed the summary writer in eval_officedocbench.py and want to
#     regenerate without re-evaluating
#   - quick.sh has just refreshed docparse and wants to mix it back into the
#     existing snapshot of competitors
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

SKIP_POSTCHECK=0
if [[ "${1:-}" == "--skip-postcheck" ]]; then
  SKIP_POSTCHECK=1
fi

SUMMARY="benchmarks/officedocbench/results/summary.json"
PREV=".claude/skills/benchmark/.previous-summary.json"

if [[ -f "$SUMMARY" && $SKIP_POSTCHECK -eq 0 ]]; then
  cp "$SUMMARY" "$PREV"
fi

echo "→ Re-aggregating summary.json from existing per-adapter results…"

# One aggregator only: the eval's own _write_summary. This script used to carry
# a second, older copy that dropped structural_fidelity, structural_features and
# provenance, which blanked those figures on the site after a quick run.
uv run benchmarks/officedocbench/eval_officedocbench.py --summarize > /dev/null

if [[ $SKIP_POSTCHECK -eq 0 ]]; then
  "$(dirname "${BASH_SOURCE[0]}")/_postcheck.sh"
fi
