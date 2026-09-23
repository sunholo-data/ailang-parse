# Sprint Plan — M-XLSX-COLOUR (colour extraction, Phase 1)

**Sprint JSON**: `.ailang/state/sprints/sprint_M-XLSX-COLOUR.json`
**Design doc**: [`v0_43_0_colour_extraction.md`](v0_43_0_colour_extraction.md), Phase 1 only
**Source**: `inbox_1790154667634_483d7d81` ("xlsx: cell fill colour dropped with no warning")
**Target**: v0.43.0 · **Mode**: sequential · **Created**: 2026-09-23

## Scope

XLSX cell fill and font colour, the shared normaliser, and warnings wherever
colour exists but is not extracted. Every other format is Phase 2.

The sender's repro workbook never arrived (their `--body-file` became the
message body; reported upstream as ailang#1276). The fixtures below are built by
script with known expected values, which a real workbook would not give us
anyway. Add the sender's file as an extra fixture if it arrives.

## What the code looks like today (drives the estimates)

- `xlsx_parser.ail` (749 lines) never opens `xl/styles.xml`. `parseXlsxCell`
  ends in `simpleCell(text)`.
- The streaming fold accumulator (`XlsxStreamFold`) already carries the
  shared-string map. The style map rides alongside it the same way, which
  avoids capturing a closure in a hot fold. The comment at line 680 records a
  13.9% CPU cost from exactly that.
- Styled empty cells `<c r="B2" s="3"/>` are **already emitted** (text `""`).
  Row and column default styles (`row/@s`, `col/@style`) are not read, and
  cells Excel omits are not synthesised outside merge regions. **Row/column
  inheritance is out of this sprint**: it changes row geometry for every
  xlsx and deserves its own golden review. It is recorded as a known gap.
- `TableCell` is built at 17 literal sites (8 are constructors in
  `document.ail`). Adding two fields is mechanical but touches 8 files.
- `output_formatter.ail:297` already omits empty cell fields, so goldens only
  change for files that contain colour. **None of the existing xlsx fixtures
  does**, so no existing golden should move. That is itself a check.
- XLSX warnings today are `TextBlock(style: "warning")` blocks.
  `ParseOutcome.warnings` is the proper channel and already reaches the JSON
  (`output_formatter.ail:35`) and the terminal (`main.ail:242`).

## M1 — `colour.ail` normaliser (~160 LOC)

`docparse/services/colour.ail`:
- `normaliseHex`: ARGB/RGB/`#rgb`/`#rrggbb`, with `auto`/`none`/`transparent`/
  alpha `00` mapped to `""`. Contract: `result == "" || isCanonicalHex(result)`.
- `xlsxIndexedColour(i)`: the 64-entry default palette (ECMA-376 §18.8.27).
- `applyTint(hex, tint)`: HSL tint per §18.8.19. The tint is a decimal string
  and is parsed here.
- `themeIndexToSlot(i)`: the lt1/dk1 and lt2/dk2 swap.

**Accept**: tests run via a `main()`-driven check for tint against
openpyxl/Excel reference values, the swap, the palette ends (0, 7, 63), and
contract violations caught by `--verify-contracts`.

## M2 — `TableCell.fill` / `TableCell.color` (~60 LOC)

Add fields, update every literal site, and add a `withColours(cell, fill,
color)` helper. JSON emits them when non-empty. `a2ui_formatter` reads them
back with `""` defaults. Python/JS/Go SDK types get optional fields.

**Accept**: `./bin/docparse --check` clean. Office suite 105/105 with **zero
golden diffs**, because no existing fixture has colour.

## M3 — XLSX styles and theme (~220 LOC)

- One pass over `xl/styles.xml`: `fills` → solid `fgColor`, `fonts` → `color`,
  `cellXfs` → `Map[int, {fill, color}]`. The map is built once per workbook
  and carried in the fold accumulator.
- One pass over `xl/theme/theme1.xml` `a:clrScheme` (sysClr uses `lastClr`).
- Colour resolution order: `rgb`, then `theme`+`tint`, then `indexed`, then
  `auto`→`""`.
- Fill ids 0/1 give `""`. Non-solid patterns give `fgColor`. Gradient gives `""`.
- The `parseSheetXml` compatibility path gets an empty style map, so it
  behaves as before.

**Accept**: every expected cell in `xlsx_fills.xlsx` matches, and so does the
form fixture. Stress suite time is within 10% of main.

## M4 — Warnings (~90 LOC)

`parseXlsxOutcome` returns `{blocks, warnings}` and the orchestrator passes
the warnings into `ParseOutcome.warnings`. Emitted once per sheet:
- conditional formatting present (sheet, ranges, rule count). Counted with a
  streaming pass over `conditionalFormatting`.
- gradient or non-solid pattern fills reported as their foreground colour.
- a theme colour referenced while `theme1.xml` is missing or unreadable.

**Accept**: `xlsx_condfmt.xlsx` produces the conditional-formatting warning in
JSON and on stderr. Existing fixtures produce no new warnings.

## M5 — Fixtures, goldens, `check_colours` (~180 LOC incl. Python)

- `benchmarks/create_colour_fixtures.py` (openpyxl) builds
  `xlsx_fills.xlsx`, `xlsx_form_template.xlsx` and `xlsx_condfmt.xlsx`, and
  writes the expected `(sheet, row, col, fill, color)` sidecar it checks against.
- `check_colours` in `eval_office.py` compares per-position fill/colour sets
  and colour warnings between the golden and the actual output. It only
  applies when the golden has colour.
- Single-file golden generation (path sed, see the v0.41.0 plan).

**Accept**: office suite includes the 3 new files at 100%, and a deliberately
wrong fill fails `check_colours`. That negative control is run once and the
result recorded.

## M6 — Gate

All four suites (office, roundtrip, verify_generated, failure_check), plus
`--suite stress`, `--check`, `--prove`, and `--verify-contracts` over the new
fixtures. Also read a fixture back through the real CLI (`./bin/docparse
xlsx_form_template.xlsx`) and inspect the JSON by hand.

## Estimates

~710 LOC at the recent pace of roughly 250 LOC/day is about 3 days of
elapsed work. Most of the risk is in M3: the theme swap, tint rounding, and
fold performance.

## Risks

- **AILANG float support for tint.** HSL needs float maths and hex
  formatting. If stdlib lacks something, stop and report per the bug policy;
  do not hand-roll a workaround.
- **Stress regression.** The style lookup is one map lookup per cell. It
  should be fine, but it is measured, not assumed.
