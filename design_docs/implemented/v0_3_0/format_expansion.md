# Design: Expanded Format Support & Benchmark Corpus

**Status**: Planned
**Priority**: Medium
**Target**: v0.3.0
**Principle**: All parsing logic must be implemented in AILANG. No Python dependency wrapping.

## Core Principle

DocParse is an AILANG library, not a Python wrapper. When we say "support HTML", we mean
implementing an HTML parser in AILANG that produces Block ADT output — not calling
BeautifulSoup from Python. The whole point is to eliminate dependency hell by having
a single compiled binary (via `ailang compile --emit-go`) that handles all formats.

Competitors like Unstructured require ~50 Python packages to parse documents.
DocParse should require zero runtime dependencies beyond the compiled binary.

## Competitor Format Landscape

| Format | Unstructured | Docling | LlamaParse | **DocParse** | Parsing Complexity |
|--------|-------------|---------|-----------|-------------|-------------------|
| DOCX/PPTX/XLSX | Yes | Yes | Yes | **Yes (best structural)** | High (ZIP+XML) |
| PDF | Yes | Yes | Yes | **Yes (AI effect)** | AI-delegated |
| Images | Yes | Yes | Yes | **Yes (AI effect)** | AI-delegated |
| CSV/TSV | Yes | CSV | No | **Planned** | Trivial |
| HTML | Yes | Yes | Yes | **Planned** | Medium |
| Markdown | Yes | Yes | No | **Planned** | Simple |
| RTF | Yes (→DOCX) | No | Yes | **Planned** | Medium |
| ODT/ODP/ODS | Yes (→DOCX) | No | No | **Planned (strategic)** | Medium (ZIP+XML) |
| EPUB | Yes | No | Yes | **Planned** | Medium (ZIP+XHTML) |
| Email (EML) | Yes | No | No | Future | Medium |
| Email (MSG) | Yes | No | No | Future | Hard (binary) |
| DOC/PPT/XLS | Yes | No | Yes | Future | Very hard (binary) |
| LaTeX | No | Yes | No | Future | Hard |

## Implementation Priority (by AILANG feasibility)

### Tier 1: Trivial in AILANG (v0.3.0)

These formats need only string parsing — no external libraries, no binary formats.

#### CSV/TSV
- Split on delimiter, handle quoting, produce Table blocks
- ~50 lines of AILANG: `split`, `map`, string operations
- Pure function, no effects needed
- **AILANG implementation**: `docparse/services/csv_parser.ail`

