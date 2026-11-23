# AILANG Parse — Universal Document Parsing

## Why Use AILANG Parse

You need one tool for every document format. AILANG Parse parses **16 input formats** into **4 structured output formats** — and generates documents in **9** — Office documents in 11ms, PDFs and images via AI, audio and video transcription. No format-specific libraries. No separate OCR pipeline. No inconsistent output schemas.

Every format returns the same block structure: headings, tables, lists, images, sections. Your downstream code handles one schema regardless of whether the input was a DOCX, a scanned PDF, or a video recording.

**Parse anything. Get consistent structure. Move on.**

**For AI agents using the hosted service:** fetch <https://www.sunholo.com/ailang-parse/llms-full.txt> for a single-request reference covering the hosted MCP endpoint, RFC 8628 device authorization flow, and all 7 MCP tools.

## Quick Start (CLI)

```bash
# Install AILANG CLI first: https://github.com/sunholo-data/ailang
# Then:
git clone https://github.com/sunholo-data/ailang-parse.git
cd ailang-parse

# Parse Office documents (deterministic, instant)
./bin/docparse data/test_files/sample.docx

# Parse with AI (PDF, images)
GOOGLE_API_KEY="" ./bin/docparse document.pdf --ai gemini-3.5-flash-lite

# Convert between formats
./bin/docparse report.docx --convert output.html

# Generate documents from prompts
ailang run --entry main --caps IO,FS,Env,AI --ai gemini-3.5-flash-lite \
  docparse/main.ail --generate report.docx --prompt "Q1 sales report with tables"
```

## Installed shims: `docparse` and `docparse-pdf`

`ailang install sunholo/ailang_parse` gives you two commands, no clone needed.
`docparse` handles every deterministic format (DOCX, PPTX, XLSX, ODT, ODP, ODS,
HTML, MD, CSV, EML, EPUB, RTF, …) with `IO,FS,Env` — no subprocess rights.
`docparse-pdf` is the same parser with `Process` added, for the local PDF
backends, which run the bundled Python adapter (`assets/pdf_backends/`) through
`uv run`:

```bash
DOCPARSE_PDF_BACKEND=liteparse docparse-pdf scan.pdf --convert out.md
```

- `pdftotext` (default tier) needs poppler on PATH.
- `docling` / `liteparse` run through `uv run --no-project --with <backend>`,
  an ephemeral environment in uv's cache holding only that backend; first use
  needs network once, later runs reuse the cache.
- AI parsing (`--pdf-backend ai`, `describe`, `summarize`) stays a deliberate
  opt-in through the full `bin/docparse` wrapper with `--ai` — neither shim
  carries the AI capability, so a local-policy "never send the PDF to Gemini"
  rule is enforced by the shim's own capability set.

## Email attachments need the second pass: `--deep` / `deep: true`

EML/MBOX parsing is deliberately two-pass. The first pass is pure and
deterministic: it preserves PDF and Office attachment bytes as base64
`attachment-data` blocks, but it cannot extract their text — reading a PDF
attachment means running the PDF backend ladder, which shells out. The second
pass does that, and it is one parameter away:

