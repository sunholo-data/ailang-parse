# OfficeDocBench v2.1

OfficeDocBench evaluates document parsers on **87 files across 11 formats**. It measures structural fidelity as well as text extraction. The corpus retains the original 69 cases and adds 18 Office regression fixtures. Those 18 fixtures were written by the AILANG Parse team alongside fixes to its parser, so they cover features AILANG Parse was built to handle; about half of all 87 files were authored by the team, and the rest come from the Pandoc, Apache POI, LibreOffice, Unstructured and other public test suites (`benchmarks/SOURCES.md`). `corpus.json` declares the exact case set; extra files downloaded by CI never silently change the public comparison. Results from v1 use different scoring and must not be compared directly with v2 percentages.

## What changed

The reference adapter now preserves comment anchors and sheet attribution, logical table cells, formulas, colours on empty cells, list depth, inline formatting, bookmarks, breaks, and slide/notes relationships. Competitor adapters map the same evidence when their output exposes it. They never reopen the input document to fill in features missing from a provider's response. Raw OOXML is explicitly a local reference parser, not an external product.

## Where the ground truth comes from

Every scored value is computed from the source document by a reader that shares no code or output with AILANG Parse: Python's `zipfile`, `xml.etree` and `csv`, BeautifulSoup (`html.parser`) and markdown-it-py. Nothing is taken from the `.ail` parsers, from `benchmarks/office/golden/`, or from `annotate.py`/`enrich_gt.py`. Those two scripts produced the original 69 annotations from AILANG Parse's own output. They are kept for history and are not part of the maintenance path. A value that depends on one parser's conventions rather than on the document is removed, and the scorer then skips it.

Two oracles write the files in `ground_truth/`, and both run with `--check` in CI:

- `build_structure_truth.py` writes the v2 `structure` assertions for 49 DOCX/PPTX/XLSX cases from the Office XML and records the source SHA-256 under `verification`.
- `audit_legacy_truth.py`, with its readers in `source_truth.py`, rebuilds the legacy `features`, `full_text_words` and metadata for all 69 original cases. Each case gets a `legacy_verification` record. It names the reader and the source SHA-256, lists the recomputed fields, and lists each field that is no longer scored and why. `verified: true` means every scored value in the case came from these readers.

