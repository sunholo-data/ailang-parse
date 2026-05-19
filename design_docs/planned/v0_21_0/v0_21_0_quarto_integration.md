# Quarto Integration — Local Renderer for AILANG Parse

**Status**: PLANNED (2026-05-18)
**Theme**: Make Quarto a first-class output renderer for `./bin/docparse`, using a **locally installed `quarto` binary**.
**Supersedes**: [`v0_10_0/v0_10_0_quarto_integration.md`](../v0_10_0/v0_10_0_quarto_integration.md) — that doc proposed routing through the multivac Cloud Run Quarto service. That strategy is correct for the **API repo** (`ailang-parse-api`), but **not** for this repo. This doc re-scopes for the local CLI.
**Depends on**: `qmd_generator.ail` (Phase 1, shipped in v0.10.0).

## Why this re-scope

The original v0.10.0 plan called any Quarto rendering out to a Cloud Run service that already exists at `multivac-system-services/quarto/` (used by aitana). That decision still applies to the deployable API — adding a Quarto binary to the API Docker image (~500MB with TinyTeX) doesn't make sense when there's a dedicated, battle-tested service already running.

`ailang-parse` is the **library/CLI** repo. The constraints are different:

| Concern | API repo | This repo |
|---|---|---|
| Deployment surface | Cloud Run container | User's laptop / CI runner |
| Network expectations | Has internet, has GCP auth | May be offline, no GCP |
| Image size budget | Tight (cold-start) | N/A |
| Who installs Quarto | Service operator | User |
| Latency tolerance | Variable (HTTP RTT) | Sub-second expected |

The CLI should call the user's local `quarto` binary via AILANG's `std/process.exec`. If `quarto` isn't installed, we print a friendly install hint and exit non-zero. No fallback, no degraded mode — per the project's [no-fallbacks rule](../../../CLAUDE.md).

## Current state (what shipped in v0.10.0 Phase 1)

