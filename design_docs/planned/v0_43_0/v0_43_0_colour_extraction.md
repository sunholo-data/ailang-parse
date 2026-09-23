# Design Doc: Colour Extraction Across Parsers (v0.43.0)

**Status**: Phase 1 (XLSX) implemented on `feat/xlsx-colour-extraction`, 2026-09-23. Phases 2–4 planned.
**Date**: 2026-09-23
**Author**: Mark + Claude
**Source**: `pkg:sunholo/ailang_parse` inbox, `inbox_1790154667634_483d7d81`
(2026-09-23, from `cli`): *"xlsx: cell fill colour dropped with no warning"*.
The message body did not arrive. The sender passed `--body-file <path>` as the
literal message text, and the repro report it pointed at is on the sender's
machine. The title is enough to act on. Separately, Mark reports form filling
as a strong use case, where colour marks which cells are inputs.

**Related**:
- [v0.30.0 Inline runs](../../implemented/v0_30_0/v0_30_0_inline_runs.md): left
  colour and highlight out of `InlineRun` on purpose and noted that the
  additive shape makes adding them cheap later. This doc adds them.
- [Form-field read & fill](../unscheduled/form_filling.md): colour is how
  most real spreadsheet and Word forms mark their input cells. That doc gives
  a field its identity; this one supplies the visual signal that finds
  unmarked fields.