| Field | Source reader | Formats | Status |
|---|---|---|---|
| `full_text_words` | All content text, tokenized with the scorer's own tokenizer: body paragraphs, table cells, slide shapes, sheet cells, headers/footers, footnotes/endnotes, comments, speaker notes, text boxes, and both inserted and deleted tracked text. Each OMML math run counts as its own word source. Excluded: metadata, sheet and slide names, alt text, link targets, field instructions, chart and SmartArt text. Spreadsheet numbers count only in General format, as Excel shows them. | all 11 | recomputed |
| `text.key_phrases` | Legacy phrases kept only where the phrase occurs verbatim (case and whitespace normalised) in one source paragraph | all | filtered (191 of 209 kept) |
| `text.paragraph_count` | — | all | removed: it depends on parser segmentation |
| `element_order` | — | all | removed: a reading order in one parser's block granularity |
| `headings` | HTML/EPUB `h1`–`h6`; Markdown ATX/setext headings; ODT/ODP `text:h` with `text:outline-level`; DOCX paragraph or style-chain `w:outlineLvl`, a `heading N` style name, or an undefined built-in `HeadingN` id (Title and Subtitle have no outline level and are not headings); PPTX title placeholders and ODP title frames (level 1) | docx, pptx, odt, odp, html, epub, md | recomputed |
| `tables.count`, `has_merged_cells` | `w:tbl` (`gridSpan`/`vMerge`), `a:tbl` (`gridSpan`/`rowSpan`/`hMerge`/`vMerge`), `table:table` (spanned attributes), HTML `<table>` (`colspan`/`rowspan`), GFM pipe tables and Pandoc grid tables, one table per CSV/TSV file. Nested tables count. | docx, pptx, odt, odp, html, epub, md, csv, tsv | recomputed |
| `tables` (spreadsheets) | — | xlsx, ods | removed: how many tables a worksheet holds is a parser convention. v2 `table_cells` assertions cover XLSX cells. |
| `tables.total_rows` | — | all | removed: "rows excluding header" is a convention |
| `lists` | Top-level `<ol>`/`<ul>`, Markdown lists and `text:list` elements with text. Nested lists add depth (`max_depth`, `has_nested`), not extra lists. Ordered/unordered counts are given only when every list's type is declared. | odt, html, epub, md | recomputed |
| `lists` | — | docx, pptx, odp | removed: WordprocessingML has no list container, slide bullets come from masters, and ODP wraps each outline paragraph in its own list. v2 `list_items` assertions cover DOCX levels. |
| `images` | DOCX `a:blip`/`v:imagedata` pointing to an embedded image part (not under `mc:Fallback`); PPTX `p:pic` on slides; XLSX drawing pictures; ODF frames holding an embedded `draw:image` (not an object preview); HTML/EPUB `<img>`; Markdown images | all but csv/tsv | recomputed |
| `comments` (count, authors, texts, ranges) | `word/comments.xml`; ranges from `commentRangeStart`/`End` | docx | recomputed |
| `track_changes` | `w:ins`/`w:del`/`w:moveFrom`/`w:moveTo` with text, and ODF `text:changed-region` | docx, odt | recomputed |
| `headers_footers` | Header/footer parts referenced by a `w:sectPr`, and the master pages an ODT uses, counted when they contain text | docx, odt | recomputed |
| `footnotes_endnotes` (count, texts) | `w:footnote`/`w:endnote` of type normal (separators excluded); ODF `text:note` | docx, odt | recomputed |
| `speaker_notes` | Notes slides/`presentation:notes` with text, excluding number, date, header and footer placeholders | pptx, odp | recomputed |
| `text_boxes` | `w:txbxContent` with text, counted once (not again under `mc:Fallback`); ODF frames holding a `draw:text-box` | docx, odt | recomputed |
| `text_boxes` | — | pptx, odp | removed: every slide shape is a text frame |
| `metadata` | OOXML `docProps/core.xml` (`dc:title`, `dc:creator`, `dcterms:created`, `dcterms:modified`); ODF `meta.xml` (`dc:title`; `meta:creation-date` for created, `dc:date` for modified, author only when `meta:initial-creator` exists and agrees with `dc:creator`); HTML `<title>`/`<meta name=author>`; EPUB OPF `dc:title`, a single `dc:creator`, `dcterms:modified`. Fields the source does not set are not asserted. | all with metadata | recomputed |
| `sheets.names` | `xl/workbook.xml` sheet order; ODS `table:table` order | xlsx, ods | recomputed |
| `section_breaks` | `w:sectPr` inside a paragraph's `w:pPr`. The body's final `w:sectPr` is not a break. | docx (8 cases) | recomputed |
| `bookmarks`, `hyperlinks`, `fields` | `w:bookmarkStart` names (hidden `_` names excluded); `w:hyperlink` text plus relationship target or `#anchor`; cached field results with their instruction type | docx (1 case each) | recomputed |
| `equations` | OMML has no text form. A formula is asserted only when it contains no layout elements (fractions, scripts, radicals, ...), joined from its runs. | docx (1 case, 1 of 4 formulas) | recomputed in part |
| `styles` | — | docx (1 case) | removed: counts run segmentation. v2 `runs` assertions check explicit formatting instead. |

The v2 `structure` assertions follow the same rule. `breaks` records a `section-break` for a `w:sectPr` in paragraph properties and a `page-break` for an explicit `w:br w:type="page"` (not `w:lastRenderedPageBreak`). Only `challenge_page_breaks.docx` has either. Until v2.1 every DOCX asserted a section break for the closing body `w:sectPr`, which only AILANG Parse emitted. `runs` assert only formatting a run switches on: bold, italic, underline, strike, a colour other than black, and a non-baseline vertical alignment. An explicit "off" or `#000000` is not asserted, because a parser that reports no formatting already implies it. Twelve DOCX cases had no assertion other than the closing section break or default-colour runs. They now carry legacy fields only.

The rebuild corrected values that disagreed with the source. Examples: `challenge_bookmarks.docx` text words copied from another file; comment ranges in `comments.docx` and `challenge_comment_ranges.docx` that extended past `commentRangeEnd`; ODF creation dates taken from `dc:date` (the last-save date) in 8 files; footnotes missing in `pandoc_notes.docx`, `poi_footnotes.docx` and `officeparser.odt`; 8 text boxes counted twice through `mc:Fallback` in `docx-shapes.docx`; empty header/footer parts counted in `docx-hdrftr.docx`; one Pandoc grid table counted as four in `pandoc_planets.md`; and speaker notes or slide titles missed in `officeparser.odp` and `poi_sampleshow.pptx`. `truth_rebuild_v2_1.json` lists every changed value, with the old parser-derived value beside the new source-derived one.

