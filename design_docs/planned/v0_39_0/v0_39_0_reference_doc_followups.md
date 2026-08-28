# `--reference-doc` follow-ups: section picking, numbering resolution, table styles

**Status**: PLANNED (2026-08-28)
**Source**: ailang message `inbox_1787906079375_e820fe40` from ailang-parse-claude — "Follow-ups after --reference-doc (DOCX style templates)", filed at `--reference-doc` ship time with the items deliberately left out.
**Follows**: the `--reference-doc` feature (CHANGELOG "Unreleased", working tree; module `docparse/services/docx_template.ail`).
**Related**: [`v0_19_0_style_inheritance.md`](../../planned/v0_19_0/v0_19_0_style_inheritance.md) — owns the *style-level* numbering half (see boundary in item 2); [`v0_32_0_generation_surfaces.md`](../../planned/v0_32_0/v0_32_0_generation_surfaces.md) — owns the MCP/WASM surface gaps (items 4–5 deferred there).

## Scope

Three follow-ups, all in the DOCX styling path, all verifiable against the
in-repo L6 templates:

1. `--reference-section N` — pick WHICH of a template's `<w:sectPr>` elements
   supplies page setup, headers and footers (today: always the last).
2. numbering resolution — replace `isOrderedList`'s `numId != "1"` guess with
   `numId → abstractNum → w:numFmt` read from `word/numbering.xml`.
3. template table styles — bind generated `<w:tbl>` to a table style the
   template defines, instead of hardcoded borders.

Deferred (unchanged from the source message, reasons recorded at the bottom):
MCP wiring (item 4), browser/WASM (5), ODT/PPTX templates (6), splice mode (7),
release chores (8, applied at tag time).

## Verified current state

Every claim below was checked against the working tree (2026-08-28), not taken
from the message.

