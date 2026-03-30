# DocParse v0.2.0 — PDF Pipeline Improvements

**Status**: Planned
**Theme**: Make PDF extraction work reliably across all model tiers

## Goals

1. Local Ollama models produce usable PDF extraction results (>50% benchmark score)
2. Expand PDF test corpus from 3 to 10+ diverse documents
3. Multi-model benchmark matrix as a first-class CI artifact

## Features

### 1. Two-Stage PDF Pipeline

See [ollama_model_aware_prompting.md](ollama_model_aware_prompting.md) for full design.

Split extraction into:
- **Stage 1** — Raw OCR via simple prompt (works with any model)
- **Stage 2** — Heuristic structuring into Block ADT (pure, no AI needed)

Keep the existing single-stage `callJsonSimple` path for capable models (Gemini, Claude) as a fast path.

**Files**: `docparse/services/direct_ai_parser.ail`

### 2. Expanded PDF Test Corpus

Current test PDFs are synthetic (fpdf2-generated). Add real-world diversity:

| PDF Type | Why | Source |
|----------|-----|--------|
| Academic paper | Multi-column, footnotes, references | arXiv public domain |
| Invoice/form | Tables, key-value pairs, logos | Generated |
| Scanned document | OCR challenge, noise, skew | Generated from Office test files |
| Presentation export | Slides as pages, mixed text/images | Export from test PPTX |
| Government form | Complex tables, checkboxes | Public domain |

Each needs a golden ground truth JSON in `benchmarks/pdf/golden/`.

**Files**: `benchmarks/pdf/generate_test_pdfs.py`, `benchmarks/pdf/golden/*.json`

### 3. Multi-Model Benchmark Matrix

Automate running all models and producing a comparison table:

```bash
uv run benchmarks/pdf/eval_pdf.py --matrix  # Runs all configured models
```

Model tiers:
- **Cloud**: gemini-2.0-flash, gemini-3-flash-preview, claude-haiku-4-5
- **Local**: ollama:granite3.2-vision, ollama:MedAIBase/PaddleOCR-VL:0.9b

Output: JSON + markdown table with per-model scores, times, and cost estimates.

**Files**: `benchmarks/pdf/eval_pdf.py`

### 4. PDF Metadata Extraction Improvements

Current `parsePdfMetadata` uses AI to extract page count. For the two-stage pipeline, we should also extract:
- Document title from first heading
- Author from PDF metadata (if available)
- Page count from PDF structure (not AI)

**Files**: `docparse/services/direct_ai_parser.ail`

## Success Criteria

- granite3.2-vision: >50% mean PDF benchmark score
- PaddleOCR-VL: >40% mean PDF benchmark score
- gemini-2.0-flash: maintains >90% (no regression)
- 10+ diverse PDF test files with golden outputs
- `--matrix` flag produces comparison table

## Dependencies

- AILANG runtime (no language changes needed)
- Ollama models installed locally

## Risks

- Heuristic structuring may be too naive for complex layouts
- Two-stage adds latency (two AI calls instead of one)
- Real-world PDFs are much harder than synthetic test files