Assertions are selective, not an exhaustive claim about every Office feature. For example, stored numbers are not treated as display-formatted text, theme/tint colours are not yet fully annotated here, and spreadsheet row-coordinate assertions stop at row 100 to avoid conflating original rows with parsers' collapsed large gaps. Image detection remains a count metric; lossless image bytes and document generation are covered by separate regression suites.

Five cases carry `input_profile: recovery`. `challenge_threaded_comments.xlsx` deliberately lacks workbook relationships. `challenge_footnotes.docx` references notes but has no note parts, so the note text cannot be recovered. `test.odt`, `test.ods` and `test.odp` are hand-made minimal ODF packages with only `mimetype`, the manifest, `content.xml` and `meta.xml`, and no `styles.xml`. Failures on these cases test recovery from a minimal package. They should not be described as failures on a fully formed document. Each result row carries the case's `input_profile`, and the summary lists `recovery_errors` per tool.

`allow_empty_output` marks cases whose body has no words, so a tool that correctly returns no text is scored rather than counted as an error: `lo_nested_table.odt` (empty paragraph, empty tables in the footer), `lo_table_styles.odt` (empty table), `lo_image_mimetype.odt` (one image), `python_pptx_slides.pptx` and `poi_table.pptx`. AILANG warning blocks remain in adapter diagnostics and do not count as source prose.

## Scoring

The seven original dimensions keep their relative weights: feature detection (15%), structural recall (20%), structural quality (15%), content fidelity (15%), text Jaccard (10%), element count (15%), and metadata (10%).

The eighth dimension, **structural fidelity**, uses the source-derived assertions. On annotated legacy cases, it receives 25% of the score and the seven legacy dimensions share 75%. The 18 added cases test only independently derived assertions, so their score is structural fidelity alone. Cases without new assertions retain the legacy weights. Metric aggregates omit explicitly inapplicable dimensions.

Structural assertions compare identity and position, not just word presence. Reading/container order uses a sequence alignment that penalizes missing, additional, or reordered entries. Other assertions require their declared properties to agree; missing evidence scores zero. Styled phrases can match within a coalesced run. Formula comparisons ignore the optional leading `=` used in spreadsheet display notation; missing or changed expressions still lose credit. An actual paragraph containing the target words does not establish a comment-to-target relationship.

The legacy scorer checks actual comment anchors and ordered sheet names. Legacy reading order and paragraph counts are no longer scored (see above); v2 assertions carry order where the source defines it (sheets, slides). Within a legacy dimension, a check whose ground truth was removed is skipped. A dimension left with no check at all scores 1.0 for every tool, as it did before v2.1 for cases without that feature. This narrows the spread between tools but favours none.

**Composite** is the mean over successfully parsed cases. **Coverage** is successful parses divided by all 87 cases. **Coverage-adjusted score** is composite times coverage; failed and unsupported cases contribute zero. Always publish coverage and error counts alongside scores. Per-feature structural results expose which new capabilities actually survive extraction.

## Run

```bash
# Reference parser, live by default
uv run benchmarks/officedocbench/eval_officedocbench.py

# Tests include saved pre-fix outputs and deliberately corrupted structures
uv run python -m unittest discover -s benchmarks/officedocbench/tests -v
python3 benchmarks/officedocbench/build_structure_truth.py --check
uv run python benchmarks/officedocbench/audit_legacy_truth.py --check

# Install the local comparison providers; install native pandoc separately
uv sync --extra competitors
uv run benchmarks/officedocbench/eval_officedocbench.py --all \
  --output-cache /tmp/officedocbench-output

# One provider, or one format
uv run benchmarks/officedocbench/eval_officedocbench.py --adapter docling
uv run benchmarks/officedocbench/eval_officedocbench.py --adapter pandoc --format docx

# Explicit reuse of matching converted output, not a hidden fallback
uv run benchmarks/officedocbench/eval_officedocbench.py --all \
  --output-cache /tmp/officedocbench-output --reuse-cache

# Rescore an identifiable live parse after a scoring/annotation correction
# This preserves its original parser/adapter revision and parse timestamps.
uv run benchmarks/officedocbench/rescore.py \
  --results-dir benchmarks/officedocbench/results \
  --output-cache /tmp/officedocbench-output
uv run benchmarks/officedocbench/eval_officedocbench.py --summarize
```