- [v0.16.0 Style map round-trip](../v0_16_0/style_map_roundtrip.md): says
  colours "do not belong on semantic blocks". This doc narrows that rule. See
  [Why colour is content here](#why-colour-is-content-here).
- [v0.19.0 Style inheritance](../v0_19_0/v0_19_0_style_inheritance.md): plans
  `RunProps.color` and `TblProps.shading` as style-chain properties. This doc
  covers only *direct* formatting and sits below that work (see Phase 4).

---

## Problem

No parser reads colour. A grep of `docparse/services/*.ail` for `color`,
`w:shd`, `highlight`, `fgColor`, `patternFill`, `solidFill` and
`fo:background` finds only generators and three false positives. The RTF
parser skips `\colortbl`, `pdf_annotations` reads highlight *annotations*
rather than colour, and one match is an AI prompt string. `xlsx_parser.ail`
never opens `xl/styles.xml`.

That is a data-loss bug for spreadsheets, not just lost presentation.

1. **Colour carries meaning in spreadsheets.** A yellow fill means "enter a
   value here", red means "overdue", and a green row means "approved". Many
   real workbooks record status only in the fill, with no status column. Once
   parsed, that information is gone.
2. **Forms use colour to mark input cells.** Supplier forms, claim forms and
   budget templates shade the cells a person must fill. Those cells have no
   `w:sdt` content control and no defined name, so fill colour is often the
   *only* signal. [form_filling.md](../unscheduled/form_filling.md) finds
   fields that are declared; this finds fields that are only drawn.
3. **The loss is silent.** Title of the report: "dropped with no warning".
   `ExtractionResult.warnings` exists and is empty. A caller cannot tell a
   plain sheet from a colour-coded one.
4. **No suite could see it.** None of the four xlsx fixtures in
   `data/test_files/` has a single solid fill (`<patternFill
   patternType="solid">` count is 0 in each) or any conditional formatting.
   The office suite scored 100% because nothing it scores contains colour.
   This is the blind spot `.claude/rules/benchmarks.md` warns about, applied
   to the parse side.

---

## Why colour is content here

The v0.16.0 rule ("colours, fonts, CSS classes… do not belong on semantic
blocks") is about *theme* and *design* colours: brand palettes, slide masters,
CSS. Those stay out. This doc carries only colour that an author applied to a
specific cell or span, and it normalises that colour to one value so consumers
can compare it. Where it lives:

| Carried | Not carried |
|---|---|
| Cell fill (XLSX/ODS/DOCX/ODT/PPTX/ODP/HTML table cells) | Slide backgrounds, masters, layouts |
| Cell font colour (XLSX/ODS, where a cell has no runs) | Theme palettes as data (only used to *resolve* theme references) |
| Run font colour and highlight (DOCX/ODT/PPTX/ODP/HTML/RTF) | Borders, gradients, pattern textures, chart series colours |
| Warnings when colour exists that we cannot resolve | CSS classes and stylesheet cascade in HTML |

The test is simple: would an author read the colour of this cell or span as
saying something? Direct formatting passes. Inherited design mostly does not.
Style-inherited colour is the grey area, which Phase 4 addresses.

---

## Non-goals

- **Evaluating conditional formatting.** XLSX/ODS conditional formats are
  rules that the viewer evaluates at render time, not colours stored on the
  cell. We will not build a formula evaluator. Instead we **report** that
  rules exist (a warning naming the sheet, range and rule count) so the
  "no warning" part of the report is fixed even where the colour isn't. See
  Open Question 3 for a narrow `cellIs` subset.
- **Colour naming.** We emit hex. We will not turn `#FFFF00` into "yellow" in
  the parser (see Open Question 2).
- **PDF / images.** The AI path has no deterministic colour. Out of scope.
  Prompting the model for fills is a separate experiment.
- **Pixel accuracy.** Tint/shade maths is implemented to spec. We don't chase
  sub-1-LSB rounding against Excel's renderer.

---

## Data model

### Canonical colour value

One string format everywhere: **`"#rrggbb"` lowercase, or `""`**.

- `""` means *no colour was specified*. It is **not** white. Cells in almost
  every sheet are unfilled, and treating "unfilled" as "white" would make
  every cell look coloured. The same convention as `TableCell.align`.
- Alpha is dropped and **never interpreted**. XLSX `ARGB` `FFFFFF00` becomes
  `#ffff00`, and so does `00FFFF00`. *(Changed during Phase 1: the first draft
  treated alpha `00` as transparent. openpyxl writes alpha `00` on every
  colour, and Excel renders those fills opaque, so that rule would have erased
  every openpyxl-authored fill.)*
- `auto`, `none`, `transparent`, `nil` and `windowText` all become `""`,
  because they mean "the viewer decides".

One shared normaliser, `docparse/services/colour.ail`, and a contract that can
actually fail:

```ailang
-- Result is "" or exactly "#" followed by six lowercase hex digits.
export pure func normaliseHex(raw: string) -> string
  ensures { result == "" || isCanonicalHex(result) }
```

`isCanonicalHex` checks length 7, a leading `#`, and `[0-9a-f]` for the six
digits. An upper-case pass-through or a leftover alpha byte violates it.
Also: `resolveTint(hex, tint)` (ECMA-376 §18.8.19 HSL tint), `indexedColour(i)`
(the 64-entry legacy palette, §18.8.27), and `htmlNamedColour(name)` (the CSS
named colours).

### Type changes (additive)

```ailang
export type TableCell = {
  ...existing fields...,
  fill: string,       -- cell background, "#rrggbb" or ""
  color: string       -- cell-level font colour, "#rrggbb" or ""
                      --   (XLSX/ODS style it per cell, not per run)
}

export type InlineRun = {
  ...existing fields...,
  color: string,      -- font colour, "#rrggbb" or ""
  highlight: string   -- highlight/marker/background behind the run, "#rrggbb" or ""
}
```

**Font colour means "differs from the default".** `color` is reported only
when it differs from the document's default text colour: XLSX `fonts[0]`, the
Normal style's font. Every styled cell references *some* font, and without
this rule every filled cell reported `#000000`. Phase 1 found that the first
time the fixtures ran. An unresolvable theme reference on the default font is
likewise not warned about.

`coalesceRuns` must treat `color` and `highlight` as part of run identity, or
it will merge a red run into a black neighbour. That needs an inline test.

**JSON:** `output_formatter.ail` already omits empty cell fields (`scope` and
`align` are only emitted when non-empty, `output_formatter.ail:297`). New
fields follow the same rule, so **goldens only change for files that really
contain colour**. Regenerate those one at a time. Goldens embed the absolute
path of the machine that generated them, so a bulk `generate_golden.sh` run
rewrites every one.

**SDKs:** additive optional fields in Python/JS/Go, the same as `runs` in
v0.30.0. Go `TableCell`/`InlineRun` get `omitempty`.

**A2UI / JSON ingest:** `a2ui_formatter.ail:319` builds `TableCell` from JSON.
It should read `fill`/`color` with a `""` default so colour survives JSON
round-trips.

### Paragraph shading

DOCX `w:pPr/w:shd` and ODF paragraph `fo:background-color` (shaded callout
paragraphs, some form "answer here" lines) are real, but they need a new
field on `TextBlock`. **Deferred to Phase 3.** Until then the run-level
`highlight` covers the case when the shading is on the run, and a warning
reports paragraph shading we skipped.

---

## Per-format extraction

| Format | Cell fill | Font / run colour | Highlight | Needs theme resolution |
|---|---|---|---|---|
| **XLSX** | `c/@s` → `cellXfs[s]/@fillId` → `fills[i]/patternFill[@patternType="solid"]/fgColor` | `cellXfs[s]/@fontId` → `fonts[i]/color`; rich text runs `r/rPr/color` | — | yes: `@theme` + `@tint`, `@indexed`, `@rgb` |
| **ODS** | `table:table-cell/@table:style-name` → automatic style `style:table-cell-properties/@fo:background-color` | `style:text-properties/@fo:color` | — | no |
| **DOCX** | `w:tcPr/w:shd/@w:fill` | `w:rPr/w:color/@w:val` | `w:rPr/w:highlight/@w:val` (named, 16 values) and `w:rPr/w:shd/@w:fill` | yes: `@w:themeFill`/`@w:themeColor` + tint/shade |
| **ODT** | table cell automatic style `fo:background-color` | `fo:color` (extend `odf_runs.ail`) | `fo:background-color` on text style | no |
| **PPTX** | `a:tcPr/a:solidFill` | `a:rPr/a:solidFill` | `a:rPr/a:highlight` | yes: `a:schemeClr` + `lumMod`/`lumOff`/`tint`/`shade`, via `clrMap` |
| **ODP** | as ODT | as ODT | as ODT | no |
| **HTML** (and EPUB, EML HTML bodies) | `td/@style` `background-color`, `td/@bgcolor` | inline `style="color:…"`, `<font color>` | `<mark>` → `#ffff00`, inline `background-color` | named CSS colours, `rgb()`, `#rgb` |
| **RTF** | `\clcbpat<n>` → `\colortbl[n]` | `\cf<n>` | `\highlight<n>`, `\cb<n>` | no (the table is inline) |
| Markdown, CSV, TEX | none; nothing to extract | | | |
| PDF, images | out of scope (AI path) | | | |

### XLSX detail: the reported case, and the one to get right first

XLSX has the most indirection, which is where naive implementations go wrong:

1. Parse `xl/styles.xml` once per workbook: `fills`, `fonts`, `cellXfs`, and
   `indexedColors` if the file overrides the default palette.
2. Parse `xl/theme/theme1.xml` `a:clrScheme` once. The theme index order
   is **lt1, dk1, lt2, dk2, accent1–6, hlink, folHlink**. Note that 0/1 and
   2/3 are *swapped* relative to the XML element order. That is a known trap,
   so there should be a fixture for it.
3. For each `<c s="n">`, look up `cellXfs[n]`. Honour `applyFill`/`applyFont`
   only as hints: Excel itself ignores `applyFill="0"` when `fillId` is set.
4. Fill ids 0 and 1 are reserved (`none`, `gray125`), which gives `""`.
5. Non-solid `patternType` (`darkGray`, `lightGrid`, …): emit `fgColor` and
   add a warning once per sheet. See Open Question 1.
6. `gradientFill`: gives `""` plus a warning.
7. Rows and columns can carry a style too (`row/@s` with `customFormat="1"`,
   `col/@style`). A cell with no `s` inherits it. This matters for *empty*
   input cells in forms, which are often styled only through the row or
   column. Empty cells that carry a style *through their own `<c s="n"/>`* are
   already emitted (with text `""`), which the form fixture confirms. Cells
   styled only through their row or column have no `<c>` at all and are not
   emitted. For form filling, an empty yellow cell *is* the field, so that
   gap matters (see Phase 1 outcome).

Performance: `styles.xml` is small. It should be one pass, read into a
`Map[int, (fill, color)]` keyed by xf index, and passed into the existing
`xlsxFoldRow`/`xlsxFoldRowStep` folds. It must not re-scan per cell, and the
streaming path used for large sheets (`scanFoldStep`) must get the same map.
The stress suite (`--suite stress`) is the check.

### Warnings (fixes the "no warning" half of the report)

Added to `ExtractionResult.warnings`. Deduplicated to one per sheet and kind:

- `Sheet "Budget": 3 conditional formatting rules on B2:F40 — colours they produce are not extracted`
- `Sheet "Form": 12 cells use gradient/pattern fills; reported as their foreground colour`
- `Theme colour referenced but xl/theme/theme1.xml missing — 40 cell colours dropped`
- `DOCX: 5 paragraphs have shading (w:pPr/w:shd); paragraph shading is not extracted yet`

Every place where colour is present but we emit `""` must produce a warning.
That is the property that stops this report from recurring.

---

## Output writers

- **JSON:** carries everything, and is the primary target.
- **HTML writer:** `style="background-color:…"` on `td`, `color`/
  `background-color` spans on runs. This is round-trippable through
  `html_parser`, which gives a cheap symmetric test.
- **Markdown writer:** **no change by default.** Markdown has no colour
  syntax, and the round-trip suite asserts pipe-table structure. But LLM
  consumers read the markdown, and form filling by LLM is exactly the use
  case. See Open Question 4.
- **Generators (Phase 2):** `xlsx_generator`, `docx_generator`,
  `pptx_generator`, ODF and HTML generators honour non-empty `fill`/`color`/
  `highlight`. Some generators already write fixed header colours. Explicit
  cell colour should override those. `verify_generated.py` then reads the
  colour **back** with openpyxl/python-docx/python-pptx. Checking that the
  file opens is not enough (see the blind-spot rule).

---

## Test plan

Fixtures to add to `data/test_files/`. The first two are built by hand with
openpyxl so their expected values are known. Checking in a random workbook
would give no known answers.

| Fixture | Exercises |
|---|---|
| `xlsx_fills.xlsx` | solid `rgb` fill, `theme`+`tint` fill (incl. theme 0–3 swap), `indexed` fill, font colour, row-styled and column-styled empty cells, a gradient, a `darkGray` pattern |
| `xlsx_form_template.xlsx` | a realistic form: labels in column A, **empty yellow input cells** in B, one merged coloured header. This is the use-case fixture. |
| `xlsx_condfmt.xlsx` | conditional formatting only, and asserts the warning |
| `ods_fills.ods` | the same values as `xlsx_fills` saved via LibreOffice, so both give the same hex |
| `docx_colour.docx` | `w:tcPr/w:shd`, `w:color`, `w:highlight` (named), theme colour + `themeTint`. Plus existing `table_header_rowspan.docx` (12 `w:shd` already) |
| `pptx` | existing `poi_comment.pptx` (51 `a:solidFill`); add one table cell with `schemeClr` + `lumMod` |
| `html_colour.html`, `rtf_colour.rtf` | named, `rgb()`, `#rgb`, `bgcolor`, `<mark>`; `\colortbl` + `\clcbpat`/`\cf`/`\highlight` |

Suites:

1. **Office suite:** new `check_colours` in the office scorer. It compares
   the multiset of `(cell/run text, fill, color, highlight)` against the golden.
   Colour on the wrong cell must fail, so it is keyed by position, not a bag
   of hexes.
2. **Cross-format agreement:** `xlsx_fills.xlsx` and `ods_fills.ods` must
   produce identical `(row, col, fill, color)` sets. This is the "unified
   across parsers" property stated as a test.
3. **Normaliser contract** `normaliseHex` runs under
   `--verify-contracts` across the whole office suite.
4. **Inline tests** for `resolveTint` against published Excel values, the
   theme-index swap, the indexed palette and `coalesceRuns` colour identity.
   (Tests must go through `main()` where they call stdlib; see the
   test-harness bug in `.claude/rules/ailang-coding.md`.)
5. **Round-trip** (Phase 2) parse → HTML → parse preserves colours, and
   generate → read back with the Python libraries preserves them.

All four mandatory suites (office, roundtrip, verify_generated,
failure_check) must stay green.

---

## Phases

**Phase 1: XLSX + warnings.** This is the reported bug.
`colour.ail` normaliser, `TableCell.fill`/`color`, XLSX styles + theme +
indexed + row/col styles, emitting styled empty cells, conditional-formatting
and unresolved-colour warnings, JSON, SDK fields, the XLSX fixtures and
`check_colours`. Also reply on `inbox_1790154667634_483d7d81`, and ask for the
original repro workbook to add as a fixture if it can be shared.

**Phase 2: every other table-cell and run format.**
ODS, DOCX, ODT, PPTX, ODP, HTML, RTF. Add `InlineRun.color`/`highlight`,
the HTML writer, generator honouring, verify_generated read-back, and the
cross-format agreement test.

**Phase 3: paragraph shading and markdown exposure.**
`TextBlock` shading field and the Open Question 4 decision.

**Phase 4: style-inherited colour.**
After v0.19.0 lands style-chain resolution, apply the same `normaliseHex` to
colour that comes from `w:tblStyle`/`w:pStyle`/ODF parent styles. Until then,
direct formatting only, and **documented as such**. Many corporate templates
colour header rows through the table style, so Phase 1–2 output will show
those as uncoloured.

---

## Phase 1 outcome (2026-09-23)

Shipped: `colour.ail`, `TableCell.fill/color` (JSON and all four SDKs, plus
A2UI ingest), XLSX styles/theme/indexed/custom-palette resolution, and
warnings for conditional formatting, pattern fills, gradient fills and missing
themes. Four fixtures (`xlsx_fills`, `xlsx_no_theme`, `xlsx_form_template`,
`xlsx_condfmt`) are built by `benchmarks/create_colour_fixtures.py`, whose
`--verify` mode checks the parser against expectations computed independently
with `colorsys`. `check_colours` in the office suite has a recorded negative
control: swapping the lt2/dk2 fills in a golden drops that file to 83% and
names both cells.

Known gaps, which are not silent:
- **Row/column default styles** (`row/@s`, `col/@style`) are not applied, and
  cells Excel omits outside merge regions are not synthesised. A form whose
  input cells are styled only through their column shows those cells as
  missing. This needs its own golden review because it changes row geometry.
- **Browser/WASM path** (`parseSheetXml`) receives one sheet's XML with no
  `styles.xml`, so it carries no colour.
- **`x14:conditionalFormatting`** (Excel 2010 extension rules in `extLst`) is
  probably not counted: the streamed tag match is on `conditionalFormatting`.
- Tint rounding can differ from Excel by one step on some channels (Accent1
  darker 50% gives `#203864`), which is within the stated non-goal.

## Open questions

1. **Pattern fills.** Emit `fgColor` for non-solid patterns (current plan), or
   `""`? A `lightGray` hatch on an input cell is still a signal, so the
   recommendation is `fgColor` plus a warning.
2. **Colour names for consumers.** Add a `nearestColourName(hex)` helper to
   the SDKs (not the parser) so an LLM prompt can say "yellow cells"? It is
   cheap and useful for form filling. It stays out of the Block ADT.
3. **Conditional formatting subset.** `cellIs` with constant operands
   (`greaterThan 0` → red) is evaluable without a formula engine and covers a
   large share of real status sheets. Worth doing in a later phase, or does
   partial evaluation mislead more than it helps? Recommendation: warnings only
   until someone asks.
4. **Markdown exposure.** LLM form-filling reads markdown. Options are (a)
   nothing; (b) opt-in `--colours` that appends a legend after each table
   (`Coloured cells: B2–B9 #ffff00 (input?)`); or (c) inline
   `<span style>` in cells. (c) breaks the round-trip suite's pipe-table
   assumptions and makes the text noisy. Recommendation: (b), opt-in, legend
   after the table, with cell refs that match how the markdown writer already
   labels XLSX tables.
5. **Styled empty cells.** Emitting them grows tables for sheets whose
   formatting extends past the data (whole-column fills). The range should be
   limited to `dimension` ∩ (rows that have any value or any non-default
   fill), so a column filled to row 1,048,576 doesn't become a million-row
   table.
