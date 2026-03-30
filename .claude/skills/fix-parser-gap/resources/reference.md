# Fix Parser Gap — Reference

## Gap Priority Table

### Closed (Round 1 — all at 100%)

| Feature | Spec Section | Format | Parser File | Status |
|---------|-------------|--------|------------|--------|
| Numbering definitions | §17.9 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |
| Styles (custom headings) | §17.7 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |
| Hyperlink URL targets | §17.16.22 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |
| Run formatting (bold/italic) | §17.3.2 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |
| Field display text | §17.16 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |
| XLSX merged cells | §18.3.1.55 | XLSX | docparse/services/xlsx_parser.ail | ✅ 100% |
| Title/Subtitle as headings | §17.7 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |
| Equation text extraction | §22.1 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |

### Closed (Round 2 — all at 100%)

| Feature | Spec Section | Format | Parser File | Status |
|---------|-------------|--------|------------|--------|
| Speaker notes | §19.3 | PPTX | docparse/services/pptx_parser.ail | ✅ 100% |
| PPTX text formatting | §21.1 | PPTX | docparse/services/pptx_parser.ail | ✅ 100% |
| XLSX comments | §18.7 | XLSX | docparse/services/xlsx_parser.ail | ✅ 100% |
| Section breaks | §17.6 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |
| XLSX hyperlinks | §18.3 | XLSX | docparse/services/xlsx_parser.ail | ✅ 100% (already worked) |
| XLSX number formats | §18.8.30 | XLSX | docparse/services/xlsx_parser.ail | ✅ 100% (already worked) |

### Closed (Round 3 — all at 100%)

| Feature | Spec Section | Format | Parser File | Status |
|---------|-------------|--------|------------|--------|
| XLSX formula text fallback | §18.3 | XLSX | docparse/services/xlsx_parser.ail | ✅ 100% |
| Comment ranges | §17.13.1 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |
| Bookmark definitions | §17.13.6 | DOCX | docparse/services/docx_parser.ail | ✅ 100% |

### Open (Round 4 candidates)

| Priority | Feature | Spec Section | Format | Parser File | Gap Score | Spec Pages |
|----------|---------|-------------|--------|------------|-----------|------------|
| P3 | Charts | §21.2 | DOCX/PPTX | — | N/A | pp 3365-3472 |
| P3 | SmartArt/Diagrams | §21.4 | DOCX/PPTX | — | N/A | pp 3494-3602 |
| P3 | XLSX data validation | §18.3 | XLSX | docparse/services/xlsx_parser.ail | N/A | — |
| P3 | Run properties (font/size/color) | §17.3.2 | DOCX | docparse/services/docx_parser.ail | N/A | pp 244-422 |

### Closed (Email — all at 100%)

| Feature | Spec | Format | Parser File | Status |
|---------|------|--------|------------|--------|
| Header extraction (From, To, Subject, Date) | RFC 5322 §2.2 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| Header folding (continuation lines) | RFC 5322 §2.2.3 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| Plain text body extraction | RFC 5322 §2.3 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| Metadata mapping (Subject→title, etc.) | RFC 5322 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| multipart/alternative (text + HTML) | RFC 2046 §5.1.4 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| multipart/mixed (body + attachments) | RFC 2046 §5.1.3 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| Base64 body decoding | RFC 2045 §6.8 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| Quoted-printable decoding | RFC 2045 §6.7 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| RFC 2047 encoded-words in headers | RFC 2047 §2 | EML | docparse/services/eml_parser.ail | ✅ 100% |
| MBOX parsing (multi-message archives) | RFC 4155 | MBOX | docparse/services/eml_parser.ail | ✅ 100% |

## Key File Locations

| File | Purpose |
|------|---------|
| `docparse/services/docx_parser.ail` | DOCX parser (~800 lines) |
| `docparse/services/xlsx_parser.ail` | XLSX parser (~530 lines) |
| `docparse/services/pptx_parser.ail` | PPTX parser (~400 lines) |
| `docparse/services/xml_helpers.ail` | Shared XML utilities |
| `docparse/services/zip_extract.ail` | ZIP file extraction |
| `docparse/services/eml_parser.ail` | EML/MBOX parser (~350 lines) |
| `docparse/types/document.ail` | Block ADT (9 variants) |
| `specs/ecma-376/part1/ECMA-376-1-5th-edition-december-2016-Part1.pdf` | OOXML spec PDF |
| `specs/rfc/rfc5322.txt` | RFC 5322 — Internet Message Format |
| `specs/rfc/rfc2045.txt` | RFC 2045 — MIME Part 1 |
| `specs/rfc/rfc2046.txt` | RFC 2046 — MIME Part 2 (multipart) |
| `specs/rfc/rfc2047.txt` | RFC 2047 — MIME Part 3 (encoded-words) |
| `specs/rfc/rfc4155.txt` | RFC 4155 — MBOX format |
| `design_docs/planned/v0_5_0/spec_coverage_audit.md` | Full gap audit |
| `benchmarks/office/eval_gaps.py` | Gap analysis tool (14 checks) |
| `benchmarks/officedocbench/eval_officedocbench.py` | Full benchmark |
| `benchmarks/officedocbench/ground_truth/` | Hand-verified ground truth |
| `benchmarks/office/golden/` | Golden parser outputs |
| `data/test_files/challenge/` | Challenge test files (18 files) |

