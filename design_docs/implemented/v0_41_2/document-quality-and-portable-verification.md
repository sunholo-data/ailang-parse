# Document quality and portable verification

**Status:** Implemented in v0.41.2
**Release:** v0.41.2
**Priority:** P1
**Created:** 2026-09-10
**Estimated effort:** 3–5 engineering days including verification and documentation
**Baseline:** 160c7f1 (AILANG Parse), 24a0f22 (docparse-skill)
**Dependencies:** AILANG runtime >=0.35.0 (`renameFileResult`); LibreOffice and Poppler for optional rendering;
No hosted API, AI, Python, or Pillow is required by the new package features.

## Problem

The shared skill can create documents but cannot itself execute its visual QA
instructions without another skill or application. Template selection lacks a
repeatable inspection step, and good Markdown structure does not guarantee good
Word layout. In the DOCX generator, tables use a fixed 9360-twip width and equal
columns, even when a reference section defines a different usable width. Header
rows are bold but lack the repeating-header flag.

This is a boundary problem across authoring, generation, and verification. More
prompt instructions alone cannot repair generator geometry. A successful parse
or a populated styles.xml cannot establish visual fidelity or applied styling.

## Goals and acceptance criteria

- [x] Shared skill has concise editorial and template-inspection references.
- [x] Local render helper produces a fresh PDF and numbered page PNGs, records
      input hashes and tool paths, preserves input bytes, and never claims human
      visual review occurred merely because rendering succeeded.
- [x] Missing tools, conversion failure, timeout, and stale/reused output paths
      produce clear nonzero failures; there is no hosted fallback.
- [x] Optional comparison produces page images and a machine-readable changed-
      page inventory, including added/removed pages.
- [x] AILANG DOCX audit reports section geometry, table widths/header flags,
      heading gaps, image descriptions, comment anchors, and field inventory.
      It reports findings without changing document content or metadata.
- [x] Generated DOCX tables fit the selected reference section, use bounded
      content-sensitive column widths, preserve merged-cell geometry, and repeat
      semantic header rows. Default page geometry remains US Letter.
- [x] Focused positive and negative tests pass, plus the four required parser/
      generator regression suites; documentation states any unavailable checks.

## Scope and boundaries

Keep the local CLI and hosted API choices separate. Rendering/auditing operate
on existing local files, never upload them, and do not require MCP. The shared
skill remains in sunholo-data/docparse-skill; engine and portable tool source
live here. Skill wrappers resolve an installed tool or explicit executable;
they do not copy implementation into a second repo.

This implementation includes read-only audits and before/after visual comparison.
It does not implement a new Word editor, tracked-change authoring, destructive
metadata scrubbing, automatic fixes, full accessibility certification, or native
Google Docs import. Existing specialised editing routes remain appropriate.

## Design

### 1. Authoring and template inspection

Add short on-demand writing and template-inspection references to the shared
skill. Review intended audience and voice, headings as an outline, preserved
facts/units/qualifications, meaningful alt text and links, and table suitability.
Avoid prescribed colours, punctuation bans, or generic document styling that
would override the user's reference.

Distinguish styling a new body (`--reference-doc`) from editing exact slots in
an existing document (copy and targeted editing). Record only relevant template
geometry, page patterns, styles and preservation requirements. A template
inspection record should identify source path/hash and unresolved observations.
Document current template support for DOCX, ODT, PPTX and HTML; DOCX-only flags
remain section selection and table style selection.

### 2. Portable rendering and comparison

Provide `docparse-render` alongside `docparse`, backed by the AILANG service
`docparse/services/document_render.ail`. Use `std/process` for allowlisted local
commands, `std/fs` for staging and `std/crypto` for hashes. A Bash launcher resolves
paths and supplies runtime capability/timeout limits, following the existing CLI.
All new verification logic and durable regression tests are AILANG; temporary
Python development utilities do not ship in the repository.

Resolve explicitly supplied tool paths first, otherwise PATH and the native
macOS LibreOffice application location. Use argument arrays (no shell), bounded
subprocess timeouts, a private LibreOffice profile and a temporary staging area.
Require a new output directory and publish it only after a nonempty PDF and page
PNGs exist. Keep source files untouched. Emit a manifest with input SHA-256,
renderer paths, page count, and `visual_review: pending`. An optional second
input is rendered with the same engine/DPI and compared using hashes of Poppler's
uncompressed PPM rasters (including geometry). Report changed, added and removed
pages and provide both sets of PNGs for side-by-side inspection. This deliberately
does not claim semantic alignment or produce pixel-difference overlays.
Tool availability is a dependency error, not a skipped passing check.

### 3. AILANG audit

