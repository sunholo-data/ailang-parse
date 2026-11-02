# Design Doc: Recover Document Structure from PDFs (v0.54.0)

**Status**: Planned
**Date**: 2026-11-02
**Author**: Mark + Claude
**Motivation**: PDF → DOCX with `--reference-doc`. The template side works; the parse feeding it
does not.

## Problem

`docparse in.pdf --convert out.docx --reference-doc ref.docx` runs end to end on every backend.
The reference doc is applied correctly each time (header, logo, footer, fonts, page setup,
`--table-style`). What the template has to style, though, is only as good as the PDF parse, and
the parse is weak.

We measured this on 2026-11-02 with `docs/templates/output/ailang-proposal.pdf`, chosen because
the source `ailang-proposal.docx` sits beside it and gives a ground truth. We converted it with
`--reference-doc references/ailang-reference.docx --table-style SunholoTable`:

| Backend | Time | Blocks recovered | Source has |
|---|---|---|---|
| `pdftotext` (default) | 0.4s | 53 text, 0 headings, 0 tables, 0 lists | 17 headings, 4 tables, 3 lists |
| `liteparse` | 1s | 51 text, 0 headings | |
| `docling` | 11s | 17 headings (all level 2), 4 tables, 22 text | |
| `ai` (Gemini 2.5 Flash) | 30s | 19 headings (levels 1–3), 4 tables, 3 lists | |

Defects found, by cause:

1. **Page furniture lands in the body on every backend.** That covers the running header
   (`AILANG  PROPOSAL`, `Trustworthy AI code`), the footer (`Holosun ApS · CVR …`) and bare page
   numbers. With a reference doc this is pure duplication. On the `ai` backend the running header
   becomes an H1 on every page, and the reference template breaks the page before each H1, so
   the 4-page source comes out as 7 pages.
2. **The default backend has no structure at all.** `run_pdftotext` uses `pdftotext -layout`
   and `_blocks_from_plaintext` on purpose ("no structural inference"). Tables come out as
   space-aligned text, and sentences keep the PDF's hard line breaks. Even the synthetic
   `data/test_files/table_report.pdf` returns 7 text blocks and no table. This is the backend
   hosted users actually get. The hosted image deliberately installs neither docling nor
   liteparse: docparse's `pdf_backend.pyproject.toml` has no dependencies, to keep the image
   small. Docling would not fit serve-api's fixed 30s Process timeout anyway. So on the API
   the choice is flat text or paid AI.
3. **Docling goes through a Markdown round trip.** `run_docling` calls `export_to_markdown()`
   and re-parses the result with `_blocks_from_markdown`, which:
   - flattens every heading to level 2, because the Markdown export writes `##` for all
     section headers;
   - joins each list into one paragraph, because `_blocks_from_markdown` has no list case;
   - passes the `<!-- image -->` placeholder through as a text block, so it appears as literal
     text in the generated DOCX.
4. **The adapter protocol cannot carry lists or images.** `decodeBlock` in
   `pdf_backend_external.ail` knows `heading`, `table` and `text`, and any other kind falls back
   to text. So even a backend that finds a list cannot hand it over.
5. **The liteparse heading heuristic never matches.** `run_liteparse` tests whole lines against
   a set of font-size *fragments* (`line in heading_texts`), so it finds 0 headings. The level is
   also hard-coded to 2.
6. **Duplicate glyphs.** This PDF (LibreOffice export) draws some glyphs twice at the same
   position. Docling and `pdftohtml -xml` both read the duplicates, giving "matteers",
   "diffeerent", "Thee", "Confinrm" and "CVR 443 243 7". `pdftotext` (both `-layout` and
   `-bbox-layout`) removes overlapping duplicates and reads it cleanly.

## Goal

A text-layer PDF should come back with headings at the right levels, tables, lists, paragraphs
reflowed across line breaks, and its running header and footer separated from the body. It
must stay deterministic, free, and fast enough for the hosted 30s Process limit. With a
reference doc the result should look like the source document. Without one, the PDF's own
header and footer should become real Word header and footer parts.

## Approach

### 1. Furniture pass, in AILANG, for every backend

A new pure module, `docparse/services/pdf_furniture.ail`, runs on the blocks of every PDF
backend (including `ai`) before they leave the orchestrator.

