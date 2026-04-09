# Changelog

All notable changes to AILANG Parse are documented here. This changelog is
derived from [design docs](design_docs/README.md) (the authoritative source
for feature context) and git history.

Format: version headers link to git compare views. SDK versions are tracked
separately — see `sdks/` for per-SDK changelogs.

---

## [Unreleased](https://github.com/sunholo-data/ailang-parse/compare/v0.9.3...HEAD)

### SDKs (v0.5.0 → v0.5.3)
- `sourceUrl` field and `ResponseMeta` headers across all SDKs
- Structured error types with machine-readable codes
- Markdown+metadata output support and `Section` type
- `key_id` parameter for `key_info()` across all SDKs
- R SDK: fix R CMD check warnings

### Fixed
- Pages deploy: authenticate GitHub API calls for WASM download
- Bump GitHub Actions to Node.js 24-compatible versions
- Fix setup-uv version (use v7, v8 major tag doesn't exist yet)
- Remove speed claims from docs until AILANG benchmarking is reliable

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