LlamaParse needs `LLAMA_CLOUD_API_KEY`, Extend needs `EXTEND_API_KEY` and Reducto needs `REDUCTO_API_KEY`; inject them into the process from your secret manager. Reducto takes the same raw-response switches as Extend: `REDUCTO_RAW_DIR` and `REDUCTO_REUSE_RAW=1`. For Extend, `EXTEND_RAW_DIR=DIR` keeps every parse-run response, and adding `EXTEND_REUSE_RAW=1` remaps stored responses without new requests (recorded as `raw_reuse` in provenance; its timings are mapping time, not parse latency). Standard non-premium mode is the default. `LLAMAPARSE_PREMIUM=1` is a different, more expensive run configuration and is recorded in provenance. Local adapters need their native dependencies, including Node.js/LibreOffice for LiteParse (plus `lit models pull ocria-nano` for `liteparse_ocria`) and Pandoc for the Pandoc adapter and some Unstructured formats.

`--golden` is diagnostic only and cannot produce a published summary. `--results-dir` supports isolated runs; only the canonical results directory mirrors a summary into `docs/data/officedocbench-summary.json`. `--summarize` rejects incompatible corpus revisions, filtered/incomplete case sets, duplicate cases, legacy results, and golden diagnostics.

## Reproducibility and failures

Each adapter result records its installed version, adapter hash, corpus/scorer hashes, source commit, toolchain, run timestamps, and configuration. Converted-output caches are keyed by provider version, adapter revision, and input bytes. Cached reads are not reported as fresh parsing latency. A rescore has its own timestamp and revision and retains the original parse provenance. Its separately hashed portable normalizer may use evidence already present in cached output, such as worksheet headings; it never reads the source to fill a provider gap.

Provider errors and unsupported formats are explicit. An empty response is an error except for source-verified blank documents and slide decks. Failed runs overwrite their own result with the failure; they never substitute a historical score. The command exits nonzero on parse or missing-fixture errors while retaining the complete report. A comparison may therefore be publishable with documented provider failures even when the command exits nonzero.

The current comparison environment is pinned in `results/environment.txt`. Raw converted-output caches are local artifacts and are not committed. v1 repository and website summaries are retained separately in `results/v1/` because those summaries previously disagreed.

Parser-specific regression gates supplement the public comparison. Run
`python3 benchmarks/check_xlsx_hyperlinks.py` for source-derived sheet/cell
hyperlink targets, HTML target writing, sparse rows and bounded truncation.
Chromium shares the same expectations. Its dedicated fixture is outside the
87-file corpus and does not contribute to published scores. XLSX generation
and Markdown table-cell link writing remain separate roadmap items.

Ground truth must be checked against the input source, not regenerated to make the reference parser pass. Run the oracle with no `--check` to rebuild source assertions, inspect the diff, and run the corruption tests. Legacy `annotate.py`/`enrich_gt.py` are v1 annotation utilities, not the v2 maintenance path.

## License

Benchmark annotations: CC-BY-4.0. Evaluation code: Apache-2.0. Source files retain their original licenses; see `benchmarks/SOURCES.md`.

## Results (v2.1, 2026-11-24)

Every tool was run on 2026-11-24 against the v2.1 ground truth, with the same scorer. Local tools were run live. Extend, Reducto and LlamaParse were run live through their APIs once, with every raw response kept (`EXTEND_RAW_DIR`, `REDUCTO_RAW_DIR`, `LLAMAPARSE_RAW_DIR`), and the published results map those stored responses with the final adapters (`raw_reuse` in provenance). The exact tool versions are in `results/environment.txt` and each result's provenance.

| Provider | Version | Parsed | Composite | Coverage-adjusted | Structural fidelity | Text overlap | Errors |
|---|---|---:|---:|---:|---:|---:|---:|
| AILANG Parse | 0.58.0 | 87/87 | 95.0% | 95.0% | 99.0% | 97.2% | 0 |
| Pandoc | 3.14 | 79/87 | 81.0% | 73.5% | 75.9% | 91.9% | 2 |
| Kreuzberg | 4.10.4 | 83/87 | 74.7% | 71.2% | 56.3% | 92.2% | 4 |
| Docling | 2.152.0 | 84/87 | 73.4% | 70.9% | 73.0% | 96.4% | 2 |
| Reducto | r-1@v1.12.24-1094-g7ca71926b723 | 72/87 | 79.8% | 66.1% | 70.7% | 85.5% | 0 |
| Unstructured | 0.27.37 | 79/87 | 67.6% | 61.4% | 63.5% | 95.1% | 2 |
| LlamaParse | 0.6.94 | 85/87 | 61.2% | 59.8% | 53.9% | 88.9% | 2 |
| MarkItDown | 0.1.5 | 73/87 | 68.4% | 57.4% | 64.5% | 86.3% | 2 |
| Raw OOXML | 2.0.0-stdlib | 60/87 | 81.8% | 56.4% | 61.3% | 96.2% | 1 |
| Extend | parse_performance@api-2026-02-09 | 77/87 | 61.9% | 54.8% | 53.4% | 88.1% | 4 |
| LiteParse | 2.21.1 | 74/87 | 38.9% | 33.1% | 23.0% | 85.6% | 2 |
| LiteParse + OCRia-nano-1 | 2.21.1+ocria-nano@1.0.0 | 74/87 | 36.3% | 30.9% | 22.9% | 85.8% | 2 |

