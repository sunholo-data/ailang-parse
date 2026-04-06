# OfficeDocBench

**The first benchmark for Office structural document parsing.**

Every existing document parsing benchmark (OmniDocBench, READOC, SCORE-Bench, DP-Bench) evaluates PDF extraction only. No benchmark measures whether a parser can extract **structural Office features**: track changes, comments, merged cells, headers/footers, text boxes, speaker notes, footnotes, or document metadata from DOCX, PPTX, XLSX, ODT, ODP, and ODS files.

OfficeDocBench fills this gap.

## Dataset

**69 test files** across **10 formats**, sourced from real-world test suites (54 core + 15 challenge):

| Format | Files | Sources |
|--------|-------|---------|
| DOCX   | 29    | Pandoc, Apache POI, original, 15 challenge files |
| PPTX   | 8     | Pandoc, Apache POI, python-pptx, Unstructured, challenge |
| XLSX   | 6     | Pandoc, Apache POI, XlsxWriter, Unstructured, challenge |
| ODT    | 6     | LibreOffice, OfficeParser, original |
| ODP    | 2     | OfficeParser, original |
| ODS    | 4     | LibreOffice, OfficeParser, original |
| EPUB   | 3     | Project Gutenberg, original |
| HTML   | 5     | Pandoc, original, challenge |
| CSV    | 2     | Original |
| MD     | 3     | Pandoc, original |
| TSV    | 1     | Original |

### Feature Distribution (17 features)

| Feature | Files | Notes |
|---------|-------|-------|
| Tables | 36 | Including merged cell detection |
| Headings | 30 | With level distribution scoring |
| Lists | 15 | Ordered/unordered + nesting depth |
| Images | 8 | |
| Section breaks | 8 | ECMA-376 §17.6 (aspirational) |
| Sheets | 5 | With sheet name accuracy |
| Track changes | 3 | With author attribution |
| Headers/footers | 3 | |
| Text boxes | 2 | |
| Comments | 2 | With comment range accuracy §17.13.1 |
| Footnotes/endnotes | 1 | Aspirational |
| Equations | 1 | ECMA-376 §22.1 (aspirational) |
| Field codes | 1 | ECMA-376 §17.16 (aspirational) |
| Bookmarks | 1 | ECMA-376 §17.13.6 (aspirational) |
| Hyperlinks | 1 | Aspirational |
| Styles | 1 | Aspirational |

## Evaluation Protocol

### Ground Truth

Each test file has a parser-independent ground truth annotation (`ground_truth/*.json`) documenting which structural features are present and their expected values. Ground truth was auto-generated from validated golden outputs and follows `schema/ground_truth.schema.json`.

Features use `null` for "not applicable to this format" and `{"present": false}` for "applicable but absent in this file".

### Adapter Interface

Parsers implement the `OfficeDocBenchAdapter` interface:

```python
from adapters.base_adapter import OfficeDocBenchAdapter

class MyParserAdapter(OfficeDocBenchAdapter):
    def name(self) -> str: ...
    def version(self) -> str: ...
    def parse(self, filepath: Path) -> dict: ...
    def supported_formats(self) -> set[str]: ...
```

The `parse()` method returns a dict matching `schema/adapter_output.schema.json` — a flat structure with lists for each feature type (headings, tables, track_changes, comments, etc.).

### Metrics

Seven scoring dimensions, each in [0, 1]:

| Metric | Weight | Description |
|--------|--------|-------------|
| **Feature Detection** | 0.15 | Binary: did the parser detect each of 17 features? Includes aspirational features (equations, bookmarks, fields, section breaks) |
| **Structural Recall** | 0.20 | How completely were features extracted? (count accuracy + type matching) |
| **Structural Quality** | 0.15 | Heading level distribution, TC author attribution, comment text matching, list numbering accuracy (§17.9), table merge span accuracy (§18.3.1.55), heading text match, section break detection (§17.6), comment range accuracy (§17.13.1) |
| **Content Fidelity** | 0.15 | Key phrase recall, paragraph count, element ordering (LCS), hyperlink extraction, style preservation, equation text (§22.1), field display text (§17.16), footnote text, bookmark detection (§17.13.6) |
| **Text Jaccard** | 0.10 | Word-level Jaccard similarity with ground truth |
| **Element Count** | 0.15 | `1 - |actual - expected| / max(actual, expected, 1)` per element type (9 types) |
| **Metadata** | 0.10 | Exact match on title, author, created, modified + sheet name accuracy |

