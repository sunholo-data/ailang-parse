# ECMA-376 Spec Coverage Audit

Living document mapping DocParse parser coverage against the ECMA-376 5th Edition (OOXML) specification.

**Spec location**: `specs/ecma-376/part1/` (34MB PDF, ~5000 pages)
**Last updated**: 2026-03-28
**Benchmark**: 97.8% composite (67 files), 10% gap coverage (8 challenge checks)
**Gap analysis**: `uv run benchmarks/office/eval_gaps.py --verbose`

## Summary

| Format | Spec Chapter | Spec Pages | Features Handled | Est. Coverage |
|--------|-------------|------------|-----------------|---------------|
| DOCX (WordprocessingML) | Ch 17 | 1355 pp (167-1522) | 12 of ~40 | ~15% |
| XLSX (SpreadsheetML) | Ch 18 | 993 pp (1523-2516) | 5 of ~30 | ~10% |
| PPTX (PresentationML) | Ch 19 | 202 pp (2517-2719) | 8 of ~15 | ~25% |
| DrawingML | Ch 20-21 | 882 pp (2720-3602) | 2 of ~20 | ~5% |
| Shared (Math, etc.) | Ch 22 | 200 pp (3603-3803) | 1 of ~10 | ~5% |

---

## WordprocessingML (DOCX) — `docparse/services/docx_parser.ail` (489 lines)

### Handled Features

| Spec Section | Feature | Parser Lines | Notes |
|---|---|---|---|
| §17.2 | Document body (`w:body`) | L134-142 | Top-level container |
| §17.2 | Paragraphs (`w:p`) | L176-186 | Text extraction, style detection |
| §17.2 | Runs (`w:r` → `w:t`) | L280-285 | Text only, formatting ignored |
| §17.3 | Paragraph style (`w:pStyle`) | L288-295 | Style name only, not definition |
| §17.3 | Heading detection | L299-317 | Hardcoded "Heading1"-"Heading6" only |
| §17.4 | Tables (`w:tbl/w:tr/w:tc`) | L341-417 | Full structure with first-row headers |
| §17.4 | Horizontal merge (`w:gridSpan`) | L384-394 | Column span values |
| §17.4 | Vertical merge (`w:vMerge`) | L398-403 | Restart/continue states |
| §17.13 | Track changes — insert (`w:ins`) | L229-236 | Author, date, text |
| §17.13 | Track changes — delete (`w:del`) | L229-236 | Author, date, delText |
| §17.13 | Track changes — move (`w:moveTo/From`) | L229-236 | Author, date, text |
| §17.13 | Comments (`w:comment`) | L447-487 | Author, date, text (from comments.xml) |
| §17.10 | Headers (`word/header*.xml`) | L64-67 | Via parseSectionEntries |
| §17.10 | Footers (`word/footer*.xml`) | L70-73 | Via parseSectionEntries |
| §17.11 | Footnotes (`word/footnotes.xml`) | L76-79 | Via parseSectionEntries |
| §17.11 | Endnotes (`word/endnotes.xml`) | L82-85 | Via parseSectionEntries |
| §17.5 | SDT content (`w:sdt`) | L265-273 | Text extracted, metadata lost |
| — | Text boxes (`w:txbxContent`) | L161-174 | Extracted as SectionBlock |
| — | Hyperlink text (`w:hyperlink`) | L209 | Text only, URL discarded |
| — | Smart tags (`w:smartTag`) | L208 | Text only, metadata lost |
| — | Images (`word/media/*`) | L432-443 | Binary data + MIME type |
| — | Metadata (`docProps/core.xml`) | L420-431 | Title, author, created, modified |

### NOT Handled — By Impact

#### P1: HIGH Impact (common in real documents, degrades content understanding)

| Spec Section | Feature | Impact | Effort | Notes |
|---|---|---|---|---|
| §17.9 (pp 691-732) | **Numbering definitions** (`word/numbering.xml`) | HIGH | Medium | List type/level completely guessed. `numId != "1"` heuristic is wrong. Need to read abstractNum definitions for bullet vs number and indent level. |
| §17.7 (pp 613-668) | **Styles** (`word/styles.xml`) | HIGH | Medium | Can't detect custom heading styles (e.g. "Title", "Subtitle", "Chapter"). Only hardcoded "Heading1"-"Heading6" work. 56 pages of spec. |
| §17.16 (pp 1157-1291) | **Hyperlink targets** | HIGH | Low | We extract hyperlink text (L209) but discard the URL. Need to read `r:id` attr → resolve via `word/_rels/document.xml.rels`. |
| §17.3.2 | **Run properties** (`w:rPr`) — bold, italic | MEDIUM-HIGH | Medium | `w:b`, `w:i`, `w:u` carry semantic meaning (gene names, emphasis, book titles). Currently invisible. 178 pages for full §17.3. |
| §17.16 | **Field result text** (`w:fldSimple`, `w:fldChar`) | MEDIUM | Medium | TOC entries, cross-refs, page numbers all invisible. 135 pages of spec. At minimum extract display text. |

