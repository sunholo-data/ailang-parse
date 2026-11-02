# Design Doc: PDF to PowerPoint (v0.55.0)

**Status**: Planned
**Date**: 2026-11-02
**Author**: Mark + Claude
**Follows**: v0.54.0 PDF structure recovery (`v0_54_0_pdf_structure_recovery.md`)
**Absorbs**: v0.53.0 slide pagination (`../v0_53_0/v0_53_0_office_slide_pagination.md`), which was
designed but never built

## Problem

v0.54.0 made PDF → Word good: real headings, lists, tables, pictures, one header and footer,
any template. PDF → PowerPoint has none of that.

On 2026-11-02 we rendered three of our own test decks to PDF and converted them back with
`--pdf-backend poppler --convert x.pptx`:

| Source deck | PDF pages | Slides back |
|---|---|---|
| `pandoc_basic.pptx` | 4 | **1** |
| `poi_sampleshow.pptx` | 2 | **1** |

There are two causes.

1. **No slide boundaries.** `pptxSplitBySlides` starts a slide only at a
   `SectionBlock(kind: "slide")`. Only the PPTX and ODP parsers emit those, so PDF, DOCX and
   Markdown input all land on a single slide. The PDF backends know which page every block
   came from (`page` on each adapter block since v0.54.0), but `decodeBlock` drops it.
2. **No slide layout.** `pptxBlockShape` puts block *n* at `n * 1200000` EMU with fixed box
   heights (heading 0.8M, text 0.6M, list 1.0M, table 1.5M), 8229600 EMU wide on every slide
   size. About five blocks fit before the content runs off the bottom (6858000 EMU). A
   paragraph longer than its box overflows it. A 16:9 slide (12192000 wide) uses 67% of its
   width. This is exactly the problem in the v0.53.0 pagination design.

## Goal

A PDF made from a slide deck comes back as an editable deck: one slide per page, the page's
title as the slide title, its bullets as a list, its tables and pictures, and nothing running
off a slide. It can be restyled with a `.pptx` template through the existing `--reference-doc`
theme tier. A document PDF (report, proposal) also converts without losing content: busy pages
continue onto extra slides.

## Approach

### 1. Keep page boundaries

`decodeAdapterDoc` gains `keepPages: bool`. When it is true, a block whose `page` differs from
the previous block's is preceded by `mkNamedSection("page-break", "<page>", [])`. This is the
marker the DOCX parser (explicit breaks) and `html_layout` (EDGAR pages) already emit.

- **Which backends.** `parsePdfViaBackend` passes `keepPages = backend != "pdftotext"`, so
  pdftotext parse output stays byte-identical, as v0.54.0 promised. The adapter tags pdftotext
  blocks with `page` (pages are already split on `\f`) so the conversion path can use them;
  see §2.
- **Other generators.** An empty page-break section renders as nothing in DOCX
  (`docxSectionLabel` returns "" and there are no children). Markdown, HTML, ODT and QMD must be
  checked to render it as nothing as well, as they already must for EDGAR HTML.
- **Furniture pass.** In `pdf_furniture.ail` a page-break marker becomes a transparent role. It
  is kept in place, it is not body (so it does not end a header/footer run), and it is not
  furniture. `pdfFurnitureApply` stays idempotent.

### 2. One PDF page, one slide

In `main.ail writeOutputs`, when a PDF is converted to `pptx` or `odp`, a new pure
`pdfPagesAsSlides(blocks)` groups the blocks between page-break markers into
`SectionBlock("slide", …)`. Header and footer sections are dropped from the slides, since the
template's master carries its own footer and slide number. With pdftotext, which has no markers
in the parse, the convert path asks the adapter for page tags (`keepPages` on the convert path
only), so the default command works too.

If a PDF has no page information (the `ai` backend), the blocks fall through to pagination
(§3), which still splits them over as many slides as they need.

### 3. Slide layout and pagination (the v0.53.0 design, built)

In `pptx_generator.ail`, extracted into a new `pptx_layout.ail`, since the generator is at 962
lines:

