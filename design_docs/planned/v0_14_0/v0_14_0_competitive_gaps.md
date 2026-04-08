# v0.14.0 — Closing Competitive Format & Feature Gaps

**Status**: Planned
**Target version**: 0.14.0
**Source**: Competitive audit run 2026-04-08 against Unstructured, Docling,
LlamaParse, MarkItDown, Kreuzberg, Pandoc on OfficeDocBench v1.

## Goal

Close the small set of file-format and structural-feature gaps where at least
one mainstream competitor offers something AILANG Parse currently does not, in
the order that gives us the largest defensibility-per-week-of-work.

This doc is **prioritization, not implementation detail**. Each item gets its
own follow-up design doc when picked up.

## Background

After fixing the OfficeDocBench fairness issues in the competitor adapters
(driving each adapter the way its own documentation recommends — see commit
history for `benchmarks/officedocbench/adapters/` around 2026-04-08), AILANG
Parse leads the leaderboard at 93.9% adjusted vs Kreuzberg at 68.0%.
The lead is real and durable on the **structural Office** axis we already
target, but two flanking risks remain:

1. **Format breadth**: Kreuzberg, Unstructured and MarkItDown each handle
   formats we don't (RTF, .msg, .ipynb, iWork, RST, etc.). A reader scanning
   feature matrices will see "supports X" / "doesn't support X" without ever
   looking at quality.
2. **Structural depth**: Several features are within reach via the same
   ECMA-376 XML we already parse but are not yet surfaced (chart data, content
   controls, comment threads, conditional formatting). These are pure
   differentiators — competitors mostly cannot do them at all.

## Rubric

Each item is scored on:

- **Effort**: Low (≤ 1 day), Medium (2–5 days), High (> 1 week)
- **Strategic value**: how much it strengthens the "use AILANG Parse instead
  of X" pitch, weighted toward enterprise/legal/AI-pipeline buyers
- **Defensive vs offensive**: defensive = closes a gap a competitor exploits;
  offensive = creates a moat nobody else has

Items selected for v0.14.0 must be Low/Medium effort. High-effort items
(legacy binary Office, Apple iWork) are deferred to a future version with
their own design doc.

## In scope — Formats

Three new format parsers, all reading the existing FS effect, no new
dependencies, pure AILANG.

### F1. RTF (`.rtf`) — `docparse/services/rtf_parser.ail`

| | |
|---|---|
| **Effort** | Low |
| **Value** | High |
| **Type** | Defensive |

RTF is a token stream of `\controlword[N] text` groups inside `{ }` braces.
A small recursive descent over the brace structure plus a control-word table
(`\par`, `\b`, `\i`, `\fonttbl`, `\trowd`/`\cell`/`\row` for tables,
`\pict` for images) yields a Block stream that maps directly onto our existing
ADT. No external libraries.

Why it matters:

- Common in legal and enterprise document workflows.
- macOS TextEdit's default rich-text format.
- The body of an Outlook `.msg` is frequently RTF — landing this first
  unblocks F3.
- Kreuzberg, Unstructured, Pandoc, MarkItDown all support it.

Acceptance: parses the 5–10 RTF samples in `data/test_files/`, lands in the
office benchmark, golden output committed, scores ≥ 0.85 composite.

### F2. Jupyter notebooks (`.ipynb`) — `docparse/services/ipynb_parser.ail`

| | |
|---|---|
| **Effort** | Low |
| **Value** | High |
| **Type** | Offensive (audience alignment) |

Notebooks are JSON with a top-level `cells[]` array. Each cell has
`cell_type` (`markdown`, `code`, `raw`), a `source[]` (string array we join),
and `outputs[]` (for code cells: `text/plain`, `text/html`,
`image/png` etc.). Trivial to map onto our `Block` ADT — markdown cells
become Markdown blocks, code cells become Code blocks (new variant or reuse
existing CodeBlock), outputs become Text/Image blocks.

Why it matters:

- Our entire AI-pipeline / LLM-developer audience lives in notebooks. Being
  able to feed `.ipynb` straight into a docparse pipeline is on-brand in a
  way no competitor can match — Kreuzberg and Unstructured technically
  support it but as a curiosity, not a first-class story.
- Differentiates us from the "old enterprise" parsers (Pandoc, Unstructured)
  on "modern dev workflows."
- Pairs naturally with our planned RAG features in v0.13.0.

Acceptance: parses notebooks containing markdown, code, plot outputs,
errors. New OfficeDocBench fixture under `data/test_files/`.

