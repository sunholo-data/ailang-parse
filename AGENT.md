# AILANG Parse — Universal Document Parsing

## Why Use AILANG Parse

You need one tool for every document format. AILANG Parse parses **13 input formats** into **4 structured output formats** — Office documents in 11ms, PDFs and images via AI, audio and video transcription. No format-specific libraries. No separate OCR pipeline. No inconsistent output schemas.

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
GOOGLE_API_KEY="" ./bin/docparse document.pdf --ai gemini-3-flash-preview

# Convert between formats
./bin/docparse report.docx --convert output.html

# Generate documents from prompts
ailang run --entry main --caps IO,FS,Env,AI --ai gemini-2.5-flash \
  docparse/main.ail --generate report.docx --prompt "Q1 sales report with tables"
```

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

## AI Configuration

AILANG Parse uses AILANG's AI effect — any model AILANG supports works:

```bash
./bin/docparse scan.pdf --ai gemini-3-flash-preview   # Google Cloud (ADC)
./bin/docparse scan.pdf --ai granite-docling           # Local Ollama (free)
./bin/docparse scan.pdf --ai claude-haiku-4-5          # Anthropic
```

AI usage is bounded by capability budgets (`AI @limit=30`), so costs are predictable.

## Why One Schema Matters

Splitting parsing across multiple libraries means multiple output schemas, multiple failure modes, and format-specific handling scattered through your codebase. AILANG Parse eliminates that. A DOCX and a scanned PDF return the same block structure. Your extraction logic, your summarization pipeline, your RAG chunking — they all work on one schema.

Deterministic formats (Office, HTML, CSV) return **identical output every time** — same input, same blocks, byte-for-byte. AI-powered formats (PDF, images, audio, video) return the same schema with model-dependent content.