Add a read-only AILANG service and a small CLI wrapper (`docparse-audit`). Use
std/zip and std/xml, return structured JSON with findings, section/table/image/
comment/field inventories. Check resolved OOXML structure rather than relying on
text extraction alone. Missing or malformed package parts fail clearly. Keep
checks bounded to DOCX story parts and explicitly document their coverage.
No finding mutates a document. Ordinary warnings are distinct from unreadable
input; an optional strict mode may treat findings as failure for automation.

### 4. DOCX table layout

Compute usable width once from the selected `sectPr` (page width minus left,
right and gutter; account for explicit/equal section columns). Missing geometry
uses documented defaults. Clamp invalid geometry to a safe positive fallback.
Thread this width through the existing indexed block walk, including nested
sections, rather than introducing a second template-only generator.

Compute bounded per-column content weights from header/body cell text. Cap long
narrative influence and share a spanned cell's weight over its covered columns.
Allocate positive integer widths summing exactly to the usable width; cell
widths are sums of the columns they span. Keep current merged-continuation
handling intact. Mark only actual header rows with `w:tblHeader`.

## Verification

Use synthetic Markdown and reference DOCX fixtures, never client documents.
Assert selected-section widths (narrow, landscape, gutter, columns), positive
column widths and exact sums, uneven content allocation, merged-cell consistency,
repeating headers and the absence of header flags on ordinary rows. Test audit
positive and negative fixtures and rendering failure paths. Exercise real
Markdown → AILANG DOCX → parse/audit/render, and inspect the resulting pages.
Compare two outputs with a deliberate content change and verify it is detected.

Run `docparse --check`, relevant inline tests/contracts and:

- `uv run benchmarks/run_benchmarks.py --suite office`
- `uv run benchmarks/roundtrip_check.py`
- `uv run benchmarks/verify_generated.py`
- `uv run benchmarks/failure_check.py`

Use isolated checkouts for work and test artifacts, then apply reviewed changes
to the user's clean checkouts. Do not release or publish packages as part of this
implementation. Record actual results below before completion.

## Axiom alignment

Determinism and replayability: pure geometry functions and repeatable structural
audits; renderer identity recorded because different engines may paginate
 differently. Effects and authority: file/process effects are explicit and local,
no network required. Bounded verification: finite package checks and subprocess
timeouts. Existing Block ADT/public generation signatures remain compatible.

## Related documents

- [Reference DOCX follow-ups](../../implemented/v0_39_0/v0_39_0_reference_doc_followups.md)
- [Templates beyond DOCX](../../planned/v0_41_0/v0_41_0_reference_doc_beyond_docx.md)
- [Legal DOCX writeback](../../planned/v0_18_0/v0_18_0_legal_docx_writeback.md)

## Implementation report

Implemented in AILANG: `docx_layout.ail`, `docx_audit.ail`,
`document_render.ail`, and `scripts/verify_document_quality.ail`. Existing Bash
CLI/installer conventions expose the companions. The shared skill adds writing
and template inspection references and thin companion launchers. No new Python
files ship; temporary Python utilities were used only outside the repositories.

Verification on macOS with AILANG v0.36.0, local LibreOffice and Poppler:

- Type checking passed; module-list check covers all 58 package modules.
- AILANG layout inline test and 100 generated contract cases passed; template
  inline tests and the new AILANG regression script passed.
- Native cases cover default/narrow/landscape/gutter/column geometry, first/last
  reference selection, merged-cell widths, semantic headers, positive/negative
  audits, fresh output protection and failed subprocesses.
- Real rendering and raster comparison passed for identical and deliberately
  changed documents. Inspected the generated report PNG: content and table fit.
- CLI checks passed for missing executables, timeout, and audit exit codes 0/1/2.
- Office suite: 105 files, 100%; round-trip suite: 102 checked, zero failures;
  generated-document and failure suites passed. The generated-document suite
  reports a non-fatal missing-grid warning for the existing `demo_report.docx`.
- Skill metadata validation and shell syntax checks passed.
- Static Z3 verification cannot encode `Option[XmlNode]` in the geometry helper;
  that proof is explicitly skipped, not claimed as passing. Runtime property
  cases exercise its positive-width contract. The runtime also warns about the
  existing lock's v0.34.0 toolchain versus installed v0.36.0; no lock upgrade is
  included in this change.

A regression fixture exposed an existing reference scanner omission for bare
`<w:sectPr/>`; corrected it so the selected last section is used. The module-list
check also found two existing template modules omitted from the CLI check list;
added both so package checks cover the full source set.

Remaining boundaries: structural audit is deliberately bounded (no full style
inheritance, accessibility certification, or comment-order validation), comparison
is page-index raster equality rather than semantic alignment or diff overlays,
and render completion leaves visual review pending. Windows and hosted/browser
execution of local Process-based QA were not tested. The implementation ships in the v0.41.2 package release.
