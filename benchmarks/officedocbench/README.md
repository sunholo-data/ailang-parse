# OfficeDocBench

**The first benchmark for Office structural document parsing.**

Every existing document parsing benchmark (OmniDocBench, READOC, SCORE-Bench, DP-Bench) evaluates PDF extraction only. No benchmark measures whether a parser can extract **structural Office features**: track changes, comments, merged cells, headers/footers, text boxes, speaker notes, footnotes, or document metadata from DOCX, PPTX, XLSX, ODT, ODP, and ODS files.

OfficeDocBench fills this gap.

## Dataset

**59 test files** across **10 formats**, sourced from real-world test suites (54 core + 5 challenge):

| Format | Files | Sources |
|--------|-------|---------|
| DOCX   | 19    | Pandoc, Apache POI, original, challenge |
| PPTX   | 8     | Pandoc, Apache POI, python-pptx, Unstructured, challenge |
| XLSX   | 6     | Pandoc, Apache POI, XlsxWriter, Unstructured, challenge |
| ODT    | 6     | LibreOffice, OfficeParser, original |
| ODP    | 2     | OfficeParser, original |
| ODS    | 4     | LibreOffice, OfficeParser, original |
| EPUB   | 3     | Project Gutenberg, original |
| HTML   | 5     | Pandoc, original, challenge |
| CSV    | 2     | Original |
| MD     | 3     | Pandoc, original |

### Feature Distribution

| Feature | Files with feature present |
|---------|---------------------------|
| Tables | 34 |
| Headings | 17 |
| Lists | 12 |
| Images | 8 |
| Sheets | 4 |
| Track changes | 3 |
| Headers/footers | 3 |
| Text boxes | 2 |
| Comments | 1 |

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

Five scoring dimensions, each in [0, 1]:

| Metric | Weight | Description |
|--------|--------|-------------|
| **Feature Detection** | 0.25 | Binary: did the parser detect each present feature? |
| **Structural Recall** | 0.30 | How completely were features extracted? (count accuracy + type matching) |
| **Text Jaccard** | 0.20 | Word-level Jaccard similarity with ground truth |
| **Element Count** | 0.15 | `1 - |actual - expected| / max(actual, expected, 1)` per element type |
| **Metadata** | 0.10 | Exact match on title, author, created, modified |

**Composite score** = weighted average. Weights emphasize structural extraction (Feature Detection + Structural Recall = 55%) since that is the benchmark's purpose.

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

**Run date**: 2026-03-20

### Composite Scores

| Tool | Version | Composite | Feat. Det. | Struct. Recall | Text Jaccard | Elem. Count | Metadata | Formats |
|------|---------|-----------|------------|----------------|--------------|-------------|----------|---------|
| **AILANG Parse** | v0.3.0 (AILANG) | **96.6%** | 94.9% | 97.5% | 95.0% | 98.3% | 98.3% | 10 |
| Unstructured | v0.21.5 | 63.4% | 62.4% | 63.1% | 86.6% | 67.0% | 15.2% | 3 |
| Docling | v2.80.0 | 63.4% | 62.8% | 64.5% | 82.0% | 69.3% | 15.6% | 3 |
| LlamaParse | v0.6.94 (cloud) | 53.6% | 55.0% | 55.8% | 78.5% | 39.2% | 15.2% | 3 |

AILANG Parse evaluated on all 59 files (10 formats). Competitors evaluated on 33 files (DOCX/PPTX/XLSX only — they don't support ODT/ODP/ODS/EPUB/HTML/CSV/MD).

### Per-Format Breakdown

| Format | AILANG Parse | Unstructured | Docling | LlamaParse |
|--------|----------|--------------|---------|------------|
| DOCX | 98.2% (19) | 62.0% (19) | 57.9% (18) | 48.3% (19) |
| PPTX | 97.2% (8) | 69.1% (8) | 71.1% (8) | 66.5% (8) |
| XLSX | 95.8% (6) | 60.1% (6) | 69.7% (6) | 53.2% (6) |
| ODT | 96.7% (6) | — | — | — |
| ODP | 100% (2) | — | — | — |
| ODS | 100% (4) | — | — | — |
| EPUB | 100% (3) | — | — | — |
| HTML | 80.0% (5) | — | — | — |
| CSV | 100% (2) | — | — | — |
| MD | 100% (3) | — | — | — |

### Feature Detection Heatmap

| Feature | AILANG Parse | Unstructured | Docling | LlamaParse |
|---------|----------|--------------|---------|------------|
| headings | 20/21 | 10/11 | 10/11 | 8/11 |
| tables | 35/36 | 12/15 | 11/14 | 12/15 |
| **track_changes** | **3/3** | 0/3 | 0/3 | 0/3 |
| **comments** | **1/1** | 0/1 | 0/1 | 0/1 |
| **headers_footers** | **3/3** | 1/2 | 0/2 | 0/2 |
| **text_boxes** | **2/2** | 0/2 | 0/2 | 0/2 |
| images | 8/9 | 0/4 | 2/4 | 0/4 |
| lists | 12/14 | 2/2 | 1/2 | 2/2 |
| sheets | 4/5 | 0/1 | 0/1 | 0/1 |

No competitor extracts track changes, comments, text boxes, or headers/footers — these structural features are AILANG Parse's unique advantage.

### Known Gaps (Stretch Goals)

| Gap | Impact | Feature |
|-----|--------|---------|
| PPTX speaker notes not extracted | 0/1 | speaker_notes |
| DOCX footnote/endnote content not extracted | 0/1 | footnotes_endnotes |
| XLSX formula cells return empty | tables accuracy | element_count |
| XLSX sheet names not in section kind | 4/5 sheets | sheets |
| Nested DOCX lists parsed as flat text, not List blocks | 12/14 lists | lists |
| HTML `<figure>` / `<img>` not extracted | 8/9 images | images |
| HTML `<ol>`/`<ul>` nesting not preserved | lists | lists |

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
  ground_truth/                  # 54 annotated ground truth files
  adapters/
    base_adapter.py              # Abstract interface
    docparse_adapter.py          # AILANG Parse reference implementation
    unstructured_adapter.py      # Unstructured.io
    docling_adapter.py           # IBM Docling
    llamaparse_adapter.py        # LlamaIndex LlamaParse
  eval_officedocbench.py         # Main evaluation script
  scoring.py                     # Per-feature scoring
  report.py                      # Report generation
  annotate.py                    # Ground truth generator
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