- **CLI**: `docparse message.eml --deep` (batch runs: `DOCPARSE_DEEP=1`)
- **Hosted API**: `"deep": true` on the parse request
- **stdio MCP / `parseDocumentPure`**: not available in-process (no Process
  capability in the embedder's caps) — use the CLI or the hosted API

A shallow parse that leaves deep-parseable attachments unresolved says so in
the outcome's `warnings` (which attachment, and how to run the second pass)
on every output surface, so "attachments preserved and recoverable" is never
the only signal. Image attachments are preserved as bytes but never parsed —
`--deep` leaves their data blocks untouched — and `--no-attachment-data`
omits the base64 entirely while keeping `attachment-meta`.

## SDKs

```bash
pip install ailang-parse          # Python
npm install @ailang/parse         # JavaScript/TypeScript
go get github.com/sunholo-data/ailang-parse-go  # Go
```

## What You Get

| Capability | Formats | Speed |
|------------|---------|-------|
| **Office parsing** | DOCX, PPTX, XLSX, ODT, ODP, ODS | 11ms deterministic |
| **Web/text parsing** | HTML, Markdown, CSV, EPUB, EML | 5-15ms deterministic |
| **PDF parsing** | PDF (text + scanned) | AI-powered, any model |
| **Image parsing** | PNG, JPG, GIF, TIFF, WebP | AI-powered, any model |
| **Audio transcription** | MP3, WAV | AI-powered |
| **Video transcription** | MP4 | AI-powered |
| **Document generation** | DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, MD, QMD | Instant |

Office parsing preserves structural details competitors miss: track changes, comments, merged cells, headers/footers, footnotes, text boxes, speaker notes. These aren't extras — they're the data your users created.

## Block Types

All formats return the same block structure:

| Block Type | Description |
|-----------|-------------|
| `Text` | Paragraphs with style metadata |
| `Heading` | H1-H6 with level |
| `Table` | Rows and cells with merge info |
| `Image` | Binary data + MIME type + optional AI description |
| `Audio` | Audio content + transcription |
| `Video` | Video content + transcription |
| `List` | Ordered/unordered items |
| `Section` | Named containers (slides, sheets, chapters) |
| `Change` | Track changes (insertions, deletions) |
| `Link` | Hyperlink with text, href and title |
| `Comment` | Review comment with author, date, anchor and thread parent |

## Authoring comments and track changes from the CLI

`Change` and `Comment` blocks have always been part of the parse schema; two
paths now author them into real Office markup — no second toolchain needed.

**Blocks JSON input.** A parse-output JSON file (`{"document": {"blocks":
[...]}}`, `{"blocks": [...]}`, or a bare block array) passed as the input is
loaded instead of parsed, so the same file that records what a document
contains can produce one:

```bash
# contract.json carries Change and Comment blocks in the parse schema
docparse contract.json --convert contract.docx
docparse budget.json   --convert budget.xlsx    # comments anchored to cells
docparse deck.json     --convert deck.pptx      # comments pinned to slides
```

A `change` block becomes real `<w:ins>`/`<w:del>` revision markup in DOCX
(`changeType` `"insert"`/`"delete"`, with `author` and W3CDTF `date`). A
`comment` block becomes a real comment — a DOCX comment range plus
`word/comments.xml`, an XLSX cell note (`xl/commentsN.xml` + legacy VML shape,
anchored by `anchorText` starting with a cell reference like `"B5"` or
`"B5: cell value"`), or a PowerPoint slide comment (`ppt/comments/commentN.xml`
+ `ppt/commentAuthors.xml`, anchored by `anchorText` starting `"Slide N"` or
`anchorBlockIndex`). Every other block type and field is optional and defaults
the way the parse side writes them; unknown block types are skipped, not fatal.

**CriticMarkup in Markdown.** The parser reads the CriticMarkup convention
(<https://criticmarkup.com>) inside paragraphs, so plain Markdown can carry
revisions with no docparse-specific syntax:

```markdown
The fee is {--10000--}{++12000++} {>>confirm with client<<} net.
```

`{++inserted++}` stays in the paragraph and yields a `Change(insert)`;
`{--deleted--}` leaves the paragraph and yields a `Change(delete)`; `{>>comment<<}`
leaves the paragraph and yields a `Comment` anchored to the surrounding text.
Convert as usual: `docparse review.md --convert review.docx`. The existing
blockquote comment/track-change readback is unchanged and still wins when both
are present.

## AI Configuration

AILANG Parse uses AILANG's AI effect — any model AILANG supports works:

```bash
./bin/docparse scan.pdf --ai gemini-3.5-flash-lite          # Google (default; fast)
./bin/docparse scan.pdf --ai granite-docling           # Local Ollama (free)
./bin/docparse scan.pdf --ai claude-haiku-4-5          # Anthropic
```

AI usage is bounded by capability budgets (`AI @limit=30`), so costs are predictable.

## Why One Schema Matters

Splitting parsing across multiple libraries means multiple output schemas, multiple failure modes, and format-specific handling scattered through your codebase. AILANG Parse eliminates that. A DOCX and a scanned PDF return the same block structure. Your extraction logic, your summarization pipeline, your RAG chunking — they all work on one schema.

Deterministic formats (Office, HTML, CSV) return **identical output every time** — same input, same blocks, byte-for-byte. AI-powered formats (PDF, images, audio, video) return the same schema with model-dependent content.