- **Height estimate per block**, in EMU, from the slide width and font size:
  - text: lines = ceil(chars × average char width / box width) × line height;
  - list: the sum over its items;
  - table: rows × row height, with wrapped cells counted;
  - picture: `imageExtentEmu` capped to the remaining height, keeping its ratio.
  It only has to be conservative.
- **Geometry from the slide size**: margins at 5% of the width, content width = slide width
  minus the margins. This fixes the 9-inch boxes on 16:9.
- **Title first.** A slide's first heading becomes its title box at the top. The body flows
  below it.
- **Pagination.** When the next block does not fit, start a continuation slide that repeats the
  title with "(cont.)". A text block taller than a whole slide is split at a sentence boundary.
  A table is split by rows with the header repeated. A picture is shrunk.
- **Byte identity.** A slide whose content fits in the existing slots keeps the old geometry,
  so existing PPTX goldens are unchanged. This is the v0.53.0 verification rule. Only
  overflowing slides change.

`odp_generator.ail` gets the same estimate and split (one `draw:page` per slide).

### 4. Templates

`--reference-doc deck.pptx` already carries theme, masters and layouts (`pptx_template.ail`,
theme tier). For the page we build two or three example reference decks in AILANG
(`docs/scripts/pdf_to_powerpoint_templates.ail`), each a copy of our generated base deck with
surgery on the theme (colour scheme and fonts) and on the master background (a band or accent
shape and a footer line). The fonts have LibreOffice metric-compatible stand-ins (see the
v0.54.0 page work), so renders match what PowerPoint shows.

### 5. Page

`docs/pdf-to-powerpoint.html`, in the same shape as `pdf-to-word.html`: a template gallery
first, then a live side-by-side (the source PDF next to the generated deck rendered to PDF),
then what is recovered and what a PDF cannot give back, then which backend to use, then how to
run it.

The source is a short deck of our own, written as HTML slides and printed to PDF with Chrome.
That is how real decks arrive (exported from Slides or Keynote), and it has no third-party
content. It is rebuilt by `docs/scripts/build-pdf-to-powerpoint-assets.sh`.

## Open questions

1. **Keep the original positions?** A deck PDF is spatial. A "layout" mode could place each
   block where it sat on the PDF page, scaled to the slide, instead of reflowing into title and
   body. That gives a closer match to the original, but templates matter less. Recommendation:
   reflow (title + body) first, which is consistent with the template story; layout mode is a
   follow-up if people ask.
2. **Bind to placeholders?** Real title and body placeholders would make "Reset slide" and
   outline view work, but it rebases every PPTX golden (`pptx_template.ail` notes). Not in this
   release.
3. **Slide notes.** A PDF has none, except annotations. Leave them out.

## Verification

- **Round-trip benchmark.** `benchmarks/pdf/slides_roundtrip.py`: our PPTX test decks → PDF
  (LibreOffice) → PPTX → parse, scored against the source deck on:
  - slide count;
  - slide title recall;
  - bullet recall;
  - table cell F1;
  - picture count;
  - overflow, measured as blocks positioned past the slide bottom, which must be 0.
- **Pagination.** A 40-block document renders every block in LibreOffice; check each slide as
  PNG.
- **Goldens.** Existing PPTX/ODP goldens are byte-identical for content that fits (zip-entry
  comparison against HEAD, as in v0.52.0).
- **Parse output.** pdftotext parse JSON is byte-identical. Poppler and docling parse output
  gains only page-break markers, and the PDF → Word renders from v0.54.0 are unchanged.
- **Gates.** `--check`, `--test`, `--prove`, inline tests for the estimator and splitter,
  adapter unit tests, and the module-list and doc checks.

## Effort

Medium–large. Pagination is the bulk of it (estimator, splitter, plumbing for PPTX and ODP);
page markers and slide grouping are small, and the templates and page follow the v0.54.0
pattern. It splits into PRs in this order: markers → slide grouping → layout and pagination →
templates → benchmark → page.