**Structural fidelity** is the share of source-checked structural assertions a tool reproduces (cell positions, comment targets, list depth, explicit formatting, slide and sheet order, notes, hyperlinks, breaks). **Text overlap** is word-level Jaccard against the source text. A file a tool fails on or does not support counts as zero in the coverage-adjusted score.

LlamaParse uses the legacy `llama-parse` 0.6.94 client in standard non-premium mode. Its two errors are the minimal hand-made `test.ods` and `test.odt` recovery fixtures.

Extend ran through its REST API (`parse_performance@api-2026-02-09`) at its strongest documented settings: the `parse_performance` engine (Parse 2.0) with agentic text and table correction, advanced chart extraction, formulas, `formattingDetection: change_tracking`, HTML tables, and `excelParsingMode: advanced` with cell metadata and formatting. The exact request is recorded in `provenance.provider_config`. Extend renders DOCX and PPTX to PDF before parsing. ODP, EPUB and TSV are rejected at upload and count as unsupported. Its four errors are provider failures: two `OCR_ERROR`s (`challenge_footnotes.docx`, `test.ods`), an HTTP 500 (`test.odt`), and no blocks for the recovery fixture `challenge_threaded_comments.xlsx`. An empty answer is scored, not counted as an error, where the file is genuinely empty (`python_pptx_slides.pptx`).

Reducto ran through its REST API (server build `r-1@v1.12.24-1094-g7ca71926b723`) at its strongest documented settings: the `r-1` model, HTML tables, `formatting.include` change tracking, comments and hyperlinks, `spreadsheet.clustering: accurate` with formulas and cell colours, large tables kept whole, document properties, and chunking disabled. ODT, ODS, ODP and EPUB are refused with HTTP 415 and count as unsupported. There were no provider errors.

LiteParse was run twice on 2026-11-24, on CPU, with version 2.21.1 and identical settings apart from the OCR backend. The `liteparse` adapter pins Tesseract. The `liteparse_ocria` adapter uses OCRia-nano-1 (8.1M parameters, model 1.0.0), which needs `lit models pull ocria-nano` once beforehand. With OCRia-nano-1 on, LiteParse's LayoutNet table and layout model also runs on the pages LiteParse renders from Office files. Its tables arrive as `merged_table` blocks with spans, and its running headers and footers as `page_header` / `page_footer`. Both adapters map these. It finds one more table and both header/footer cases, but fewer headings and list items: it returns many list items as `code` blocks. Median time per file was about 1.0 s for both runs, because LiteParse's LibreOffice conversion takes most of the time. The model weights are under the OCRia-nano-1 Model License, which permits benchmarking.

### What changed in v2.1

- The legacy ground truth for 69 cases was rebuilt from the source documents (`source_truth.py`). Before v2.1 most of it had been generated from AILANG Parse's own output. Fields that depend on one parser's conventions (paragraph count, reading order, table row counts, some list counts) are no longer scored. `truth_rebuild_v2_1.json` lists every changed value.
- A section break is asserted only where the document has one. Every DOCX ends with a body-level `w:sectPr`, which had been asserted as a break that only AILANG Parse emitted.
- Run assertions cover only formatting the source switches on (no default black, no `bold: false`).
- The scorer skips a dimension with nothing to check instead of scoring it 1.0, reads heading text from the source-derived headings, treats tracked-change type synonyms as equal, and matches a covered table cell by position rather than span.
- Adapters were corrected where they dropped output their tool returns, after checking each tool's raw output: Pandoc (xlsx, pptx, csv and tsv are supported; comments, runs, rowspans), MarkItDown (md and tsv; slides and notes; placeholder header rows), Unstructured (list and heading depth, slides, notes), Docling (comments, notes, headers and footers, merged cells), Kreuzberg (hyperlinks), LiteParse (slides), shared Markdown list grouping, and formatting runs for every tool that returns them.
- `test.odt`, `test.ods` and `test.odp` are labelled recovery fixtures, and three ODT files with no body text accept an empty answer.

Results scored against the v2.0 ground truth are not comparable with these and are not kept in `results/`.
