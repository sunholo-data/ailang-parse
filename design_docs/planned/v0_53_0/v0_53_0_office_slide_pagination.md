# Design Doc: Paginate PPTX and ODP Output Across Slides (v0.53.0)

**Status**: Planned
**Date**: 2026-10-19
**Author**: Mark + Claude
**Follows**: v0.52.0 picture embedding (feat/office-picture-embedding)

## Problem

PPTX and ODP lay blocks out on a fixed grid. The PPTX slide builder starts a new slide only
for an explicit `slide` section (`pptx_generator.ail`, `pptxSplitBySlides`). Markdown and most
parsers emit no such sections, so a whole document lands on one slide. Each block is placed at
`shapeId * 1200000` EMU (`pptxSlideXml`, `yOff`), so blocks past the bottom of the slide are
drawn off the page and cannot be seen.

Measured 2026-10-19 with a table plus four pictures: the fourth picture was off the bottom of
the slide in PPTX and in ODP. Pictures are also capped to one 1.2M EMU slot, so a 4:1 image
is only 4.8 × 1.2 in on a 13.3 in slide.

This predates v0.52.0. Long text documents already lose their tail the same way.

## Goal

Split a flow of blocks onto as many slides as they need, so that every block is visible, with
pictures at their natural aspect ratio up to the full text width.

## Approach

1. **Height estimate per block.** Text: lines from character count and font size. Table: rows
   times row height. Picture: the extent from `imageExtentEmu`, with its width capped to the
   column. Headings and lists get their own constants. The estimate only has to be
   conservative: a slide that is a little short is better than one that overflows.
2. **Pagination.** Walk the blocks with a running height. When the next block does not fit,
   start a new slide. A block taller than a whole slide is shrunk (pictures) or split across
   slides (long text and tables, by row).
3. **Plumbing.** Slide count is no longer known from the section list. The slide entries,
   slide relationships, notes relationships, `presentation.xml` slide list and
   `[Content_Types].xml` overrides all derive from the paginated list. `pptxBuildSlideEntries`
   and the picture numbering already thread a running index, so the same pattern carries over.
4. **ODP.** Each page becomes a `draw:page`. The same estimate and split apply.

## Open questions

- Should a level-1 heading always start a new slide? It reads well but makes short documents
  longer.
- Split long tables by row with a repeated header, or keep the table whole and shrink it?
- ODP slide size is 28 × 15.75 cm. Is that the intended default, or should it follow the PPTX
  16:9 size (33.87 × 19.05 cm)?

## Verification

- A document that fits on one slide produces byte-identical output to v0.52.0 (same regression
  method as v0.52.0: compare zip entries against HEAD).
- A long document with 40+ blocks, tables and pictures renders every block in LibreOffice
  (PDF to PNG, read each page).
- `ailang check` and inline tests for the estimator and the splitter.

## Effort

Medium. The splitter and estimator are a few hundred lines in `pptx_generator.ail` and
`odp_generator.ail`. Most of the risk is in the plumbing and in LibreOffice rendering, so the
render checks are the important part.
