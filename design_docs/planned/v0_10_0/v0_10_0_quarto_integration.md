# DocParse Quarto Integration — Parse to QMD, Render via Quarto

**Status**: PLANNED (2026-03-20)
**Theme**: Two rendering engines — AILANG for lightweight generation, Quarto for publication-quality output
**Depends on**: v0.6.0 (document generation), v0.7.0 (API server)

## Motivation

DocParse currently generates documents in 8 formats using pure AILANG generators. These produce structurally correct files, but output fidelity is limited by what raw XML/ZIP manipulation can achieve — styled tables, cross-references, citations, mathematical typesetting, and templated layouts are difficult to build from scratch.

[Quarto](https://quarto.org) is an open-source scientific/technical publishing system that renders `.qmd` (extended Markdown) files to PDF, HTML, DOCX, PPTX, EPUB, and more — with full support for LaTeX math, citations, cross-references, themes, and custom templates. It's the successor to R Markdown and is widely adopted in data science, academia, and technical documentation.

By adding a Quarto-compatible output format, DocParse gains:

1. **Publication-quality rendering** — Quarto handles typography, layout, themes, and PDF via LaTeX/typst
2. **Rich features for free** — citations (BibTeX/CSL), cross-references, callouts, tabsets, code execution
3. **Template ecosystem** — journal templates, corporate themes, book/website/blog projects
4. **Two-engine strategy** — AILANG generators for fast lightweight output, Quarto for polished documents
5. **Roundtrip workflows** — parse any Office doc → QMD → re-render to any Quarto output format

## Design Principles

1. **QMD as the interchange format** — DocParse's Block ADT maps cleanly to Quarto Markdown
2. **Quarto is optional** — QMD generation works without Quarto installed; rendering requires it
3. **AILANG generates, Quarto renders** — no Quarto dependency in the parsing pipeline
4. **Best of both** — route to AILANG generators for simple output, Quarto for complex/styled output

## Architecture

```
                    ┌──────────────────────────┐
                    │     Input Document        │
                    │  (DOCX, PDF, PPTX, ...)   │
                    └────────────┬───────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │   DocParse Parser Layer   │
                    │   (deterministic/AI)      │
                    └────────────┬───────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │      Block ADT            │
                    │  (structured content)     │
                    └──────┬───────────┬────────┘
                           │           │
              ┌────────────▼──┐   ┌────▼────────────┐
              │ AILANG Gen    │   │ QMD Generator    │
              │ (fast, light) │   │ (blocks → .qmd)  │
              └──────┬────────┘   └────┬─────────────┘
                     │                 │
                     ▼                 ▼
              ┌────────────┐   ┌──────────────────┐
              │ DOCX/HTML/ │   │   .qmd file       │
              │ PPTX/etc.  │   │  + YAML front     │
              └────────────┘   │  + assets/         │
                               └────────┬───────────┘
                                        │
                                        ▼ (optional)
                               ┌──────────────────┐
                               │  Quarto CLI       │
                               │  quarto render    │
                               └────────┬──────────┘
                                        │
                                        ▼
                               ┌──────────────────┐
                               │  PDF / HTML /     │
                               │  DOCX / PPTX /   │
                               │  EPUB / RevealJS  │
                               └──────────────────┘
```

## Block ADT → QMD Mapping

| Block Type | QMD Output |
|-----------|------------|
| `Text` | Paragraph text (with inline formatting: `**bold**`, `*italic*`) |
| `Heading(level)` | `# ` / `## ` / `### ` etc. |
| `Table` | Pipe table or grid table (for merged cells) |
| `Image` | `![caption](path){width=X}` with image extracted to `assets/` |
| `List` | `- ` / `1. ` with nesting |
| `Section` | Div blocks `::: {.section}` or heading hierarchy |
| `Change(insert/delete)` | Custom callout blocks or tracked via CriticMarkup `{++ ++}` / `{-- --}` |
| `Audio` / `Video` | Embedded shortcodes or raw HTML blocks |

### YAML Front Matter Generation

The QMD generator produces appropriate YAML front matter from document metadata:

```yaml
---
title: "Extracted Document Title"
author: "Original Author"
date: "2026-03-20"
format:
  html:
    theme: cosmo
  pdf:
    documentclass: article
  docx:
    reference-doc: template.docx
---
```

## Implementation Plan

### Phase 1: QMD Generator (AILANG module)

**New module**: `docparse/services/qmd_generator.ail`

Core function:

```
fn generateQmd(blocks: List[Block], meta: DocMetadata, opts: QmdOptions): String
```

- Maps Block ADT to Quarto-flavored Markdown
- Generates YAML front matter from metadata
- Extracts images/media to `assets/` directory
- Handles table complexity:
  - Simple tables → pipe tables
  - Merged cells → grid tables with colspan/rowspan spans
  - Wide tables → scrollable div wrapper
- Track changes → CriticMarkup syntax (`{++ inserted ++}`, `{-- deleted --}`)
- Inline styles → Quarto spans: `[text]{.class style="..."}`

### Phase 2: Quarto Rendering (optional, requires Quarto CLI)

**New module**: `docparse/services/quarto_render.ail`

Wraps `quarto render` via AILANG's IO effect:

```
fn renderQmd(qmdPath: String, format: String): String
```

- Checks for Quarto installation, returns helpful error if missing
- Supports all Quarto output formats: `html`, `pdf`, `docx`, `pptx`, `epub`, `revealjs`
- Passes through Quarto options via `_quarto.yml` or front matter

### Phase 3: CLI Integration

Extend the CLI and `--convert` flag:

```bash
# Parse to QMD (no Quarto needed)
./bin/docparse report.docx --convert output.qmd

# Parse → QMD → render via Quarto (Quarto required)
./bin/docparse report.docx --convert output.pdf --via quarto
./bin/docparse data.xlsx --convert dashboard.html --via quarto

# AI-generated documents via Quarto
./bin/docparse --generate report.qmd --prompt "Q1 sales report with charts"
quarto render report.qmd --to pdf
```

### Phase 4: API Integration

New API endpoints:

```
POST /api/v1/convert/qmd     — parse document → return QMD string
POST /api/v1/render/quarto    — parse → QMD → Quarto render → return file
```

The render endpoint requires Quarto installed on the server (Docker image with Quarto + TinyTeX for PDF).

### Phase 5: Quarto Project Templates

Pre-built Quarto project templates for common workflows:

- **Report template** — parsed Office doc → styled PDF report
- **Slide deck template** — parsed content → RevealJS/PPTX presentation
- **Dashboard template** — parsed data → interactive HTML dashboard
- **Book template** — multiple parsed docs → multi-chapter book

## Workflows Enabled

### 1. Office → Publication PDF

```bash
# Parse a DOCX with track changes, render as clean PDF
./bin/docparse manuscript.docx --convert manuscript.qmd
quarto render manuscript.qmd --to pdf
```

Track changes become CriticMarkup, tables get proper LaTeX rendering, images are extracted and referenced.

### 2. Spreadsheet → Data Report

```bash
# Parse Excel data, AI enriches with analysis, render as HTML dashboard
./bin/docparse financials.xlsx --convert report.qmd --ai gemini-2.5-flash
quarto render report.qmd --to html
```

The AI generates narrative around the parsed table data; Quarto renders with interactive tables and charts.

### 3. Presentation Roundtrip

```bash
# Parse PowerPoint, edit as text, re-render
./bin/docparse slides.pptx --convert slides.qmd
# Edit slides.qmd in any text editor
quarto render slides.qmd --to pptx
# Or render as RevealJS for web
quarto render slides.qmd --to revealjs
```

### 4. Multi-Document Assembly

```bash
# Parse multiple sources into a Quarto book project
./bin/docparse chapter1.docx --convert book/chapter1.qmd
./bin/docparse chapter2.pdf --convert book/chapter2.qmd --ai gemini-2.5-flash
./bin/docparse appendix.xlsx --convert book/appendix.qmd
quarto render book/
```

### 5. API Pipeline (Programmatic)

```python
from ailang_parse import DocParse

client = DocParse(api_key="dp_...")

# Parse → QMD in one call
qmd = client.to_qmd("report.docx")

# Or full render if server has Quarto
pdf = client.render("report.docx", format="pdf", engine="quarto")
```

## Quarto vs AILANG Generators — When to Use Which

| Criterion | AILANG Generator | Quarto |
|-----------|-----------------|--------|
| **Speed** | Fast (ms) | Slower (seconds, shells out) |
| **Dependencies** | None | Quarto CLI + optional LaTeX |
| **Output quality** | Structurally correct, basic styling | Publication-quality, themed |
| **PDF support** | No (not implemented) | Yes (via LaTeX or typst) |
| **Math/equations** | No | Yes (LaTeX, MathJax) |
| **Citations** | No | Yes (BibTeX, CSL) |
| **Cross-references** | No | Yes (figures, tables, sections) |
| **Code execution** | No | Yes (Python, R, Julia, Observable) |
| **Templates** | No | Rich ecosystem |
| **Server deployment** | Easy (no deps) | Heavier (Quarto in Docker) |
| **Best for** | Quick conversions, lightweight API | Reports, papers, dashboards, books |

**Default behavior**: `--convert` uses AILANG generators. Add `--via quarto` to route through Quarto. The API auto-selects based on requested features (citations, math → Quarto; simple conversion → AILANG).

## Existing Quarto Infrastructure

### Quarto Cloud Run Service (`multivac-system-services/quarto/`)

A Flask-based Quarto rendering service is already deployed on Cloud Run, used by aitana and other multivac services.

- **Source**: `multivac-system-services/quarto/`
- **Infra**: defined in `multivac-aitana/infrastructure/environments/common/terraform.tfvars`
- **Resources**: 2 CPU, 4Gi memory, max 10 instances, 1500s timeout
- **Service account**: `sa-llmops`, invoked by `sa-emissary`
- **Cloud Build**: triggers on changes to `quarto/**` in `multivac-system-services`

**Endpoint**: `POST /quarto_render`

**Request**:
```json
{
  "content": "# Markdown content\nBody text with **formatting**...",
  "metadata": {
    "title": "Document Title",
    "author": "Author Name",
    "date": "2026-03-20",
    "format": "docx",
    "userId": "user123",
    "subtitle": "Optional subtitle"
  },
  "timestamp": 1714432687000,
  "sender": "system",
  "userName": "user@example.com",
  "bucketName": "target-gcs-bucket"
}
```

**Response** (success):
```json
{
  "status": "success",
  "render": {
    "document_id": "e1b9e2ce",
    "filename": "document.docx",
    "filePath": "output.docx",
    "download_url": "https://storage.googleapis.com/...(signed URL)",
    "gcs_urls": ["gs://bucket/users/user123/.../output.docx"],
    "user_id": "user123",
    "stdout": "",
    "stderr": "Quarto/Pandoc rendering logs"
  }
}
```

**Key implementation details** (`render_quarto.py`, `tools/quart_funcs.py`):
- Generates YAML front matter from `metadata` dict (excluding `format` key)
- For HTML output: adds `html: embed-resources: true` to front matter
- Processes inline SVG → PNG via `cairosvg` (except for PDF format where SVG is kept)
- Processes `<plot>` tags with Plotly-style JSON specs
- Renders via subprocess: `quarto render {file}.qmd --to={format} --output=output.{format}`
- Uploads all rendered files + source QMD to GCS, returns signed download URLs
- Supported formats: `html`, `pdf`, `docx`, `pptx`, `epub`

### Aitana / Multivac Integration

The Quarto service is exposed as a **GenAI agent** (`quarto_test` VAC) in `multivac/config/llm_config.yaml`:

```yaml
quarto_test:
  llm: vertex
  model: gemini-2.0-flash
  agent: quarto
  display_name: Quarto Agent
  tools:
    quarto:
      render: pdf
```

The `QuartoProcessor` class (`quarto_agent.py`) extends `GenAIFunctionProcessor` from the sunholo library and gives Gemini these tools:
- `render_and_upload_quarto(markdown_filename, format)` — render + upload to GCS
- `quarto_command(cmd)` — run arbitrary `quarto` CLI commands
- `write_to_file(text, file_path)` — write `.py`/`.r` files for Quarto script rendering
- `quarto_version()` — check Quarto installation

The API gateway (`endpoints/openapi-run.yaml`) exposes the Quarto VAC at:
- `POST /quarto/vac/quarto_test` — invoke VAC (requires `ApiKeyAuth`)
- `POST /quarto/vac/streaming/quarto_test` — streaming VAC
- `POST /quarto/openai/v1/chat/completions` — OpenAI-compatible endpoint

**Note**: The agent system prompt tells the LLM to use `.py` files (percent format) instead of `.qmd` due to markdown parsing issues in the agent workflow. Direct API calls via `POST /quarto_render` use `.qmd` and work fine.

## Deployment Strategy — Service-to-Service

Rather than bundling Quarto into the DocParse Docker image (~500MB+), DocParse calls the existing Quarto service.

### Architecture

```
┌──────────────────────┐        ┌──────────────────────┐
│  DocParse API        │        │  Quarto Service       │
│  (Cloud Run)         │──POST──│  (multivac-services)  │
│                      │        │                       │
│  1. Parse input doc  │        │  POST /quarto_render  │
│  2. Block ADT        │        │  - Renders QMD        │
│  3. Generate QMD     │        │  - Uploads to GCS     │
│  4. POST to Quarto   │        │  - Returns signed URL │
│  5. Return result    │        │                       │
└──────────────────────┘        └───────────────────────┘
      ↑                                    ↑
      │ docparse SA                        │ sa-emissary
      │                                    │ (existing invoker)
      └──── IAM service-to-service auth ───┘
```

### Options (in priority order)

1. **Call existing Quarto service** (recommended) — DocParse generates QMD content string, POSTs to `/quarto_render` with metadata and format. Service handles rendering + GCS upload. DocParse returns the signed download URL to the user.
2. **Embed Quarto in DocParse** — Self-contained but heavy Docker image. Consider as a "full" image variant for air-gapped deployments.
3. **Client-side only** — API returns QMD string; user renders locally with their Quarto install.

**Recommendation**: Option 1. The Quarto service is already deployed, battle-tested (used by aitana), and maintained. DocParse stays lightweight. The only new requirement is granting DocParse's service account invoker access to the Quarto service.

### End-to-End Conversion Flow

```
User: POST /api/v1/convert  (uploads report.pptx, requests PDF via Quarto)

  → DocParse parses PPTX to Block ADT
  → QMD generator produces markdown string with YAML front matter
  → DocParse POSTs to existing Quarto service:
      {
        "content": "<generated QMD markdown>",
        "metadata": {
          "title": "Parsed from report.pptx",
          "format": "pdf",
          "userId": "dp_user_123"
        },
        "bucketName": "docparse-renders"
      }
  → Quarto service renders PDF, uploads to GCS, returns signed URL
  → DocParse returns signed download URL to user

Total: one API call from the user's perspective
```

### DocParse API Design

New endpoint on the DocParse API:

```
POST /api/v1/convert
{
  "file": <upload>,
  "output_format": "pdf",
  "engine": "quarto",           // or "ailang" (default)
  "quarto_options": {           // mapped to QMD YAML front matter
    "theme": "cosmo",
    "pdf-engine": "typst",
    "csl": "apa.csl"
  }
}

Response (engine=quarto):
{
  "status": "success",
  "download_url": "https://storage.googleapis.com/...(signed)",
  "qmd_preview": "---\ntitle: ...\n---\n\n# First heading...",
  "engine": "quarto",
  "elapsed_ms": 4200
}

Response (engine=ailang):
{
  "status": "success",
  "file": <binary>,
  "engine": "ailang",
  "elapsed_ms": 15
}
```

### Configuration

```bash
# Quarto service URL (Cloud Run service-to-service)
QUARTO_SERVICE_URL=https://quarto-{hash}-ew.a.run.app

# GCS bucket for rendered outputs
QUARTO_RENDER_BUCKET=docparse-renders

# Local dev: fall back to local `quarto render` subprocess
QUARTO_SERVICE_URL=local
```

### IAM Requirements

```bash
# Grant DocParse's SA permission to invoke the Quarto service
gcloud run services add-iam-policy-binding quarto \
  --member="serviceAccount:YOUR_SERVICE_ACCOUNT" \
  --role="roles/run.invoker" \
  --region=europe-west1
```

## Testing Strategy

- **QMD generator unit tests**: Block ADT → QMD string, verify Markdown correctness
- **Roundtrip tests**: DOCX → QMD → DOCX (via Quarto), compare structural similarity
- **Golden outputs**: Add QMD golden files to `benchmarks/office/golden/` for all 18 test files
- **Quarto validation**: `quarto check` on generated QMD files (CI only if Quarto installed)
- **CriticMarkup**: Verify track changes survive parse → QMD → render cycle

## Open Questions

1. **Grid tables vs pipe tables** — Quarto's pipe tables don't support merged cells. Use grid tables always, or only when needed? (Grid tables are harder to read as raw text.)
2. **Image extraction** — Extract to `assets/` relative dir, or embed as base64 data URIs? (Quarto supports both; relative paths are cleaner.)
3. **Quarto extensions** — Should we create a DocParse Quarto extension that adds custom shortcodes for our Block types (e.g., `{{< track-change type="insert" >}}`)?
4. **CriticMarkup support** — Quarto doesn't natively render CriticMarkup. Use a Lua filter, or convert to Quarto's native diff rendering?
5. **Typst vs LaTeX** — For PDF rendering, default to typst (faster, simpler) or LaTeX (more mature)? Could make this configurable.

## Success Metrics

- QMD output passes `quarto check` for all 53 golden benchmark files
- Roundtrip fidelity: DOCX → QMD → DOCX preserves >90% of structural checks
- QMD generation adds <5ms to parse pipeline (string formatting only)
- At least 3 Quarto output formats working end-to-end (HTML, PDF, DOCX)