### F3. Outlook `.msg` — `docparse/services/msg_parser.ail`

| | |
|---|---|
| **Effort** | Medium |
| **Value** | High |
| **Type** | Defensive |

Outlook saves messages as Compound File Binary Format (CFBF, aka OLE2) — the
same container as legacy `.doc`/`.xls`. The MAPI properties for body, sender,
recipients, subject and attachments live in known-named streams inside the
container. The body is usually RTF (hence F1 first) or plain text;
attachments are additional sub-storages.

Implementation strategy: write a minimal CFBF reader in AILANG (sector
table, FAT, mini-FAT, directory walk), then extract the standard MAPI
property streams. Spec is well-documented (MS-CFB, MS-OXMSG). No external
libraries.

Why it matters:

- Highest enterprise ROI of the three formats. Email-as-evidence,
  email-archive-search, contract-discovery are real use cases.
- Completes the "email parsing" story alongside our existing EML support.
- Unstructured, Kreuzberg, MarkItDown all handle it.

Acceptance: extracts headers, body (HTML/RTF/text), attachment list with
filenames and content-types from the standard `.msg` test corpus.

### Stretch — ZIP archive walker

~30 lines of glue around the existing format dispatch: open the zip, recurse
into each entry, return a flattened or grouped Block stream. CLI demo:
`docparse archive.zip` dumps everything inside. Low effort, good
demo/marketing value, no real architectural risk. Land this as a single PR
after F1–F3.

## In scope — Structural Features

Five structural-feature additions that reuse the existing OOXML unzip-and-walk
pipeline. All are deterministic — no AI involvement.

### S1. Chart data extraction (DOCX/PPTX/XLSX)

| | |
|---|---|
| **Effort** | Medium |
| **Value** | Very High |
| **Type** | Offensive (moat) |

Charts in OOXML files live as `chart*.xml` parts referenced from
`drawing*.xml`. The series, categories and values are stored as plain XML,
not as a rendered image. We can extract structured chart data
(`{type, title, series: [{name, categories, values}]}`) without ML.

This is the single highest-leverage offensive feature. Docling explicitly
defers chart understanding to "VLMs coming soon"; LlamaParse charges for
`extract_charts` premium-mode. We can be **deterministic, free, and faster**
on the same workload.

Acceptance: new `Block::Chart` ADT variant, extracted from `chart*.xml` in
all three OOXML format parsers. New benchmark fixture with line, bar, pie,
scatter charts. Cited by docs alongside the existing track-changes story.

### S2. Threaded comment replies (DOCX)

| | |
|---|---|
| **Effort** | Low |
| **Value** | High |
| **Type** | Offensive |

Word 2016+ stores parent/child reply chains in
`word/commentsExtended.xml` alongside the existing `word/comments.xml`.
We already unzip and read `comments.xml` in the docx parser; adding
`commentsExtended.xml` is one more part read and a small data-structure
change to thread the existing flat list.

Why it matters:

- Legal and editorial review workflows revolve around comment threads,
  not flat comments.
- No competitor handles this well — even Pandoc drops comments entirely.
- Tiny code change relative to user-visible value.

Acceptance: existing `Comment` block gains `parent_id` and `replies[]`;
benchmark fixture with a 3-deep comment thread; docs page on `comments.html`
updated to lead with thread support.

### S3. Content controls / Structured Document Tags (`w:sdt`)

| | |
|---|---|
| **Effort** | Low–Medium |
| **Value** | High |
| **Type** | Defensive + offensive |

`w:sdt` blocks are how Word templates carry semantic field metadata — `tag`,
`alias`, `placeholder`, databinding to custom XML parts. They are the
foundation of contract-automation, form-fill, and SharePoint-bound document
templates.

Audit task first: check what `docparse/services/docx_parser.ail` currently
does with `w:sdt`. If it walks through into the run content, the SDT
metadata is being silently dropped. The fix is to emit a `Block::ContentControl`
wrapper or attach SDT metadata to existing blocks.

Why it matters:

- Contract automation is a real enterprise market segment that buys
  document-parsing tools specifically.
- Nobody handles content controls cleanly.

Acceptance: docx parser emits SDT metadata, new fixture, scoring dimension
added to OfficeDocBench under feature_detection.

### S4. XLSX data validation + conditional formatting

| | |
|---|---|
| **Effort** | Medium |
| **Value** | High |
| **Type** | Offensive |