## Challenge Files and Expected Behavior

### Round 1

| Challenge File | Tests | What a Correct Parser Should Do |
|---------------|-------|--------------------------------|
| `challenge_styles.docx` | Custom heading styles | ChapterTitle->h1, SectionHeader->h2, Subsection->h3, Title->h1, Subtitle->h2 |
| `challenge_numbering.docx` | Multi-level lists | ListNumber/ListBullet styles -> ListBlock with correct type and nesting |
| `challenge_formatting.docx` | Bold/italic semantics | Run properties preserved as **bold**/*italic* markers |
| `challenge_fields.docx` | Field display text | w:fldSimple display text visible (date, page count, filename) |
| `challenge_hyperlinks.docx` | Hyperlink URLs | r:id resolved to URL via _rels/document.xml.rels |
| `challenge_equations.docx` | OMML equations | m:t text elements extracted from m:oMath |
| `challenge_merged_cells.xlsx` | XLSX merged cells | mergeCells element parsed, correct column spans |
| `challenge_real_world.docx` | Mixed features | Title/Subtitle as headings, lists detected, all features combined |

### Round 2

| Challenge File | Tests | What a Correct Parser Should Do |
|---------------|-------|--------------------------------|
| `challenge_speaker_notes.pptx` | PPTX speaker notes | Notes text from notesSlides/ extracted as SectionBlock(kind: "notes") |
| `challenge_pptx_formatting.pptx` | PPTX bold/italic | a:rPr b/i attributes -> **bold**/*italic* markers |
| `challenge_comments.xlsx` | XLSX cell comments | Comments from xl/comments1.xml with author and cell ref |
| `challenge_page_breaks.docx` | Section breaks | w:sectPr detected as SectionBlock(kind: "section-break") |
| `challenge_hyperlinks.xlsx` | XLSX hyperlinks | URLs from hyperlinks element + rels |
| `challenge_number_formats.xlsx` | XLSX number formatting | Dates, percentages, currency formatted correctly |

### Round 3

| Challenge File | Tests | What a Correct Parser Should Do |
|---------------|-------|--------------------------------|
| `challenge_formula_cached.xlsx` | XLSX formula text fallback | Show formula text (=B2+C2) when cached value is empty |
| `challenge_comment_ranges.docx` | DOCX comment ranges | Comment blocks include annotated text from w:commentRangeStart/End |
| `challenge_bookmarks.docx` | DOCX bookmark definitions | w:bookmarkStart names emitted as SectionBlock(kind: "bookmark") |

## AILANG Parser Patterns

### Reading a new XML file from the ZIP
```ailang
-- In the main parse function, extract from ZIP:
let numbering = extractFileFromZip(zipData, "word/numbering.xml")
```

### Processing XML elements
```ailang
pure func extractNumFormat(abstractNum: XmlNode) -> string {
  let lvls = findChildren(abstractNum, "w:lvl");
  let lvl0 = nth(lvls, 0);
  let numFmt = findChild(lvl0, "w:numFmt");
  getOrElse(getAttr(numFmt, "w:val"), "decimal")
}
```

### Important AILANG conventions
- `pure func` for deterministic functions (no side effects)
- `getOrElse(getAttr(node, "attr"), "default")` for optional attributes
- `findAll(root, "tag")` returns list, `findFirst(root, "tag")` returns Option
- `flatMap(f, xs)` for recursive expansion
- Internal helpers MUST be prefixed with module name to avoid name collisions (known bug)
- Import `std/string` for string functions (`split`, `join`, `find`, `substring`, etc.)
- HOFs are function-first: `map(f, xs)`, `flatMap(f, xs)`, `foldl(f, init, xs)`
- NON-HOFs are data-first: `nth(list, index)`, `concat(xs, ys)`
- Generic types use `Option[T]` not `Option<T>`
