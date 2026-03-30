# Design: Migrate Benchmark Evaluation to AILANG

**Status**: Planned
**Priority**: Medium
**Target**: v0.3.0
**Principle**: All DocParse logic must exercise AILANG code paths

## Problem

Current benchmark evaluation is entirely Python (`eval_office.py`, `eval_pdf.py`). These scripts:
- Parse DocParse's JSON output
- Compute metrics (text Jaccard, element counts, structural checks)
- Compare against golden outputs
- Generate reports

This evaluation logic is core DocParse functionality and should be in AILANG to dogfood the language and reduce Python dependency.

## What Moves to AILANG

### 1. Golden Output Comparison
Currently `eval_office.py` reads golden JSON and compares. In AILANG:
```ailang
-- docparse/services/eval.ail
export func compareGolden(actual: ExtractionResult, goldenPath: string) -> EvalResult ! {FS} {
  let goldenJson = readFile(goldenPath);
  let golden = parseExtractionResult(goldenJson);
  computeMetrics(actual, golden)
}
```

### 2. Text Jaccard Similarity
Currently Python regex + set operations. In AILANG:
```ailang
pure func textJaccard(a: string, b: string) -> float {
  let wordsA = wordSet(a);
  let wordsB = wordSet(b);
  let intersection = setIntersect(wordsA, wordsB);
  let union = setUnion(wordsA, wordsB);
  intToFloat(length(intersection)) / intToFloat(length(union))
}
```

### 3. Structural Feature Checks
Table count, heading count, track change detection — all pure functions on Block ADT.

### 4. Markdown Export for OmniDocBench
`blocks_to_markdown` in Python adapter → `renderMarkdown` in `output_formatter.ail` (already partially exists).

### 5. Benchmark Runner
```ailang
-- docparse/services/benchmark_runner.ail
export func runOfficeBenchmark(testDir: string, goldenDir: string) -> [EvalResult] ! {IO, FS} {
  let files = listFiles(testDir);
  map(\f. evaluateFile(f, goldenDir), files)
}
```

## What Stays Python

- **OmniDocBench evaluation** — TEDS, CDM metrics are complex Python libraries
- **Competitor adapters** — Import docling, llama-parse, unstructured
- **Benchmark orchestration** — `run_benchmarks.py` as thin wrapper calling `ailang run`
- **Report generation** — Markdown tables, charts (nice-to-have in Python)

## Implementation Plan

1. Add `std/set` operations to AILANG stdlib (or implement in pure AILANG)
2. Create `docparse/services/eval.ail` — golden comparison, Jaccard, structural checks
3. Create `docparse/services/benchmark_runner.ail` — run eval across files
4. Update `main.ail` to support `--eval` flag that runs benchmarks
5. Thin Python wrapper calls `ailang run --entry eval` and formats output
6. Gradually deprecate Python eval logic

## AILANG Dependencies

May need stdlib additions:
- `std/set` or set operations on lists (intersect, union)
- `std/regex` or word tokenization
- `std/dir` or directory listing (currently only `std/fs` has file read/write)

If these don't exist yet, implement as pure AILANG functions or send as AILANG feedback.

## Success Criteria

- `ailang run --entry eval docparse/eval.ail --suite office` runs benchmarks
- Produces same scores as current Python eval
- Python scripts become thin wrappers (<50 lines each)
- New benchmark features implemented in AILANG first
