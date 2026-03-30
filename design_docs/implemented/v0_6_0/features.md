# DocParse v0.6.0 — Document Generation Features

## Overview

DocParse is now a **bidirectional document pipeline**: it both parses AND generates documents across 10 input formats and 8 output formats, all as a single dependency-free AILANG binary.

## Two Modes of Operation

### 1. Format Conversion (`--convert`)

Parse any supported input format and convert it to a different output format:

```bash
# DOCX → HTML
./bin/docparse input.docx --convert output.html

# Markdown → DOCX
./bin/docparse notes.md --convert report.docx

# XLSX → ODT
./bin/docparse data.xlsx --convert summary.odt

# CSV → PPTX
./bin/docparse metrics.csv --convert slides.pptx

# EPUB → HTML
./bin/docparse book.epub --convert book.html
```

Any of the 10 parseable formats (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, Markdown, CSV/TSV, EPUB) can be converted to any of the 8 output formats.

### 2. AI Document Generation (`--generate --prompt`)

Generate documents from natural language descriptions using any AI backend:

```bash
# Generate a Word report
./bin/docparse --generate report.docx \
  --prompt "Quarterly sales report with revenue table and 3 key findings"

# Generate a presentation
./bin/docparse --generate slides.pptx \
  --prompt "5-slide pitch deck for DocParse with competitive comparison table"

# Generate a spreadsheet
./bin/docparse --generate data.xlsx \
  --prompt "Employee directory with 8 employees across 2 department sheets"

# Generate an HTML page
./bin/docparse --generate docs.html \
  --prompt "Product documentation with installation steps, supported formats table, and FAQ"

# Generate an ODF document
./bin/docparse --generate letter.odt \
  --prompt "Formal business letter with feature comparison table"

# Use a specific AI model
GOOGLE_API_KEY="" ./bin/docparse --generate report.docx \
  --prompt "Project status report" --ai gemini-2.5-flash
```

The AI generates structured Block ADT JSON (headings, paragraphs, tables, lists), which is then piped through the appropriate format generator. The `--ai` flag selects the model (defaults to gemini-2.5-flash via ADC).

## Supported Output Formats

| Format | Extension | Generator Module | Opens In |
|--------|-----------|-----------------|----------|
| HTML | `.html` | html_generator.ail | All browsers, roundtrips through DocParse |
| Markdown | `.md` | output_formatter.ail | Any text editor, roundtrips through DocParse |
| Word | `.docx` | docx_generator.ail | Word, Pages, LibreOffice, Google Docs |
| PowerPoint | `.pptx` | pptx_generator.ail | LibreOffice, Google Slides, python-pptx* |
| Excel | `.xlsx` | xlsx_generator.ail | Numbers, Excel, LibreOffice, Google Sheets |
| ODF Text | `.odt` | odt_generator.ail | LibreOffice |
| ODF Presentation | `.odp` | odp_generator.ail | LibreOffice |
| ODF Spreadsheet | `.ods` | ods_generator.ail | LibreOffice |

*PPTX: Keynote compatibility is a known limitation (see verification_loop.md).

## What Gets Generated

### Document Formats (DOCX, ODT, HTML, Markdown)

The generators map Block ADT variants to native format elements:

| Block Type | DOCX | HTML | ODT |
|------------|------|------|-----|
| HeadingBlock | `<w:pStyle val="HeadingN">` | `<h1>`–`<h6>` | `<text:h outline-level="N">` |
| TextBlock | `<w:p><w:r><w:t>` | `<p>` | `<text:p>` |
| TableBlock | `<w:tbl>` with borders, colspan | `<table>` with colspan/rowspan | `<table:table>` |
| ListBlock | Bullet/number prefix paragraphs | `<ol>`/`<ul>` | `<text:list>` |
| ImageBlock | Placeholder text (binary blocked) | `<img>` with base64 data URI | Placeholder text |
| SectionBlock | Labeled subsections | `<section class="kind">` | `<text:section>` |
| ChangeBlock | Strikethrough/bold with attribution | `<ins>`/`<del>` | Attributed paragraph |

### Presentation Formats (PPTX, ODP)

