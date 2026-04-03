# DocParse v0.12.0 — AILANG Package Registry Integration

**Status**: PLANNED (2026-03-20)
**Theme**: Publish DocParse as an AILANG package and manage dependencies via the new AILANG package registry
**Depends on**: v0.8.0 (Cloud deployment), v0.4.0 (Go binary for compiled distribution)

## Motivation

AILANG has introduced a package registry system. Today DocParse is a monolithic module tree (`docparse/`) that users obtain by cloning the repo or using the Docker image. This has several problems:

1. **No versioned consumption** — users pin to a git commit, not a semantic version
2. **No dependency declaration** — DocParse's 17 stdlib imports are implicit; there's no manifest
3. **No composability** — other AILANG projects can't `import docparse/services/docx_parser` without vendoring the entire tree
4. **No discoverability** — new AILANG users can't find DocParse without knowing the repo URL

The package registry solves all of these. DocParse becomes a first-class AILANG package that anyone can install with a single command.

### Strategic Value

DocParse is one of the largest and most complex AILANG projects. Being an early registry adopter:
- Validates the registry with a real, non-trivial package (31 modules, 50+ contracts, 17 stdlib deps)
- Establishes best practices for AILANG package structure that others will follow
- Makes DocParse the reference example in AILANG's registry documentation
- Drives feedback to AILANG core on registry DX (consistent with our feedback-first approach)

## Design

### Package Manifest: `ailang.pkg`

Every AILANG package needs a manifest file at the repo root. Based on the registry system:

```toml
[package]
name = "docparse"
version = "0.12.0"
description = "Universal document parsing and generation — Office, PDF, images, 9 output formats"
license = "Apache-2.0"
repository = "https://github.com/sunholo-data/docparse"
authors = ["Mark Edmondson <mark@sunholo.com>"]
keywords = ["document-parsing", "office", "pdf", "docx", "pptx", "xlsx", "generation"]
entry = "docparse/main.ail"

[capabilities]
required = ["IO", "FS"]           # minimum for deterministic parsing
optional = ["AI", "Env", "Net", "Rand", "Clock"]  # for PDF/image, API server, keys

[dependencies]
# stdlib deps are implicit — they ship with AILANG
# Third-party deps go here when they exist:
# xml-schema-validator = "^1.0"

[dev-dependencies]
# Future: test harness packages, benchmark tools

[exports]
# Public API surface — what other packages can import
modules = [
  "docparse/types/document",
  "docparse/services/format_router",
  "docparse/services/docx_parser",
  "docparse/services/pptx_parser",
  "docparse/services/xlsx_parser",
  "docparse/services/csv_parser",
  "docparse/services/markdown_parser",
  "docparse/services/html_parser",
  "docparse/services/epub_parser",
  "docparse/services/odt_parser",
  "docparse/services/odp_parser",
  "docparse/services/ods_parser",
  "docparse/services/direct_ai_parser",
  "docparse/services/html_generator",
  "docparse/services/docx_generator",
  "docparse/services/pptx_generator",
  "docparse/services/xlsx_generator",
  "docparse/services/odt_generator",
  "docparse/services/odp_generator",
  "docparse/services/ods_generator",
  "docparse/services/qmd_generator",
  "docparse/services/ai_generator",
  "docparse/services/output_formatter",
  "docparse/services/eval",
]

# Internal modules — NOT exported (implementation details)
# docparse/services/zip_extract
# docparse/services/xml_helpers
# docparse/services/layout_ai
# docparse/services/api_server      (use serve-api instead)
# docparse/services/api_keys         (internal to API server)
# docparse/services/unstructured_compat
# docparse/services/docparse_browser

[scripts]
check = "ailang check docparse/"
test = "ailang run --entry main --caps IO,FS,Env docparse/main.ail --test"
prove = "ailang run --entry main --caps IO,FS,Env docparse/main.ail --prove"
benchmark = "bash benchmarks/quick_check.sh"
```

### Public vs Internal Modules

A key decision: which modules are part of the public API surface?

**Exported (stable API):**
- `docparse/types/document` — Block ADT, the core data type
- All parsers — consumers need to parse documents
- All generators — consumers need to generate documents
- `format_router` — high-level parse-any-format entry point
- `output_formatter` — Block → JSON/text serialization
- `eval` — structural evaluation checks (for downstream testing)

**Internal (may change without notice):**
- `zip_extract`, `xml_helpers` — implementation details of Office parsers
- `layout_ai` — internal AI layout inference
- `api_server`, `api_keys`, `unstructured_compat` — server-side only
- `docparse_browser` — WASM-specific entry point

This distinction matters because registry consumers should only depend on exported modules. Internal modules can change freely between versions.

### Consuming DocParse as a Dependency

Other AILANG projects can depend on DocParse:

```toml
# In another project's ailang.pkg
[dependencies]
docparse = "^0.12"
```

