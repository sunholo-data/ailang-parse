# AILANG Parse Design Documentation

## Structure

```
design_docs/
├── implemented/              # Changelog — grouped by the version features shipped in
│   ├── v0_1_0/              # Office parsing, PDF pipeline, benchmarks
│   ├── v0_3_0/              # 13 format parsers, ODT/ODP/ODS, eval module
│   ├── v0_5_0/              # Spec audit, external benchmarks, large file perf
│   ├── v0_6_0/              # Document generation (8 formats), verification loop
│   ├── v0_7_0/              # API server & Unstructured compatibility
│   ├── v0_8_0/              # API keys, auth, agent API, SDKs, website, playground,
│   │                        #   ecosystem benchmarks, Gemini Files API, WASM threat model
│   └── v0_9_0/              # Email parsing, MCP server, workbench,
│                            #   OfficeDocBench v2, GTM, markdown+metadata
├── planned/                  # Future features (> v0.9.3)
│   ├── v0_10_0/             # Quarto, trust, PDF pipeline, Ollama, auth providers,
│   │                        #   WASM images, manifest API, friction onboarding
│   ├── v0_11_0/             # Structured extraction (FAST-TRACK)
│   ├── v0_12_0/             # AILANG package registry
│   ├── v0_13_0/             # RAG pipeline (chunking, hierarchy, embeddings)
│   └── v0_4_0_go_binary.md  # Go binary — blocked on AILANG compiler bugs
├── archive/                  # Superseded or abandoned designs
│   ├── authalla_evaluation.md     # Superseded by Firebase Auth
│   ├── responsibility-docparse.md # Superseded by v0.8.0 billing
│   └── xlsx_deep_performance.md   # 99% resolved, remaining is edge case
└── README.md
```

> **Current version**: v0.9.3 (`ailang.toml`). Folders in `implemented/` reflect
> the version each feature actually shipped in. Folders in `planned/` are target
> versions for upcoming work. See also [CHANGELOG.md](../CHANGELOG.md) for a
> concise release-by-release summary.

## Document Organization

### Implemented (Changelog)
When a feature ships, move its design doc to `implemented/vX_Y_Z/` where X.Y.Z is
the **actual release version** it shipped in. Update the Status header. This creates
a changelog showing what was built in each release.

### Planned
Design docs for features not yet built, organized by target version.

### Archive
Designs that were superseded or abandoned (never delete — move here).

---

## Changelog (Implemented)

### v0.1.0 — Initial Release (March 2026)
- Deterministic Office parsing (DOCX, PPTX, XLSX)
- AI-powered PDF extraction via pluggable models
- 18 golden benchmarks at 100% baseline
- Comment extraction, track changes, headers/footers
- PDF benchmark infrastructure with multi-model support
- Competitor adapter framework (Docling, LlamaParse, Unstructured)
- [Implementation Report](implemented/v0_1_0/v0_1_0_implementation_report.md)

### v0.3.0 — Parser Coverage & Format Expansion
- 13 format parsers (DOCX, PPTX, XLSX, CSV, TSV, Markdown, HTML, EPUB, ODT, ODP, ODS, EML, MBOX)
- All parsers in pure AILANG (zero runtime dependencies)
- 53 golden benchmark files at 100% baseline
- AILANG eval module — 8 structural checks with contracts
- ODT/ODP/ODS native parsing — strategic gap, nobody else does this
- [Format Expansion](implemented/v0_3_0/format_expansion.md) | [Parser Coverage](implemented/v0_3_0/v0_3_0_parser_coverage.md) | [Eval](implemented/v0_3_0/ailang_benchmark_eval.md)

### v0.5.0 — Spec Coverage & Benchmarks
- ECMA-376 spec coverage audit — 19 gaps closed across Rounds 1-3
- OmniDocBench integration (Text ED 0.183, Table TEDS 0.871)
- Large file performance — DOCX/PPTX/XLSX within tier limits
- [Spec Audit](implemented/v0_5_0/spec_coverage_audit.md) | [External Benchmarks](implemented/v0_5_0/external_benchmarks.md) | [Large File Perf](implemented/v0_5_0/large_file_performance.md)

