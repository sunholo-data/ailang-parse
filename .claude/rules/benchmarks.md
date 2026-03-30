---
description: Benchmark commands, golden file management, and testing philosophy
---

# Benchmark Rules

## Commands

```bash
# Office structural benchmark (no API, instant)
uv run benchmarks/run_benchmarks.py --suite office

# Stress tests (large/slow files, not for day-to-day use)
uv run benchmarks/run_benchmarks.py --suite stress

# PDF benchmark (needs AI backend)
uv run benchmarks/run_benchmarks.py --suite pdf --ai gemini-2.5-flash

# Competitor comparison (requires: uv pip install -e '.[competitors]')
uv run benchmarks/run_benchmarks.py --competitors              # all
uv run benchmarks/run_benchmarks.py --competitors docling      # just Docling
uv run benchmarks/run_benchmarks.py --competitors llamaparse   # just LlamaParse
uv run benchmarks/run_benchmarks.py --competitors markitdown   # just MarkItDown

# Regenerate golden outputs after changing parser code
bash benchmarks/generate_golden.sh
```

## Office Structural Benchmark

- Golden outputs in `benchmarks/office/golden/`
- Checks: tables, merged cells, track changes, comments, headers/footers, text boxes, images, metadata, text Jaccard
- Baseline: 100% across all files
- Run after any parser change to catch regressions

## Stress Tests

- Large/slow files live in `data/test_files/stress/` with golden outputs in `benchmarks/office/stress/`
- Not included in the standard `--suite office` run
- Run explicitly with `--suite stress` for performance testing

## Philosophy

The real differentiator is **deterministic structural Office parsing** (track changes, headers/footers, merged cells, text boxes, comments) that competitors miss entirely. For PDFs, we delegate to whatever AI model the user plugs in — we don't try to beat specialized OCR.
