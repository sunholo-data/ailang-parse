#!/usr/bin/env bash
# Post-run check: diff new summary.json against the snapshot from before the
# run, print headline numbers, and warn if static SEO copy needs updating.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

SUMMARY="benchmarks/officedocbench/results/summary.json"
PREV=".claude/skills/benchmark/.previous-summary.json"

if [[ ! -f "$SUMMARY" ]]; then
  echo "✗ summary.json was not produced. Did the eval fail?" >&2
  exit 1
fi

uv run python - "$SUMMARY" "$PREV" <<'PY'
import json
import sys
from pathlib import Path

new_path = Path(sys.argv[1])
prev_path = Path(sys.argv[2])
new = json.loads(new_path.read_text())
prev = json.loads(prev_path.read_text()) if prev_path.exists() else None

def get(summary, aid):
    for a in summary["adapters"]:
        if a["id"] == aid:
            return a
    return None

ailang = get(new, "ailang_parse")
print()
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  OfficeDocBench  ·  run {new['run_date']}  ·  {new['total_files']} files")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  AILANG Parse")
print(f"    composite : {ailang['composite']*100:5.1f}%")
print(f"    adjusted  : {ailang['adjusted']*100:5.1f}%")
print(f"    coverage  : {ailang['coverage']*100:5.1f}%")
print(f"    files OK  : {ailang['files_ok']}/{ailang['files_total']}")

# Show next 3 competitors by adjusted score
others = [a for a in new["adapters"] if a["id"] != "ailang_parse"]
others.sort(key=lambda a: a["adjusted"], reverse=True)
print()
print("  Next-best competitors (by coverage-adjusted):")
for a in others[:3]:
    print(f"    {a['name']:14s}  composite {a['composite']*100:5.1f}%   adjusted {a['adjusted']*100:5.1f}%")

# Diff against previous
ai_changed = False
ai_delta = 0.0
if prev:
    prev_ai = get(prev, "ailang_parse")
    if prev_ai:
        ai_delta = ailang["composite"] - prev_ai["composite"]
        if abs(ai_delta) >= 0.0005:  # 0.05% threshold
            ai_changed = True
            sign = "+" if ai_delta > 0 else ""
            print()
            print(f"  ⚠ AILANG Parse composite changed: "
                  f"{prev_ai['composite']*100:.1f}% → {ailang['composite']*100:.1f}% "
                  f"({sign}{ai_delta*100:.2f}%)")
        else:
            print()
            print("  ✓ AILANG Parse composite unchanged (within ±0.05%)")

print()

# If composite changed, remind about SEO copy
if ai_changed:
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Static SEO/JSON-LD copy needs manual update")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  These pages contain the AILANG Parse composite as literal text")
    print("  (search engines need it inline — they cannot use data-bench attrs):")
    print()
    static_files = [
        "docs/docx-parsing.html",
        "docs/pptx-parsing.html",
        "docs/xlsx-parsing.html",
        "docs/tables.html",
        "docs/integrations.html",
    ]
    prev_pct = f"{prev_ai['composite']*100:.1f}%"
    new_pct = f"{ailang['composite']*100:.1f}%"
    for f in static_files:
        print(f"    {f}")
    print()
    print(f"  Replace any occurrence of '{prev_pct}' with '{new_pct}' in the files")
    print(f"  above. Re-check related claims (vs-pdf-conversion, migrate-from-*)")
    print(f"  if competitor numbers also moved.")
    print()

# Pages already wired to data-bench will refresh automatically
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  Auto-synced pages (no action needed):")
print("    docs/index.html, docs/benchmarks.html, docs/why.html,")
print("    docs/vs-pdf-conversion.html, docs/migrate-from-unstructured.html,")
print("    docs/pricing.html")
print()
print("  Both summary files were updated:")
print("    benchmarks/officedocbench/results/summary.json  (canonical)")
print("    docs/data/officedocbench-summary.json           (mirror)")
print()
print("  Commit both together so the website stays in sync with the eval.")
print()

# Coverage drop is a red flag
if prev:
    prev_ai = get(prev, "ailang_parse")
    if prev_ai and ailang["coverage"] < prev_ai["coverage"] - 0.001:
        print(f"  ⚠ COVERAGE DROPPED: {prev_ai['coverage']*100:.0f}% → "
              f"{ailang['coverage']*100:.0f}% — a parser is now failing on files")
        print(f"    it used to handle. Check benchmarks/officedocbench/results/")
        print(f"    docparse/results.json for entries with status: ERROR")
        print()
PY
