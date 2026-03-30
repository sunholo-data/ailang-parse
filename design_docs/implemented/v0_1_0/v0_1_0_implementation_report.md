# DocParse v0.1.0 — Implementation Report

**Date**: March 2026
**Status**: Implemented

## Overview

DocParse v0.1.0 is the initial standalone release of the AILANG document parsing module. It extracts structured content from Office formats (DOCX, PPTX, XLSX) deterministically and from PDFs/images via pluggable AI backends.

## Architecture

```
docparse/
├── docparse/                    # AILANG modules (10 total)
│   ├── types/document.ail       # Block ADT (9 variants)
│   ├── services/                # 9 service modules
│   │   ├── docx_parser.ail      # DOCX: paragraphs, tables, track changes, comments
│   │   ├── pptx_parser.ail      # PPTX: slides, shapes, tables
│   │   ├── xlsx_parser.ail      # XLSX: sheets, cells, merged regions
│   │   ├── zip_extract.ail      # ZIP/Office file extraction
│   │   ├── direct_ai_parser.ail # PDF/image AI extraction pipeline
│   │   ├── layout_ai.ail        # AI image description
│   │   ├── json_emitter.ail     # JSON output serialization
│   │   ├── output_writer.ail    # File output
│   │   └── docparse_browser.ail # WASM browser adapter
│   └── main.ail                 # CLI entry point
├── bin/docparse                 # Bash CLI wrapper
├── data/test_files/             # 17 real-world test files
└── benchmarks/                  # Benchmark infrastructure
```

### Block ADT

9 variants representing all document content:
- `TextBlock` — paragraphs, body text
- `HeadingBlock` — section headers with levels
- `TableBlock` — tables with headers, rows, merged cell metadata
- `ImageBlock` — embedded images with optional AI descriptions
- `AudioBlock`, `VideoBlock` — media references
- `ListBlock` — ordered/unordered lists
- `SectionBlock` — structural grouping (headers, footers, comments, footnotes)
- `ChangeBlock` — track changes (insert, delete, move-to, move-from)

### Effect System

AILANG's algebraic effect system provides capability-bounded execution:
```
IO @limit=200   — Console output
FS @limit=40    — File system reads (ZIP entries)
AI @limit=30    — AI model calls (PDF extraction)
Env             — Environment/CLI args
```

## Features Implemented

### Office Parsing (Deterministic)
- **DOCX**: Paragraphs, headings, tables (with merged cells), track changes (insert/delete/move), comments, headers/footers, footnotes/endnotes, images, text boxes, metadata
- **PPTX**: Slides, shapes, text, tables, images, metadata
- **XLSX**: Sheets, cells, merged regions, shared strings, metadata

### PDF Parsing (AI-powered)
- Page-by-page multimodal extraction via `callJsonSimple`
- Automatic JSON repair for truncated model responses
- Retry with validation for quality assurance
- Supports any model via AILANG's AI effect abstraction

### Comment Extraction (new in v0.1.0)
- Parses `word/comments.xml` from DOCX files
- Extracts author, date, and comment text
- Represented as `SectionBlock(kind: "comment")`

### FS Budget Fix (new in v0.1.0)
- Increased FS budget from 20 to 40 to handle complex DOCX files
- `docx-hdrftr.docx` now parses successfully (was timing out)

## Benchmark Infrastructure

### Office Structural Benchmark
- **18 golden outputs** in `benchmarks/office/golden/`
- **100% baseline** across all 18 files
- Checks: tables, merged cells, track changes, comments, headers/footers, text boxes, images, metadata, text Jaccard
- Run: `uv run benchmarks/run_benchmarks.py --suite office`

### PDF Extraction Benchmark
- **3 test PDFs** generated with fpdf2 (simple text, tables, multipage)
- **Ground truth golden files** with expected headings, key phrases, tables
- Metrics: heading recall, key phrase recall, table detection, overall score
- Multi-model support via `--ai MODEL` flag

#### PDF Benchmark Results (March 2026)

| Model | simple_text | table_report | multipage_spec | Mean | Avg Time |
|-------|-------------|--------------|----------------|------|----------|
| gemini-2.0-flash | 90% | 100% | 86% | **92%** | 36s |
| ollama:granite3.2-vision | ERROR | ERROR | ERROR | 0% | 120s (timeout) |
| ollama:PaddleOCR-VL:0.9b | 0% | 8% | 0% | 2.8% | 1.6s |
| ollama:gemma3:12b | ERROR | ERROR | ERROR | 0% | — |

**Key finding**: Local Ollama models fail because AILANG's AI pipeline sends complex structured JSON prompts that small models can't follow. See [planned/ollama_model_aware_prompting.md](../../planned/ollama_model_aware_prompting.md).

### Competitor Adapter Framework
- **Docling** (`run_docling.py`): IBM Docling comparison with feature gap analysis
- **LlamaParse** (`run_llamaparse.py`): LlamaIndex cloud API comparison
- **Unstructured** (`run_unstructured.py`): Unstructured.io comparison
- Common normalization schema via `NormalizedElement`
- Run: `uv run benchmarks/run_benchmarks.py --competitors [docling|llamaparse|unstructured]`

## Models Configuration

Added to AILANG `models.yml`:
- `ollama-granite3-2-vision` — IBM Granite 3.2 Vision (2.4GB, document OCR)
- `ollama-paddleocr-vl` — PaddleOCR-VL 0.9B (935MB, lightweight OCR)
- `ollama-gemma3` — Google Gemma 3 12B (8.1GB, general multimodal)

## Known Limitations

1. **Ollama models produce near-zero PDF scores** — AILANG's `callJsonSimple` sends complex structured prompts that small local models can't follow. Needs model-aware prompting or two-stage pipeline.
2. **FS budget is a blunt instrument** — Raised to 40, but complex documents with many ZIP entries could still exhaust it. Better ZIP caching would help.
3. **No real footnote/endnote test data** — Test files only have boilerplate separators, not actual footnote content.
4. **PPTX speaker notes not extracted** — Pipeline reads slides but not `ppt/notesSlides/`.
5. **`call()` truncates at ~491 chars** — Must use `callJsonSimple` for all generation tasks.

## Files Changed (from initial commit)

| File | Change |
|------|--------|
| `docparse/main.ail` | FS budget 20→40, comment extraction pipeline |
| `docparse/services/zip_extract.ail` | Added `readComments()` |
| `docparse/services/docx_parser.ail` | Added `parseDocxComments`, `docxParseCommentNodes`, `docxExtractCommentTexts` |
| `benchmarks/pdf/eval_pdf.py` | New — PDF benchmark evaluator |
| `benchmarks/pdf/generate_test_pdfs.py` | New — PDF test file generator |
| `benchmarks/competitors/run_docling.py` | New — Docling comparison adapter |
| `benchmarks/competitors/run_llamaparse.py` | New — LlamaParse comparison adapter |
| `benchmarks/run_benchmarks.py` | Updated competitor runner |
| `pyproject.toml` | Added fpdf2, competitor optional deps |
| `CLAUDE.md` | Updated benchmark docs |

## Commits

1. `cc14304` — FS budget fix + comment extraction + uv migration
2. `7b46811` — PDF benchmark infrastructure
3. `2d43927` — Competitor adapters (Docling, LlamaParse)