#### P2: MEDIUM Impact

| Spec Section | Feature | Impact | Effort | Notes |
|---|---|---|---|---|
| §17.13.6 | **Bookmark definitions** (`w:bookmarkStart/End`) | MEDIUM | Low | Cross-reference anchors. We skip them entirely. |
| §17.13.1 | **Comment ranges** (`w:commentRangeStart/End`) | MEDIUM | Medium | We get comment text but not which document text the comment applies to. |
| §17.6 (pp 546-612) | **Section properties** (`w:sectPr`) | MEDIUM | Medium | Page breaks, columns, orientation, margins. 67 pages of spec. |
| §17.3.2 | **Run properties** — font, size, color | LOW-MEDIUM | Medium | Less semantic than bold/italic but relevant for visual structure detection. |
| §22.1 (pp 3603-3723) | **Math/Equations** (`m:oMath`) | MEDIUM | High | Academic/scientific docs. Would need OMML→text or OMML→LaTeX. 121 pages of spec. |
| §17.13 | **Property changes** (`w:rPrChange`, `w:pPrChange`) | LOW | Medium | Track changes for formatting changes (not just text). |

#### P3: LOW Impact or HIGH Effort

| Spec Section | Feature | Impact | Effort | Notes |
|---|---|---|---|---|
| §21.2 (pp 3365-3472) | **Charts** | MEDIUM | Very High | 108 pages. Data series in chart XML. Would need to parse `c:chart` → extract data. |
| §21.4 (pp 3494-3602) | **SmartArt/Diagrams** | LOW | Very High | 109 pages. Complex diagram definitions. |
| §17.14 (pp 928-968) | **Mail merge** | LOW | Medium | Rarely relevant for content extraction. |
| §17.15 (pp 969-1156) | **Settings** | LOW | Low | Document settings, not content. 188 pages. |
| §17.12 (pp 779-796) | **Glossary document** | LOW | Medium | AutoText/Building Blocks storage. |
| §17.5 (pp 484-545) | **Custom markup** (full SDT) | LOW | High | We extract text; full SDT metadata (type, binding, state) rarely needed. |
| §17.4 | **Table styles** | LOW | Medium | Visual styling, not content. |
| §17.8 (pp 669-690) | **Font definitions** | LOW | Low | Font metadata, not content. |

---

## SpreadsheetML (XLSX) — `docparse/services/xlsx_parser.ail` (264 lines)

### Handled Features

| Spec Section | Feature | Notes |
|---|---|---|
| §18.4 | Shared string table (`xl/sharedStrings.xml`) | Resolves `t="s"` references |
| §18.3 | Worksheets (`xl/worksheets/sheetN.xml`) | Row/cell extraction |
| §18.3 | Cell types (string, inline, boolean, error, number) | Type-aware extraction |
| §18.2 | Sheet names (`xl/workbook.xml`) | Read but not always in output |
| — | Metadata (`docProps/core.xml`) | Title, author, dates |

### NOT Handled — By Impact

| Spec Section | Feature | Impact | Notes |
|---|---|---|---|
| §18.3.1.55 | **Merged cells** (`<mergeCells>/<mergeCell ref="A1:C3">`) | HIGH | Completely missing. DOCX tables handle merges but XLSX doesn't. |
| §18.3 | **Formula cached values** | HIGH | Cells with `<f>` return empty even though `<v>` has cached result. |
| §18.5 (pp 1726-1741) | **Table definitions** | MEDIUM | Named tables with auto-filter, structured references. |
| §18.7 (pp 1745-1751) | **Comments/notes** | MEDIUM | Cell annotations not extracted. |
| §18.3 | **Images/shapes in worksheets** | MEDIUM | Drawing parts not read. |
| §18.8 (pp 1752-1800) | **Styles** | LOW | Number formats, conditional formatting. |
| §18.6 (pp 1742-1744) | **Calculation chain** | LOW | Formula evaluation order. |
| §18.10 (pp 1815-1958) | **Pivot tables** | LOW | 144 pages of spec. Complex feature. |
| §18.17 (pp 2039-2434) | **Formulas** | LOW | 396 pages. Evaluation engine not needed for content extraction. |