Then import and use:

```ailang
module my_app/invoice_processor

import docparse/services/format_router (parseFile)
import docparse/services/docx_parser (parseDocx)
import docparse/types/document (Block, getText)

func processInvoice(path: string) -> [Block] ! {IO, FS} {
  parseFile(path)
}
```

### Version Strategy

DocParse is pre-1.0, so minor versions can have breaking changes per semver. Our strategy:

| Version Range | Meaning |
|--------------|---------|
| `0.x.y` (current) | Breaking changes in minor bumps, patches are safe |
| `1.0.0` (future) | Stable public API — Block ADT, parsers, generators |
| `^0.12` | Compatible with 0.12.x but not 0.13.0 |

**What triggers a version bump:**
- **Patch** (0.12.1): Bug fixes, new golden benchmarks, internal refactors
- **Minor** (0.13.0): New parser/generator, Block ADT variant additions, new exports
- **Major** (1.0.0): Block ADT breaking changes, removed exports, capability changes

### Publishing Workflow

Integrate with CI/CD (extends v0.8.0 Cloud Build):

```yaml
# .github/workflows/publish.yml
on:
  push:
    tags: ["v*"]

jobs:
  publish:
    steps:
      - uses: actions/checkout@v4
      - name: Install AILANG
        run: curl -fsSL https://ailang.sunholo.com/install.sh | bash
      - name: Type-check
        run: ailang check docparse/
      - name: Run tests
        run: ailang run --entry main --caps IO,FS,Env docparse/main.ail --test
      - name: Run benchmarks
        run: bash benchmarks/quick_check.sh
      - name: Publish to registry
        run: ailang pkg publish
        env:
          AILANG_REGISTRY_TOKEN: ${{ secrets.AILANG_REGISTRY_TOKEN }}
```

**Pre-publish checklist (automated):**
1. `ailang check docparse/` passes (type-check all 31 modules)
2. Inline tests pass
3. 53-file structural benchmark at 100%
4. Version in `ailang.pkg` matches git tag
5. No uncommitted changes

### Registry Metadata & Discovery

The registry page for DocParse should show:

```
docparse v0.12.0
Universal document parsing and generation

Capabilities: IO, FS (required) | AI, Env, Net (optional)
Modules: 31 | Contracts: 50+ | Tests: 76+
Formats: DOCX, PPTX, XLSX, CSV, MD, HTML, EPUB, ODT, ODP, ODS, PDF
License: Apache-2.0

Install: ailang pkg add docparse
```

### Capability Declaration

The `[capabilities]` section in the manifest is important for the registry:

- **Required capabilities** (`IO`, `FS`) — DocParse won't work without these
- **Optional capabilities** (`AI`, `Env`, etc.) — needed for specific features

When a consumer adds DocParse as a dependency, the registry can warn:
> "docparse requires IO and FS capabilities. Your project currently declares only IO. Add FS to your capabilities."

This integrates with AILANG's capability/effect system — the manifest makes implicit requirements explicit.

### Handling the `docparse/` Module Prefix

Currently all modules use the `docparse/` prefix (e.g., `module docparse/services/docx_parser`). This matches the directory layout and works when running from the repo root.

For the registry, this prefix becomes the package namespace. The registry resolver maps:
```
import docparse/services/docx_parser  →  ~/.ailang/packages/docparse@0.12.0/docparse/services/docx_parser.ail
```

No module renaming needed — our existing `docparse/` prefix convention is already registry-compatible.

### Lock File

The registry should generate an `ailang.lock` file (similar to `package-lock.json` or `go.sum`):

```json
{
  "ailang_version": "v0.9.2",
  "generated_at": "2026-03-27T00:00:00Z",
  "generator": "ailang lock v0.9.2",
  "packages": [
    {
      "name": "sunholo/docparse",
      "version": "0.12.0",
      "source": "registry",
      "content_hash": "sha256:abc123...",
      "interface_hash": "sha256:def456...",
      "ailang": ">=0.9.2",
      "effects": [],
      "exports": []
    }
  ]
}
```

This file should be committed to source control for reproducible builds.

## Extracting Reusable Packages

Several DocParse modules contain general-purpose logic that isn't document-specific. Extracting these into standalone AILANG packages benefits the ecosystem and dogfoods the registry's dependency resolution.

### Extraction Candidates