- **Detect.** A short block (under ~120 chars) is furniture when its normalised text recurs on
  at least `max(2, ceil(pageCount / 2))` pages. Normalising means collapsing whitespace and
  replacing digit runs with `#`, so `… 1` / `… 2` and `CVR 44 324687` / `CVR 44324687` match.
  `pageCount` is already in the metadata. A bare integer block in `1..pageCount` that follows a
  furniture block counts as a page number. When the backend supplies `page` and `region` (see
  §3), those take precedence over the repetition heuristic.
- **Place.** Keep one copy of each furniture run and drop the others and the page numbers. It is
  a header if its first occurrence comes before the first body block of its page, otherwise a
  footer. Emit it as `SectionBlock({kind: "header" | "footer", …})`. `docx_generator.ail`
  already turns these into real header and footer parts, and already ignores them when
  `--reference-doc` is active (`docxPlan`, lines 81–82). So both cases come out right with no
  generator change.
- **Contracts.** The output block count is ≤ the input count, and no body block's normalised
  text equals a furniture block's. Both are pure list and string logic, so Z3 can check them as
  long as the counting core is kept out of `foldl` (the `workbookCellsInRect` pattern).

### 2. A structured poppler backend (`poppler`)

This is not a new engine. It is a second way of reading the poppler output we already depend
on, added as a backend name in `adapter.py`.

**System requirements: none new.** The hosted runtime image (`debian:bookworm-slim`) already
installs `poppler-utils`, and that package ships `pdftotext`, `pdftohtml`, `pdfinfo` and
`pdftoppm`. The adapter imports only the Python stdlib, and docparse's
`pdf_backend.pyproject.toml` stays dependency-free. The image gains no packages and no size,
so this is the one improvement that reaches hosted users. Adding a whole engine (docling,
liteparse) would cost image size, which is why the hosted image has none today.

One constraint follows. bookworm's poppler (22.x) is older than a developer's Homebrew poppler
(26.x). `-bbox-layout` and `-xml` are long-standing, but duplicate-glyph removal and the way
lines are segmented can differ between versions. So the heuristics and the benchmark must be
run against the image's poppler, for example by running the benchmark inside the
docparse image in CI.

- **Text and geometry** come from `pdftotext -bbox-layout`, which gives flows, blocks, lines and
  words with bounding boxes, with duplicate glyphs already removed (defect 6).
- **Style** comes from `pdftohtml -xml -i -stdout`: font size per `fontspec`, `<b>`/`<i>`, and
  `<a href>`. The two outputs are joined by page and by overlap of line boxes. Style is used only
  to *classify* lines, never as their text.
- **Headings.** Body size is the modal font size weighted by characters. A line is a heading
  candidate when its size is at least 1.15× body, or when it is bold, short, its own block, and
  not followed on the same line. Distinct heading sizes, ranked, give levels 1–3. The largest
  text on page 1, when it is used only once, is the title.
- **Paragraphs.** Join consecutive lines in a block that share a font and a left edge, and whose
  vertical gap is ≤ 1.5× line height. This fixes the hard breaks.
- **Lists.** A line starting with a bullet glyph (`•▪◦–-`), or with `\d+[.)]` plus a hanging
  indent, is a list item. Its level comes from the indent, and a run of items becomes one list.
- **Tables.** Two or more consecutive rows of two or more segments, whose left edges snap to a
  shared column set within a tolerance, form a table. The first row is the header when it is
  bold. The segments are already separate in `pdftohtml` (one `<text>` per cell, as verified on
  `table_report.pdf` and the proposal).
- **Furniture hints.** Lines in the top or bottom 8% of the page height are tagged
  `region: "header" | "footer"`, so §1 doesn't have to guess.
- **Links.** Text inside `<a href>` becomes an inline link run (this restores the proposal's
  "Sunholo website" link).

Images (the logo) are out of scope here. `pdftohtml` without `-i` can extract them, but they
need the same temp-path handling as `check_image_temp_paths.py` covers, so they get a separate
follow-up.

### 3. Adapter protocol additions

Two optional fields go on every block, `page: int` and `region: "body" | "header" | "footer"`.
Two kinds are added:

