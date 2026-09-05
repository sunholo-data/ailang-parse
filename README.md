# AILANG Parse

[![AILANG Registry](https://img.shields.io/badge/ailang-sunholo%2Failang__parse-blue?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgZmlsbD0id2hpdGUiIHZpZXdCb3g9IjAgMCAxNiAxNiI+PHRleHQgeD0iMiIgeT0iMTMiIGZvbnQtc2l6ZT0iMTMiPkHwnZC+PC90ZXh0Pjwvc3ZnPg==)](https://github.com/sunholo-data/ailang)
[![PyPI](https://img.shields.io/pypi/v/ailang-parse?logo=python&logoColor=white&label=PyPI)](https://pypi.org/project/ailang-parse/)
[![npm](https://img.shields.io/npm/v/@ailang/parse?logo=npm&label=npm)](https://www.npmjs.com/package/@ailang/parse)
[![Go](https://img.shields.io/github/v/tag/sunholo-data/ailang-parse-go?logo=go&logoColor=white&label=Go)](https://github.com/sunholo-data/ailang-parse-go)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-io.github.sunholo--data%2Fparse-1f6feb?logo=anthropic&logoColor=white)](https://registry.modelcontextprotocol.io/v0/servers?search=sunholo)
[![CI](https://img.shields.io/github/actions/workflow/status/sunholo-data/ailang-parse/ci.yml?logo=github&label=CI)](https://github.com/sunholo-data/ailang-parse/actions/workflows/ci.yml)

Universal document parsing **and generation** in [AILANG](https://github.com/sunholo-data/ailang). Extracts structured content from DOCX, PPTX, XLSX, PDF, and image files into JSON and markdown — and writes documents back out in 9 formats. To author a document, write Markdown and convert it; see [Writing documents in Markdown](#writing-documents-in-markdown).

**Office formats** (DOCX, PPTX, XLSX) use deterministic XML parsing — no AI, no cloud, instant results. **PDFs** default to the deterministic `pdftotext` backend (poppler) — also no AI, no cloud — with `docling` and `liteparse` as local alternatives and pluggable AI (Gemini, Claude, local Ollama) for scanned/image-only pages via `--pdf-backend ai`. **Images** delegate to whatever AI model you plug in. AILANG Parse is AI-agnostic: swap `--pdf-backend`/`--ai` to change the backend, zero code changes.

## Install

```bash
curl -fsSL https://www.sunholo.com/ailang-parse/install.sh | sh
```

Fetches the published package (~400 KB), installs the
[AILANG](https://github.com/sunholo-data/ailang) runtime if you do not have it,
and puts `docparse` on your `PATH`. `--version`, `--prefix` and `--uninstall`
are supported; re-running is a no-op.

That covers every deterministic format. PDF needs two more things, and they are
easy to miss:

```bash
brew install poppler        # pdftotext, the default PDF backend
                            # (apt install poppler-utils on Debian/Ubuntu)
docparse --install-backends # docling + liteparse, for scans and layout
```

`--install-backends` matters even if you never pass `--pdf-backend`: when
`pdftotext` finds no text layer the parser escalates to `docling` on its own, so
without it a **scanned** PDF fails on the default backend. AI backends
authenticate with Google ADC (`gcloud auth application-default login`), not an
API key.

<details>
<summary>Contributors: install from a clone instead</summary>

```bash
git clone https://github.com/sunholo-data/ailang-parse.git
ln -s "$(pwd)/ailang-parse/bin/docparse" /usr/local/bin/docparse
```

The wrapper finds the project root by walking up for `docparse/main.ail`, so it
works from a clone, an installed prefix, or a symlink chain. Note that the CLI
wrapper and the PDF adapter live under `assets/` — the only path the AILANG
publisher bundles verbatim — with symlinks at their historical locations.
</details>

## SDKs

Use AILANG Parse from your language of choice:

```bash
pip install ailang-parse          # Python
npm install @ailang/parse         # JavaScript/TypeScript
go get github.com/sunholo-data/ailang-parse-go  # Go
```

## Quick Start

```bash
# Office documents (deterministic, no AI needed)
docparse report.docx
docparse slides.pptx
docparse spreadsheet.xlsx

# PDF (deterministic pdftotext by default — no AI); images (AI auto-enabled)
docparse document.pdf
docparse photo.png

# Options
docparse report.docx describe        # AI image descriptions
docparse report.docx summarize       # AI document summary
docparse contract.pdf                # PDF: deterministic pdftotext (default)
docparse scan.pdf --pdf-backend ai --ai gemini-2.5-flash  # Scanned PDF needs AI

# Format conversion
docparse report.docx --convert output.html
docparse data.csv --convert report.docx
docparse notes.md --convert slides.pptx
docparse notes.md --convert offer.docx --reference-doc letterhead.docx

# AI document generation
ailang run --entry main --caps IO,FS,Env,AI --ai gemini-2.5-flash \
  docparse/main.ail --generate report.docx --prompt "Q1 sales report with tables"
```

## Output

Every run produces:
- `docparse/data/output.json` — Structured JSON with typed blocks
- `docparse/data/output.md` — LLM-ready markdown

## What AILANG Parse Extracts

| Feature | DOCX | PPTX | XLSX | Best Competitor |
|---------|------|------|------|-----------------|
| Tables with merged cells | Yes | Yes | Yes | Raw OOXML only |
| Track changes (redlining) | Yes | — | — | Pandoc (3/3) |
| Comments (interleaved) | Yes | — | — | Raw OOXML (2/2) |
| Headers/footers | Yes | — | — | Kreuzberg (2/3) |
| Text boxes / VML shapes | Yes | Yes | — | Raw OOXML (1/2) |
| Equations (§22.1) | Yes | — | — | None |
| Field codes (§17.16) | Yes | — | — | Kreuzberg, OOXML |
| Speaker notes | — | Yes | — | None |
| Multi-sheet extraction | — | — | Yes | Kreuzberg |

**OfficeDocBench** (69 files, 11 formats, 7 metrics): AILANG Parse **93.9%** composite with 100% coverage vs nearest competitor 68.0% coverage-adjusted. 8 parsers compared including Raw OOXML, Pandoc, Kreuzberg, MarkItDown, Unstructured, Docling. Scores include aspirational ECMA-376 spec targets that intentionally lower our score.

## Supported Formats

**Parsing (16 formats):** DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, Markdown, CSV, EPUB, EML, MBOX, TEX, RTF, PDF, images (JPG/PNG)

**Generation (9 formats):** DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, Markdown, QMD (Quarto)

### Writing documents in Markdown

Markdown is the input an LLM can write, so it is the practical way to generate a
document: write markdown, convert to any of the nine output formats.

```bash
docparse report.md --convert report.docx
```

What survives the trip: YAML front matter (title/author/date → document
properties), **bold**/*italic*/`code`/~~strike~~ as real character formatting,
links as real hyperlinks, images (local paths are read and embedded), fenced
code blocks, blockquotes, nested lists, thematic breaks, and tables with
alignment and column spans.

Headers, footers, comments and tracked changes have no Markdown syntax; those
are preserved when converting from a document that already contains them.

### Styling a generated DOCX from a template

`--reference-doc` is the Quarto/Pandoc `reference-doc` feature: an existing
`.docx` supplies the look, the Markdown supplies the content.

```bash
docparse annex.md --convert annex.docx --reference-doc letterhead.docx
```

The template's `styles.xml`, `numbering.xml`, theme, embedded fonts, headers,
footers and page setup are applied to the new content. Everything the merge does
not regenerate is carried through byte-for-byte, so the letterhead, logo and
licensed fonts come out exactly as they went in.

What comes from where:

| | |
|---|---|
| Template | page size, margins, headers, footers, page numbering, fonts, theme, colours |
| Your document | the body content, and `docProps/core.xml` (title/author) |
| Merged | `styles.xml` (ours fill only the styleIds the template lacks), `numbering.xml` (our list definitions take ids above the template's), `[Content_Types].xml`, both `.rels` |

Two consequences worth knowing:

- **The template's headers and footers win.** A source document's own headers are
  dropped rather than mixed with the letterhead. The page furniture all lives in
  the template's body `<w:sectPr>`, which is lifted whole.
- **The template's comments are dropped** along with its body, and so are
  `commentsExtended.xml` and `people.xml`. Comments in the *source* document
  still come through.

Two flags refine a multi-section template:

- `--reference-section N` picks which of the template's sections supplies the
  page setup, headers and footers — 1 is the first section, Word's numbering.
  The default is the last section (the body-level one, what the flag-less
  behaviour has always lifted). A multi-section template's wanted furniture is
  often an earlier section's — the master agreement's CONFIDENTIAL footer, not
  the Annex's missing one.
- `--table-style NAME` binds generated tables to a table style the template
  defines (matched on styleId, then style name). Without it, the style named
  `Table` is used if the template has one, else the first table style that is
  not the implicit Normal Table. Under a bound style the generator stops
  emitting its own hardcoded borders — the style carries them.

An unreadable or non-DOCX reference is an error and writes nothing — a silent
fallback to the built-in styling would produce a plausible file missing exactly
the letterhead it was asked for. DOCX output only.

## Architecture

```
docparse/
├── types/document.ail           # Block ADT (11 variants)
├── services/
│   ├── format_router.ail        # Format detection (36 inline tests)
│   ├── zip_extract.ail          # ZIP layer (9 inline tests)
│   ├── docx_parser.ail          # DOCX XML → Blocks (6 inline tests)
│   ├── pptx_parser.ail          # PPTX slides → Blocks
│   ├── xlsx_parser.ail          # XLSX worksheets → Blocks
│   ├── direct_ai_parser.ail     # PDF/image → Blocks (AI)
│   ├── layout_ai.ail            # AI self-healing (optional)
│   ├── output_formatter.ail     # JSON + markdown output
│   └── docparse_browser.ail     # WASM browser adapter
└── main.ail                     # CLI entry point
```

91 contracts, 50+ inline tests. Of the 91, Z3 proves 14 outright; the rest are
checked at runtime under `--prove`/`--verify-contracts` in CI, and skip statically
because parser code is recursive and higher-order, which is outside Z3's
decidable fragment.

## AI Configuration

AILANG Parse uses AILANG's AI effect — any model AILANG supports works:

```bash
docparse scan.pdf --ai gemini-2.5-flash          # Google (default; fast)
docparse scan.pdf --ai gemini-3-flash-preview    # Google (slower; thinking model)
docparse scan.pdf --ai granite-docling           # Local Ollama (free)
docparse scan.pdf --ai claude-haiku-4-5          # Anthropic
```

AI usage is bounded by capability budgets (`AI @limit=200` on `main`), so costs are predictable.

## Dev Commands

```bash
docparse --check       # Type-check all modules
docparse --test        # Run inline tests
docparse --prove       # Static Z3 contract verification
```

## Benchmarks

```bash
uv run benchmarks/run_benchmarks.py --suite office     # Structural (no API, instant)
uv run benchmarks/run_benchmarks.py --suite pdf         # PDF extraction (needs AI)
uv run benchmarks/run_benchmarks.py --competitors       # Compare to Docling etc.
```

See [benchmarks/](benchmarks/) for details.

## License

Apache 2.0
