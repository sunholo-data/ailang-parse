# DocParse v0.5.0 — Ecosystem & Competitor Benchmarks

**Status**: Implemented (OfficeDocBench published, competitor adapters done, OmniDocBench integrated)
**Theme**: Prove DocParse's value with published benchmark results and integrations

## Goals

1. Run comprehensive competitor benchmarks and publish results
2. Python SDK wrapper for DocParse binary
3. Integration guides for common workflows (LangChain, LlamaIndex, Haystack)

## Features

### 1. Competitor Benchmark Report

Run all three competitor adapters on the full test corpus and publish a comparison:

| Competitor | Strengths | Weaknesses vs DocParse |
|-----------|-----------|----------------------|
| **Docling** (IBM) | Good PDF layout analysis, open source | Misses track changes, comments, headers/footers, merged cells |
| **LlamaParse** (LlamaIndex) | Good PDF/table extraction, cloud API | Misses Office structural metadata, requires API key, per-page cost |
| **Unstructured** | Broad format support, mature ecosystem | Slow, heavy dependencies, misses Office structural features |

**Deliverable**: Published markdown report in `benchmarks/results/` with:
- Per-file comparison tables
- Feature gap matrix
- Speed comparison (ms per file)
- Cost comparison (API models)

**Files**: `benchmarks/competitors/run_all.py`, `benchmarks/results/`

### 2. OmniDocBench Subset

Integrate a subset of OmniDocBench (or similar public benchmark) for PDF evaluation:
- 50-100 diverse PDFs with ground truth
- Standard metrics (text extraction accuracy, table detection F1, layout analysis)
- Compare DocParse+Gemini vs DocParse+Ollama vs competitors

This positions DocParse in the broader document parsing landscape.

**Files**: `benchmarks/pdf/omnidocbench/`

### 3. Python SDK Wrapper

Wrap the Go binary (v0.4.0) in a Python package for easy integration:

```python
from ailang_parse import parse

doc = parse("report.docx")
for block in doc.blocks:
    if block.type == "table":
        print(block.headers, block.rows)
```

Features:
- Subprocess wrapper around Go binary
- Pydantic models for Block ADT
- Streaming support for large documents
- Async support

**Files**: New `python/` directory with `docparse` package

### 4. Integration Guides

Show how to use DocParse with popular frameworks:

- **LangChain**: Custom document loader
- **LlamaIndex**: Custom reader/parser
- **Haystack**: Custom converter
- **Direct**: JSON output → your pipeline

**Files**: `docs/integrations/`

### 5. WASM Browser Demo Updates

Sync the demos repo with latest parser improvements and publish updated browser demo showing:
- Office parsing with comment/track change visualization
- Side-by-side comparison with competitor output
- Live model selection for PDF extraction

**Files**: Sync to `sunholo-data/ailang-demos`

## Success Criteria

- Published benchmark report with 3+ competitors
- DocParse wins on Office structural features
- Python package installable via `pip install ailang-parse`
- At least one integration guide (LangChain recommended — largest ecosystem)
- OmniDocBench subset shows competitive PDF scores with Gemini backend

## Dependencies

- v0.4.0 Go binary (for Python SDK)
- Competitor libraries installed (`uv pip install docling llama-parse unstructured`)
- LLAMA_CLOUD_API_KEY for LlamaParse benchmarks
- OmniDocBench dataset access

## Risks

- Competitor APIs may change or require paid tiers
- OmniDocBench ground truth format may not align with our metrics
- Python SDK maintenance burden (keep in sync with Go binary)
