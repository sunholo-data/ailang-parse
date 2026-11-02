# Sprint Plan: PDF Structure Recovery (v0.54.0)

**Design doc**: [v0_54_0_pdf_structure_recovery.md](v0_54_0_pdf_structure_recovery.md) (PR #120)
**Sprint ID**: M-PDFSTRUCT
**Branch**: `feat/pdf-structure-recovery` (off `docs/pdf-structure-recovery`)
**Duration**: ~3 working days, 6 milestones, each sized for one sitting
**Risk**: Medium. The heuristics in M4 are the uncertain part, which is why the benchmark (M5)
is built to tune them, not written afterwards.
**AILANG prompt version loaded**: v0.16.8 (`ailang prompt --version-active`). Load it with
`ailang prompt` before writing `.ail` code.

## Rulings (from the user, 2026-11-02, not open)

1. `poppler` ships **opt-in**. `pdftotext` keeps its name and its parse output stays
   byte-identical.
2. The furniture pass runs on `poppler`, `docling`, `liteparse` and `ai` parse output. On
   `pdftotext` it runs only when the CLI `--convert` target is a document format (docx, odt,
   pptx, odp, html, md, qmd), never on parse JSON.
3. Recovered heading levels are kept, with no normalisation to H1.

## Constraint found while planning

`ParseOptions` must **not** gain a field. docparse's `api_server.ail:424` builds the record
literally, so a new field breaks the hosted API on its next `ailang_parse` bump. The
`--convert` furniture path (ruling 2) is therefore an exported function
(`pdfFurnitureApply`) that `main.ail` calls on the convert path. docparse can call the same
function from its own convert service in a follow-up.

## Registry reuse

| Milestone | Package | Action | Reason |
|---|---|---|---|
| M1–M6 | `sunholo/external_backend` | depend (already) | Still the adapter's exec/JSON bridge; unchanged |
| M2 | — | none | `ailang pkg search` for pdf/furniture/page header/layout/poppler: nothing does header/footer detection over blocks |
| M3–M4 | — | none | Python adapter code inside ailang-parse; not an AILANG package capability |

## Milestones

### M1: Adapter protocol: list, image, page, region (~90 LOC)

- `pdf_backend_external.ail` `decodeBlock`:
  - `kind: "list"` → `ListBlock` (items, ordered, itemLevels).
  - `kind: "image"` → `ImageBlock` (data, mime, width, height, description).
  - A block carrying `region: "header" | "footer"` → `SectionBlock({kind: region, name: "page N", blocks: [inner]})`.
- `decodeBlocks` keeps its `listLength(result) == listLength(arr)` contract.
- `adapter.py`: `_list()`, `_image()` helpers, and an optional `page`/`region` on `_text`/`_heading`.
- **Acceptance**: `./bin/docparse --check` and `--prove` pass. An inline/`main()` test decodes
  each new kind. The `pdftotext` JSON for the 3 golden PDFs is byte-identical to `origin/main`.

### M2: Furniture pass, `docparse/services/pdf_furniture.ail` (~220 LOC + tests)

- Pure core:
  - normalise text (collapse whitespace, replace digit runs with `#`);
  - count recurrences of short blocks (≤120 chars);
  - threshold `max(2, ceil(pageCount/2))`, with pageCount taken from metadata, or from the
    number of page-number blocks when that is 0;
  - recognise bare page numbers;
  - classify header vs footer by position relative to the page's first body block.
- Explicit `region` sections from M1 are taken as given.
- Output: one `SectionBlock` header and one footer, each with the first occurrence's blocks.
  All other occurrences and page numbers are removed.
- Contracts:
  - `listLength(result) <= listLength(input)`, on an extracted counting core that Z3 can
    check (the `workbookCellsInRect` pattern);
  - `result == false || …` style implications on the predicates.
- Exported: `pdfFurnitureApply(blocks: [Block], pageCount: int) -> [Block]`.
- Wiring, in `orchPdf`:
  - applied for the explicit `poppler`/`docling`/`liteparse` branch and the `ai` branch;
  - also applied on the default ladder when it escalated away from pdftotext;
  - not applied on explicit `pdftotext`, or on the default ladder when pdftotext answered.
- Add the module to `bin/docparse` MODULES (CI's `check-module-list.py`).
- **Acceptance**:
  - inline tests, plus a `main()` test over a synthetic 4-page block list built from invented
    text;
  - `--prove` proves the new contracts;
  - the AI-backend proposal parse has no "PROPOSAL", "Trustworthy AI code" or footer text
    outside the header/footer sections, and no bare page numbers;
  - the 3 golden PDFs unchanged on pdftotext.

### M3: Adapter tests, docling item walk, liteparse fix (~220 LOC)

- `tests/test_pdf_adapter.py` (stdlib `unittest`, no poppler or docling needed). Fakes stand in
  for docling items and liteparse text items.
- `run_docling` walks `document.iterate_items()`:
  - title → h1;
  - section_header → h(level+1);
  - list items grouped into a list;
  - tables taken from the cells;
  - page_header/page_footer → region;
  - pictures skipped, so `<!-- image -->` text is never emitted.
- The scanned-PDF fallback keeps working: if nothing substantive comes back, walk again with
  picture children included.
- liteparse: match headings per text item, rank sizes into levels 1–3.
- Add a CI step: `python3 -m unittest tests/test_pdf_adapter.py`.
- **Acceptance**:
  - unit tests pass;
  - locally, docling on the proposal gives headings at ≥2 distinct levels, 3 lists, 4 tables
    and no `<!-- image -->` text;
  - liteparse finds >0 headings.

### M4: `poppler` backend (~450 LOC Python + tests)

- `run_poppler`:
  - parse `pdftotext -bbox-layout` (text, geometry) and `pdftohtml -xml -i -stdout` (size,
    bold, links) with stdlib `xml.etree`;
  - join the two by page and line-box overlap.
- Classify each line as heading, list item, table row, furniture region or paragraph, per
  design doc §2.
- Register `"poppler"` in the backend table. In AILANG, add it to the backend-name docs, CLI
  help and the capability text, and handle it in `orchPdf`'s explicit branch (no ladder
  change).
- Unit tests on small invented XML fixtures inlined in the test file:
  - heading-level ranking;
  - paragraph reflow;
  - bullet and numbered lists;
  - a column-snapped table with a bold header;
  - top/bottom region tagging;
  - a link run.
- **Acceptance**:
  - unit tests pass;
  - `table_report.pdf` gives 1 table (5 columns, header + 5 rows);
  - the proposal gives ≥15 headings at ≥2 levels, 4 tables and 3 lists, with header/footer
    in sections;
  - run time under 2s for the proposal locally.

### M5: Round-trip benchmark and visual check (~250 LOC)

- `benchmarks/pdf/structure_roundtrip.py`:
  - for our own DOCX sources (the 3 proposals plus `data/test_files` DOCX with headings,
    tables, lists and header/footer), `soffice --headless --convert-to pdf` into a temp dir;
  - parse both the source and the PDF with each available backend;
  - score heading recall and level agreement, table count and cell-text F1, list item recall,
    furniture leakage, and body text similarity;
  - write a Markdown table.
- Backends that are not installed are skipped and reported as such.
- Run it, then tune the M4 thresholds against it.
- Render PDF → DOCX with and without the reference doc to PNG and read the pages.
- **Acceptance**:
  - the benchmark runs and records results in the PR;
  - `poppler` beats `pdftotext` on every structural metric;
  - furniture leakage is 0 for poppler, docling and ai;
  - the proposal with its reference doc renders as 4 pages.
- Plus a run inside the docparse image's poppler. This is a stretch item; if it can't be done
  locally, note it for the docparse PR.

### M6: `--convert` furniture on pdftotext, docs, release notes (~120 LOC)

- `main.ail` convert path: when the input format is pdf and the convert target is a document
  format, apply `pdfFurnitureApply` before generation, whatever the backend. It is
  idempotent, so running it after M2 changes nothing.
- CLI help: add `poppler` to `--pdf-backend`. Update README / docs PDF backend table and
  CHANGELOG (Unreleased).
- **Acceptance**:
  - the default `docparse proposal.pdf --convert out.docx --reference-doc …` has no
    footer/header text in the body;
  - without a reference doc, the DOCX has real header/footer parts;
  - parse JSON on pdftotext is unchanged;
  - all CI checks pass locally: `--check`, `--prove`, inline tests, `check-module-list.py`,
    `check-format-lists.py`, and `check-doc-examples.py`.

## Validation (every milestone)

`./bin/docparse --check`, `./bin/docparse --prove`, `python3 docs/scripts/check-module-list.py`,
`python3 -m unittest tests/test_pdf_adapter.py` (from M3), and the golden-PDF byte-identity
check on pdftotext. Use the released AILANG binary matching CI's floor if the local dev build
reports type errors that CI wouldn't.

## Estimate

| Milestone | LOC |
|---|---|
| M1 | 90 |
| M2 | 220 |
| M3 | 220 |
| M4 | 450 |
| M5 | 250 |
| M6 | 120 |
| **Total** | **1,350** |

Over the last 14 days ailang-parse shipped 45 commits on main. 1,350 LOC across 6 focused
milestones is about 3 days.

## Out of scope

Image extraction (the logo), heading normalisation, making `poppler` the default ladder rung,
and the docparse (hosted) wiring. Each is a follow-up once M5's numbers are in.
