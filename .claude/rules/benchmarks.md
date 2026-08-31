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

# Round-trip check: parse -> markdown -> parse (run after ANY parser or
# generator change; the office suite cannot see markdown at all)
uv run benchmarks/roundtrip_check.py

# Generated-document verification (structure, libraries, DOCX table grid)
uv run benchmarks/verify_generated.py

# Failure check: a failed parse must exit non-zero and write NO output file
uv run benchmarks/failure_check.py
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

## Round-trip suite

`benchmarks/roundtrip_check.py` parses each test file, renders it to markdown,
and parses that back, asserting table dimensions, cell text, grid width and the
heading sequence survive. 0 failures across 101 files.

It exists because **the office suite scores JSON goldens and no golden is
markdown**, so nothing scored the markdown writer at all — it read 100.0%
while a DOCX table with a two-paragraph cell was shattering into broken pipe
syntax. Files whose rendered markdown exceeds 64KB are skipped and named on
every run.

## Verifying generated documents

`benchmarks/verify_generated.py` opens each generated file with the Python
libraries AND inspects its structure. The DOCX check asserts every row spans
exactly the columns `w:tblGrid` declares and that every cell is iterable —
added after malformed geometry shipped twice while "does it open" passed,
because LibreOffice tolerates what python-docx and Word do not.

## Failure check

`benchmarks/failure_check.py` is the only suite that scores what happens when a
parse *fails*. Every other one scores documents that parsed, so none of them
could see an error being returned AS the document: an explicit `--pdf-backend`
failure was caught, formatted into a sentence, and handed back as the outcome's
only block. The CLI exited 0, wrote a 114-byte `.md` reading "PDF extraction
failed: …", and `ailang run --batch` counted it — a nine-file batch reported
9/9 with one contract silently replaced by its own error message.

The property is one line: **a file on disk means a document was parsed.** A
failed parse exits non-zero and writes nothing. The positive controls are
load-bearing — failing everything would satisfy that too.

## The blind spot to design around

Three defects in a row reached a release through green suites: parse-side
goldens and "does the file open" both pass through structurally invalid
output. Anything generated needs its structure read BACK, not just opened.

## Philosophy

The real differentiator is **deterministic structural Office parsing** (track changes, headers/footers, merged cells, text boxes, comments) that competitors miss entirely. For PDFs, we delegate to whatever AI model the user plugs in — we don't try to beat specialized OCR.
