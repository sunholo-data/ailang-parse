# AILANG Parse

[![AILANG Registry](https://img.shields.io/badge/ailang-sunholo%2Failang__parse-blue?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgZmlsbD0id2hpdGUiIHZpZXdCb3g9IjAgMCAxNiAxNiI+PHRleHQgeD0iMiIgeT0iMTMiIGZvbnQtc2l6ZT0iMTMiPkHwnZC+PC90ZXh0Pjwvc3ZnPg==)](https://github.com/sunholo-data/ailang)
[![PyPI](https://img.shields.io/pypi/v/ailang-parse?logo=python&logoColor=white&label=PyPI)](https://pypi.org/project/ailang-parse/)
[![npm](https://img.shields.io/npm/v/@ailang/parse?logo=npm&label=npm)](https://www.npmjs.com/package/@ailang/parse)
[![Go](https://img.shields.io/github/v/tag/sunholo-data/ailang-parse-go?logo=go&logoColor=white&label=Go)](https://github.com/sunholo-data/ailang-parse-go)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-io.github.sunholo--data%2Fparse-1f6feb?logo=anthropic&logoColor=white)](https://registry.modelcontextprotocol.io/v0/servers?search=sunholo)
[![CI](https://img.shields.io/github/actions/workflow/status/sunholo-data/ailang-parse/ci.yml?logo=github&label=CI)](https://github.com/sunholo-data/ailang-parse/actions/workflows/ci.yml)

Universal document parsing in [AILANG](https://github.com/sunholo-data/ailang). Extracts structured content from DOCX, PPTX, XLSX, PDF, and image files into JSON and markdown.

**Office formats** (DOCX, PPTX, XLSX) use deterministic XML parsing — no AI, no cloud, instant results. **PDFs and images** delegate to whatever AI model you plug in (Gemini, Claude, local Ollama). AILANG Parse is AI-agnostic: swap `--ai` to change the backend, zero code changes.

## Install

Requires [AILANG](https://github.com/sunholo-data/ailang) CLI.

```bash
# Clone and symlink
git clone https://github.com/sunholo-data/ailang-parse.git
ln -s "$(pwd)/ailang-parse/bin/docparse" /usr/local/bin/docparse
```

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

# PDF and images (AI auto-enabled)
docparse document.pdf
docparse photo.png

# Options
docparse report.docx describe        # AI image descriptions
docparse report.docx summarize       # AI document summary
docparse scan.pdf --ai gemini-2.5-flash  # Choose AI backend

# Format conversion
docparse report.docx --convert output.html
docparse data.csv --convert report.docx
docparse notes.md --convert slides.pptx

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

## Architecture

```
docparse/
├── types/document.ail           # Block ADT (9 variants)
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

28+ contracts, 50+ inline tests.

## AI Configuration

AILANG Parse uses AILANG's AI effect — any model AILANG supports works:

```bash
docparse scan.pdf --ai gemini-2.5-flash          # Google (default; fast)
docparse scan.pdf --ai gemini-3-flash-preview    # Google (slower; thinking model)
docparse scan.pdf --ai granite-docling           # Local Ollama (free)
docparse scan.pdf --ai claude-haiku-4-5          # Anthropic
```

AI usage is bounded by capability budgets (`AI @limit=30`), so costs are predictable.

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