---

## PresentationML (PPTX) — `docparse/services/pptx_parser.ail` (315 lines)

### Handled Features

| Feature | Notes |
|---|---|
| Slides (`p:sld/p:cSld/p:spTree`) | Full slide structure |
| Shape text (`p:sp/p:txBody`) | DrawingML text extraction |
| Placeholder detection | Title/subtitle/body via `p:ph@type` |
| Tables (`a:tbl`) | With gridSpan and merge |
| Pictures (`p:pic`) | With description |
| Group shapes (`p:grpSp`) | Recursive |
| Metadata | Title, author, dates |
| Image extraction | Media files with MIME |

### NOT Handled — By Impact

| Spec Section | Feature | Impact | Notes |
|---|---|---|---|
| §19.3 | **Speaker notes** (`ppt/notesSlides/`) | HIGH | Design doc exists. Not read at all. |
| §21.2 | **Charts** | MEDIUM | Graphic frames checked for tables only, not charts. |
| §19.5 (pp 2602-2690) | **Animations** | LOW | 89 pages. Not relevant for content. |
| §19.3 | **Slide master/layout** | LOW | Custom layouts ignored. |
| — | **Embedded video/audio** | MEDIUM | Only images extracted from media. |

---

## ODF Formats (ODT/ODP/ODS)

These use the ODF spec (OASIS), not ECMA-376. Coverage is similar in scope:
- **ODT** (321 lines): Headings, paragraphs, tables (colspan only), lists, images, text boxes, headers/footers, metadata
- **ODP** (221 lines): Slides, text boxes, headings, paragraphs, lists, tables (no spans), images, metadata
- **ODS** (146 lines): Sheets, rows, cells (colspan only), metadata

Missing: footnotes, comments, track changes, formatting, formulas, charts — same gaps as OOXML parsers.

---

## Cross-Cutting Gaps

These affect ALL parsers:

1. **No formatting extraction**: Bold, italic, font, color — invisible across all formats
2. **No hyperlink URL preservation**: Link text extracted, targets discarded
3. **No equation support**: Math content lost in all formats
4. **No chart data extraction**: Charts ignored in all formats
5. **Span values hardcoded 1-10**: All parsers cap colspan/rowspan at 10
6. **No page break detection**: Section/page boundaries lost

---

## Benchmark Coverage vs Spec Coverage

| Feature | In Benchmark? | In Parser? | In Spec? |
|---|---|---|---|
| Basic text extraction | Yes (54 files) | Yes | §17.2 |
| Tables with merges | Yes (33 files) | Yes | §17.4 |
| Track changes | Yes (4 files) | Yes | §17.13 |
| Comments | Yes (5 files) | Yes | §17.13 |
| Headers/footers | Yes (5 files) | Yes | §17.10 |
| Images | Yes (10 files) | Yes | §17.2 |
| Text boxes | Yes (8 files) | Yes | — |
| **Numbering/lists** | **Partial** (16 files) | **Guessed** | §17.9 |
| **Styles** | **No** | **No** | §17.7 |
| **Formatting** | **No** | **No** | §17.3 |
| **Hyperlink URLs** | **No** | **No** | §17.16 |
| **Fields** | **No** | **No** | §17.16 |
| **Equations** | **No** | **No** | §22.1 |
| **Charts** | **No** | **No** | §21.2 |
| **XLSX merges** | **No** | **No** | §18.3 |
| **XLSX formulas** | **Partial** (1 file) | **No** | §18.17 |

**With hand-verified ground truth**: DocParse scores **97.8%** (full suite) / **96.9%** (head-to-head). The gap analysis tool reports **10% coverage** on features we don't handle. The 6 challenge files that penalize us are: custom heading styles (0%), list detection (0%), equation text (0%), field display text (0%), XLSX merged cells (0%), title/subtitle as headings (0%).

## How to Use This Document

1. **Run gap analysis**: `uv run benchmarks/office/eval_gaps.py --verbose` — shows per-check scores
2. **Run full benchmark**: `uv run benchmarks/officedocbench/eval_officedocbench.py` — shows composite score
3. **Pick a P1 item above** → read the spec section → implement in the AILANG parser → re-run benchmarks
4. Each P1 fix should improve the composite score by 0.5-1.5 percentage points