| # | Claim | Evidence |
|---|---|---|
| C1 | `docxTplExtractSectPr` always lifts the LAST `<w:sectPr>` (`docxTplLastIndexOf`); no section selection exists | `docparse/services/docx_template.ail:182-199` |
| C2 | `--reference-section` / `referenceSection` appears nowhere in `docparse/main.ail` or `bin/docparse` | grep, 0 hits |
| C3 | `isOrderedList` decides bullet-vs-numbered with `numId != "1"`; `word/numbering.xml` is read nowhere in the parse path | `docparse/services/docx_parser.ail:553-564`; grep `numbering` in docx_parser.ail → comments only |
| C4 | `isListParagraph` requires a direct `<w:numPr>` in the paragraph's own `<w:pPr>` | `docparse/services/docx_parser.ail:546-552` |
| C5 | Generated `<w:tblPr>` hardcodes six `<w:tblBorders>` and emits no `<w:tblStyle>` | `docparse/services/docx_generator.ail:506` |
| C6 | L6 template `docx-hdrftr.docx` defines table styles `TableGrid` ("Table Grid") and `TableNormal` ("Normal Table"); `comments.docx` likewise has 2 table-type styles | unzip + grep `w:type="table"` → 2 each |
| C7 | Both L6 templates contain exactly ONE `<w:sectPr>` (the body one) — multi-section behaviour needs a synthesized variant | unzip + count → 1 each |
| C8 | `pandoc_table_list.docx`: numId 1 → abstract → `bullet`, numId 2 → `decimal`. The legacy heuristic answers both correctly by luck (pandoc's id convention) | unzip `word/numbering.xml`, resolved by hand |
| C9 | `challenge_numbering.docx` puts `numPr` in `ListBullet`/`ListNumber` **styles** (styles.xml), not on paragraphs; its golden contains **zero list blocks** — the file parses as plain text | unzip both parts; golden JSON inspection |
| C10 | The parser already has the threading shape this needs: `docxLoadRels` reads a secondary zip part with FS, parses it once, threads an immutable `Map[string,string]` through the pure walk | `docparse/services/docx_parser.ail:61-67`; `zip_extract.ail:82 readZipEntry` |

C9 is the one finding the source message did not have: the numbering defect is
two-layered. Style-based numbering (python-docx's `List Bullet`/`List Number`,
and anything Word styles carry) is not recognised as a list at all, which is a
bigger loss than mislabelling ordered-vs-bullet — but it belongs to v0_19_0
style inheritance, which already plans style-level `w:numPr` detection. This
doc fixes the numbering.xml layer and hands the style layer a resolved map to
consume (see boundary below).

## Item 1 — `--reference-section N`

### Problem (measured, from the source message)

A multi-section template has one `<w:sectPr>` per section plus the body-level
one, and the body one is the LAST section's. On the real client template
(Flying Fish consulting agreement):

```
sectPr[0] refs: header rId7, footer rId8   <- master agreement, CONFIDENTIAL footer
sectPr[1] refs: header rId10               <- Annex, no footer
output    refs: header rId10               <- today: the Annex furniture
```

Generated documents get the Annex header and no footer. The offer-letter
use case wants section 0's furniture. C1/C2 confirm the code cannot express
this today.

### Design

- CLI: `--reference-section N`, **1-based** — `1` is the first section, matching
  how Word numbers sections in the status bar ("Section 1 of 2"). Omitted →
  today's behaviour (last section). 0-based was considered and rejected: the
  message's own `sectPr[0]` notation is an array index in a bug report, not a
  user-facing convention, and "the first section" as `1` needs no explanation
  in `--help`.
- Validation: `N` must be an integer ≥ 1. Out of range (N > section count) is
  an error that writes nothing, naming the count — an off-by-one against a
  silent fallback would pick the wrong letterhead, the exact failure mode
  reference-doc exists to prevent.
- Resolution order: sections are numbered in **document order** of their
  `<w:sectPr>` elements. Mid-document sectPrs live inside a paragraph's
  `<w:pPr>`; collecting them in order is the same scan the stripper already
  does. `<w:sectPrChange>`-nested spans are dropped BEFORE collecting (C1's
  existing rule), so revision-tracked templates don't count phantom sections.
- API: `docxTplExtractSectPr` keeps its signature and semantics (last) as the
  default path; the section-aware entry point is
  `docxTplSectPrAt(docXml, section) -> string` where `section = 0` means "last"
  (today) and `section >= 1` means "Nth from the start". Both are `pure`,
  contract-carrying, and unit-testable without FS (C7: inline tests use
  synthetic multi-sectPr XML).
- Threading: `bin/docparse` parses and validates the flag → `main.ail`
  `getReferenceSection(args)` → `generateDocument` / `writeOutputs` →
  `generateDocxWithReference` gains the section parameter → `docxTplLoad`.
  No flag, no template, or template with a single sectPr: behaviour and bytes
  unchanged.

### Non-goals

No `--reference-section name` matching by header text; no negative from-end
indexing. One integer, validated, documented.

## Item 2 — numbering resolution (`isOrderedList`)

### Problem (verified)

C3: bullet-vs-numbered is decided by `numId != "1"`. It never resolves
`numId → abstractNumId → w:numFmt`. C8 shows why the suite stayed green: pandoc
assigns bullets numId 1, so the guess agrees with pandoc files by convention.
Our own reference-doc output lands on numId 8/9 (ids above the template's max),
so DocParse re-reading a document it just generated reports every bullet as
ordered. Word renders it correctly; our reader does not.

C9 adds the second layer: paragraphs numbered via styles carry no direct
`numPr` at all, so `isListParagraph` never fires and the file yields text
blocks. That layer is v0_19_0's.

### Design

- Read `word/numbering.xml` once per parse via the C10 shape:
  `readZipEntry(path, "word/numbering.xml")` in `zip_extract.ail` (new
  `readDocxNumbering(path)`, same contract as `readDocxRelationships`: missing
  part → empty string), parsed once in `parseDocx`, threaded as immutable maps
  through the otherwise-pure walk.
- Two maps, built in one pass over numbering.xml:
  - `numId → abstractNumId` from `<w:num w:numId="N"><w:abstractNumId w:val="A">`
  - `abstractId → lvl XML` (the `<w:abstractNum>`'s inner string), so the
    per-paragraph lookup can find the `<w:lvl w:ilvl="K">` matching the
    paragraph's own `w:ilvl` (default `0`) and read its `<w:numFmt>`.
- Classification: `numFmt = "bullet"` → unordered; any other known format
  (`decimal`, `lowerLetter`, `upperLetter`, `lowerRoman`, `upperRoman`,
  `decimalEnclosedCircle`, `aiueo`, …) → ordered. The numFmt string, not a
  hand-list of ids, is the decision — that is the whole point.
- Fallback: numbering.xml absent, numId dangling, or no matching `<w:lvl>` →
  keep the legacy convention (`numId != "1"`). Rationale: files with no
  numbering.xml are exactly the files whose behaviour must not move (C8-adjacent:
  `sample.docx` has numPr with no numbering.xml), and a dangling id is
  unresolvable by definition. This bounds golden churn to files that actually
  carry resolvable, non-pandoc-convention numbering.
- Known indirection not followed (recorded, deliberately): `<w:numStyleLink>`
  points at a numbering-carrying paragraph style — resolvable only with style
  inheritance, i.e. v0_19_0. Files relying on it fall back to the legacy
  heuristic, which is what they get today.
- The generator side needs no change: `docxNumberingDefs` already emits real
  `numFmt` values (`bullet`/`decimal`), and reference-doc mode already allocates
  ids above the template's max.

### Boundary with v0_19_0 (recorded, not left implicit)

This item delivers: numbering.xml on the read path, numId-keyed resolution,
numFmt-based classification — for paragraphs with direct `numPr`. v0_19_0 style
inheritance delivers: styles.xml parsing, `basedOn` chains, **style-level
`numPr` detection** — which is the fix for C9. When it lands, its style-level
resolution should call the same classification (numFmt decides), so there is
one definition of bullet-vs-ordered, not two.

## Item 3 — template table styles

### Problem (verified)

C5: the generator emits hardcoded borders and no `<w:tblStyle>`. C6: the L6
template defines `TableGrid`, unused. Tables are the one visual element that
still looks generated under a reference doc.

### Design

- Only in reference-doc mode, and only when the template actually defines a
  usable table style, the generator emits
  `<w:tblStyle w:val="STYLEID"/>` as the first child of `<w:tblPr>` and drops
  the hardcoded `<w:tblBorders>` (direct formatting would override the style —
  emitting both would silently keep our look and defeat the feature).
  `<w:tblW>` and `<w:tblLayout>` stay (layout is ours to own; width is content).
- Style resolution (`docx_template.ail`, at load, from the template's
  styles.xml):
  1. a table-type style whose `w:name` is `Table` (Pandoc's convention) —
     preferred;
  2. else the first table-type style whose name is NOT the implicit default
     (`Normal Table` / `Table Normal` — every table already has it; pointing at
     it is a no-op that looks like success);
  3. else none → today's output, byte-identical.
  The chosen id is carried on `DocxRefDoc` as `tableStyleId: string` (empty =
  none), so `docxPlan` branches on one field like every other template concern.
- `--table-style NAME`: explicit override, matched on `styleId` first, then
  `w:name`. No match → error, nothing written (same policy as an unreadable
  reference). Without `--reference-doc` → error: a `tblStyle` naming a style no
  styles.xml defines is a dangling reference, and dangling styles are how Word
  renders a table with no borders at all.
- The no-template path never emits `<w:tblStyle>`: without a carried styles.xml
  the id would name nothing. Byte-identity of today's default output is
  preserved (verified by the office suite goldens).

## Deferred items (from the source message, with reasons)

- **MCP surface (msg item 4)**: `mcpConvert`'s fixed 4-arg signature and hosted
  mode cannot receive a local template path; how a hosted API receives a
  template (upload? sample id? gs:// ref?) is a design question, not a
  parameter. Belongs with the v0_32_0 convert-endpoint work
  (`CONTRACT_convert_endpoint.md`).
- **Browser/WASM (msg item 5)**: `docxPartsFor` is `pure` and a template needs
  FS; the fix is passing template parts as bytes from JS. Unscoped; same
  surface theme as above.
- **ODT/PPTX templates (msg item 6)**: same mechanic, different packages. ODT
  is arguably easier (styles already live in a separate part); PPTX is bigger
  (layout ids). Each deserves its own doc.
- **Splice mode (msg item 7)**: different feature — marked-region insertion and
  anchor-matched amendment placement are XML surgery on the template's body,
  not part swapping. Do not conflate; scope separately.
- **Release chores (msg item 8)**: version sync, re-vendor `docs/ailang` via
  `vendor-wasm-packages.sh`, tag-triggered CI publish, notify the deployment
  repo (`ailang messages send docparse`). Applied at tag time, not in this
  sprint.

## Verification plan

- **Inline tests** (`ailang` `--test`): pure-function tests for
  `docxTplSectPrAt` (order, `<w:sectPrChange>` exclusion, self-closing forms,
  out-of-range), table-style picking (Pandoc name, default skip, absent), and
  numbering resolution (bullet/decimal/dangling/no-xml fallback).
- **`benchmarks/verify_generated.py` L6 RefDoc**:
  - existing assertions unchanged;
  - new: generated-under-`TableGrid` template carries
    `<w:tblStyle w:val="TableGrid"/>` and no hardcoded borders;
  - new: multi-section behaviour — synthesize a two-`sectPr` variant of
    `docx-hdrftr.docx` in the stage (rewrite `word/document.xml` of a copy),
    generate with `--reference-section 1`, assert the lifted `sectPr` is the
    first one (C7: no in-repo multi-section template exists; synthesizing keeps
    the fixture honest about what it stresses).
- **Three suites after any parser/generator change** (CLAUDE.md hard rule):
  `run_benchmarks.py --suite office` 100%, `roundtrip_check.py`,
  `verify_generated.py`. Numbering goldens that legitimately move are
  regenerated and listed in the CHANGELOG entry.
- **`./bin/docparse --check` and `--prove`**: type-check all modules; zero
  contract violations.
- **Round-trip proof of item 2**: generate a DOCX from markdown with bullets
  and numbered lists under a reference doc whose numbering ids collide with
  pandoc conventions (numId 1 = decimal), parse it back, assert bullets stay
  unordered — the exact case the message reported.

## Verification log

| Claim | How verified |
|---|---|
| C1 last-sectPr lifting | Read `docx_template.ail:182-199` (`docxTplLastIndexOf`) |
| C2 no section flag | `grep referenceSection docparse/main.ail bin/docparse` → 0 hits |
| C3 heuristic + numbering.xml unread | Read `docx_parser.ail:553-564`; grep `numbering` in parser → comments only |
| C5 no tblStyle, hardcoded borders | Read `docx_generator.ail:506` |
| C6 TableGrid present in L6 template | `unzip -p docx-hdrftr.docx word/styles.xml` → `TableNormal`, `TableGrid` |
| C7 single sectPr in L6 templates | unzip + count `<w:sectPr[ >]` → 1, 1 |
| C8 pandoc numFmt convention | Unzipped `pandoc_table_list.docx word/numbering.xml`; resolved numId 1 → bullet, 2 → decimal |
| C9 style-based numbering invisible | Unzipped `challenge_numbering.docx`: `document.xml` has `pStyle="ListBullet/ListNumber"` and no `<w:numId>`; `styles.xml` maps those styles to numId 1/2/3 (bullet) and 5/6/7 (decimal); golden has no `list` blocks |
| Map API available for threading | `ailang docs std/map` (`fromList`, `lookup`, `Option`) |
| Secondary-part read helper exists | `zip_extract.ail:62 readDocxRelationships`, `:82 readZipEntry` |