**Composite score** = weighted average. **Coverage-Adjusted** = Composite × (files parsed / total files).

Aspirational sub-dimensions within Structural Quality and Content Fidelity intentionally lower scores when ECMA-376 spec features aren't yet implemented, creating transparent roadmap targets.

## Usage

```bash
# Evaluate AILANG Parse (uses golden outputs, instant)
uv run benchmarks/officedocbench/eval_officedocbench.py

# Evaluate AILANG Parse (re-parse files)
uv run benchmarks/officedocbench/eval_officedocbench.py --live

# Evaluate all installed adapters
uv run benchmarks/officedocbench/eval_officedocbench.py --all

# Single adapter
uv run benchmarks/officedocbench/eval_officedocbench.py --adapter unstructured

# Filter by format
uv run benchmarks/officedocbench/eval_officedocbench.py --format docx

# Output formats
uv run benchmarks/officedocbench/eval_officedocbench.py --json
uv run benchmarks/officedocbench/eval_officedocbench.py --latex

# Regenerate ground truth from golden files
uv run benchmarks/officedocbench/annotate.py
```

## Results

**Run date**: 2026-04-06

### Composite Scores (8 Parsers)

| Tool | Files | Coverage | Composite | Adjusted | Feat. Det. | Struct. Quality | Content Fidelity | Metadata |
|------|-------|----------|-----------|----------|------------|-----------------|------------------|----------|
| **AILANG Parse** | 69/69 | **100%** | **93.9%** | **93.9%** | 91.9% | 95.3% | 81.4% | 99.6% |
| Raw OOXML | 43/69 | 62% | 84.4% | 52.6% | 82.0% | 80.3% | 68.1% | 100.0% |
| MarkItDown | 24/69 | 35% | 78.6% | 27.3% | 95.8% | 82.1% | 65.4% | 33.3% |
| Pandoc | 45/69 | 65% | 74.0% | 48.2% | 75.7% | 81.2% | 66.1% | 24.4% |
| Kreuzberg | 66/69 | 96% | 71.1% | 68.0% | 66.3% | 63.9% | 61.0% | 86.2% |
| Docling | 42/69 | 61% | 63.3% | 38.5% | 61.3% | 71.5% | 61.4% | 2.4% |
| Unstructured | 37/69 | 54% | 60.9% | 32.6% | 60.4% | 61.1% | 62.3% | 0.0% |

Coverage-Adjusted = Composite × (files parsed / total files). AILANG Parse is the only tool with 100% format coverage.

### Per-Format Breakdown

| Format | AILANG Parse | Raw OOXML | Pandoc | Kreuzberg | MarkItDown | Docling | Unstructured |
|--------|-------------|-----------|--------|-----------|------------|---------|--------------|
| DOCX | 90.9% (29) | 82.4% (29) | 69.0% (29) | 73.8% (29) | — | 59.7% (28) | 59.8% (29) |
| PPTX | 94.4% (8) | 89.1% (8) | — | 34.1% (8) | 70.2% (8) | 67.7% (8) | 64.8% (8) |
| XLSX | 96.3% (6) | 88.2% (6) | — | 95.1% (6) | 84.7% (6) | 74.0% (6) | — |
| ODT | 92.6% (6) | — | 70.9% (5) | 73.8% (6) | — | — | — |
| ODP | 97.7% (2) | — | — | — | — | — | — |
| ODS | 100% (4) | — | — | 72.2% (3) | — | — | — |
| EPUB | 98.5% (3) | — | 98.0% (3) | 71.6% (3) | 74.8% (3) | — | — |
| HTML | 94.2% (5) | — | 87.0% (5) | 72.9% (5) | 82.5% (5) | — | — |
| CSV | 100% (2) | — | — | 85.8% (2) | 89.8% (2) | — | — |
| MD | 97.7% (3) | — | 81.0% (3) | 72.1% (3) | — | — | — |

### Feature Detection Heatmap (17 Features)

