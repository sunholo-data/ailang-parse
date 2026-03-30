# CLAUDE.md — AILANG Parse

## Project Purpose

AILANG Parse is a standalone AILANG module for universal document parsing and generation. It extracts structured content from Office formats (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, Markdown, CSV, EPUB) deterministically and from PDFs/images via pluggable AI. It also generates documents in 9 formats (including Quarto Markdown) from parsed content or AI prompts.

This is a production AILANG module, not a demo. Every change must exercise AILANG code paths.

## Project Structure

```
ailang-parse/
├── docparse/              # AILANG modules (keeps docparse/ prefix for imports)
│   ├── types/document.ail # Block ADT (9 variants)
│   ├── services/          # Parser + generator modules
│   └── main.ail           # CLI entry point
├── bin/docparse           # Bash CLI wrapper
├── sdks/                  # Python, JS, Go SDKs
├── data/test_files/       # Real-world test files
└── benchmarks/            # Benchmark infrastructure
```

## Quick Commands

```bash
# Parse a document
./bin/docparse data/test_files/sample.docx

# Convert between formats
./bin/docparse input.docx --convert output.html
./bin/docparse data.csv --convert report.docx
./bin/docparse notes.md --convert slides.pptx
./bin/docparse report.docx --convert report.qmd

# AI document generation (requires --ai flag and AI capability)
ailang run --entry main --caps IO,FS,Env,AI --ai gemini-2.5-flash \
  docparse/main.ail --generate report.docx --prompt "Q1 sales report with revenue table"

# Dev commands
./bin/docparse --check       # Type-check all modules
./bin/docparse --test        # Run inline tests
./bin/docparse --prove       # Z3 contract verification
bash benchmarks/quick_check.sh    # Quick smoke test (~15s)
bash .claude/skills/verify-docs/scripts/verify_only.sh  # Verify generated files

# Direct ailang invocation (from repo root)
ailang run --entry main --caps IO,FS,Env docparse/main.ail data/test_files/sample.docx

# With AI (PDF/images)
GOOGLE_API_KEY="" ailang run --entry main --caps IO,FS,Env,AI \
  --ai gemini-3-flash-preview docparse/main.ail document.pdf
```

## AILANG Conventions

- `module` declarations use `docparse/` prefix (e.g., `module docparse/services/docx_parser`)
- Source must live under `docparse/` relative to working directory
- Type-check before committing: `ailang check docparse/`
- Use `ailang docs <module>` to check stdlib before assuming features are missing
- Set `GOOGLE_API_KEY=""` when using ADC for Vertex AI

## Key AILANG Rules

- `println` is prelude (no import needed) but may need `import std/io (println)` in non-entry modules
- String functions (`substring`, `endsWith`, `find`, `split`, `join`) must be imported from `std/string`
- Inside `{ }` blocks: use semicolons. With `=` bodies: use `in`
- HOFs are function-first, data-second: `map(f, xs)`, `flatMap(f, xs)`, `foldl(f, init, xs)`
- NON-HOFs are data-first: `nth(list, index)`, `concat(xs, ys)`
- `x == false` not `not x` in `ensures` clauses (contract verifier bug)

## Known Bugs

- **Module scoping**: Non-exported internal functions with same name + type across modules collide at runtime. Prefix all internal helpers with module name.
- **Test harness**: Inline `tests [...]` on functions calling stdlib fail with "cannot apply non-function value: nil". Test via `main()` instead.
- **Transitive imports**: Entry module must import all transitive dependencies.

## Contracts & Z3 Verification

28+ contracts across modules. Two verification modes:

- **Runtime**: `ailang run --verify-contracts ...` — checks requires/ensures at runtime
- **Static (Z3)**: `ailang verify <file>` or `./bin/docparse --prove` — proves contracts hold for ALL inputs

Z3 can verify pure functions using operations it models (arithmetic, string length, startsWith, boolean logic). It CANNOT verify contracts involving opaque stdlib functions (sha256Hex, JSON decode, JWT verify, HTTP calls) — those need runtime verification.

Contract patterns: filter bounds (`listLength(result) <= listLength(input)`), 1:1 mapper preservation (`listLength(result) == listLength(input)`), structural invariants, size preservation, implication properties (`result == false || condition`), exhaustive enum returns.

## Auth

| Provider | Auth |
|----------|------|
| Google (Vertex AI) | ADC: `GOOGLE_API_KEY="" ailang run ...` |
| Google (AI Studio) | `GOOGLE_API_KEY=xxx` env var |
| Anthropic | `ANTHROPIC_API_KEY=sk-ant-...` env var |

## Benchmarks

```bash
# Office structural benchmark (no API, instant)
uv run benchmarks/run_benchmarks.py --suite office

# PDF benchmark (needs AI backend)
uv run benchmarks/run_benchmarks.py --suite pdf --ai gemini-2.5-flash

# Competitor comparison (requires optional deps: uv pip install -e '.[competitors]')
uv run benchmarks/run_benchmarks.py --competitors              # all competitors
uv run benchmarks/run_benchmarks.py --competitors docling      # just Docling
uv run benchmarks/run_benchmarks.py --competitors llamaparse   # just LlamaParse
uv run benchmarks/run_benchmarks.py --competitors markitdown   # just MarkItDown

# Regenerate golden outputs after changing parser code
bash benchmarks/generate_golden.sh
```

### Benchmark Philosophy

Most external benchmarks (OmniDocBench, SCORE) are PDF-focused. AILANG Parse won't beat specialized OCR on PDFs — and doesn't try. For PDFs, it delegates to whatever AI model the user plugs in (Gemini, Claude, local Ollama via AILANG's AI effect). The real differentiator is **deterministic structural Office parsing** (track changes, headers/footers, merged cells, text boxes, comments) that competitors miss entirely. AILANG Parse is a pragmatic library.

### Office Structural Benchmark (implemented)

- 18 golden outputs in `benchmarks/office/golden/`
- Checks: tables, merged cells, track changes, comments, headers/footers, text boxes, images, metadata, text Jaccard
- Baseline: 100% across all 18 files
- Run after any parser change to catch regressions

## AILANG AI Integration

AILANG's AI effect abstracts the model provider. Same code works with any backend:

```bash
./bin/docparse scan.pdf --ai gemini-3-flash-preview   # Google Cloud (ADC)
./bin/docparse scan.pdf --ai granite-docling           # Local Ollama (free)
./bin/docparse scan.pdf --ai claude-haiku-4-5          # Anthropic
```

Models are defined in AILANG's `models.yml`. Ollama models use `provider: "ollama"` — no API key needed, runs locally.

## AILANG Structured AI Output

- `std/ai` exports: `call`, `callJson`, `callJsonSimple`
- `callJsonSimple(prompt)` returns raw JSON string — use `decode()` to parse
- **BUG**: `callJson` with multimodal requests corrupts large responses. Use `callJsonSimple` for multimodal.
- **BUG**: `call()` truncates at ~491 chars. Always use `callJsonSimple` for generation.
- Prompt tip: ask for "compact JSON (no whitespace)" to reduce output tokens
