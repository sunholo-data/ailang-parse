# CLAUDE.md — AILANG Parse

## Project Purpose

AILANG Parse is a standalone AILANG module for universal document parsing and generation. It extracts structured content from Office formats (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, Markdown, CSV, EPUB, EML, TEX, RTF) deterministically and from PDFs/images via pluggable AI. LaTeX/arXiv parsing resolves `\input`/`\include` recursively with cycle detection, so multi-file papers (Vaswani, BERT, GPT-3) parse end-to-end. It also generates documents in 9 formats (including Quarto Markdown) from parsed content or AI prompts.

This is a production AILANG module, not a demo. Every change must exercise AILANG code paths.

## Project Structure

```
ailang-parse/
├── docparse/              # AILANG modules (keeps docparse/ prefix for imports)
│   ├── types/document.ail # Block ADT (11 variants)
│   ├── services/          # Parser + generator modules
│   └── main.ail           # CLI entry point
├── bin/docparse           # Bash CLI wrapper
├── sdks/                  # Python, JS, Go SDKs
├── data/test_files/       # Real-world test files
└── benchmarks/            # Benchmark infrastructure
```

## Authoring documents in Markdown

Markdown is the input format you can WRITE, which makes it the way to build a
test document with known-expected structure and then check what came out the
other side. Front matter sets title/author; inline formatting, links, images
(local paths are read and embedded), fenced code, blockquotes, nested lists and
tables with alignment/colspan all survive into every output format.

It reaches roughly 70% of the generator surface. Headers, footers, comments and
tracked changes are NOT expressible in markdown — to exercise those, convert an
existing document that has them (e.g. `data/test_files/docx-hdrftr.docx`).

Generating a document and reading its structure back is how the last several
defects were found; green suites did not see any of them.

## AILANG Language & Toolchain Reference

Before writing or modifying AILANG code, load the full references:

```bash
ailang prompt              # Language reference (syntax, types, effects, contracts, patterns)
ailang devtools-prompt     # Dev tools reference (CLI flags, debugging, tracing, packages)
ailang docs --list         # List all stdlib modules
ailang docs <module>       # Show module API (e.g., ailang docs std/string)
```

These are essential — `ailang prompt` is the complete language spec, `ailang devtools-prompt` covers all CLI and tooling.

## Quick Commands

```bash
# Parse a document
./bin/docparse data/test_files/sample.docx

# Convert between formats
./bin/docparse input.docx --convert output.html
./bin/docparse notes.md --convert slides.pptx
./bin/docparse report.docx --convert report.qmd

# AI document generation
ailang run --entry main --caps IO,FS,Env,AI --ai gemini-2.5-flash \
  docparse/main.ail --generate report.docx --prompt "Q1 sales report with revenue table"

# Dev commands
./bin/docparse --check       # Type-check all modules
./bin/docparse --test        # Run inline tests
./bin/docparse --prove       # Z3 contract verification
bash benchmarks/quick_check.sh    # Quick smoke test (~15s)

# After ANY parser or generator change, all three:
uv run benchmarks/run_benchmarks.py --suite office   # 105 files, must be 100%
uv run benchmarks/roundtrip_check.py                 # parse -> md -> parse
uv run benchmarks/verify_generated.py                # generated docs + DOCX grid

# Direct ailang invocation (from repo root)
ailang run --entry main --caps IO,FS,Env docparse/main.ail data/test_files/sample.docx

# With AI (PDF/images)
GOOGLE_API_KEY="" ailang run --entry main --caps IO,FS,Env,AI \
  --ai gemini-2.5-flash docparse/main.ail document.pdf
```