| Current Module | Proposed Package | What Moves | What Stays in DocParse | Consumers (current) |
|---|---|---|---|---|
| `xml_helpers` | *(no extraction — migrate to `std/xml`)* | Nothing — `xmlEscape` already delegates to `std/xml.escapeXml`, `xmlElem`/`xmlWrap` can use `std/xml` tree API | DOCX-specific helpers (`docxContentTypes`, `docxRootRels`, `docxRun`, etc.) rename to `docx_xml_helpers` | 9 modules: all 7 generators + api_server + unstructured_compat |
| `zip_extract` | `ailang-office-zip` | Generic ZIP read/list (`readZipEntry`, `listOfficeEntries`), MIME detection (`mediaMimeType`) | DocParse-specific wrappers (`readDocxContent`, `readCoreProperties`, `findSlideEntries`, `findMediaEntries`, `readComments`, etc.) | 5 modules: docx/pptx/xlsx parsers + main + api_server |
| `eval` | `ailang-doc-eval` | Structural eval framework (`evalJaccard`, `evalComputeScore`, `evalNormalizeJson`), generic comparison logic | DocParse-specific golden benchmark integration | 1 module (main), but useful for any doc processing project |
| `output_formatter` | *(keep internal)* | — | All of it — tightly coupled to Block ADT | 3 modules: main + api_server + browser |

> **Note on `xml_helpers`**: No package extraction needed. `xmlEscape` is already a one-line wrapper around `std/xml.escapeXml`, and `xmlDecl` is a constant string. The `std/xml` stdlib already provides `xmlElement`, `xmlText`, and `serialize` for tree-based XML construction. The cleanup here is to **migrate callers to use `std/xml` directly** and rename the remaining Office-specific helpers to `docx_xml_helpers.ail` for clarity. This is a refactor, not an extraction.

### Package Details

#### `xml_helpers` → Migrate to `std/xml` (No Package Needed)

`xml_helpers.ail` is mostly redundant now that `std/xml` exists. The cleanup:

- **`xmlEscape`** → replace all 9 callers with `std/xml.escapeXml` directly
- **`xmlDecl`** → inline the constant string or keep as a one-liner in `docx_xml_helpers`
- **`xmlElem`/`xmlWrap`** → migrate to `std/xml` tree API (`xmlElement`, `xmlText`, `serialize`)
- **`xmlAttrEscape`** → alias for `xmlEscape`, just use `escapeXml`

Rename the file to `docx_xml_helpers.ail` with only the DOCX-specific functions remaining:
- `docxContentTypes`, `docxRootRels`, `docxNs`, `docxRelsNs`, etc.
- `docxRun`, `docxParagraph`, `docxStyledParagraph`

After migration, generators change from:
```ailang
import docparse/services/xml_helpers (xmlEscape, xmlDecl)
```
to:
```ailang
import std/xml (escapeXml, xmlElement, xmlText, serialize)
import docparse/services/docx_xml_helpers (docxContentTypes, docxRun, ...)  -- only DOCX generators
```

#### `ailang-office-zip` — Office ZIP Handling

Office formats (DOCX, PPTX, XLSX, ODT, ODP, ODS) are all ZIP archives with XML inside. The generic ZIP traversal and MIME detection logic is useful for any AILANG project working with Office files.

```toml
[package]
name = "ailang-office-zip"
version = "1.0.0"
description = "Read and list entries in Office ZIP archives (OOXML, ODF) with MIME detection"
keywords = ["zip", "office", "ooxml", "odf", "docx", "pptx", "xlsx"]

[capabilities]
required = ["IO", "FS"]

[dependencies]
ailang-xml = "^1.0"  # for XML parsing within ZIP entries
```

**What moves:**
- `readZipEntry(path, entry) -> string` — read a single ZIP entry as text
- `listOfficeEntries(path) -> [string]` — list all entries in an Office ZIP
- `mediaMimeType(filename) -> string` — MIME type from extension
- Generic ZIP + XML entry reading patterns

**What stays in DocParse:**
- `readDocxContent`, `readCoreProperties`, `readAppProperties` — format-specific entry paths
- `findSlideEntries`, `findSheetEntries`, `findHeaderEntries` — format-specific discovery
- `readEmbeddedImage`, `readComments`, `resolveBlockImages` — DocParse Block integration

#### `ailang-doc-eval` — Document Evaluation Toolkit

Structural comparison metrics for document parsing benchmarks. Niche but valuable — any document processing project needs eval.

```toml
[package]
name = "ailang-doc-eval"
version = "1.0.0"
description = "Jaccard similarity, JSON normalization, and scoring for document parsing evaluation"
keywords = ["evaluation", "benchmark", "jaccard", "document", "comparison"]

[capabilities]
required = ["IO", "FS"]  # for reading golden files
```

**What moves:**
- `evalJaccard(a, b) -> float` — Jaccard similarity between token sets
- `evalNormalizeJson(json) -> string` — normalize JSON for comparison
- `evalComputeScore(results) -> float` — aggregate scoring
- Generic structural comparison functions

### Extraction Strategy

**Key principle: extract only when there's a second consumer.** Don't prematurely extract just because code *could* be reused. Wait until:
1. DocParse uses the registry for its own dependencies (Phase 2 proves the workflow)
2. Another AILANG project actually needs the same utility (real demand, not hypothetical)

