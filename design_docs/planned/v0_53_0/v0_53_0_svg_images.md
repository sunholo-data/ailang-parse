# Design Doc: SVG Images in Office and OpenDocument Output (v0.53.0)

**Status**: Planned
**Date**: 2026-10-19
**Author**: Mark + Claude
**Follows**: v0.52.0 picture embedding (feat/office-picture-embedding)

## Problem

SVG is the default output of most charting and diagram tools (matplotlib, graphviz, mermaid,
d3). Markdown that references one is common, but it never embeds:

- The Markdown loader maps the extension through `orchImageMime` (`orchestrator.ail`), which
  has no `svg` entry, so the MIME type is `image/unknown`. The image is never resolved to bytes.
- The result is a `[Image: alt]` placeholder in every format.

The Decision Budget reporter worked around this by converting each SVG to PNG with
`rsvg-convert` before writing the Markdown. That workaround is the evidence that the need is
real.

## Scope by format

| Format | Native SVG | Plan |
|---|---|---|
| ODT, ODP, ODS | Yes (`image/svg+xml` is a valid ODF media type) | Phase 1 |
| HTML | Yes (references the file) | Already works if the path is kept |
| DOCX, PPTX, XLSX | No. Office needs a PNG fallback beside the SVG (`asvg:svgBlip`) | Phase 2, needs a decision |

## Phase 1: ODF embedding

1. `orchImageMime` maps `svg` to `image/svg+xml`, so the Markdown loader resolves SVG files
   to base64 like any other picture.
2. `image_embed.ail` already permits `image/svg+xml` through `embedIsEmbeddableMime`. The ODF
   generators need to stop excluding it. Check each one; `odf_image.ail` handles the frame.
3. Sizing. SVG has no pixel header, so `image_size.ail` needs a reader for the `width` and
   `height` attributes (with units) and, failing that, the `viewBox`. With neither, the 3:2
   fallback applies.
4. Verification: render in LibreOffice (ODT, ODP and ODS), and check that the picture stays
   vector when zoomed.

Security: an SVG can carry script and external references. Office and LibreOffice do not run
scripts from embedded images, but the parser should still reject SVG whose root element is not
`svg`, and strip `<script>` and `on*` attributes before embedding. Add a test for each.

## Phase 2: DOCX, PPTX and XLSX (decision needed)

These formats need a PNG rendering of the SVG alongside it. AILANG has no rasteriser, so the
options are:

- **A. External `rsvg-convert` (or similar) in the API image.** Smallest code change. It adds a
  system dependency to the Cloud Run image and a new failure mode, and the rasteriser's output
  depends on its version.
- **B. Require the author to supply a PNG.** No new dependency. Documented in the CHANGELOG and
  in the Markdown guide. This is today's workaround, written down.
- **C. Pure-AILANG rasteriser.** Not feasible for general SVG.

Recommendation: B now, and revisit A if users keep asking for SVG in Word or PowerPoint.

## Verification

- An ODT, ODP and ODS render with each SVG visible and undistorted.
- An SVG with `<script>` or an external reference produces the placeholder, and the test shows it.
- No-image output stays byte-identical to v0.52.0.