XLSX stores data validation rules in `<dataValidations>` inside each
worksheet, and conditional formatting rules in `<conditionalFormatting>`.
Both are pure XML, no calculation engine needed. Surfacing these as
structured metadata on the Block::Sheet variant would unlock spreadsheet
audit / financial-controls use cases.

Audit task: confirm what the current `xlsx_parser.ail` emits — formulas
likely yes, validation/conditional formatting unlikely.

Acceptance: XLSX block gains `data_validations[]` and
`conditional_formatting[]`, benchmark fixture, ECMA-376 §18.3.1.32 cited.

### S5. PPTX slide masters / themes

| | |
|---|---|
| **Effort** | Low–Medium |
| **Value** | Medium |
| **Type** | Offensive (synergy with generation) |

PPTX `slideMaster*.xml` and `theme*.xml` carry brand colors, font schemes
and master layouts. Surfacing these would let our **document generation**
side regenerate brand-consistent slides — a story competitors literally
cannot tell because they don't generate.

Lower priority than S1–S4 because the value depends on generation, not
parsing alone. Schedule alongside any future generation-side work.

## Out of scope (deferred)

The competitive audit also surfaced these, but they don't fit in v0.14.0:

- **Apple iWork (`.pages`/`.key`/`.numbers`)** — IWA protobuf is genuinely
  hard. Defer to v0.16.0+ with its own design doc. Only Kreuzberg supports
  these reliably and even they have caveats.
- **Legacy binary Office (`.doc`/`.ppt`/`.xls`)** — high effort (proprietary
  binary records, OLE compound storage) for diminishing returns. The
  conventional fix in this space is to shell out to LibreOffice; we should
  do the same as a v0.15.0 ergonomic feature, not reimplement.
- **LaTeX (`.tex`)** — Docling owns this niche; building a real TeX
  parser is a multi-week project for a small audience.
- **Audio/video transcription wrappers** — MarkItDown does this but it's
  fundamentally a different product surface. We already have pluggable AI
  for PDF/images; if we want transcription, plug Whisper/Gemini in via the
  existing AI effect rather than building bespoke wrappers.
- **OneNote, Visio, Project, MHT, vCard, ICS** — no competitor does these
  well, no buyer demand evident. Skip.
- **SmartArt as structured graph** — `diagrams/data*.xml` is parseable but
  the audience is small. Park.
- **Embedded OLE objects** (Excel-in-Word, etc.) — tempting differentiator
  but overlaps heavily with the binary-Office work above. Defer until that
  story is in place.

## Sequencing

Within v0.14.0, ship in this order so each item de-risks the next:

1. **F1 — RTF** (Low effort, unblocks F3)
2. **F2 — Jupyter** (Low effort, parallelizable with F1)
3. **S2 — Comment threads** (Low effort, single-file change in docx_parser)
4. **S3 — Content controls** (audit + small change in docx_parser; bundles
   with S2)
5. **S1 — Chart data** (the offensive moat — biggest investment, but built
   on top of the same OOXML drawing-walk that S3 touches)
6. **F3 — `.msg`** (Medium effort, leans on F1 for body parsing)
7. **S4 — XLSX validation/conditional formatting** (independent)
8. **S5 — Slide masters/themes** (only if generation-side work is
   landing in the same release)
9. **Stretch — ZIP walker** (one PR, ship after everything else)

A natural cut line for v0.14.0 is items 1–6, with 7–9 sliding to v0.14.1 or
v0.15.0 depending on actual velocity.

## Success criteria

v0.14.0 ships when:

- All items 1–6 above are merged with golden outputs and benchmark coverage.
- OfficeDocBench composite score does not regress (still ≥ 93%).
- Three new format parsers are listed in the workbench dropzone, the
  website feature matrix, and the SDK supported-formats endpoint.
- The benchmark page mentions chart extraction and comment threads as
  AILANG-Parse-only features.
- A short release post on `docs/blog/` covers the new formats and the
  chart-extraction moat.

## Open questions

1. Should `.ipynb` cells with `code` outputs become a new `Block::Code`
   variant or reuse existing `Block::CodeFence`? Pick during S2 audit of the
   ADT.
2. Chart extraction: do we surface the underlying values as a CSV-shaped
   `Block::Table` (lossy but searchable) or as a typed `Block::Chart` with
   series objects (richer but more SDK surface)? Pick when starting S1.
3. CFBF reader for `.msg`: do we vendor it as a small AILANG library under
   `docparse/services/_cfbf.ail` for reuse with future binary-Office work,
   or keep it inlined? Vendoring is the right call if we expect to revisit
   `.doc`/`.xls`.
