# OfficeDocBench v2

OfficeDocBench evaluates document parsers on **87 files across 11 formats**. It measures structural fidelity as well as text extraction. The corpus retains the original 69 cases and adds 18 Office regression fixtures. `corpus.json` declares the exact case set; extra files downloaded by CI never silently change the public comparison. Results from v1 use different scoring and must not be compared directly with v2 percentages.

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

## Recorded comparison (2026-10-23)

These figures were scored against the ground truth before v2.1, which still held values generated from AILANG Parse output. They have not been rescored against the rebuilt ground truth. The changed `corpus_sha256` stops `--summarize` from combining runs scored against different ground truth. Rescore cached outputs with `rescore.py` before quoting any number.

The reference is the **[XLSX hyperlink candidate (PR #116)](https://github.com/sunholo-data/ailang-parse/pull/116)**,
labeled `0.52.2+xlsx-hyperlinks`. It includes the PPTX spacing and DOCX cell-formatting
fixes merged in PR #115 and explicit XLSX hyperlink target extraction.
`DOCPARSE_BENCHMARK_LABEL=xlsx-hyperlinks` records that label; the exact clean
source revision and toolchain remain in provenance. Competitor outputs retain
their original live parse timestamps and are rescored against the same audited
expectations without new API requests. Do not attribute this candidate's score
to the unchanged v0.52.2 release.

With the same 87 inputs and unchanged assertions, the previous PR #115 parser
scores **97.70%** and this candidate scores **98.08%**. Only
`challenge_hyperlinks.xlsx` changes (66.67% to 100%); the other 86 case scores
are identical. Source-verified hyperlink assertion recall rises from 75% to
100% across four cases. The earlier published 97.3% used a six-case legacy
audit and is not the baseline for this comparison. The current legacy audit
covers eight selected cases; unaudited historical fields remain identified.

| Provider | Version | Parsed | Composite | Coverage-adjusted | Errors |
|---|---|---:|---:|---:|---:|
| AILANG Parse | 0.52.2+xlsx-hyperlinks | 87/87 | 98.1% | 98.1% | 0 |
| Kreuzberg | 4.10.4 | 82/87 | 68.5% | 64.6% | 5 |
| Docling | 2.142.1 | 83/87 | 65.2% | 62.2% | 3 |
| Reducto (r-1) | r-1@v1.12.24-681-gfa140bec3448 | 72/87 | 72.7% | 60.1% | 0 |
| LlamaParse (standard) | 0.6.94 | 83/87 | 61.9% | 59.0% | 4 |
| Extend (Parse 2.0) | parse_performance@api-2026-02-09 | 77/87 | 60.2% | 53.3% | 4 |
| Unstructured | 0.27.34 | 76/87 | 58.9% | 51.4% | 5 |
| Raw OOXML | 2.0.0-stdlib | 60/87 | 70.7% | 48.7% | 1 |
| MarkItDown | 0.1.5 | 69/87 | 58.7% | 46.6% | 2 |
| Pandoc | 3.12.1 | 49/87 | 63.1% | 35.6% | 1 |
| LiteParse (Tesseract) | 2.21.1 | 70/87 | 35.9% | 28.9% | 6 |
| LiteParse + OCRia-nano-1 | 2.21.1+ocria-nano@1.0.0 | 71/87 | 34.6% | 28.2% | 5 |

LlamaParse uses the legacy `llama-parse` 0.6.94 client in standard non-premium mode. The original provider job responses were retrieved to audit and repair the mappings; no new parsing requests were needed for that remap. Its EPUB and minimal ODS/ODT conversion failures are retained. Other model tiers require separate configured runs.

Extend was run on 2026-11-03 through its REST API (version 2026-02-09) at its strongest documented settings: the `parse_performance` engine (Parse 2.0) with agentic text and table correction, advanced chart extraction, formulas, `formattingDetection: change_tracking`, HTML tables, and `excelParsingMode: advanced` with cell metadata and formatting. The exact request is recorded in `provenance.provider_config`. Extend renders DOCX and PPTX to PDF before parsing, so comments, speaker notes, bookmarks and authorship are absent from its response; tracked changes appear only where they are visible on the page, without authors. XLSX and ODS are read natively, and the adapter scores their cells at Extend's own `data-cell` coordinates. HTML and Markdown input is returned as-is. ODP, EPUB and TSV are rejected at upload and count as unsupported. Four provider errors reproduced on a second attempt: an `OCR_ERROR` (`challenge_footnotes.docx`), an HTTP 500 (`test.odt`), an empty three-slide response (`python_pptx_slides.pptx`), and no blocks for the recovery-profile `challenge_threaded_comments.xlsx`. The run used 220 credits; the median latency was 5.6 s per file including upload and polling.

Reducto was run on 2026-11-18 through its REST API (server build v1.12.24-681-gfa140bec3448) at its strongest documented settings: the `r-1` model (the API default is still `legacy` until December 2026), HTML tables, `formatting.include` change tracking, comments and hyperlinks, `spreadsheet.clustering: accurate` with formulas and cell colours, large tables kept whole, document properties, and chunking disabled. The exact request is recorded in `provenance.provider_config`. Reducto reads Word comments with author, date, anchored text and reply threading, and returns inline formatting as HTML and nested lists by tab depth; the adapter maps each of these from the response. Speaker notes, bookmarks, section breaks and tracked-change authors are absent from its response. A tracked change is counted only where Reducto marks it with `<change>`: an insertion that comes back as a bare `<u>` is underline, and plain strikethrough that Reducto wraps in `<change><s>` is counted as the deletion it claims. Spreadsheet cells carry no sheet coordinates, so they are scored at table-local positions; cell colours come back as approximate names (`lightblue`, `lightred`) and are not converted to values. ODT, ODS, ODP and EPUB are refused at parse with HTTP 415 `DOCUMENT_CORRUPT` and count as unsupported; Markdown, HTML and TSV are not in Reducto's documented list but parse. There were no provider errors. The median latency was 1.6 s per file including upload.

LiteParse was run twice on 2026-11-24, on CPU, with version 2.21.1 and identical settings apart from the OCR backend. The `liteparse` adapter pins Tesseract. The `liteparse_ocria` adapter uses OCRia-nano-1 (8.1M parameters, model 1.0.0), which needs `lit models pull ocria-nano` once beforehand. With OCRia-nano-1 on, LiteParse's LayoutNet table and layout model also runs on the pages LiteParse renders from Office files. Its tables arrive as `merged_table` blocks with spans, and its running headers and footers as `page_header` / `page_footer`. Both adapters map these. It finds one more table and both header/footer cases, but fewer headings and list items: it returns many list items as `code` blocks. Median time per file was about 1.0 s for both runs, because LiteParse's LibreOffice conversion takes most of the time. The model weights are under the OCRia-nano-1 Model License, which permits benchmarking.