#### Markdown
- Parse headers (#), lists (- / 1.), code blocks, tables
- ~100-150 lines of AILANG using `std/string` operations
- Pure function, no effects
- Useful as both input format and output validation
- **AILANG implementation**: `docparse/services/markdown_parser.ail`

### Tier 2: Medium complexity in AILANG (v0.3.0-v0.4.0)

#### HTML
- Parse tag structure → Block ADT
- Need: tag tokenizer, basic DOM traversal
- Map `<h1-h6>` → Heading, `<p>` → Text, `<table>` → Table, `<ul>/<ol>` → List
- ~200-300 lines of AILANG
- No need for full browser-grade HTML parsing — handle well-formed HTML
- **AILANG implementation**: `docparse/services/html_parser.ail`

#### EPUB
- ZIP container (reuse existing `zip_extract.ail`) containing XHTML chapters
- Parse `META-INF/container.xml` → find content.opf → list spine items
- Each spine item is XHTML → reuse HTML parser
- Metadata from OPF (title, author, etc.)
- ~150 lines of AILANG on top of HTML parser + zip_extract
- **AILANG implementation**: `docparse/services/epub_parser.ail`

#### RTF
- Token-based format: `\b bold \b0` style control words
- Parse control words → map to Block ADT
- More complex than CSV but well-documented spec
- ~200-300 lines of AILANG
- **AILANG implementation**: `docparse/services/rtf_parser.ail`

### Tier 3: Strategic AILANG opportunity (v0.4.0)

#### ODT/ODP/ODS (OpenDocument)
- **Same architecture as OOXML**: ZIP containing XML files
- Reuse `zip_extract.ail` for container handling
- Different XML schemas (ODF vs OOXML) but same structural concepts
- `content.xml` → body text, tables, headings (like `document.xml` in DOCX)
- `styles.xml` → formatting (like `styles.xml` in DOCX)
- **Strategic differentiator**: Nobody does this natively. Unstructured converts via pandoc.
  Docling and LlamaParse don't support it at all.
- European government mandate means significant enterprise demand
- ~300-400 lines of AILANG, heavily reusing DOCX parser patterns
- **AILANG implementation**: `docparse/services/odt_parser.ail`, `odp_parser.ail`, `ods_parser.ail`

### Tier 4: Future / Hard (v0.5.0+)

#### Email (EML)
- Text-based MIME format, parseable in AILANG
- Headers (From, To, Date, Subject) → metadata
- MIME multipart → extract text/html body + attachments
- ~200 lines for basic support
- Attachments could be recursively parsed by DocParse

#### DOC/PPT/XLS (legacy binary Office)
- OLE2 compound binary format — very hard to parse from scratch
- Would need a binary parser in AILANG or delegate to conversion tool
- Low priority: these formats are declining

#### LaTeX
- Macro expansion makes full parsing extremely complex
- Could support a useful subset (sections, text, math, tables)
- ~300+ lines of AILANG

## AILANG Stdlib Requirements

Some formats may need stdlib additions. Check with `ailang docs` first.

| Need | Current Status | For Format |
|------|---------------|------------|
| String split on char | `std/string` has `split` | CSV, HTML, MD |
| Regex/pattern matching | Unknown — check `std/regex` | RTF, HTML |
| Character code operations | Unknown — check prelude | CSV quoting |
| Binary/byte operations | `std/fs` has `readFileBytes` | EPUB ZIP |
| Directory listing | May need `std/dir` | Multi-file formats |

If missing, implement as pure AILANG functions or send as AILANG feedback.

## Expanded Benchmark Corpus

### Sources for New Test Documents

#### Immediate (pull from open-source test suites)
| Source | What | Features Covered |
|--------|------|-----------------|
| python-docx fixtures | DOCX files | Headers, footers, footnotes, comments, images |
| python-pptx fixtures | PPTX files | Speaker notes, layouts, charts |
| openpyxl fixtures | XLSX files | Merged cells, formulas, styles |
| docx2python tests | DOCX files | Footnotes, endnotes, headers/footers |

#### Short-term (download curated collections)
| Source | Size | What |
|--------|------|------|
| OfficeDissector corpus | 600MB | ~600 real-world OOXML files |
| GovDocs1 msx-13 subset | Large | 22K government Office 2007 files |
| Enron spreadsheets | Medium | 15K real-world XLS/XLSX files |

#### Generate (programmatic test files)
Create test documents using python-docx/pptx/openpyxl that exercise:
- Every combination of structural features
- Edge cases: empty tables, 100+ heading levels, massive merged regions
- Multi-format: same content in DOCX + ODT + HTML + MD for cross-format comparison

### Target Benchmark Growth

| Version | Office Files | Formats | Features Tested |
|---------|-------------|---------|-----------------|
| v0.1.0 (current) | 18 | DOCX, PPTX, XLSX | Tables, track changes, comments, headers, text boxes |
| v0.3.0 (target) | 40+ | +CSV, MD, HTML | +footnotes, speaker notes, nested lists, metadata |
| v0.4.0 (target) | 60+ | +ODT, EPUB, RTF | +cross-format comparison, edge cases |

## Implementation Plan

### Phase 1: New test documents (v0.3.0)
1. Pull test fixtures from python-docx, python-pptx, openpyxl repos
2. Curate 10-15 most interesting files with diverse structural features
3. Generate golden outputs, add to office benchmark suite
4. Verify 100% baseline on expanded suite

### Phase 2: Trivial format parsers (v0.3.0)
1. Implement `csv_parser.ail` — CSV/TSV → Table blocks
2. Implement `markdown_parser.ail` — Markdown → Block ADT
3. Wire into `main.ail` with file extension routing
4. Add benchmark files for each new format

### Phase 3: Medium format parsers (v0.3.0-v0.4.0)
1. Implement `html_parser.ail` — HTML → Block ADT
2. Implement `epub_parser.ail` — EPUB → Block ADT (reuses html_parser + zip_extract)
3. Implement `rtf_parser.ail` — RTF → Block ADT

### Phase 4: Strategic formats (v0.4.0)
1. Implement `odt_parser.ail` — OpenDocument Text (reuses zip_extract patterns)
2. Implement `odp_parser.ail` — OpenDocument Presentation
3. Implement `ods_parser.ail` — OpenDocument Spreadsheet
4. Cross-format benchmark: same content in DOCX vs ODT, verify identical Block output

## Success Criteria

- 40+ benchmark files across 6+ formats
- All new parsers implemented in AILANG (zero Python parsing code)
- CSV, Markdown, HTML parsers are pure functions (no effects)
- Cross-format tests prove structural fidelity
- `ailang check docparse/` passes with all new modules