### Migration & Extraction Order

1. **`xml_helpers` → `std/xml` migration** (refactor first) — no package needed, just stop wrapping stdlib. Rename remainder to `docx_xml_helpers`
2. **`ailang-office-zip`** (extract first) — generic ZIP + MIME detection, validates the registry as both publisher and consumer
3. **`ailang-doc-eval`** (extract later) — wait for a second consumer to validate demand

### Impact on DocParse Module Count

| Before | After |
|--------|-------|
| 31 internal modules | ~29 internal modules + 1-2 package dependencies |
| `xml_helpers` wrapping `std/xml` | Direct `std/xml` usage + `docx_xml_helpers` (DOCX-only) |
| 0 registry dependencies | 1-2 registry dependencies (`ailang-office-zip`, maybe `ailang-doc-eval`) |
| All code in-repo | Generic utilities maintained as separate packages |

This also makes DocParse a better test case for the registry — it becomes both a **publisher** (the `docparse` package) and a **consumer** (depends on `ailang-office-zip`).

## Migration Plan

### Phase 1: Manifest & Local Testing
- Create `ailang.pkg` manifest at repo root
- Test `ailang pkg check` validates the manifest
- Test `ailang pkg pack` creates a distributable archive
- Verify all 31 modules resolve correctly from package layout
- Send DX feedback on any registry issues encountered

### Phase 2: First Publish
- Create first git tag (`v0.12.0`)
- Publish to AILANG registry with `ailang pkg publish`
- Test installation in a clean project: `ailang pkg add docparse`
- Verify imported modules work end-to-end (parse a DOCX, generate HTML)
- Update docs and website with installation instructions

### Phase 3: CI/CD Integration
- Add `publish.yml` GitHub Actions workflow
- Automate pre-publish checks (type-check, test, benchmark)
- Tag-triggered publishing
- Registry badge on README

### Phase 4: Migrate `xml_helpers` to `std/xml`
- Replace all `xmlEscape` calls with `std/xml.escapeXml` across 9 modules
- Migrate `xmlElem`/`xmlWrap` callers to `std/xml` tree API (`xmlElement`, `xmlText`, `serialize`)
- Rename `xml_helpers.ail` → `docx_xml_helpers.ail` with only DOCX-specific functions
- Delete the generic wrapper functions (they're now stdlib calls)
- Verify full benchmark suite still passes at 100%

### Phase 5: Extract `ailang-office-zip`
- Create package with generic ZIP read/list and MIME detection
- Keep format-specific wrappers (readDocxContent, findSlideEntries, etc.) in DocParse
- Update 5 importing modules
- Publish and add as dependency — validates transitive dependency resolution (`ailang-office-zip` → `ailang-xml`)

### Phase 6: Consuming Third-Party Dependencies (Future)
- As the AILANG ecosystem grows, adopt third-party packages:
  - JSON Schema validation library (for v0.11.0 structured extraction)
  - Template engine (for QMD generation)
- Declare these in `[dependencies]` section
- Test dependency resolution with `ailang pkg install`
- Extract `ailang-doc-eval` only when a second consumer appears

## Impact on Existing Workflows

### What Changes
- New `ailang.pkg` file at repo root
- New `ailang.lock` file (auto-generated)
- Git tags for releases (`v0.12.0`, etc.)
- CI/CD gains a publish step
- Users can `ailang pkg add docparse` instead of cloning

### What Doesn't Change
- Module structure (`docparse/` prefix stays)
- `bin/docparse` CLI wrapper still works
- Docker image / Cloud Run deployment unchanged
- `serve-api` usage unchanged
- All existing imports and code unchanged

## Open Questions

1. **Registry availability** — When does the AILANG package registry go live? Is there a beta/staging registry for early adopters?
2. **Private packages** — Can we publish pre-release versions privately before going public?
3. **Capability negotiation** — Does the registry enforce capability compatibility at install time, or only at runtime?
4. **Monorepo support** — DocParse has `benchmarks/`, `sdks/`, `docs/` alongside `docparse/`. Does `ailang pkg pack` include only the AILANG source, or the whole repo?
5. **Binary distribution** — Once v0.4.0 ships (Go compilation), can the registry distribute compiled binaries alongside source?
6. **Transitive dependencies** — How does the registry handle AILANG's known transitive import issue (entry module must import all transitive deps)?
7. **Registry CLI commands** — What are the exact `ailang pkg` subcommands? (publish, add, remove, update, list, search, pack, check?)

## AILANG DX Feedback to Send

After implementing, send feedback on:
- Registry setup DX (how easy was first publish?)
- Manifest format (is TOML right? missing fields?)
- Capability declaration UX
- Dependency resolution behavior
- Lock file format and tooling
- Public/internal module boundary enforcement
- Package size limits and what gets included
