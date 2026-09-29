# Design Doc: Partner-Report Follow-ups (v0.47.0)

**Status**: Planned
**Date**: 2026-09-29
**Author**: Mark + Claude
**Source**: A BD partner's report (2026-09-29): a two-sheet workbook with
misaligned columns and mislabelled sheets, a 21-slide deck in the wrong order
with its speaker notes detached, and workbench failures on `comments.docx`,
`track_changes_move.docx` and `sample_rtf.rtf`. Fixed the same day by:

- [#73](https://github.com/sunholo-data/ailang-parse/pull/73) (open): XLSX
  cells placed by `r=` reference; sheets resolved through workbook rels.
- [#74](https://github.com/sunholo-data/ailang-parse/pull/74) (merged): WASM
  workbench budget, `markdown_parser` split, RTF on the workbench.
- [#75](https://github.com/sunholo-data/ailang-parse/pull/75) (open): PPTX
  slide order from `sldIdLst`; notes attached to their slide as
  `SectionBlock{kind:"notes", name:"Slide N"}`.

Each of those PRs lists what it left open. This doc designs those gaps, plus
three more found while checking them (G2b, G9, and the stale goldens in G8).
Code references are to the PR branches `origin/fix/xlsx-blank-cells` and
`origin/fix/pptx-slide-order-notes` where they differ from `main`.

**Related**:
- [v0.43.0 Colour extraction](../v0_43_0/v0_43_0_colour_extraction.md):
  cell-colour check keyed by position (`_coloured_cells` in
  `eval_office.py`). That is the model for the structural metric in G8.
- [v0.19.0 Comment threading](../v0_19_0/v0_19_0_comment_threading.md):
  the XLSX comment records G3 re-routes.
- [v0.40.0 PPTX reference doc](../v0_40_0/v0_40_0_pptx_reference_doc.md):
  `pptxRefContentTypes` already strips template notes parts. G1 has to
  change that.

---

## Summary

| # | Gap | Where | Priority | Size |
|---|-----|-------|----------|------|
| G3 | XLSX comments attached to the wrong sheet | `xlsx_parser.ail` | P0 | S |
| G2b | Workbench XLSX: sheets in string order, named `Sheet1..N` | `wasm-demo.js` | P0 | S |
| G9 | Image temp files share one path across documents | `zip_extract.ail` | P0 | S |
| G2 | Workbench PPTX has no speaker notes | `wasm-demo.js`, `docparse_browser.ail` | P1 | S |
| G1 | PPTX → PPTX drops speaker notes | `pptx_generator.ail` | P1 | M |
| G8 | Suite can't see structure; three stale goldens | `eval_office.py`, `normalize.py` | P1 | M |
| G4 | `a:fld` field text ignored | `pptx_parser.ail` | P2 | S |
| G7 | XLSX rows with no `<row>` element are skipped | `xlsx_parser.ail` | P2 | S |
| G6 | WASM type-check headroom | repo + AILANG upstream | P2 | M (repo) |
| G5 | `std/xml` drops undeclared prefixes; prefix-literal matching | AILANG upstream + repo | P3 | S (upstream) |

S is about half a day to a day. M is two to three days.

---

## G1. PPTX → PPTX conversion drops speaker notes

**Problem.** Since #75, notes are emitted as a top-level
`SectionBlock{kind:"notes", name:"Slide N"}` directly after each slide
section. The PPTX generator never writes them.

**Evidence** (run against the #75 branch):

```
parse  pptx_slide_order_notes.pptx         → 13 slide sections, 12 notes sections
--convert rt.pptx, then parse rt.pptx      → 13 slide sections,  0 notes sections
unzip -l rt.pptx | grep -c notesSlide      → 0
```

**Root cause.** `pptxSplitBySlides` in `docparse/services/pptx_generator.ail`
keeps a section only when `s.kind == "slide"`. Every other section, notes and
comments included, falls through to `else pptxSplitBySlides(rest, acc)` and is
dropped. The generator has no notes-slide, notes-master or `notesMasterIdLst`
output at all. On the reference-deck path, `pptxRefContentTypes` explicitly
removes the template's `/ppt/notesSlides/` overrides.

**Fix.**
1. Change the slide grouping from `[[Block]]` to
   `[{blocks: [Block], notes: [Block]}]`. A `notes` section attaches to the
   slide group immediately before it. A notes section with no preceding slide
   is dropped with a warning; that shape never comes from the parser.
2. For each slide that has notes, emit:
   - `ppt/notesSlides/notesSlideN.xml`: one `p:sp` with `<p:ph type="body" idx="1"/>`,
     one `a:p` per line of the notes text;
   - `ppt/notesSlides/_rels/notesSlideN.xml.rels`: links to the slide and to
     `../notesMasters/notesMaster1.xml`;
   - a `notesSlide` relationship in that slide's rels.
3. When any slide has notes, also emit `ppt/notesMasters/notesMaster1.xml`
   (minimal: `cSld` with a body placeholder, plus `clrMap`), its rels (to the
   theme), `<p:notesMasterIdLst>` in `presentation.xml` (after `sldMasterIdLst`),
   the presentation rel, and content-type overrides for each part.
4. Reference-deck path: if the template carries a notes master, reuse it and
   point new notes slides at it. Otherwise add ours. Stop stripping the
   notesSlides overrides only for the parts we write.
5. Number notes parts in deck order, so `notesSlideN` belongs to `slideN` in our
   output. The parser does not rely on that (it goes through rels).

ODP has the same gap (`odp_generator.ail` has no reference to notes) but is
out of scope here. Add it later with `presentation:notes`.

**Test plan.**
- New `benchmarks/check_pptx_notes_roundtrip.py`, wired into `ci.yml` next to
  the `create_pptx_order_fixture.py --verify` step. It parses
  `pptx_slide_order_notes.pptx`, converts it to PPTX, and parses the result.
  Exact assertion: the list of `(name, text)` for notes sections is identical
  before and after, and each notes section directly follows the slide section
  at the same index. Fails today with `0 != 12` notes.
- The same file with `--reference-doc` set to a template that has a notes master,
  and to one without.
- `verify_generated.py`: LibreOffice opens the output. Check it by hand in
  PowerPoint/Keynote once (verify-docs skill). A notes slide without a notes
  master is a known "repair this file" trigger in PowerPoint.

**Risks.** PowerPoint is strict about notes parts. The minimal notes master
must be validated in PowerPoint, not only LibreOffice. Adding step cost to
`pptx_generator` affects the WASM gate only if the lab page loads it (only
`docx_generator` is lab-loaded today).

**Size.** M.

---

## G2. Workbench (WASM) PPTX path has no speaker notes

**Problem.** The public workbench never shows speaker notes.

**Root cause.** `parsePptxZip` in `docs/js/wasm-demo.js` reads only
`ppt/slides/slideN.xml` and calls `parsePptxSlide(xml)` in
`docparse/services/docparse_browser.ail`. That function takes one slide XML
and returns one slide section. The slide's rels and notes part are never
opened. The notes logic in `pptx_parser.ail` is `pptxSlideNotes`, which does
file I/O (`! {FS}`) and so can't be called from the browser. Its pure core,
`pptxFindNotesBodyText`, is not exported. Slide comments are missing on this
path too; that is noted here but not designed.

**Fix.**
1. Export a pure `pptxNotesSection(notesXml: string, slideNo: int) -> [Block]`
   from `pptx_parser.ail`. It wraps `pptxFindNotesBodyText` and is shared by
   `pptxSlideNotes`, so the server and browser paths can't drift.
2. Add binding `parsePptxNotes(notesXml, slideNo)` in `docparse_browser.ail`.
   Register it in the bindings list checked by `check-wasm-bindings`.
3. In `parsePptxZip`, for slide *i* (deck order):
   - read `ppt/slides/_rels/<name>.rels`;
   - find the Relationship whose `Type` ends `/notesSlide`, and resolve its
     `Target` relative to `ppt/slides/`. There is a pure `pptxResolveTarget`
     in `zip_extract`; expose it the same way `orderPptxSlides` was;
   - call `parsePptxNotes`, and append the result after the slide's blocks.
4. Mirror `docs/ailang/...` copies.

**Test plan.** Extend the #75 Playwright test in `tests/browser/wasm-smoke.spec.ts`
("browser returns the fixture's slides in deck order"). Assert that the
`(kind, name)` sequence of sections from `DocParseEngine.parseFile` equals the
server's sequence from `create_pptx_order_fixture.py`'s expectation, notes
included. It fails today because no `notes` sections are returned.

**Risks.** Adds one or two zip reads per slide, bounded by `MAX_SLIDES = 50`.
`pptx_parser` is at 16k steps, so there is no budget concern.

**Size.** S.

## G2b. Workbench XLSX still has the #73 sheet bugs (found while checking G2)

**Problem.** #73 fixed sheet order and names in `xlsx_parser.ail`. The browser
does not use that code. On the #73 branch, `parseXlsxZip` in
`docs/js/wasm-demo.js` still does:

```js
.filter(n => n.match(/^xl\/worksheets\/sheet\d+\.xml$/)).sort();   // lexicographic
var sheetName = 'Sheet' + (i + 1);                                   // not the tab name
```

So on the workbench, the partner's workbook still shows tabs in part-number
string order (`sheet10` before `sheet2`), with generic names. Cell placement
*is* fixed there, because `parseXlsxSheet` → `parseSheetXml` uses the new row
fold.

**Fix.** Same pattern as #75's `orderPptxSlides`:
1. Make `xlsxResolveWorkbookSheets(workbookXml, relsXml, parts)` in
   `xlsx_parser.ail` public. It is already pure.
2. Add a `orderXlsxSheets(workbookXml, relsXml, entries)` binding that returns
   `name\tpart` lines.
3. Use it in `parseXlsxZip`. Keep the numeric-sort fallback.

**Test plan.** Add a Playwright test that loads `challenge_sparse_rows.xlsx`
(from #73) through `DocParseEngine.parseFile`. Assert that sheet section names
equal `check_xlsx_positions.py`'s `EXPECTED_SHEETS`. Better: have that script
emit its expectations as JSON so both checks share one list. It fails today
with `Sheet1, Sheet10, Sheet11, Sheet2 …`.

**Size.** S. It should land with or right after #73.

---

## G3. XLSX comments matched to sheets by position

**Problem.** Comments are attached to the wrong sheet, and anchored to the wrong
cell's text, on any workbook where comment parts don't line up one-to-one with
sheets in tab order.

**Evidence** (openpyxl, two sheets, one comment on `Reviewed!B1 = 1200`, run
against the #73 branch):

```
xl/comments/comment1.xml   ← referenced by xl/worksheets/_rels/sheet2.xml.rels
parsed:
  sheet   Plain     [...]
  comment           author Ann, "Check this figure", anchorText "B1"   ← wrong sheet; should be "1200"
  sheet   Reviewed  [Budget | 1200]
```

**Root cause.** `xlsxReadLegacyComments` and `xlsxReadThreadedComments` in
`docparse/services/xlsx_parser.ail` do `nth(findXlsxCommentEntries(...), sheetIdx)`
and `nth(findXlsxThreadedEntries(...), sheetIdx)`. `sheetIdx` is the tab-order
index from `xlsxParseOneSheet`. The entry lists are ZIP-listing order from
`zip_extract.ail` (`filterByPrefix`). Excel numbers comment parts by creation
order, and only for sheets that *have* comments. So the positional pairing is
wrong whenever a sheet without comments comes before one with comments. That
is the common case.

**Fix.** Resolve through the sheet's own rels, as #75 does for PPTX notes:
1. Change `xlsxSheetCommentRecords(filepath, idx)` to take the sheet part
   `entry`.
2. Read `xl/worksheets/_rels/<sheetN>.xml.rels`, and take targets whose `Type`
   ends with `/comments` (legacy) or `/threadedComment` (MS 2017 relationship
   URI). Resolve them relative to `xl/worksheets/`. Absolute `/xl/...` targets
   also occur; `challenge_comments.xlsx` uses one.
3. Fallback: if *no* sheet rels in the workbook reference any comment part,
   keep today's positional pairing, but only when there is exactly one sheet.
   `challenge_threaded_comments.xlsx` is a hand-built single-sheet file with no
   sheet rels at all, and must keep working.
4. Comment parts that no sheet references and that the fallback doesn't claim:
   emit them unanchored after the last sheet with a `warnings` entry. Don't
   drop them silently.

**Test plan.** Build a fixture `challenge_comments_multisheet.xlsx` in
`benchmarks/create_challenge_files.py` with three sheets:
- sheet 1 has no comments;
- sheet 2 has a legacy note on `B1`;
- sheet 3 has a threaded comment on `C4`;
- comment parts are numbered in the *opposite* order to the sheets.

Add to `check_xlsx_positions.py`: exact `(sheet name, comment text, anchorText)`
triples, and each comment section must come after its own sheet section. It
fails today. Existing goldens `challenge_comments` and
`challenge_threaded_comments` should not change.

**Risks.** Threaded comment rel types differ between Excel builds. Match on
the suffix, as `pptxIsNotesRel` does, not on the full URI.

**Size.** S.

---

## G4. PPTX `a:fld` field text ignored

**Problem.** `a:fld` runs (slide number, date/time, and other fields) carry
their display text in a cached `<a:t>`. The parser drops them. On a slide
where a text box reads "Slide `<fld slidenum>`7`</fld>` of 20", the output is
"Slide  of 20".

**Root cause.** In `docparse/services/pptx_parser.ail`, `drawingMLNodeText` and
`drawingMLNodeRuns` handle `a:r`, `a:br`, `m:oMath` and `m:oMathPara`. Any
other child of `a:p`, including `a:fld`, returns `""` / `[]`. The same
functions feed slide shapes, tables (`a:tc`) and notes (`pptxShapeText`).
`pptxFirstSlideText` (the comment anchor) uses `findAll(root, "a:t")` and so
*does* see field text. The two paths already disagree.

**Scope check.** None of the 11 PPTX fixtures has an `a:fld` in slide XML. In
notes, `poi_comment.pptx` (22) and `poi_sampleshow.pptx` (2) have them, but
all inside `sldNum`/`dt` placeholders, which notes extraction deliberately
skips. So the fix changes **no existing golden**, and no fixture can show the
bug today. That is the reason this is P2, and why it needs a new fixture.

**Fix.** Treat `a:fld` like `a:r` in both functions: its `a:t` text, and its
`a:rPr` formatting through `extractDrawingMLRun`. Keep the placeholder
exclusions as they are: page-furniture placeholders in notes stay excluded.
On slides, `sldNum`/`dt`/`ftr` placeholders will start emitting their cached
value where they hold a field. That is correct: the text is on the slide.

**Test plan.**
- Inline tests on `drawingMLNodeText`: `<a:p><a:r><a:t>Slide </a:t></a:r><a:fld type="slidenum"><a:t>7</a:t></a:fld></a:p>` → `"Slide 7"`.
- Add to `create_pptx_order_fixture.py`: one slide with that text box and one
  notes body with a `datetime1` field. `--verify` asserts the exact strings.
  It fails today.

**Size.** S.

---

## G5. `std/xml` and namespace prefixes: upstream, with a small repo change

**Brief's claim:** "std/xml renames tags with undeclared namespace prefixes
(p:sldId → sldId)." That is true, and it is not the whole picture. It was
verified with AILANG v0.48.0 `parseLenient`:

| Input | Root tag | `findFirst(root, "p:cSld")` |
|-------|----------|-----------------------------|
| `<p:notes><p:cSld/></p:notes>` (prefix undeclared) | `notes` | miss |
| `xmlns:p="…presentationml…"` declared | `p:notes` | hit |
| `xmlns="…presentationml…"` (default namespace) | `notes` | miss |
| `xmlns:pml="…presentationml…"` (other prefix) | `pml:notes` | miss |

**Root cause (upstream).** `resolveTagName` in AILANG's
`internal/builtins/xml.go`: Go's decoder puts the *prefix* in `Name.Space` when
it is undeclared, and the URI when it is declared. `lookupPrefix` searches by
URI, so an undeclared prefix finds nothing and the function returns
`name.Local`. The tag is kept as the source's literal prefix, not normalised to
the namespace. Also, `lookupPrefix` iterates a Go map. If two prefixes bind the
same URI in one scope, the choice is not deterministic.

**Root cause (repo).** Every OOXML parser matches literal prefixed names
(`"p:sldId"`, `"a:t"`, `"p:cSld"`). That works because Office always writes
`p:`/`a:`/`r:` and declares them. A writer that uses a default namespace or a
different prefix makes the parser see nothing. No fixture does this, and no
field report has shown it.

**Decision.** This is **mainly upstream**. The undeclared-prefix rename is a
`std/xml` bug. It should keep `prefix:local` when the prefix can't be resolved,
which is a one-line fallback in `resolveTagName`. The prefix-vs-namespace
matching problem is also best solved upstream, by exposing the namespace URI
and local name on `XmlNode`, or by a `findAllNs(node, uri, local)`. The repo
should not grow a parallel namespace resolver in AILANG.

- **Upstream ask** (send with `ailang-feedback`): (1) keep undeclared prefixes
  literally; (2) deterministic prefix choice; (3) a namespace-aware
  lookup/`localName` accessor.
- **Repo** (after upstream (3) lands): switch the handful of structural
  lookups that decide *what the document is* to namespace-aware matching:
  `pptxPresentationSlidePaths`, notes/slide `p:cSld`/`p:spTree`, and xlsx
  `sheet`. Leave the rest literal. Until then, the inline-test fixtures keep
  declaring `xmlns:p`/`xmlns:r`, as `pptxOrderSlideEntriesJoined`'s comment
  already says.

**Test plan.** Upstream: `xml_test.go` cases for the four rows above. Repo:
add an inline test on `pptxFindNotesBodyText` with a default-namespace notes
part. Expected `"…"` today, and the real text once the repo change lands.

**Size.** S upstream. The repo part is S after that.

---

## G6. WASM type-check headroom

### Measured state

Per-module counts are from #74's CI Browser WASM job (run 36559050682, pinned
runtime v0.43.1, GitHub runner). Step counts are deterministic. Milliseconds
are for that runner only.

| Module | Steps | Cap | ms (CI) |
|--------|------:|----:|--------:|
| docx_generator (lab only) | 151,174 | 155,000 | 8,751 |
| html_parser | 91,194 | 100,000 | 2,642 |
| eml_parser | 86,753 | 100,000 | 3,301 |
| tex_parser | 82,738 | 100,000 | 3,984 |
| output_formatter | 66,119 | 100,000 | 2,789 |
| xlsx_parser | 52,395 | 100,000 | 3,981 |
| docx_parser | 39,687 | 100,000 | 4,126 |

Summed over all 32 measured modules, the CI boot is **~51s**, or ~42s without
the lab-only `docx_generator`. The brief says docx/xlsx/tex are ~2s each on an
M4 Max, and that matches what #74 recorded. Two points the brief missed:

- **The next modules to trip the 100k step gate are html_parser (91%),
  eml_parser (87%) and tex_parser (83%).** It is not docx/xlsx.
- **Time and steps are not proportional.** `docx_parser` spends ~104µs per
  step, and `html_parser` ~29µs. The slow parsers are slow outside the counted
  steps. This matches upstream ask 1 below: the timer covers more than
  type-checking.

The `mdProcessLine` recipe from #74 (typed helpers in place of
`let s = … in { s | … }` inside if/else chains) **does not obviously transfer**.
A grep of the hot modules finds 0–2 record-update expressions each. Their cost
comes from somewhere else. We don't have per-declaration attribution, so any
split now would be guesswork.

### Upstream (AILANG)

These are the three follow-ups #74 raised, confirmed against
`cmd/wasm/main.go` and `internal/types/typecheck_budget.go`:

1. `types.BeginWasmTypeCheck(name)` runs *before* `replInstance.LoadModule(name, code)`.
   That call parses, elaborates and type-checks, so parse and elaboration count
   against the "type-check" deadline. Arm the deadline at type-check entry, or
   report phase times separately.
2. Superlinear cost for `let s = … in { s | … }` in long if/else chains. #74
   has the before/after (`mdProcessLine` 46k → 21k).
3. Make the step count the enforced gate. The upstream queue already has
   **`m-wasm-deterministic-typecheck-budget`**, blocked on "a step
   distribution over a real corpus" (ailang#662). **Our `loadStats()` output is
   that corpus.** It covers 32 legitimate modules from 1.6k to 151k steps, and
   is reproducible from CI. Send it upstream. That unblocks the row.
4. New ask: per-declaration step attribution in `loadStats()`, for example the
   top 5 declarations per module. Without it, repo-side splitting is blind.

### Repo side: getting headroom back

1. **Lower the step gate once there is headroom, not before.** Keep the 100k
   ceiling. Add a *warning* at 85k in `module-budget.spec.ts`, so html, eml and
   tex show up in CI output now, before they fail.
2. **docx_generator (151k/155k).** It loads only on the lab page, so
   splitting it is less urgent than the three parsers. Split it by concern, as
   #74 split markdown: tables and grid layout, numbering and lists, and
   run/paragraph XML. Target: every piece under 100k, then delete the
   `OVER_CEILING_CAPS` entry.
3. **html_parser, eml_parser, tex_parser.** Once upstream ask 4 lands (or by
   bisecting declarations into a scratch module by hand), split each so that
   no module is above 70k. This is the only change that makes room for new
   features in these parsers.
4. **Wall-clock budget.** Leave it at 30s until upstream ask 1 lands. Then
   re-measure and bring it back towards 10–15s. The clock's real job is to
   bound a hung checker, and 30s is a long freeze.
5. **Boot time.** ~42s of serial module loading on a CI runner is a UX problem
   in its own right. Lazy-load format modules when a file of that type is
   first dropped, as the generators already are. The measurements above show
   this is the largest lever. Cost: the first parse of each format waits for
   its module.

**Test plan.** `module-budget.spec.ts` is already the exact gate. Each split
PR must show a lower step count and unchanged output (office suite, round trip,
and the #74 workbench smoke test).

**Size.** Upstream report: S. docx_generator split: M. Three parser splits:
M each, after attribution exists. Lazy loading: M.

---

## G7. XLSX rows with no `<row>` element are skipped

**Problem.** Excel writes no `<row>` for an empty row. The parser appends rows
in the order it meets them, so every row after a gap moves up. Columns are
now positionally exact (#73). Rows are not.

**Evidence.** `pandoc_basic.xlsx` sheet 1 has `<row r="1|2|3|6">`. The #73
golden shows "Just a random cell" as the 4th row. In the sheet it is row 6.

**Root cause.** `xlsxFoldRowStep` in `docparse/services/xlsx_parser.ail` prepends
`cells` for each `<row>` that has any `<c>` (`xlsxRowHasCells`). It never
consults the row's `r` attribute (`xlsxRowNumber` exists and is used only for
merge narrowing). A `<row>` with no cells is also dropped.

**Scope.** Scan of all 16 xlsx fixtures (+ `challenge_sparse_rows`):
interior gaps in **4 files**: `pandoc_basic` (2 missing rows),
`challenge_formula_cached`, `challenge_formulas` and `challenge_merged_cells`
(1 each). No fixture has leading missing rows or self-closed `<row/>`
elements.

**Recommendation: fill interior gaps, bounded.**
- Before appending row *r*, insert `r - lastRow - 1` empty rows. They are
  padded to width later by the existing `xlsxPadRow`.
- **Bound:** fill a gap only if it is ≤ 100 rows. Filled rows count toward the
  existing 5,000-row cap. A larger gap means a sheet with far-apart blocks,
  such as a data table and a totals block 1,000 rows down. For that, emit one
  empty row as a separator, and add a `warnings` entry naming the sheet and
  the collapsed range. A gap never produces thousands of blank rows.
- **Leading rows are not filled.** The first `<row>` stays the header row,
  which keeps header detection unchanged. Column A-padding already records
  horizontal offset. Vertical offset goes unrecorded, and that is acceptable:
  a caller who needs it has the anchor refs on comments.
- Trailing empty rows stay trimmed, as for cells.

**Goldens.** Exactly the 4 files above change. Each gains 1–2 all-blank rows.
Bag-of-words scoring doesn't move, so the office suite stays at 100%, and the
change needs its own check.

**Test plan.** Add a third sheet to `challenge_sparse_rows.xlsx` (via
`create_challenge_files.py`):
- rows 1, 2, 5, 6, then 400;
- `check_xlsx_positions.py` asserts the exact row list: two blank rows between
  row 2 and row 5, one separator row before row 400, and the collapse warning.

It fails today, because it gets 5 rows.

**Risks.** Markdown output gains blank table rows (`|  |  |`). The markdown
round trip must keep them. `roundtrip_check.py` will show it if not.

**Size.** S.

---

## G8. Test infrastructure: structure is invisible to the office suite

### What the suite actually checks

The brief says `eval_office.py` scores tables by bag-of-words. It is weaker
than that:
- `check_tables` computes `cell_text_jaccard`, but the pass rule counts only
  keys ending `_match` (`table_count_match`, `merge_match`). **Cell text
  doesn't gate at all.** A table with every cell wrong passes if the count
  matches.
- `check_text_jaccard` is a token *set* ≥ 0.95, so order and position don't
  count.
- `normalize.py` flattens sections and discards `name`. Sheet names, "Slide N"
  labels and notes attribution never reach any check.
- The module docstring lists "speaker notes" as a feature it evaluates. There
  is no notes check.
- `element_count_match` is computed but not scored.

That is why #73's and #75's bugs, and G1/G3/G7, all score 100%.

### Structural metric

Add `check_structure(golden_json, actual_json)`, modelled on `check_colours`
(which is already keyed by position):
1. **Section sequence:** the ordered list of `(kind, name)` for every
   `SectionBlock`, recursively. It must be equal. This catches slide order,
   sheet mislabels, notes and comment attribution.
2. **Table grids:** for the *i*-th table in document order, the exact
   `[[cell text]]` grid, whitespace-normalised, with headers as row 0. Report
   `grid_exact` (bool) and `cell_accuracy` (matching cells ÷ max(golden,
   actual) cells). Gate on `grid_exact`. This catches column shifts, row shifts
   and padding.
3. **Block type sequence:** the ordered list of top-level `type`s. Gate on
   equality. This catches list-wrapping and block splits (see below).

Each check exposes a `*_match` key, so the existing scorer counts it. The
per-bug scripts (`check_xlsx_positions.py`, `create_pptx_order_fixture.py
--verify`) stay. They check expectations that come from the fixture's
*builder*, not from a golden, and a golden can carry a bug (as `poi_two_sheets`
did).

**Rollout.** Turning this on will fail on every golden that has drifted. That
is the point, and it is why the next section must land in the same PR.

### The three "environmental" golden drifts

They are not environmental. Checked on `main` today:

- **`ailang_architecture.md`: stale golden, and the new output is correct.**
  The golden has 55 blocks and splits a lazy-continuation list item
  ("…CSV) are" / "parsed with pure logic…") into a list plus a stray paragraph.
  Current output has 48 blocks with the item joined. The same 48-block output
  comes from `bc7f098`, before #74, so the change is from `f68307e`
  (2026-08-27, "lazy list continuation"). The golden was never regenerated,
  and the suite couldn't tell.
- **`image_vml.docx`, `pandoc_inline_images.docx`: stale goldens plus a real
  defect (G9).** Since `38b0974` (2026-09-16, "images base64-retained…"),
  image blocks carry a temp-file path in `src`
  (`/tmp/docparse-images/docparse-img-0.jpeg`), with `dataLength` equal to the
  *path's* length (39/40). The goldens predate that and hold inline base64
  (`dataLength` 19728 / 2312). One of `pandoc_inline_images`' two golden
  images has `src` and one doesn't. It was hand-edited or half-regenerated.

**Fix.** Regenerate those three goldens in the G8 PR. Have `normalize.py`
replace any `src` under the image temp dir with a placeholder, and drop
`dataLength` for `LocalFile` images, so the goldens don't contain
machine-local paths.

**Size.** M: the metric, the normaliser change, regenerated goldens, and
triage of whatever else the metric surfaces.

## G9. Image temp files collide across documents (found in G8)

**Problem.** `extractMediaToFiles` in `docparse/services/zip_extract.ail` writes
to the fixed `imageTempDir() = "/tmp/docparse-images"`. The file name is
`docparse-img-${counter}` with `counter` starting at 0 **for every document**.
Two documents parsed in one batch, or concurrently under `serve-api` (the
hosted API runs concurrency 80), write the same paths. The earlier document's
block then names a file that now holds the later document's image, whenever
the two first images share an extension (a local batch of `pandoc_inline_images.docx`
and `image_vml.docx` escaped only because one wrote `.jpg` and the other
`.jpeg`).

**Impact to verify first:** which consumers follow `src` back to the file
(`layout_ai`'s `LocalFile` branch does; JSON output emits the path). If any
hosted-API output resolves it, this leaks images between requests. That would
make it P0 on its own.

**Fix.** Name each file by content: `docparse-img-${sha256Hex(b64)}${ext}`
(`std/crypto`). This is deterministic, so goldens become stable. It is
collision-free across documents, and concurrent writers of the same image
write identical bytes. Keep `counter` only for ordering.

**Test plan.** Build two small DOCX fixtures whose first media entries have
the same extension and different bytes (`create_challenge_files.py`). Add a
`failure_check.py`-style script that parses both in one batch. Assert that the
two documents' image `src` values are disjoint, and that each file's sha256
equals the source media entry's. It fails today: both write `docparse-img-0.png`,
and the first document's file holds the second's bytes.

**Size.** S.

**Status (feat/gaps-img).** Implemented as above: the name is the sha256 of
the decoded bytes, written via a `.part` file and renamed. Test:
`benchmarks/check_image_temp_paths.py` (DOCX pair built from `image_vml.docx`;
PPTX output carries no image blocks, so no PPTX pair). Blast radius, checked
against `sunholo-data/docparse` run locally under `serve-api`: no hosted output
reads the file back (`useAI: false` is hard-coded, so `layout_ai` never runs;
html/qmd emit the path string; the Office generators drop path images to a
placeholder). But the JSON `filepath` parameter accepts any server path, and
`/tmp/docparse-images/docparse-img-0.<ext>` was predictable. That is a separate
docparse issue. For G8: with content names the image `src` is machine-independent
(`/tmp/docparse-images/docparse-img-<sha256><ext>`), so goldens can keep it and
`normalize.py` needs no path placeholder. `dataLength` for a temp-file image
is now the path length (102 for `.jpg`, 103 for `.jpeg`).

---

## Priority order and milestones

**M1: correctness the partner can see (≈2 days).** G3, G2b, G9 and G2.
- All are small.
- All but G9 are direct continuations of #73/#75.
- G2b and G2 are what the partner sees on the public workbench.
- Land G2b after #73 merges; both touch `wasm-demo.js`.

**M2: close the loop on structure (≈3–4 days).** G8, then G1 and G7.
- G8 goes first, so that G1 and G7 land against a suite that can see them. It
  also refreshes the three stale goldens.
- G7's four golden changes then show up as intended structural diffs.

**M3: field text and headroom (≈2–3 days + upstream).** G4, the G6 repo items
(85k warning, docx_generator split, lazy loading), and the upstream reports for
G5 and G6 (with the step corpus).
- The parser splits for html, eml and tex wait for per-declaration
  attribution upstream.

Suggested target: M1 + M2 in v0.47.0. M3 in v0.47.x/v0.48.0, depending on
upstream.

## Verification log

| Claim | How checked |
|-------|-------------|
| G1: PPTX→PPTX notes 12 → 0 | #75 branch: parse, `--convert`, re-parse; `unzip -l` shows no notesSlide |
| G1: notes dropped in `pptxSplitBySlides` | read `pptx_generator.ail` |
| G2/G2b: browser paths | read `wasm-demo.js` on both PR branches, and `docparse_browser.ail` |
| G3: misattribution | openpyxl two-sheet workbook against the #73 branch |
| G3: single-sheet fixtures lack sheet rels | `unzip -l` of `challenge_threaded_comments.xlsx` |
| G4: no fixture has slide `a:fld`; notes fields only in `sldNum`/`dt` | grep over all 11 PPTX fixtures |
| G5: four tag behaviours | `parseLenient` probe, AILANG v0.48.0; `resolveTagName` read |
| G6: step counts | #74 CI log, job "Browser WASM Smoke Test" |
| G6: timer armed before `LoadModule` | `cmd/wasm/main.go` |
| G6: step gate blocked on corpus | AILANG `design_docs/v1-mission.md`, `m-wasm-deterministic-typecheck-budget` |
| G7: 4 fixtures with gaps, 0 leading | zip scan of every xlsx fixture's `<row r>` |
| G8: `cell_text_jaccard` not gated | `evaluate_file` scoring loop reads only `*_match` keys |
| G8: md golden stale since before #74 | same 48-block output from `bc7f098` source |
| G9: fixed path, per-document counter | `extractMediaToFiles` / `mediaToFilesFrom` |