### v0.6.0 — Document Generation
- Block ADT → file output for 8 formats (HTML, DOCX, PPTX, XLSX, ODT, ODP, ODS, Markdown)
- AI-assisted generation: `--generate output.docx --prompt "Q1 sales report"`
- Cross-format conversion via `--convert` flag
- [Generation](implemented/v0_6_0/v0_6_0_document_generation.md) | [Features](implemented/v0_6_0/features.md) | [Verification](implemented/v0_6_0/verification_loop.md)

### v0.7.0 — API Server
- REST API via `ailang serve-api` with `@route` annotations
- Unstructured API drop-in compatibility (`POST /general/v0/general`)
- Auto-generated OpenAPI spec + Swagger UI, 25 smoke tests
- Cloud Run `concurrency=80` safe
- [Design Doc](implemented/v0_7_0/v0_7_0_api_server.md)

### v0.8.0 — Platform & Ecosystem
- Per-user API keys & Cloud deployment (Terraform, Firestore, Firebase Auth)
- Agent-friendly API: capabilities manifest, typed errors, device auth, pricing, tools
- Firebase JWT verification, removed unauthenticated key generation
- Python SDK v0.1.3 (PyPI), JS SDK v0.1.3 (npm), Go SDK
- Static website: 19 pages on GitHub Pages
- In-browser API playground with Firebase auth, code generation, response panel
- OfficeDocBench published: AILANG Parse 96.6% vs Unstructured 63.4%, Docling 63.4%, LlamaParse 53.6%
- Gemini Files API: upload once, reference by URI (large PDF optimization)
- WASM threat model: keep open, Office parsing is costless funnel
- [API Keys](implemented/v0_8_0/api_keys_cloud_deployment.md) | [Agent API](implemented/v0_8_0/agent_friendly_api.md) | [Auth](implemented/v0_8_0/auth_security.md)
- [SDKs](implemented/v0_8_0/sdks.md) | [Website](implemented/v0_8_0/website.md) | [Playground](implemented/v0_8_0/api_playground.md)
- [Ecosystem](implemented/v0_8_0/ecosystem.md) | [Gemini Files API](implemented/v0_8_0/gemini_files_api/gemini_files_api.md) | [WASM Threat Model](implemented/v0_8_0/wasm_threat_model.md)

### v0.9.0 — Email, Benchmarks v2, MCP & GTM (April 2026)
- Full EML/MBOX email parsing: attachments, thread reconstruction, `--deep` two-pass Office parsing
- OfficeDocBench v2: 69 files, 8 parsers, 7 metrics, 9 ECMA-376 scoring dimensions
- MCP stdio bridge, auth/billing/estimate tools for agent self-discovery
- SDK multipart file upload (`parse_file`), device auth, key persistence
- Website GTM: WASM demo, pricing page, format landing pages, FirebaseUI auth
- Batch mode, folder parsing, Windows CLI
- HTML email sanitization, QP decoder optimization, Z3 contracts
- Kreuzberg added as benchmark competitor (77.2% composite)
- [Email Parsing](implemented/v0_9_0/email_parsing.md) | [MCP Server](implemented/v0_9_0/mcp_server.md) | [Workbench](implemented/v0_9_0/workbench.md)

### v0.9.1 — Workbench & R SDK
- Workbench page: dedicated multi-file WASM playground with shared frontend module
- R SDK (v0.4.0) with full feature parity
- MCP modules reorganized into `docparse/services/mcp/`
- Shared credential helpers and auto-load saved API key in MCP bridges

### v0.9.2 — MCP Registry & Agent Discoverability
- MCP Registry publishing with CI job and badge
- llms.txt + llms-full.txt for AI agent discoverability
- Workbench polish: copy-to-clipboard, mini tutorial, format list, progress bar
- SDKs v0.4.1–v0.4.6: MCP registry metadata, markdown field, FormatsResult helpers

