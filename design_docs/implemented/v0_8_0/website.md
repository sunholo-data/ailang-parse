# DocParse Website — Three-Area Static Site Design

**Status**: Implemented (19 pages shipped, only try.html WASM demo page remaining)

## Context

DocParse has a deployed API (Cloud Run), WASM browser module, API key management, and a landing page — but no interactive website for users to try parsing, manage API keys, or learn self-hosting. The website needs three areas serving different user personas, all as static HTML on GitHub Pages (no build system).

## Architecture: 4 Static HTML Pages

| Page | Area | Purpose | JS Dependencies |
|------|------|---------|-----------------|
| `docs/index.html` | Landing | Marketing, overview, CTAs to other pages | Scroll reveal only |
| `docs/try.html` | WASM "Try It" | In-browser parsing, zero server | JSZip + AILANG WASM |
| `docs/api.html` | API Playground | Explorer, dashboard, code snippets, MCP/AI integration | Firebase Auth, Prism.js |
| `docs/selfhost.html` | Self-Host Docs | Installation, Docker, AI models, config | Prism.js |
| `docs/benchmarks.html` | Benchmarks | Office structural benchmark, competitor comparison | Prism.js |

**Why not Docusaurus/Hugo?** The existing site is plain HTML with a shared design system CSS. Adding a framework would introduce build complexity for what is essentially 4 pages. The `js/components.js` pattern (inject shared header/footer via DOM) handles shared layout without a build step.

## File Structure

```
docs/
├── index.html                 # Landing (existing, refactored)
├── try.html                   # WASM in-browser parsing
├── api.html                   # API playground + dashboard
├── selfhost.html              # Self-hosting documentation
├── benchmarks.html            # Benchmark results + methodology
├── css/
│   ├── design-system.css      # Existing shared Sunholo CSS
│   └── docparse.css           # NEW: extracted from index.html inline <style>
├── js/
│   ├── components.js          # NEW: shared header/footer/nav injection
│   ├── prism.min.js           # NEW: syntax highlighting
│   ├── firebase-app.js        # NEW: Firebase Auth + key management
│   └── wasm-demo.js           # NEW: WASM file handling + JSZip
├── img/                       # Existing SVG logos
└── vendor/
    ├── jszip.min.js           # ~100KB, ZIP extraction for WASM
    └── firebase/              # Firebase compat SDK (~90KB)
```

## Page Designs

### 1. `try.html` — WASM "Try It" (Privacy-First)

**Hero:** "Parse Documents in Your Browser — No Data Leaves Your Machine"

**Layout:** Split panel — drop zone (left) + tabbed output (right), stacks vertically on mobile.

**Drop Zone:** Drag-and-drop or file picker. Supports DOCX, PPTX, XLSX, ODT, ODP, ODS, EPUB (ZIP-based via JSZip), HTML, MD, CSV (text-based, read directly).

**Output Tabs:** Blocks (rendered HTML), JSON (highlighted), Markdown (plain text).

**Format Info Bar:** Shows detected format, strategy (deterministic/AI), block count, table/heading/change counts.

**PDF/Image with AI:** Users can provide their own Google API key (stored in localStorage, same pattern as ailang-demos). Uses Gemini 2.5 Flash via the WASM AI effect. Settings panel with:
- API key input (saved to localStorage, never sent to our servers)
- Model selector (default: gemini-2.5-flash)
- "Your key is stored locally and used for AI calls only"
- Without a key, PDF/image shows "Add your Google API key in Settings to parse PDFs" with a link to get one

