# Changelog

All notable changes to AILANG Parse are documented here. This changelog is
derived from [design docs](design_docs/README.md) (the authoritative source
for feature context) and git history.

Format: version headers link to git compare views. SDK versions are tracked
separately — see `sdks/` for per-SDK changelogs.

---

## [Unreleased](https://github.com/sunholo-data/ailang-parse/compare/v0.15.1...HEAD)

---

## [0.15.1](https://github.com/sunholo-data/ailang-parse/compare/v0.15.0...v0.15.1) — 2026-05-14

### Added
- **`<picture>` element handling** in [html_parser.ail](docparse/services/html_parser.ail).
  HTML5 responsive-image markup wraps an `<img>` fallback in a `<picture>`
  parent with one or more `<source srcset>` siblings. The browser picks
  one candidate at runtime; for deterministic parsing we recurse into
  `<picture>` and surface the inner `<img>` fallback as a normal
  `ImageBlock`. `<source>` elements have no `src` attribute (only
  `srcset`, which we don't model) so they emit nothing.

  Example: `<picture><source srcset="big.png"><img src="small.png" alt="x"></picture>`
  now produces `ImageBlock(src="small.png", description="x")` instead of
  dropping silently.

  `data/test_files/messy_html5_demo.html` extended with a `<picture>`
  example covering the art-direction pattern; golden refreshed.

### Deferred
- Extending `ImageBlock` with `width`/`height`/`srcset`/`title`/`loading`
  attributes was attempted and reverted: the schema change cascades
  through 13+ files (every parser that constructs `ImageBlock` —
  DOCX/PPTX/ODT/EPUB/Markdown/TeX/AI/a2ui/zip_extract, plus the JSON
  serializer). The blast radius is disproportionate to the value;
  parking until there's a real consumer asking for these fields.

---

## [0.15.0](https://github.com/sunholo-data/ailang-parse/compare/v0.14.1...v0.15.0) — 2026-05-14

### Added
- **`LinkBlock` ADT variant** for HTML anchors. `LinkBlock({text, href, title})`
  captures the visible text and target URL of an `<a href>`. JSON output:
  ```json
  {"type":"link","text":"Try it free","href":"/ailang-parse/","title":""}
  ```
  Every match site that pattern-matches on `Block` gained a sensible
  `LinkBlock` arm:
  - `output_formatter.ail`: JSON serialization + console pretty-print
    (`[link] text → href`) + markdown rendering (`[text](href)`).
  - `html_generator.ail`: round-trips back to `<a href="...">text</a>`,
    preserving `title` if present.
  - `qmd_generator.ail`: markdown link syntax.
  - `odt_generator.ail`: `<text:a xlink:href="...">` proper ODF link.
  - `docx_generator.ail`/`pptx_generator.ail`/`odp_generator.ail`/
    `xlsx_generator.ail`: text downgrade with URL in parens (full
    `<w:hyperlink>` / shape-link round-tripping deferred).
  - `a2ui_formatter.ail`: callout with `href` + `title` metadata.
  - `unstructured_compat.ail`: NarrativeText with `link_urls`
    metadata field (matches unstructured.io's hyperlink schema).
  - `layout_ai.ail`: compact `[link] text → href` representation
    suitable for LLM context.

### Changed
- **HTML parser anchor handling rewritten.** The `<a>` branch now
  treats anchors as HTML5 "transparent" elements: recurses into
  children to surface any block content (images, headings, nested
  structure), and additionally emits a `LinkBlock` when `href` is
  present so the URL is captured.

  Three concrete improvements measured on www.sunholo.com:

  | Metric | v0.14.1 | v0.15.0 | Source |
  |---|---|---|---|
  | Images captured | 4 | **10** | 12 `<img>` in source |
  | Anchor URLs captured | 0 | **31** | 62 `<a href>` in source |
  | LinkBlock support | none | full ADT | — |

  The remaining 2 images / 31 anchors are inside constructs we don't
  yet handle (`<picture>`, anchors with no visible text, etc.).

### Known limitations (not addressed in this release)
- `<img>` attributes beyond `src` + `alt` — `width`, `height`,
  `srcset`, `loading`, `title` — are still ignored. Adding them
  requires extending the `ImageBlock` record, which cascades through
  every parser that constructs `ImageBlock` (DOCX/PPTX/ODT/EPUB/Markdown/TeX).
  Deferred.
- `<picture>` and `<source>` (responsive image art-direction) — not
  yet parsed.
- DOCX/PPTX hyperlink round-trip — the writers currently downgrade
  `LinkBlock` to plain text with the URL in parens. Full
  `<w:hyperlink>` / `<a:hlinkClick>` round-tripping is deferred to a
  future write-back release.

---

## [0.14.1](https://github.com/sunholo-data/ailang-parse/compare/v0.14.0...v0.14.1) — 2026-05-14

### Added
- **Image/audio/video `src` URLs surfaced in JSON output.** Previously,
  the URL was captured into `ImageBlock.data` by HTML/ODT/Markdown/EPUB
  parsers but `output_formatter.ail` only serialized its character
  count (`dataLength`) — the actual URL was thrown away. Inspecting
  parsed output of www.sunholo.com showed image alt text + mime + a
  numeric length, but zero way to recover "where did this image come
  from?" without re-parsing the source. The JSON now emits:
  ```json
  {"type":"image","description":"AILANG Logo","mime":"image/unknown",
   "dataLength":15,"src":"ailang-logo.svg"}
  ```
  The `src` field is **length-gated to 2048 chars**: short URLs/paths
  from HTML, Markdown, ODT, and EPUB surface in the output, while
  DOCX/PPTX inline base64 binary payloads (often megabytes) stay
  represented by `dataLength` alone — emitting them as `src` would
  bloat JSON outputs by orders of magnitude.

  Same change applies to `AudioBlock` and `VideoBlock` for symmetry.

  This is a purely **additive** schema change: existing consumers that
  read `description`/`mime`/`dataLength` continue to work; new
  consumers can opt into the `src` field. Refresh affected goldens
  (`ailang_guide.html`, `test.html`, `messy_html5_demo.html`,
  `sunholo_homepage.html`, `lo_image_mimetype.odt`, `image_vml.docx`,
  `pandoc_inline_images.docx`, `pandoc_basic.pptx`, `officeparser.odt`,
  `officeparser.odp`, `challenge_html_multipart.eml`) — all eval at
  100% against the new shape.

### Known limitations (not addressed in this patch)
- Images nested inside `<a>` tags are still dropped (the anchor branch
  falls through to text-only mode). On www.sunholo.com this loses 8 of
  12 images — they live in `<a class="card"><img></a>` patterns.
- `<a href>` URLs themselves are not captured (62 hrefs on sunholo.com
  → 0 in output). A future `LinkBlock` type or extended `TextBlock`
  with optional `href` would close this.
- `<img>` attributes beyond `src` and `alt` (`width`, `height`,
  `srcset`, `loading`, `title`) and `<picture>`/`<source>` elements
  are not captured. Schema change, deferred.

---

## [0.14.0](https://github.com/sunholo-data/ailang-parse/compare/v0.13.0...v0.14.0) — 2026-05-13

### Changed
- **HTML parser now uses `std/html`** (WHATWG HTML5 spec via Go's
  `golang.org/x/net/html`, shipped in AILANG v0.19.1). The in-repo
  sanitizer pipeline introduced in v0.13.0 — ~475 lines of boolean-
  attribute normalization, tag-stack auto-closing, script stripping,
  conditional-comment stripping, HTML-comment stripping, void-element
  closing, and entity normalization — is **deleted entirely**. Every
  block extractor (`htmlExtractBlocks`, `htmlProcessNode`, `htmlParseTable`,
  `htmlDeepText`, etc.) is unchanged because `std/html` returns the
  same `XmlNode` ADT as `std/xml`.

  Side-effects of switching to a real HTML5 parser:
  - Unicode characters in inline anchors (e.g. `→` in "See how →") are
    now preserved rather than stripped by the entity pipeline.
  - Adjacent inline elements (e.g. "Connect With Us" + `<a>LinkedIn</a>`)
    parse as separate text blocks instead of being concatenated.
  - Document tree shape is the canonical HTML5 tree (always wrapped in
    `<html><head><body>…</body></html>`), which matters only if you
    walked the tree manually — `parseHtml`'s block-list output is
    unaffected.

  Sunholo homepage golden refreshed to reflect the better text
  extraction. All other goldens (test.html, test_complex.html,
  ailang_guide.html, pandoc_nordics.html, pandoc_planets.html,
  messy_html5_demo.html) produce 100%-identical output.

### Requires
- **AILANG ≥ 0.19.1** (was `>=0.12.0`). `std/html` was added upstream
  on 2026-05-13. End-users on AILANG 0.12.x – 0.19.0 must upgrade.

---

## [0.13.0](https://github.com/sunholo-data/ailang-parse/compare/v0.12.9...v0.13.0) — 2026-05-13

### Added
- **Tolerant HTML5 parsing** in [docparse/services/html_parser.ail](docparse/services/html_parser.ail).
  Production HTML pages — sourced from CMSes, scraped websites, HTML email
  templates, and saved browser pages — previously failed deterministic
  parsing because the underlying XML parser is strict and HTML5 is not XML.
  The sanitizer now closes three real-world gaps without an AI fallback:
  - **Boolean attributes** (`<link ... crossorigin>`, `<input disabled>`,
    `<details open>`) are rewritten to `name=""` form for 23 known
    HTML5 booleans (`disabled`, `checked`, `selected`, `readonly`,
    `multiple`, `required`, `autofocus`, `hidden`, `novalidate`,
    `formnovalidate`, `defer`, `async`, `open`, `reversed`, `controls`,
    `autoplay`, `loop`, `muted`, `default`, `ismap`, `nomodule`,
    `crossorigin`, `itemscope`, `playsinline`). Fixed-point iteration
    handles adjacent booleans on the same tag.
  - **Tag-stack auto-closing** walks the token stream maintaining a
    stack of open elements. Stray close tags are dropped; overlapping
    closes (`<p>` closed by `</a>`) trigger implicit closes for
    everything above the target; elements still open at end-of-input
    are closed.
  - **Inline script + conditional-comment stripping** removes
    `<script>...</script>` (JSX, template literals, raw `<`/`&` in JS
    routinely broke the parser) and `<!--[if IE]>...<![endif]-->`
    (HTML email IE-conditionals). HTML comments are now stripped
    rather than left to fail on inner `--`.

  Canonical regression: `curl https://www.sunholo.com` saved at
  [data/test_files/sunholo_homepage.html](data/test_files/sunholo_homepage.html)
  previously produced a single `TextBlock(style: "error")` (XML parse
  failed on the `crossorigin` boolean attribute on line 10). Now
  extracts 13 structured blocks including header, nav, sections,
  h1–h4 headings, lists, and the full footer.

  Well-formed HTML (existing test files: `test.html`, `test_complex.html`,
  `ailang_guide.html`, `pandoc_nordics.html`, `pandoc_planets.html`)
  continues to produce byte-identical output — the tolerant passes are
  no-ops on already-valid input.

  See [v0_13_0_html_tolerant_parsing](design_docs/implemented/v0_13_0/v0_13_0_html_tolerant_parsing.md).

### Known limitations
- Tag-name case-folding (`<P>` → `<p>`) and Word/Office namespace
  stripping (`<o:p>` → `<p>`) are deferred. Real-world impact is
  limited (Word's HTML export is the primary remaining offender;
  `<script>` stripping already handles JSX-style custom-cased React
  components).
- A `std/html` stdlib module wrapping `golang.org/x/net/html` would
  let this whole sanitizer pipeline collapse to a single call. Filed
  as an upstream proposal to the AILANG core.

---

## [0.12.4](https://github.com/sunholo-data/ailang-parse/compare/v0.12.3...v0.12.4) — 2026-04-27

### Added
- **Content-aware format detection** in `format_router.ail`: new `sniffFormat`
  and `resolveFormat` exports plus a `ResolvedFormat` type. The sniffer
  identifies PDF/PNG/JPG/GIF/WAV/WEBP/MP3 via base64-prefix and
  DOCX/PPTX/XLSX/ODT/ODP/ODS/EPUB by inspecting ZIP entries
  ([Content_Types].xml for OOXML, mimetype for ODF/EPUB). `resolveFormat`
  composes extension + content sniffing with a clear precedence so
  callers can confidently route files whose extension is missing,
  ambiguous, or wrong. See [v0_12_4_format_detection_signed_urls](design_docs/implemented/v0_12_4/v0_12_4_format_detection_signed_urls.md).

### Fixed
- **DOCX heading detection** in `docx_parser.ail`: now recognizes the
  space-separated style names some non-conformant tools emit
  (`"Heading 1"` in addition to `"Heading1"`) and maps Word's `Title` /
  `Subtitle` styles to H1/H2 instead of body text.

### Bug Reports Addressed
- `msg_20260427_173916_463d1f6b` (aitana-platform v6) — DOCX served via
  signed GCS URL was producing flat-text output. Root cause: when the
  signed-URL fetch saved the file to a temp path that lost or mangled
  the extension, format detection fell back to the generic `unknown`
  category and bypassed the structured DOCX parser. The new
  `resolveFormat` is the building block; the API server in the
  downstream `docparse` repo wires it in to fix the user-facing bug.

---

## [0.9.3](https://github.com/sunholo-data/ailang-parse/compare/v0.9.2...v0.9.3) — 2026-04-08

### Added
- **Markdown+metadata renderer**: new output mode combining clean markdown with
  structured metadata (change attribution, merged-cell annotations)

---

## [0.9.2](https://github.com/sunholo-data/ailang-parse/compare/v0.9.1...v0.9.2) — 2026-04-07

### Added
- **MCP Registry**: publish to MCP registry with CI job, badge, and install docs
- **llms.txt + llms-full.txt**: AI agent discoverability files
- **Workbench polish**: copy-to-clipboard, mini tutorial, full format list in
  dropzone, progress bar during WASM boot, demo set loader

### SDKs (v0.4.1 → v0.4.6)
- MCP registry metadata
- `markdown` text field, `FormatsResult` helpers, `key_info()`
- Fix Python `parse_file` NameError

---

## [0.9.1](https://github.com/sunholo-data/ailang-parse/compare/v0.9.0...v0.9.1) — 2026-04-04

### Added
- **Workbench page**: dedicated multi-file WASM playground with shared frontend module and CI guards
- **R SDK** (v0.4.0): full feature parity with Python/JS/Go SDKs
- MCP modules reorganized into `docparse/services/mcp/` subdirectory
- Shared credential helpers and auto-load saved API key in MCP bridges (SDK v0.3.1)

---

## [0.9.0](https://github.com/sunholo-data/ailang-parse/compare/v0.8.2...v0.9.0) — 2026-04-01

This was a major release spanning website GTM, email parsing, OfficeDocBench v2,
MCP tooling, multipart file upload, and significant frontend/auth work.

### Added — Email Parsing
- Full EML/MBOX email parsing wired into format router
- Attachment chain parsing and thread reconstruction
- Two-pass Office attachment parsing (`--deep` flag)
- HTML email sanitization (non-XHTML, `<style>` blocks, zero-width Unicode)
- Quoted-printable decoder and HTML sanitizer performance optimization
- Z3 contracts on email and HTML parser pure functions
- 3 AILANG-themed email sample files

### Added — OfficeDocBench v2
- 9 ECMA-376 spec-driven scoring dimensions
- Content Fidelity and Structural Quality metrics
- Pandoc + Raw OOXML benchmark adapters
- Kreuzberg v4.7.2 added as competitor (77.2% composite)
- Results: 69 files, 8 parsers, 7 metrics

### Added — MCP & Agent Tooling
- MCP stdio bridge in JS SDK
- MCP auth, billing, and estimate tools for agent self-discovery

### Added — SDKs (v0.2.0 → v0.3.0)
- `parse_file` / `parseFile` / `ParseFile` multipart upload methods
- Device auth helpers: `client.device_auth()` across Go, Python, JS
- Key persistence: auto-save/load credentials across sessions
- Integration tests for multipart upload and Unstructured compat

### Added — Website & Frontend
- GTM Phases 1-3: messaging cleanup, WASM demo, funnel, comparison table
- A2UI tab: rich document rendering with streaming animation
- Format-specific landing pages (DOCX, XLSX, PPTX, PDF, HTML)
- Dedicated pricing page with build-time price stamping
- Frontend design refresh: distinctive identity, sidebar consistency
- FirebaseUI multi-provider sign-in (email magic link, avatar, sign-out)
- `?env=test|dev|prod` support for Firebase auth and API URLs
- Privacy policy, terms of service, DPA, beta badge

### Added — Parser Improvements
- Batch mode, folder parsing, and Windows CLI for docparse
- Nested SDT element handling in DOCX parser
- Strip Wingdings/symbol font PUA characters from DOCX output
- AILANG native string builtins for email/HTML parsing performance
- HTML deep text extraction: whitespace insertion, newline collapsing
- Case-insensitive file extensions
- Large PDF optimization: upload once, reference by URI (Gemini Files API)
- PPTX large file fix (50 MB in 9.4s), hardened XLSX memory

### Changed
- 10x request limits, reframe daily as rate limit
- Boost free tier to 2,000 req/month
- Rebrand selfhost page as "Install" / "Run Locally"
- Honest speed claims: sub-second for WASM, sub-ms for CLI
- XLSX parser: use `std/map`, `scanFold`, `parseFold` from new AILANG stdlib

### Fixed
- npm publish: OIDC trusted publishing with pinned npm@11.5.0
- JS SDK multipart file upload in ESM contexts
- A2UI export, WASM binary, call pattern fixes
- Firebase auth: apiKey auth, cached key clearing, dashboard paths

---

## [0.8.2](https://github.com/sunholo-data/ailang-parse/compare/v0.8.1...v0.8.2) — 2026-03-17

### Fixed
- AILANG_REGISTRY_VALIDATOR secret in publish workflow
- Repo URLs in SDK manifests (`docparse` → `ailang-parse`)
- Use `astral-sh/setup-uv@v4` in all workflows

---

## [0.8.1](https://github.com/sunholo-data/ailang-parse/compare/v0.8.2...v0.8.1) — 2026-03-17

### Added
- AILANG package publish workflow for registry releases

---

## 0.8.0 — Platform & Ecosystem (March 2026)

- **API keys & Cloud deployment**: Terraform, Firestore, Firebase Auth
- **Agent-friendly API**: capabilities manifest, typed errors, device auth, pricing, tools
- **SDKs**: Python v0.1.3 (PyPI), JS v0.1.3 (npm), Go SDK
- **Website**: 19-page static site on GitHub Pages
- **API playground**: in-browser with Firebase auth, code gen, response panel
- **OfficeDocBench**: AILANG Parse 96.6% vs Unstructured 63.4%, Docling 63.4%, LlamaParse 53.6%
- **Gemini Files API**: upload once, reference by URI for large PDFs
- **WASM threat model**: keep open — Office parsing is costless funnel
- Design docs: [API Keys](design_docs/implemented/v0_8_0/api_keys_cloud_deployment.md) | [Agent API](design_docs/implemented/v0_8_0/agent_friendly_api.md) | [Auth](design_docs/implemented/v0_8_0/auth_security.md) | [SDKs](design_docs/implemented/v0_8_0/sdks.md) | [Website](design_docs/implemented/v0_8_0/website.md) | [Playground](design_docs/implemented/v0_8_0/api_playground.md) | [Ecosystem](design_docs/implemented/v0_8_0/ecosystem.md)

## 0.7.0 — API Server

- REST API via `ailang serve-api` with `@route` annotations
- Unstructured API drop-in compatibility (`POST /general/v0/general`)
- Auto-generated OpenAPI spec + Swagger UI, 25 smoke tests
- Cloud Run `concurrency=80` safe
- Design doc: [API Server](design_docs/implemented/v0_7_0/v0_7_0_api_server.md)

## 0.6.0 — Document Generation

- Block ADT → file output for 8 formats (HTML, DOCX, PPTX, XLSX, ODT, ODP, ODS, Markdown)
- AI-assisted generation: `--generate output.docx --prompt "Q1 sales report"`
- Cross-format conversion via `--convert` flag
- Design docs: [Generation](design_docs/implemented/v0_6_0/v0_6_0_document_generation.md) | [Features](design_docs/implemented/v0_6_0/features.md) | [Verification](design_docs/implemented/v0_6_0/verification_loop.md)

## 0.5.0 — Spec Coverage & Benchmarks

- ECMA-376 spec coverage audit — 19 gaps closed across Rounds 1-3
- OmniDocBench integration (Text ED 0.183, Table TEDS 0.871)
- Large file performance — DOCX/PPTX/XLSX within tier limits
- Design docs: [Spec Audit](design_docs/implemented/v0_5_0/spec_coverage_audit.md) | [External Benchmarks](design_docs/implemented/v0_5_0/external_benchmarks.md) | [Large File Perf](design_docs/implemented/v0_5_0/large_file_performance.md)

## 0.3.0 — Parser Coverage & Format Expansion

- 13 format parsers (DOCX, PPTX, XLSX, CSV, TSV, Markdown, HTML, EPUB, ODT, ODP, ODS, EML, MBOX)
- All parsers in pure AILANG (zero runtime dependencies)
- 53 golden benchmark files at 100% baseline
- AILANG eval module — 8 structural checks with contracts
- ODT/ODP/ODS native parsing — strategic gap, nobody else does this
- Design docs: [Format Expansion](design_docs/implemented/v0_3_0/format_expansion.md) | [Parser Coverage](design_docs/implemented/v0_3_0/v0_3_0_parser_coverage.md) | [Eval](design_docs/implemented/v0_3_0/ailang_benchmark_eval.md)

## 0.1.0 — Initial Release (March 2026)

- Deterministic Office parsing (DOCX, PPTX, XLSX)
- AI-powered PDF extraction via pluggable models
- 18 golden benchmarks at 100% baseline
- Comment extraction, track changes, headers/footers
- PDF benchmark infrastructure with multi-model support
- Competitor adapter framework (Docling, LlamaParse, Unstructured)
- Design doc: [Implementation Report](design_docs/implemented/v0_1_0/v0_1_0_implementation_report.md)