- [`docparse/services/qmd_generator.ail`](../../../docparse/services/qmd_generator.ail) — 250 lines, generates Quarto Markdown from the Block ADT (front matter, pipe/grid tables, CriticMarkup, callout divs for sections).
- `--convert *.qmd` wired in [`main.ail:1312`](../../../docparse/main.ail#L1312) and the MCP tool at [`services/mcp/tools.ail:364`](../../../docparse/services/mcp/tools.ail#L364).
- Smoke-verified: `./bin/docparse data/test_files/pandoc_basic.pptx --convert /tmp/x.qmd && quarto render /tmp/x.qmd --to html` produces a valid HTML page.

## What's missing (this doc's scope)

1. **No `--via quarto` flag** — once we generate the QMD, we drop it on disk. The interesting outputs (PDF, EPUB, RevealJS) require shelling out to `quarto render` and we don't.
2. **No `quarto_render.ail` service module** — needs to own `std/process.exec`, the binary-presence check, the format allowlist, and the error surface.
3. **No QMD parser (input)** — closes the roundtrip story (`docx → qmd → edit → pptx`). Out of scope for this doc; tracked separately.
4. **Images embedded as base64 data URIs** — works for HTML, partially works for DOCX (Quarto warned during testing), poor for PDF. The design doc planned `assets/` extraction; this doc commits to it.
5. **Zero golden coverage** — 93 golden files in `benchmarks/office/golden/`, zero `.qmd` outputs. Easy to regress silently.
6. **Quarto-flavor features the generator skips** — math (`$...$`), citations (`@key`), cross-refs (`{#fig-x}`, `{#tbl-y}`), exec code blocks, raw blocks. These map onto specific Block variants we don't yet emit them for.

## AILANG capabilities — confirmed available

- `std/process.exec(cmd, args) -> Result[ProcessOutput, ProcessError] ! {Process}` — see [`std/process.ail`](https://github.com/sunholo/ailang/blob/main/std/process.ail). `ProcessOutput` carries `stdout: bytes, stderr: bytes, exitCode: int, truncated: bool, resolvedPath: string`. Returns `Ok` for every completed process (even non-zero exit); `Err` only for spawn/infrastructure failures.
- Security knobs ship with the language: `--process-allowlist`, `--process-timeout` (default 30s — we'll need to raise this for PDF), `--process-max-output` (default 10MB).
- Existing pattern in the repo: [`docparse/services/pdf_backend_external.ail`](../../../docparse/services/pdf_backend_external.ail) + [`pkg/sunholo/external_backend/runner.ail`](https://github.com/sunholo/ailang-packages/blob/main/packages/external-backend/runner.ail) — clean separation of effectful exec from pure error formatting. `quarto_render.ail` will follow the same shape.

## Architecture

```
┌──────────────────────────┐
│   Input Document          │
│  (DOCX, PDF, PPTX, ...)   │
└────────────┬───────────────┘
             │
             ▼
┌──────────────────────────┐
│   DocParse Parser Layer   │
└────────────┬───────────────┘
             │
             ▼
┌──────────────────────────┐
│      Block ADT            │
└──────┬───────────┬────────┘
       │           │
┌──────▼──────┐  ┌─▼──────────────┐
│ AILANG Gen  │  │ QMD Generator   │
│ (existing)  │  │ (v0.10.0 ship)  │
└──────┬──────┘  └─┬───────────────┘
       │           │
       ▼           ▼
  DOCX / HTML    .qmd + assets/
                   │
                   ▼ (--via quarto)
            ┌──────────────────┐
            │  quarto_render   │  ← NEW MODULE
            │  std/process.exec│     local quarto binary
            └────────┬─────────┘
                     │
                     ▼
            PDF / EPUB / RevealJS / DOCX / HTML
```

## Module: `docparse/services/quarto_render.ail`

```ailang
module docparse/services/quarto_render

import std/process (exec)
import std/bytes (toString)
import std/result (Result, Ok, Err)
import std/string (length, contains)
import std/list (any)
import std/fs (fileExists)

-- Discriminated error states. Each carries enough context for a caller to
-- decide whether to fail loud, print install hint, or surface stderr.
--
-- NotInstalled     — `quarto` binary not on PATH (most common first-run failure)
-- UnsupportedFmt   — caller asked for a format we don't whitelist
-- RenderFailed     — quarto ran but exited non-zero; stderr is captured
-- SpawnFailed      — infrastructure failure: timeout, perms, allowlist
export type QuartoError =
  | NotInstalled
  | UnsupportedFmt(string)
  | RenderFailed({code: int, stderr: string})
  | SpawnFailed(string)

-- Pure: render a human-readable error for logging.
export pure func formatQuartoError(err: QuartoError) -> string =
  match err {
    NotInstalled =>
      "quarto not found on PATH. Install from https://quarto.org/docs/get-started/",
    UnsupportedFmt(f) =>
      "unsupported quarto format: '${f}' (allowed: html, pdf, docx, pptx, epub, revealjs, typst)",
    RenderFailed(e) =>
      "quarto render exited ${show(e.code)}; stderr: ${e.stderr}",
    SpawnFailed(msg) =>
      "could not invoke quarto: ${msg}"
  }

-- Whitelist of formats we pass through to `quarto render --to <fmt>`.
-- Anything else is rejected before we touch the subprocess.
pure func isAllowedFormat(fmt: string) -> bool =
  any(\f. f == fmt, ["html", "pdf", "docx", "pptx", "epub", "revealjs", "typst"])

-- Probe whether quarto is on PATH. Single fast exec; returns true iff
-- the binary launches AND exits 0.
export func quartoAvailable() -> bool ! {Process} =
  match exec("quarto", ["--version"]) {
    Ok(out) => out.exitCode == 0,
    Err(_) => false
  }

-- Render a .qmd file to the requested format using the local quarto binary.
--
-- Args:
--   qmdPath:    Path to a .qmd file on disk (caller already wrote it).
--   format:     One of the allowed formats.
--   outputPath: Where quarto writes the result (passed via --output).
--
-- Returns Ok(outputPath) on success, Err otherwise. We do NOT silently
-- substitute formats or fall back — failure is loud per project policy.
export func renderQmd(
  qmdPath: string,
  format: string,
  outputPath: string
) -> Result[string, QuartoError] ! {Process, FS} =
  if !isAllowedFormat(format)
  then Err(UnsupportedFmt(format))
  else if !fileExists(qmdPath)
  then Err(SpawnFailed("input .qmd not found: ${qmdPath}"))
  else
    match exec("quarto", ["render", qmdPath, "--to", format, "--output", outputPath]) {
      Err(_) =>
        -- Distinguish "binary missing" from other spawn failures by
        -- probing PATH on the error branch.
        Err(NotInstalled),
      Ok(out) =>
        if out.exitCode == 0
        then Ok(outputPath)
        else Err(RenderFailed({code: out.exitCode, stderr: toString(out.stderr)}))
    }
```

**Effect surface**: `! {Process, FS}`. Callers compose with `IO` for logging.
**Caps required**: `--caps IO,FS,Process` (Process is new for this codebase outside the PDF backend).
**Timeout**: bump `--process-timeout` to ~120s in the CLI wrapper for PDF/EPUB which invoke TinyTeX.

## CLI surface

Extend [`bin/docparse`](../../../bin/docparse) and [`main.ail`](../../../docparse/main.ail) to accept `--via quarto`:

```bash
# Default: AILANG generators (fast, no deps) — unchanged
./bin/docparse report.docx --convert report.html

# Route through Quarto: PDF / EPUB / RevealJS / better DOCX
./bin/docparse report.docx --convert report.pdf --via quarto
./bin/docparse slides.pptx --convert slides.revealjs --via quarto
./bin/docparse manuscript.docx --convert paper.pdf --via quarto

# Probe (useful in scripts / CI)
./bin/docparse --quarto-check       # exits 0 if quarto is on PATH
```

**Routing rule** (deliberately strict, no surprises):
- Without `--via quarto`: existing behavior. Output extension picks the AILANG generator. `pdf` extension errors (unsupported by AILANG generators).
- With `--via quarto`: we **always** go QMD → quarto, regardless of output extension. The output extension is passed to `--to`. Allowed formats per `isAllowedFormat`. PDF requires `--via quarto`.
- If `--via quarto` is set but `quartoAvailable()` returns false: print `formatQuartoError(NotInstalled)` and exit non-zero.

**Why a flag, not auto-detection**: the user knows which engine they want. Magic that flips between local generators and an external binary based on heuristics is the kind of thing that bites in CI.

## Image asset extraction

`qmd_generator.ail` lines 124–129 currently embed images as base64 data URIs. This is fine for HTML, lossy-to-broken for DOCX/PDF (Quarto warned during testing). Replace with:

- New helper: `qmdWriteAssets(blocks: [Block], assetsDir: string) -> [(BlockId, string)] ! {FS}` — walks blocks, writes each `ImageBlock` to `assetsDir/img_NNN.{png,jpg,...}` using the existing `mime` field, returns a path map.
- `generateQmd(doc)` stays pure; add a sibling `generateQmdWithAssets(doc, assetsDir) -> string ! {FS}` that rewrites image refs to relative paths.
- The CLI sets `assetsDir = <qmdpath>_files/` (Quarto's convention).

Out-of-scope hooks (we'll touch in the QMD generator at the same time, no separate doc needed):
- Emit `$...$` for any future `MathBlock` (currently no such variant — we'd land that with equations work).
- Emit `{#sec-foo}`, `{#fig-bar}`, `{#tbl-baz}` IDs on heading/image/table blocks when present.

## Golden coverage

Add `.qmd` goldens alongside the existing JSON ones. Two layers:

1. **String goldens** — for each test file in `benchmarks/office/golden/`, emit `<name>.qmd` by running the generator. Add a `--qmd` mode to [`benchmarks/generate_golden.sh`](../../../benchmarks/generate_golden.sh). Diff on regen.
2. **Quarto validation** — CI step that runs `quarto check` over generated `.qmd` files. Only runs if `quarto` is on PATH (so contributor laptops without Quarto don't break).

The benchmark `eval_office.py` already structure-checks JSON — add an optional QMD step that:
- Generates `.qmd`,
- If `quarto` is on PATH, runs `quarto render --to html` into a temp dir,
- Asserts non-zero file size, zero stderr `[ERROR]` lines.

## Testing strategy

- **Unit (qmd_generator)** — existing pure tests, extend with cases for the new asset-aware path. Inline tests are blocked by the test-harness bug noted in [CLAUDE.md](../../../CLAUDE.md#known-bugs); drive via `main()` as elsewhere.
- **Integration (quarto_render)** — guarded by `quartoAvailable()`. Skip cleanly when quarto isn't installed.
- **Round-trip** — `docx → qmd → quarto render --to docx` and compare structural checks via the existing eval module. Loose threshold (≥90%); Quarto rewrites a lot of structure even on identity rendering.

## Workflows this unlocks

```bash
# Office → publication PDF (the original v0.10.0 motivation)
./bin/docparse manuscript.docx --convert manuscript.pdf --via quarto

# Spreadsheet → HTML dashboard with proper tables
./bin/docparse financials.xlsx --convert dashboard.html --via quarto

# PowerPoint → RevealJS (web-native presentation)
./bin/docparse slides.pptx --convert slides.html --via quarto

# AI-generated report rendered to publication quality
ailang run --entry main --caps IO,FS,Env,AI,Process --ai gemini-2.5-flash \
  docparse/main.ail --generate report.qmd --prompt "Q1 sales report" \
  && quarto render report.qmd --to pdf
```

## Non-goals (deliberately)

- **No bundled Quarto.** We do not vendor it, do not auto-install it, do not download it on first use. User installs Quarto via the official channel.
- **No Cloud Run fallback.** That belongs to the API repo. If it's useful to share `quarto_render.ail` between repos, we'll factor it into a package later — not today.
- **No QMD as input format.** Tracked separately. This doc is write-side only.
- **No Quarto extensions.** Custom shortcodes (`{{< track-change >}}`) are interesting but additive — out of scope.
- **No `_quarto.yml` project generation.** Single-file render only for v1.

## Implementation phases

| Phase | Deliverable | Effort |
|---|---|---|
| 1 | `quarto_render.ail` module + unit-level smoke from `main()` | 1 day |
| 2 | `--via quarto` flag in `main.ail` + `bin/docparse` | 0.5 day |
| 3 | Asset extraction in `qmd_generator.ail` (images → `_files/`) | 1 day |
| 4 | `--qmd` mode for `generate_golden.sh` + diff in eval_office | 0.5 day |
| 5 | CI: optional `quarto check` step when binary is present | 0.5 day |
| 6 | README + AGENT.md + `prompt_get` mention of `--via quarto` | 0.5 day |

Total: ~4 days. Phases 1–2 are the user-visible win; the rest is hardening.

## Success metrics

- `./bin/docparse <docx> --convert <out.pdf> --via quarto` produces a valid PDF for ≥90% of the office golden corpus.
- `--via quarto` adds zero overhead when not set (no eager `quartoAvailable()` probe).
- QMD output passes `quarto check` for all 93 golden files (under the CI guard).
- Friendly error in <50ms when quarto is not installed and `--via quarto` is set.

## Open questions

1. **PDF engine**: default to `--pdf-engine=typst` (faster, no LaTeX install) or LaTeX (more features, ubiquitous in academic workflows)? Lean: typst, with `--pdf-engine` passthrough.
2. **Passthrough flags**: do we need a generic `--quarto-arg=KEY=VAL` escape hatch for users who want CSL/theme/template control? Probably yes in v2; not v1.
3. **Stdin to quarto**: `quarto render` doesn't read QMD from stdin in any version we tested — we have to write the file. Confirm before locking the API shape.
4. **Asset cleanup**: do we leave `*_files/` next to the output, or clean up after a successful render? Lean: leave it (Quarto convention, user expects).