| Feature | AILANG Parse | Raw OOXML | Pandoc | Kreuzberg | MarkItDown | Unstructured | Docling |
|---------|-------------|-----------|--------|-----------|------------|--------------|---------|
| headings | **30/30** | 21/21 | 22/23 | 24/29 | 9/9 | 20/21 | 20/21 |
| tables | **36/36** | 16/16 | 18/18 | 29/34 | 17/17 | 9/10 | 13/15 |
| **track_changes** | **3/3** | 2/3 | 3/3 | 0/3 | — | 0/3 | 0/3 |
| **comments** | **2/2** | 2/2 | 0/2 | 0/2 | — | 0/2 | 0/2 |
| **headers_footers** | **3/3** | 2/2 | 0/3 | 2/3 | — | 1/2 | 0/2 |
| **text_boxes** | **2/2** | 1/2 | 0/2 | 0/2 | — | 0/2 | 0/2 |
| images | 7/8 | 3/4 | 5/5 | 3/7 | 2/3 | 0/4 | 2/4 |
| lists | **15/15** | 1/4 | 11/12 | 8/13 | 4/4 | 4/4 | 1/4 |
| sheets | 4/5 | 1/1 | — | 4/4 | 0/1 | — | 0/1 |
| equations (§22.1) | **1/1** | 0/1 | 0/1 | 0/1 | — | 0/1 | 0/1 |
| fields (§17.16) | **1/1** | 1/1 | 0/1 | 1/1 | — | 0/1 | 0/1 |
| *footnotes* | 0/1 | 0/1 | 0/1 | 0/1 | — | 0/1 | 0/1 |
| *hyperlinks* | 0/1 | 0/1 | 0/1 | 0/1 | — | 0/1 | 0/1 |
| *styles* | 0/1 | 0/1 | 0/1 | 0/1 | — | 0/1 | 0/1 |
| *bookmarks (§17.13.6)* | 0/1 | 0/1 | 0/1 | 0/1 | — | 0/1 | 0/1 |
| *section_breaks (§17.6)* | 0/8 | 0/8 | 0/8 | 0/8 | — | 0/8 | 0/8 |

*Italic* = aspirational features that no tool handles yet. **Bold** = AILANG Parse leads or ties for best.

### Aspirational Roadmap Targets

These ECMA-376 spec features intentionally lower every tool's score — they represent the next frontier:

| Feature | Spec Reference | Impact | What's Needed |
|---------|---------------|--------|---------------|
| Footnotes/endnotes | — | 0/1 detection | Extract footnote content as separate blocks |
| Hyperlink URLs | §17.16.22 | 0/1 detection | Surface URL + display text in output |
| Style preservation | §17.3.2 | 0/1 detection | Expose bold/italic/underline on text elements |
| Bookmark detection | §17.13.6 | 0/1 detection | Detect and surface bookmark names |
| Section breaks | §17.6 | 0/8 detection | Surface section break markers in output |
| Comment ranges | §17.13.1 | Quality score | Link comments to annotated text spans |
| List numbering | §17.9 | Quality score | Preserve ordered/unordered + nesting depth |
| Table merge spans | §18.3.1.55 | Quality score | Cell-level merge span comparison |

## Adding Your Tool

1. Create `adapters/your_parser_adapter.py` implementing `OfficeDocBenchAdapter`
2. Add a loader in `eval_officedocbench.py:load_adapter()`
3. Run: `uv run benchmarks/officedocbench/eval_officedocbench.py --adapter your_parser`

See `adapters/unstructured_adapter.py` for a minimal example.

## File Structure

```
benchmarks/officedocbench/
  README.md                      # This file
  schema/
    ground_truth.schema.json     # Ground truth format spec
    adapter_output.schema.json   # Adapter output format spec
  ground_truth/                  # 69 annotated ground truth files
  adapters/
    base_adapter.py              # Abstract interface
    docparse_adapter.py          # AILANG Parse reference implementation
    unstructured_adapter.py      # Unstructured.io
    docling_adapter.py           # IBM Docling
    llamaparse_adapter.py        # LlamaIndex LlamaParse
    markitdown_adapter.py        # Microsoft MarkItDown
    kreuzberg_adapter.py         # Kreuzberg (Rust)
    pandoc_adapter.py            # Pandoc (Haskell)
    ooxml_adapter.py             # Raw OOXML (stdlib)
  eval_officedocbench.py         # Main evaluation script
  scoring.py                     # 7-metric scoring (ECMA-376 spec-driven)
  report.py                      # Report generation (markdown, JSON, LaTeX)
  annotate.py                    # Ground truth generator
  enrich_gt.py                   # GT enrichment from golden outputs
  results/                       # Per-tool results
```

## License

- Benchmark data and ground truth: CC-BY-4.0
- Evaluation code: Apache-2.0
- Test files: see `benchmarks/SOURCES.md` for per-file attribution

## Citation

```bibtex
@misc{officedocbench2026,
  title={OfficeDocBench: A Benchmark for Office Structural Document Parsing},
  author={AILANG Parse Contributors},
  year={2026},
  url={https://github.com/sunholo-data/docparse}
}
```
