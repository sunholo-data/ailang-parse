# Design: External Benchmark Integration

**Status**: Phase 1 Complete (OmniDocBench score obtained)
**Priority**: High
**Target**: v0.2.0

## Landscape Analysis

Every major document parsing benchmark is PDF-only:

| Benchmark | Venue | Formats | Metrics | Key Feature |
|-----------|-------|---------|---------|-------------|
| **OmniDocBench** | CVPR 2025 | PDF→MD | Edit dist, TEDS, CDM | 1,355 pages, 9 doc types, leaderboard |
| **READOC** | ACL 2025 | PDF→MD | Edit dist, BLEU | 2,233 docs from arXiv/GitHub |
| **SCORE-Bench** | Unstructured | PDF→text | ChrF++, content fidelity | Enterprise docs, hallucination metric |
| **DP-Bench** | Upstage | PDF→layout | mAP, 12 element types | Layout detection focus |

**No benchmark covers Office structural extraction** (DOCX, PPTX, XLSX) — track changes, comments, headers/footers, merged cells, text boxes, metadata. This is DocParse's unique strength.

## Two-Pronged Strategy

### Part A: Run OmniDocBench (PDF — compare with industry)

Get an official score for DocParse+Gemini on the standard PDF benchmark.

**How OmniDocBench works:**
- Input: PDF pages as images
- Parser produces: Markdown files (one .md per page)
- Evaluation: Compare markdown against annotated ground truth
- Metrics: Text Edit Distance, Table TEDS, Formula CDM, Reading Order

**DocParse adapter needed:**
1. Convert DocParse JSON block output → Markdown
2. Handle page-by-page output (OmniDocBench evaluates per-page)
3. Map Block ADT types to markdown elements

**Actual results (2026-03-11, Demo 18 pages):**

| Category | Metric | DocParse+Gemini 2.0 Flash |
|----------|--------|---------------------------|
| Text Block | Edit Distance (page avg) | **0.186** (lower=better) |
| Table | TEDS | **0.787** (higher=better) |
| Table | TEDS Structure Only | **0.848** |
| Table | Edit Distance (page avg) | **0.167** |
| Reading Order | Edit Distance (page avg) | **0.170** |

- Strong on notes (TEDS 0.97), exam papers (0.94), books (0.87)
- Weak on colorful textbooks (TEDS 0.25), newspapers (text ED 0.48)
- Reading order excellent on single column (0.07), struggles on newspaper layout (0.48)
- Full results in `benchmarks/omnidocbench/results/gemini-2.0-flash/RESULTS.md`

### Part B: Create OfficeDocBench (Office — own the category)

The first published benchmark for Office structural extraction. No competitor has this.

**Dimensions to evaluate:**

| Feature | DOCX | PPTX | XLSX |
|---------|------|------|------|
| Text extraction | Body text, paragraphs | Slide text, shapes | Cell content |
| Headings | Heading styles 1-6 | Slide titles | — |
| Tables | Row/col, headers | Shape tables | Sheet data |
| **Merged cells** | Row/col spans | — | Merged regions |
| **Track changes** | Insert/delete/move | — | — |
| **Comments** | Author, date, text | — | — |
| **Headers/footers** | Per-section | — | — |
| **Footnotes/endnotes** | Content, references | — | — |
| **Speaker notes** | — | Per-slide notes | — |
| **Text boxes** | Floating content | Shape text | — |
| **Images** | Presence detection | Presence detection | — |
| **Metadata** | Title, author, dates | Slide count | Sheet names |

**Evaluation metrics:**
- **Structural Recall**: What fraction of structural features were detected (scored per-feature)
- **Text Jaccard**: Word-level overlap with ground truth
- **Element Count Accuracy**: Correct number of headings, tables, etc.
- **Feature Detection Rate**: Binary — did the parser find track changes? Comments? Headers?
- **Metadata Accuracy**: Exact match on title, author, page count

**Test corpus (18 existing + new):**
We already have 18 golden test files. Formalize these as the benchmark dataset with:
- Documented ground truth per structural feature
- Scoring rubric
- Adapter interface for competitors to plug in

## Implementation Plan

### Phase 1: OmniDocBench Integration — COMPLETE

1. ~~Clone OmniDocBench repo, install deps~~ ✓
2. ~~Download demo dataset (18 pages)~~ ✓
3. ~~Write `benchmarks/omnidocbench/adapter.py`~~ ✓ — runs DocParse (via AILANG) on pages, outputs .md
4. ~~Write markdown emitter: Block ADT → clean markdown~~ ✓ — `blocks_to_markdown()` + `table_to_html()`
5. ~~Add `parseDocumentImage` to AILANG pipeline~~ ✓ — in `direct_ai_parser.ail`
6. ~~Run evaluation, report score~~ ✓ — Text ED 0.186, Table TEDS 0.787, Reading Order ED 0.170
7. TODO: Compare against leaderboard (need other tools' scores on same demo subset)
8. TODO: Run on full dataset (1,355 pages)

### Phase 2: OfficeDocBench Formalization

1. Create `benchmarks/officedocbench/` directory structure
2. Define ground truth JSON schema for all structural features
3. Convert existing 18 golden files to OfficeDocBench format
4. Write evaluation script with per-feature scoring
5. Write adapter interface for competitors (Docling, Unstructured, LlamaParse)
6. Run all competitors, publish comparison
7. Write up as publishable benchmark spec

## File Structure

```
benchmarks/
├── omnidocbench/           # OmniDocBench integration
│   ├── adapter.py          # DocParse → markdown converter
│   ├── run_omnidocbench.py # Evaluation runner
│   └── results/            # Score outputs
├── officedocbench/         # Our benchmark (new)
│   ├── README.md           # Benchmark specification
│   ├── ground_truth/       # Annotated feature expectations per file
│   ├── eval_office.py      # Evaluation script
│   └── results/            # Comparison outputs
└── ...existing benchmarks...
```

## Success Criteria

- OmniDocBench score reported for DocParse+Gemini (target: >85 overall)
- OfficeDocBench running with 18+ test files
- At least 2 competitors evaluated on OfficeDocBench
- Published comparison showing DocParse's structural extraction advantage