```
{"kind": "list",  "items": [str], "ordered": bool, "levels": [int]}
{"kind": "image", "data": str (base64), "mime": str, "width": int, "height": int, "description": str}
```

`decodeBlock` maps these to `ListBlock` / `ImageBlock`. The adapter and the decoder ship in the
same package, so no version skew is possible. Older adapters simply never emit the new kinds.
`decodeBlocks` keeps its 1:1 count contract.

### 4. Docling: walk the document, not its Markdown

Replace `export_to_markdown()` → `_blocks_from_markdown` with `document.iterate_items()`:

| Docling item | Block |
|---|---|
| title | heading level 1 |
| section_header | heading `level + 1`, capped at 6 |
| list_item | grouped into a list, ordered from the item's `enumerated` flag |
| table | table, from `export_to_dataframe()` or the table cells |
| page_header, page_footer | `region` header or footer |
| picture | skipped (image follow-up); never a `<!-- image -->` text block |

The scanned-PDF fallback (`traverse_pictures=True`) stays, re-expressed as descending into
picture children. Duplicate glyphs (defect 6) are a docling text-layer issue. Try docling's
pypdfium backend against `docling-parse` on the proposal, and keep whichever matches
`pdftotext`'s text. If neither does, document it as a known docling limitation.

### 5. liteparse

Match headings per text item, not per joined line, and rank sizes into levels as in §2.
This is small. If §2 lands, liteparse has little left to offer and could be deprecated, but
that is a separate decision.

## Open questions

1. **Make `poppler` the default?** `pdftotext` is documented as layout-preserving "so tables and
   signature grids stay faithful", and existing users rely on that. Recommendation: ship
   `poppler` as opt-in, measure it, then make it the default ladder's first rung (`poppler →
   docling`) with `pdftotext` kept unchanged by name. This needs a minor version bump and a
   CHANGELOG note. docparse (the hosted API) would pick it up via its `ailang_parse` pin.
2. **Should the furniture pass run on `pdftotext` too?** It changes output that existing users
   get. Recommendation: on for `poppler`, `docling` and `ai`. On `pdftotext` only when the output
   target is a document format (`--convert`), not for parse JSON.
3. **Heading levels against a reference doc.** In these templates H1 starts a new page. Should
   `--convert` with a reference doc normalise the shallowest heading in the body to H1, or keep
   the recovered levels as they are?

## Verification

- **New benchmark `benchmarks/pdf/structure_roundtrip.py`.** For each source DOCX (the three
  proposals, plus DOCX files from `data/test_files/` with headings, tables, lists and a
  header/footer), render a PDF with `soffice --headless --convert-to pdf`, parse the source DOCX
  and the PDF, and score the PDF parse against the source on:
  - heading recall and level agreement;
  - table count and cell-text F1;
  - list item recall;
  - furniture leakage (header/footer text in the body, which must be 0);
  - body text similarity.
  Run it per backend, so the table above becomes a tracked number.
  Fixtures are our own documents only (see the never-copy-reporter-data rule).
- `benchmarks/pdf/golden/*.json` (3 synthetic PDFs) do not regress, and `table_report.pdf`
  yields one 5-column table.
- `pdftotext` backend output is byte-identical to v0.53.0 unless open question 2 decides
  otherwise.
- PDF → DOCX with and without a reference doc, rendered with LibreOffice to PNG and read page
  by page (the verify-docs loop). The proposal comes out as 4 pages in its template, and with
  no template the header and footer appear as real Word header and footer parts.
- Timing: `poppler` on a 50-page text PDF stays well inside 30s on the hosted image.
- `ailang check`, inline tests for the furniture core, `./bin/docparse --prove` for its
  contracts, and adapter unit tests for line classification, table snapping and list grouping.

## Effort

Medium–large, but it splits cleanly into independent PRs, in order of user-visible value:

1. Protocol additions and the furniture pass: AILANG, small, fixes the `ai` backend at once.
2. The `poppler` backend: the bulk of the work, about 400 lines of Python in `adapter.py`.
3. The docling item walk: small, and it fixes the `<!-- image -->` leak.
4. The liteparse fix: trivial.
5. The benchmark: should land with or before item 2, so the heuristics are tuned against it.