**WASM Integration:** Load AILANG WASM from `sunholo.com/ailang-demos/` (already deployed). JS calls `docparse_browser.ail` exported functions:
- `parseDocxBody(xml)` / `parseDocxSection(xml, kind)` / `parseDocxComments(xml)` for DOCX
- `parsePptxSlide(slideXml)` for PPTX
- `parseXlsxSheet(sheetXml, sharedStringsXml, sheetName)` for XLSX
- `getFormatInfo(filename)` for format detection
- `parseFileFromBase64(base64Data, mimeType, filename)` for PDF/image (requires AI effect + user's API key)
- `parsePdfFromBase64(base64Data, filename)` for PDF specifically
- `describeImageBase64(base64Data, mimeType)` for image description

Graceful fallback: if WASM fails to load, link to `sunholo.com/ailang-demos/docparse.html`.

### 2. `api.html` — API Playground + Dashboard

**Two states based on Firebase Auth:**

**Unauthenticated:**
- Quick start curl example with API URL
- "Sign in to get your API key" CTA
- API Explorer: collapsible cards for each endpoint with description, request format, response example
- Live "Try It" buttons for public endpoints (`/health`, `/formats`) — fetch() directly
- Code snippet tabs: curl, Python, JavaScript for each endpoint
- Unstructured migration guide (swap `server_url`, keep everything else)
- Tier comparison table (free/pro/enterprise)

**Authenticated (Firebase sign-in):**
- Dashboard at top: welcome message, tier, usage bars (requests today, pages this month)
- API Keys table: label, created, status, actions (revoke/rotate)
- Generate New Key modal: label input → POST to Cloud Run → one-time key display with copy button
- API explorer still visible below dashboard

**API URL:** `https://api.parse.sunholo.com`

**Endpoints documented:**
- `GET /api/v1/health` — health check
- `GET /api/v1/formats` — supported formats
- `POST /api/v1/parse` — parse document
- `POST /general/v0/general` — Unstructured compat
- `POST /api/v1/auth/device` — request device code (RFC 8628)
- `POST /api/v1/auth/device/approve` — approve device code (Firebase auth required)
- `POST /api/v1/auth/device/poll` — poll for API key
- `POST /api/v1/keys/list` — list keys
- `POST /api/v1/keys/revoke` — revoke key
- `POST /api/v1/keys/rotate` — rotate key
- `POST /api/v1/keys/usage` — usage stats
- `GET /api/_meta/docs` — Swagger UI (link to live auto-generated docs)
- `GET /api/_meta/openapi.json` — OpenAPI 3.1.0 spec (156 paths)

**AI Integration Guide section — "Connect Your AI":**
Three ways for AI systems to use DocParse:
1. **CLI** — `ailang run --entry main --caps IO,FS,Env docparse/main.ail myfile.docx` (direct invocation, best for scripts/pipelines)
2. **REST API** — standard HTTP calls with `x-api-key` header (best for applications, any language)
3. **MCP Server** — DocParse as an MCP tool server for AI assistants (Claude, etc.) — parse documents as part of AI workflows
- How to configure as MCP server
- Example MCP tool definitions
- Integration with Claude Desktop / Claude Code

**SDK Downloads / Installation section — "Client Libraries":**
- **Python:** `pip install ailang-parse` — thin wrapper around REST API
- **JavaScript/TypeScript:** `npm install @ailang/parse`
- **Go:** `go get github.com/sunholo-data/ailang-parse-go`
- **curl:** raw HTTP examples (already in API explorer)
- Each SDK section: install command, quick start example, link to full docs
- SDKs are thin HTTP wrappers — generate API key, parse files, handle pagination
- Unstructured compatibility: SDKs accept same args as `unstructured-client`

**Note:** A2A (Agent-to-Agent) protocol support is on the roadmap but not included yet.

### 3. `selfhost.html` — "Run It Yourself"

**Layout:** Content page with sticky sidebar ToC (desktop), collapsible ToC (mobile).

**Sections:**
1. Quick Start (3 commands to parse a document)
2. AILANG CLI Installation (binary download, platform support)
3. Docker Image (`docker run` — pre-built image, no build needed)
4. Configuration Reference (env vars, capability budgets)
5. AI Model Configuration (Google, Anthropic, Ollama — bring your own key)
6. Benchmarks (53 golden files, 100% recall, perf baselines)
7. Contact Us (for Cloud/enterprise deployment, consultancy)

**Explicitly NOT included:** Terraform, Cloud Run deployment details, infrastructure setup. Users who want managed cloud deployment contact us; self-hosters get the binary and Docker image.

Content sourced from CLAUDE.md, design docs, and existing README material.

### 5. `benchmarks.html` — Benchmarks Landing Page

**Two benchmark programs:**

**A. Office Structural Benchmark (OfficeDocBench) — our moat:**
- 53 golden files across 10 formats (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, MD, CSV, EPUB)
- Structural checks: tables, merged cells, track changes, comments, headers/footers, text boxes, images, metadata
- 100% baseline across all files
- Competitor comparison: DocParse vs Unstructured vs Docling vs LlamaParse on Office formats
- Interactive results table with pass/fail per check per file
- "Nobody else benchmarks Office parsing quality" — this is the differentiator

**B. PDF Benchmark (OmniDocBench subset):**
- Text ED, Table TEDS, Reading Order metrics
- Multi-model results: Gemini 2.5 Flash (best), Ollama models
- DocParse delegates to AI for PDFs — benchmark measures the AI, not our parsing

**Layout:** Results tables, charts, methodology explanation, "Run it yourself" commands.

**Link to:** benchmark source code in repo (`benchmarks/`), golden files, eval scripts.

### 6. `index.html` — Landing Page (Refactored)

**Changes:**
- Extract inline `<style>` (~946 lines) → `css/docparse.css`
- Extract inline `<script>` → `js/components.js`
- Update nav: add links to Try It, API, Self-Host pages
- Add three CTAs in hero: "Try in Browser" / "API Playground" / "Self-Host"
- Keep all existing sections (formats, capabilities, benchmarks, etc.)

## Shared Components (`js/components.js`)

Injects header + footer into `<div id="header-mount">` / `<div id="footer-mount">` placeholders. Each page includes:
```html
<div id="header-mount"></div>
<!-- page content -->
<div id="footer-mount"></div>
<script src="js/components.js"></script>
```

**Nav:** `[Home] [Try It] [API] [Self-Host] [Benchmarks]` ... `[GitHub] [sunholo.com]`
Active page highlighted based on `window.location.pathname`.
Mobile hamburger at 560px breakpoint.

## Dependencies (All Vendored, No CDN)

| Library | Size | Pages | Purpose |
|---------|------|-------|---------|
| JSZip | ~100KB | try.html | Extract Office XML from ZIP |
| Prism.js | ~20KB | api.html, selfhost.html | Syntax highlighting |
| Firebase SDK | ~90KB | api.html | Auth + ID tokens |
| AILANG WASM | External | try.html | Loaded from sunholo.com/ailang-demos/ |

## Implementation Phases

### Phase 1: CSS extraction + shared components
1. Extract `index.html` inline styles → `css/docparse.css`
2. Create `js/components.js` (header/footer/nav injection)
3. Refactor `index.html` to use external CSS + components.js
4. Verify landing page looks identical
- **Files:** `docs/index.html`, `docs/css/docparse.css`, `docs/js/components.js`

### Phase 2: Self-host docs (`selfhost.html`)
1. Create page with sidebar ToC layout
2. Vendor Prism.js
3. Write content: CLI install, Docker image, config reference, AI models, benchmarks
4. Contact section for cloud/enterprise deployment
- **Files:** `docs/selfhost.html`, `docs/js/prism.min.js`, `docs/js/prism.css`

### Phase 3: API playground (`api.html`)
1. Create page with endpoint explorer cards
2. Add code snippet tabs (curl/Python/JS)
3. Wire live "Try It" for public endpoints
4. Add Unstructured migration guide + tier table
5. AI Integration Guide (CLI / REST API / MCP)
6. SDK section (Python, JS/TS, Go install + quick start)
- **Files:** `docs/api.html`

### Phase 4: Firebase Auth + Dashboard
1. Vendor Firebase JS SDK
2. Create `js/firebase-app.js` (auth flow + key management API calls)
3. Add authenticated dashboard to `api.html`
4. Test key generation flow against Cloud Run
- **Files:** `docs/js/firebase-app.js`, `docs/vendor/firebase/`

### Phase 5: Benchmarks page (`benchmarks.html`)
1. Create page with Office structural benchmark results (53 files, 100% baseline)
2. Competitor comparison tables (DocParse vs Unstructured vs Docling vs LlamaParse)
3. PDF benchmark results (OmniDocBench subset, multi-model)
4. Methodology explanation + "run it yourself" commands
- **Files:** `docs/benchmarks.html`

### Phase 6: WASM Try It (`try.html`)
1. Create page with drop zone + output panel
2. Vendor JSZip, create `js/wasm-demo.js`
3. Implement format-specific parsing (DOCX/PPTX/XLSX/text-based)
4. Output rendering (blocks, JSON, markdown tabs)
5. AI settings panel (Google API key in localStorage for PDF/image)
6. Graceful fallback if WASM unavailable
- **Files:** `docs/try.html`, `docs/js/wasm-demo.js`, `docs/vendor/jszip.min.js`

## Verification

1. `python3 -m http.server 8000 --directory docs/` — serve locally, check all 4 pages
2. Each page loads in <2s on 3G throttle (check DevTools Network)
3. `try.html`: drag a DOCX file, verify blocks render
4. `api.html`: click "Try It" on `/health`, verify live response
5. `api.html`: sign in with Google, generate a key, verify it appears
6. `selfhost.html`: all code blocks syntax-highlighted, sidebar nav works
7. Mobile: all pages usable at 375px width (iPhone SE)
8. No console errors on any page

## Critical Files to Reference

- `docs/index.html` — existing landing page (refactor target)
- `docs/css/design-system.css` — shared Sunholo CSS (reuse variables, cards, breakpoints)
- `docparse/services/docparse_browser.ail` — WASM exports (10 functions, defines JS API contract)
- `docparse/services/api_server.ail` — API endpoint definitions (routes, params)
- `docparse/services/api_keys.ail` — key management endpoints (generate/list/revoke/rotate/usage)
- `design_docs/planned/v0_8_0/v0_8_0_api_keys_cloud_deployment.md` — Firebase Auth flow, dashboard spec