### v0.9.3 — Markdown+Metadata (Current)
- Markdown+metadata renderer: change attribution, merged-cell annotation
- SDKs v0.5.0–v0.5.3: sourceUrl, ResponseMeta, structured errors, key_id parameter

---

## Roadmap (Planned)

### v0.10.0 — Quarto, Trust & Deferred v0.9.0 Items
- Quarto Markdown generation with two rendering engines
- API privacy & trust commitments for hosted API
- Two-stage PDF pipeline (OCR → heuristic structuring) for Ollama models
- Ollama model-aware prompting (target: local models >50%)
- Email follow-ups: calendar invite parsing (P4), inbox monitoring (P2), Outlook .msg (P3), S/MIME (P5)
- Additional auth providers: Microsoft, Phone SMS, Apple, SAML/OIDC
- WASM image rendering (currently placeholder-only)
- Manifest-driven API page (3 missing endpoints: formats, pricing, capabilities)
- Valuable friction onboarding: structural insights banner, guided sample tour
- [Quarto](planned/v0_10_0/v0_10_0_quarto_integration.md) | [Privacy & Trust](planned/v0_10_0/api_privacy_trust.md)
- [PDF Pipeline](planned/v0_10_0/pdf_pipeline.md) | [Ollama](planned/v0_10_0/ollama_model_aware_prompting.md)
- [Auth Providers](planned/v0_10_0/auth_providers.md) | [WASM Images](planned/v0_10_0/wasm_images.md)
- [Manifest API](planned/v0_10_0/manifest_driven_api_page.md) | [Valuable Friction](planned/v0_10_0/valuable_friction_onboarding.md)

### v0.11.0 — Structured Extraction `FAST-TRACK`
- JSON Schema-driven extraction: `--extract --schema`, `--template invoice`
- Two-stage pipeline: deterministic parse → AI extraction
- Built-in templates (invoice, resume, contract, receipt, form, meeting notes, table)
- [Design Doc](planned/v0_11_0/v0_11_0_structured_extraction.md)

### v0.12.0 — AILANG Package Registry
- Publish as versioned AILANG package (`ailang pkg add docparse`)
- `ailang.pkg` manifest, CI/CD publish workflow, lock file
- [Design Doc](planned/v0_12_0/v0_12_0_package_registry.md)

### v0.13.0 — RAG Pipeline
- Document chunking (fixed-size, structural, section-based, semantic)
- Hierarchy metadata (parent-child blocks, heading paths)
- Embedding generation via AI API keys
- [Chunking](planned/v0_13_0/v0_13_0_chunking.md) | [Hierarchy](planned/v0_13_0/v0_13_0_hierarchy_metadata.md) | [Embeddings](planned/v0_13_0/v0_13_0_embeddings.md)

### Go Binary — Blocked on AILANG Compiler
- All 19 modules compile to Go (406 declarations, 16K lines)
- `go build` fails on 3 codegen bugs (function collisions, constant redeclaration, markdown syntax)
- Target: 10-100x faster parsing, single binary distribution
- [Design Doc](planned/v0_4_0_go_binary.md)

### Go-to-Market Strategy
- Rebrand from "DocParse" to "AILANG Parse"
- Positioning: enhancer to PDF-first tools, not competitor
- AI-native distribution (Claude Code skill, MCP server, npm/PyPI)
- *Design docs not yet created — roadmap planning only*

---

## Guidelines

1. **Before implementation**: Create design doc in `planned/vX_Y_Z/`
2. **After implementation**: Move to `implemented/vX_Y_Z/` using the **actual shipped version**, update Status header
3. **Version folders**: Use underscores (`v0_8_0`), match `ailang.toml` version
4. **Always update**: This README when features ship or plans change
5. **Archiving**: Move superseded docs to `archive/`, never delete
6. **Audit**: Run `bash .claude/skills/audit-design-docs/scripts/audit.sh` to check consistency
