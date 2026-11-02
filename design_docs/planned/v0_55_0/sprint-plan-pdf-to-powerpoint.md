# Sprint Plan: PDF to PowerPoint (v0.55.0)

**Design doc**: [v0_55_0_pdf_to_powerpoint.md](v0_55_0_pdf_to_powerpoint.md)
**Sprint ID**: M-PDF2PPTX
**Branch**: `feat/pdf-to-powerpoint` (off `main` at a34aa31, after v0.54.0's #121)
**Duration**: ~4 working days, 7 milestones
**Risk**: Medium. Pagination touches every PPTX/ODP output, so byte identity for content that
fits is the guard. The rest is additive.
**AILANG prompt version loaded**: v0.16.8 (loaded this session).

## Rulings (user, 2026-11-02)

- Scope is **PowerPoint first**: engine work (page = slide, slide fitting), 2–3 PowerPoint
  templates, and `pdf-to-powerpoint.html`. Other formats later.
- Same process as v0.54.0: design doc → sprint plan → milestones → PR for review before it goes
  live.
- Open question 1 (reflow vs keep positions): reflow, per the design doc recommendation;
  layout mode is a follow-up.

## Registry reuse

| Milestone | Package | Action | Reason |
|---|---|---|---|
| M1–M7 | `sunholo/external_backend` | depend (already) | Unchanged adapter bridge |
| M3–M4 | — | none | Slide layout is generator-internal; `ailang pkg search` (slide, layout, pptx) finds no layout package |

## Milestones

### M1: Page markers (~150 LOC)

- `decodeAdapterDoc(doc, keepPages)`: a page change inserts
  `mkNamedSection("page-break", "<n>", [])`. `parsePdfViaBackend` passes
  `backend != "pdftotext"`.
- adapter: pdftotext blocks carry `page`, split on `\f`. The parse path ignores it.
- `pdf_furniture.ail`: a page-break marker is a transparent role, kept in place, neither body nor
  furniture.
- Check that an empty page-break renders as nothing in the md, html, odt and qmd writers; fix any
  that print a label.
- **Acceptance**:
  - inline tests for marker insertion and for the furniture pass with markers, idempotence
    included;
  - pdftotext parse JSON byte-identical on the golden PDFs and the proposal;
  - the v0.54.0 PDF → DOCX example renders unchanged (same page count and same text per page);
  - `--check`, `--test` and `--prove` pass.

### M2: Slides from pages (~120 LOC)

- `pdfPagesAsSlides(blocks) -> [Block]`, pure, in `pdf_furniture.ail` (the page-structure
  module): marker-delimited groups become `SectionBlock("slide", …)`, and header/footer
  sections are dropped.
- `main.ail writeOutputs`: a PDF converted to pptx or odp is grouped into slides. On pdftotext the
  convert path keeps page tags.
- **Acceptance**:
  - inline tests;
  - `pandoc_basic.pdf` (4 pages) → 4 slides and `poi_sampleshow.pdf` (2) → 2, with poppler and
    with the default backend;
  - parse JSON unchanged.

### M3: PPTX layout and pagination (~450 LOC, new `pptx_layout.ail`)

- Height estimator per block, geometry from the slide size, title-first, continuation slides
  "(cont.)", text split at sentences, tables split by rows with a repeated header, pictures
  shrunk.
- Old geometry is kept for slides that fit, so goldens stay byte-identical.
- **Acceptance**:
  - inline tests for the estimator, the splitter and the fits-unchanged rule;
  - a zip-entry comparison against HEAD for a fixture set (md, docx and pptx inputs converted to
    pptx) shows identical output for content that fits;
  - the 40-block document renders with every block on a slide (PNG check);
  - `--check`, `--test` and `--prove` pass.

### M4: ODP pagination (~150 LOC)

- The same estimator and split in `odp_generator.ail`, reusing `pptx_layout.ail`'s pure core.
- **Acceptance**: the same fixture identity check for ODP, the PDF deck → ODP slide count, and a
  render check.

### M5: Slides round-trip benchmark (~250 LOC)

- `benchmarks/pdf/slides_roundtrip.py`: our PPTX test decks → PDF (LibreOffice) → PPTX
  (backends) → parse, scored on slide count, title recall, bullet recall, table cell F1,
  picture count and overflow (must be 0).
- Results file alongside.
- **Acceptance**: it runs; poppler slide count is 100% on the decks; overflow is 0 for every
  backend.

### M6: PowerPoint templates (~250 LOC AILANG)

- `docs/scripts/pdf_to_powerpoint_templates.ail` builds 2–3 reference decks from our base deck:
  theme colours and fonts, plus a master background band or accent and a footer line. Fonts
  have LibreOffice stand-ins.
- **Acceptance**: each one applies through `--reference-doc` ("reference doc applied"), and the
  renders show distinct looks in LibreOffice.

### M7: Source deck, page, assets (~600 LOC HTML/CSS/JS + script)

- A source deck of our own written as HTML slides and printed to PDF with headless Chrome.
- `docs/scripts/build-pdf-to-powerpoint-assets.sh`: renders, PageMode patch, screenshots,
  gallery thumbnails, path-leak check.
- `docs/pdf-to-powerpoint.html` in the `pdf-to-word.html` shape: gallery first, live
  side-by-side, recovered structure, limits, backends, run it, FAQ JSON-LD.
- Links from `pdf-to-word.html`, `docs.html`, `llms.txt` and `pdf-parsing.html`; CHANGELOG
  entry.
- **Acceptance**:
  - desktop and true-phone-width (iframe) screenshots read correctly;
  - the doc checks pass;
  - the Tailscale preview is registered for review.

## Validation (every milestone)

`./bin/docparse --check`, `--test`, `--prove`, `python3 -m unittest tests/test_pdf_adapter.py`,
`python3 docs/scripts/check-module-list.py` (new modules in MODULES/TEST_MODULES via
`assets/bin/docparse`, not the `bin/docparse` symlink), the pdftotext byte-identity check, and
the PPTX/ODP golden identity check from M3 on.

## Estimate

| Milestone | LOC |
|---|---|
| M1 | 150 |
| M2 | 120 |
| M3 | 450 |
| M4 | 150 |
| M5 | 250 |
| M6 | 250 |
| M7 | 600 |
| **Total** | **~1,970** |

The v0.54.0 sprint landed ~1,350 LOC plus a site page in one day of focused work. This one is
larger and riskier because of M3, so the estimate is 2–4 days.
