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

uv run python <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path.cwd()
RESULTS = REPO / "benchmarks" / "officedocbench" / "results"

ADAPTER_ID = {
    "DocParse": "ailang_parse",
    "Unstructured": "unstructured",
    "Docling": "docling",
    "LlamaParse": "llamaparse",
    "MarkItDown": "markitdown",
    "Kreuzberg": "kreuzberg",
    "Pandoc": "pandoc",
    "Raw OOXML": "ooxml",
}

adapters_summary = []
total_files = 0

for sub in sorted(RESULTS.iterdir()):
    rj = sub / "results.json"
    if not rj.is_file():
        continue
    ar = json.loads(rj.read_text())
    name = ar["adapter"]
    results = ar["results"]
    n_total = len(results)
    total_files = max(total_files, n_total)
    ok = [r for r in results if r["status"] == "OK"]
    n_ok = len(ok)
    coverage = n_ok / n_total if n_total else 0
    composite = sum(r["scores"]["composite"] for r in ok) / n_ok if ok else 0

    def avg(key):
        return sum(r["scores"].get(key, {}).get("score", 0) for r in ok) / n_ok if ok else 0

    by_fmt = {}
    for r in ok:
        by_fmt.setdefault(r["format"], []).append(r["scores"]["composite"])
    per_format = {
        fmt: {"composite": round(sum(s) / len(s), 4), "files": len(s)}
        for fmt, s in sorted(by_fmt.items())
    }

    adapters_summary.append({
        "id": ADAPTER_ID.get(name, name.lower().replace(" ", "_")),
        "name": name,
        "version": ar.get("version", ""),
        "files_ok": n_ok,
        "files_total": n_total,
        "coverage": round(coverage, 4),
        "composite": round(composite, 4),
        "adjusted": round(composite * coverage, 4),
        "feature_detection": round(avg("feature_detection"), 4),
        "structural_recall": round(avg("structural_recall"), 4),
        "structural_quality": round(avg("structural_quality"), 4),
        "content_fidelity": round(avg("content_fidelity"), 4),
        "text_jaccard": round(avg("text_jaccard"), 4),
        "element_count": round(avg("element_count"), 4),
        "metadata": round(avg("metadata"), 4),
        "per_format": per_format,
    })

adapters_summary.sort(key=lambda a: a["adjusted"], reverse=True)

summary = {
    "schema_version": 1,
    "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    "total_files": total_files,
    "adapters": adapters_summary,
}

(RESULTS / "summary.json").write_text(json.dumps(summary, indent=2))
print(f"  Wrote {(RESULTS / 'summary.json').relative_to(REPO)}")

mirror = REPO / "docs" / "data" / "officedocbench-summary.json"
mirror.parent.mkdir(parents=True, exist_ok=True)
mirror.write_text(json.dumps(summary, indent=2))
print(f"  Wrote {mirror.relative_to(REPO)}")
PY

if [[ $SKIP_POSTCHECK -eq 0 ]]; then
  "$(dirname "${BASH_SOURCE[0]}")/_postcheck.sh"
fi
