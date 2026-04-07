# OfficeDocBench Results

This directory contains the canonical benchmark output. **`summary.json` is the single source of truth** for the headline numbers shown across the website.

## Files

| File | Purpose |
|------|---------|
| `summary.json` | Compact aggregates per adapter (composite, adjusted, coverage, per-format, per-metric). Used by the docs website. |
| `<adapter>/results.json` | Full per-file scoring detail for each adapter. |

## Sync workflow

Whenever you re-run the full benchmark, `summary.json` is regenerated automatically and **mirrored to `docs/data/officedocbench-summary.json`**:

```bash
uv run benchmarks/officedocbench/eval_officedocbench.py --all
```

The website (`docs/index.html`, `docs/benchmarks.html`) loads the mirror via `docs/js/bench-data.js`, which resolves `data-bench="<adapter_id>.<field>"` attributes at page load. Inline values in HTML serve as static fallbacks if the fetch fails.

### Adding a new score to a page

1. Pick the field path, e.g. `kreuzberg.per_format.docx.composite`.
2. Add `<span data-bench="kreuzberg.per_format.docx.composite">73.8%</span>` in HTML — the inline text is the fallback.
3. The injector formats `[0,1]` numbers as percentages automatically.

### Top-level paths

- `total_files` — total files in the benchmark
- `run_date` — UTC date of the run
- `<adapter_id>.composite` / `.adjusted` / `.coverage`
- `<adapter_id>.feature_detection` / `.structural_recall` / `.structural_quality` / `.content_fidelity` / `.text_jaccard` / `.element_count` / `.metadata`
- `<adapter_id>.per_format.<fmt>.composite` / `.files`

Adapter ids: `ailang_parse`, `kreuzberg`, `ooxml`, `pandoc`, `markitdown`, `unstructured`, `docling`, `llamaparse`.
