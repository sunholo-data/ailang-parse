# AILANG Parse — Architecture Overview

> **One parser to rule them all.** Convert 16+ document formats into a single
> structured representation — deterministically for office files,
> AI-powered for PDFs and media.

## Design Principles

1. **Deterministic first** — Office formats (DOCX, XLSX, PPTX, HTML, CSV) are
   parsed with pure logic. No AI, no network calls, no variance.
2. **AI when needed** — PDFs, images, audio, and video use multimodal AI
   (Gemini or Claude) because their structure can't be extracted mechanically.
3. **One output schema** — Every format produces the same Block ADT. Downstream
   code never cares what the input format was.
4. **Agent-friendly** — The capability manifest at `/api/v1/capabilities` is
   the product surface. Browsers, CLI tools, and AI agents all discover
   features from it.

---

## The Block ADT

All parsed content maps to exactly **9 block types**:

| Block     | Purpose                    | Example                          |
|-----------|----------------------------|----------------------------------|
| `Text`    | Paragraphs, body copy      | Word document paragraphs         |
| `Heading` | Section headers (1–6)      | `# Title` or `<h1>Title</h1>`    |
| `Table`   | Rows × columns with cells  | Excel sheet, HTML `<table>`      |
| `Image`   | Embedded visual content    | DOCX inline image, PPTX shape    |
| `Audio`   | Sound with transcription   | MP3 recording                    |
| `Video`   | Video with description     | MP4 lecture                       |
| `List`    | Ordered or unordered items | Bullet points, numbered steps    |
| `Section` | Logical grouping           | PPTX slide, EPUB chapter         |
| `Change`  | Tracked revision           | DOCX insertion or deletion       |

### Block JSON Structure

```json
{
  "type": "Heading",
  "level": 2,
  "content": "Q3 Revenue Summary",
  "metadata": {
    "style": "Heading2",
    "source_element": "w:p"
  }
}
```

### Table Block (with merged cells)

```json
{
  "type": "Table",
  "headers": ["Region", "Q1", "Q2", "Q3", "Q4"],
  "rows": [
    ["EMEA", "$12M", "$14M", "$16M", "$18M"],
    ["APAC", "$8M", "$9M", "$11M", "$13M"],
    ["Americas", "$22M", "$24M", "$28M", "$31M"]
  ],
  "merged_cells": [
    { "row": 0, "col": 0, "rowspan": 1, "colspan": 1 }
  ]
}
```

---

## Processing Pipeline

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Input   │───▶│   Format     │───▶│   Parser     │───▶│   Output     │
│  File    │    │  Detection   │    │  Execution   │    │  Formatting  │
└──────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                      │                    │                    │
                 MIME type +          ZIP extract +        JSON, Markdown,
                 extension           XML/AI parse         HTML, or A2UI
```

### Stage 1: Format Detection

The **format router** examines:
- File extension (`.docx`, `.pdf`, etc.)
- MIME type from upload headers
- ZIP archive contents (for OOXML and ODF files)

Detection categories:

- **zip-office** → DOCX, PPTX, XLSX
- **zip-odf** → ODT, ODP, ODS
- **epub** → EPUB (ZIP + XHTML)
- **csv** → CSV, TSV
- **markdown** → MD
- **html** → HTML, XHTML
- **pdf** → PDF (AI-required)
- **image** → PNG, JPG, GIF, WebP, TIFF (AI-required)
- **audio** → MP3, WAV, OGG, FLAC (AI-required)
- **video** → MP4, MOV, AVI, WebM (AI-required)
- **eml** → Email messages (EML, MBOX)

### Stage 2: Parser Execution

Each category has a dedicated parser module:

```
docparse/services/
├── docx_parser.ail      # OOXML word processing
├── pptx_parser.ail      # OOXML presentations
├── xlsx_parser.ail      # OOXML spreadsheets
├── odf_parser.ail       # OpenDocument (ODT/ODP/ODS)
├── html_parser.ail      # HTML and XHTML
├── csv_parser.ail       # Delimited text
├── markdown_parser.ail  # CommonMark + GFM tables
├── epub_parser.ail      # EPUB e-books
├── eml_parser.ail       # Email (RFC 5322 + MIME)
└── direct_ai_parser.ail # PDF, images, audio, video
```

### Stage 3: Output Formatting

Blocks can be serialized to four output formats:

| Output     | Use Case                              |
|------------|---------------------------------------|
| **blocks** | Raw JSON — for pipelines and indexing |
| **markdown** | Human-readable — for LLM context    |
| **html**   | Web-ready — for previews and embeds   |
| **a2ui**   | Agent-to-UI — for rich MCP responses  |

---

## Deployment Modes

AILANG Parse runs in three environments:

### Browser (WASM)

```
User drops file → JSZip extracts → WASM parses XML → Blocks rendered
```

- No server needed — runs entirely client-side
- Supports: DOCX, PPTX, XLSX (ZIP-based formats)
- Limits: 20MB files, 100 ZIP entries, 30s timeout
- AI formats available if user provides their own API key

### CLI

```bash
ailang run docparse/ report.docx --output markdown
```

- Full format support including AI parsers
- Batch processing with glob patterns
- Pipe-friendly JSON output

### Cloud API

```bash
curl -X POST https://docparse.ailang.sunholo.com/api/v1/parse \
  -H "Authorization: Bearer dp_your_api_key" \
  -F "file=@report.docx" \
  -F "output=markdown"
```

- Managed service with API key authentication
- Three tiers: Free (1K req/mo), Pro (100K), Business (500K)
- Device auth flow for CLI/SDK integration
- Request replay for debugging and auditing

---

## Performance

Benchmarks on Apple M2 (deterministic parsers):

| Scenario                | Time    | Throughput        |
|-------------------------|---------|-------------------|
| Single DOCX (5KB)       | ~11ms   | 450 KB/s          |
| 5× DOCX sequential      | ~55ms   | 11ms each         |
| 5× DOCX concurrent      | ~26ms   | Near-linear scale |
| 10× mixed concurrent    | ~32ms   | 3.2ms each        |
| Alice in Wonderland EPUB | ~45ms  | 4.2 MB/s          |

Cloud Run handles `concurrency=80` safely with warm response times of 0–10ms.

---

## Key Concepts Glossary

- **Block ADT**: Algebraic Data Type with 9 variants representing document structure
- **A2UI**: Agent-to-UI protocol for rich rendering in agent frameworks
- **Deterministic parser**: Produces identical output for identical input (no AI)
- **Capability manifest**: Machine-readable JSON describing all API features
- **Device auth**: RFC 8628 flow for CLI/SDK authentication without browser redirect
- **Format router**: Module that maps MIME types to parser implementations
- **AILANG**: The programming language that AILANG Parse is written in

---

*Built with [AILANG](https://sunholo.com/ailang) — a language for reliable AI-native systems.*