SectionBlock(kind="slide") boundaries define slides. If no slide sections exist, all blocks go on one slide. Each block becomes a positioned shape/text box on the slide.

### Spreadsheet Formats (XLSX, ODS)

TableBlocks become sheets. SectionBlock(kind="sheet") boundaries define named sheets. Non-table blocks (headings, text) go into a "Content" sheet. XLSX uses shared strings for efficiency.

## Architecture

```
input.docx ──→ Parser ──→ [Block] ──→ Generator ──→ output.pptx
                             │
"Q1 report" ──→ AI Effect ──→ [Block] ──→ Generator ──→ output.docx
```

All generators are pure AILANG — no runtime dependencies. The pattern is:
1. Map each Block variant to format-specific XML strings
2. Wrap in boilerplate (namespaces, relationships, content types)
3. Pack into ZIP via `std/zip.createArchive`

For AI generation, the prompt is enriched with the Block ADT JSON schema and format-specific hints (e.g., "wrap each slide in a section block"), then `callJsonSimple` returns structured JSON that gets decoded into Blocks.

## AILANG Module Summary

| Module | Lines | Purpose |
|--------|-------|---------|
| xml_helpers.ail | ~100 | `xmlEscape`, XML element/attribute builders, DOCX namespace constants |
| html_generator.ail | ~160 | Block → XHTML (all 9 variants, standalone document with CSS) |
| docx_generator.ail | ~210 | Block → DOCX (headings, tables with borders/colspan, styled paragraphs) |
| pptx_generator.ail | ~400 | Block → PPTX (slides, text boxes, tables, theme, presProps) |
| xlsx_generator.ail | ~280 | Block → XLSX (multi-sheet, shared strings, column letters, cellStyles) |
| odt_generator.ail | ~170 | Block → ODT (ODF text with sections, tables, lists, metadata) |
| odp_generator.ail | ~180 | Block → ODP (ODF presentation with draw:page slides) |
| ods_generator.ail | ~160 | Block → ODS (ODF spreadsheet with named sheets) |
| ai_generator.ail | ~140 | Prompt → AI → Block ADT (schema-aware prompting, format hints) |

## Verification

```bash
# Quick type-check + smoke test (~15s)
bash benchmarks/quick_check.sh

# Full verification loop (structure + library + roundtrip)
uv run --with python-pptx --with openpyxl --with python-docx benchmarks/verify_generated.py

# Regenerate demos + verify
bash .claude/skills/verify-docs/scripts/regen_and_verify.sh
```

## Known Limitations

1. **No embedded images** in DOCX/PPTX — `createArchive` only accepts string content. Needs `writeEntryBytes` from AILANG for binary ZIP entries. Images render as `[Image: description]` placeholder text.
2. **PPTX Keynote incompatibility** — Keynote requires extensive boilerplate XML (placeholder shapes, text style hierarchy, full theme resolution chain) beyond what's practical in string templates. Files open in LibreOffice, Google Slides, and python-pptx.
3. **ODF mimetype compression** — `createArchive` compresses all entries. ODF spec wants `mimetype` uncompressed. Files still open in LibreOffice but `file` command doesn't detect the MIME type.
4. **Lists in DOCX** — Rendered as bullet/number character prefixes rather than native Word numbering (would need `word/numbering.xml`). Content is correct, styling is basic.
5. **No cell formatting in XLSX** — All cells are text. Number/date detection and formatting are future enhancements.

## Demo Files

Pre-generated examples in `data/examples/`:

| File | Type | Content |
|------|------|---------|
| demo_report.docx | AI-generated | Quarterly business report with revenue table |
| demo_pitch.pptx | AI-generated | 5-slide pitch deck with comparison tables |
| demo_data.xlsx | AI-generated | 2-sheet employee directory |
| demo_page.html | AI-generated | Documentation page with format table and FAQ |
| demo_letter.odt | AI-generated | Business letter with feature comparison |
| converted_sample.html | Conversion | sample.docx → HTML |
| converted_sample.pptx | Conversion | sample.docx → PPTX |
| converted_sample.odt | Conversion | sample.docx → ODT |
