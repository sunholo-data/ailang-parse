# In-band structure — where the Block ADT gets flattened into a string

**Status**: DONE (2026-08-13, shipped in v0.33.0). All four reported defects and
every Class A/B item below are fixed except A13 and the structured half of
A10/A11, which are deferred with reasons in §7. Office suite **100.0% across 104
files** (was 99 — five had no golden at all), and a new round-trip suite reads
**0 failures across 101 files** where it failed on every table before.
**Theme**: Four roundtrip defects were reported against `ailang_parse@0.32.0`. All
four reproduce. All four are the same bug: **structure serialised into a plain-text
field, then re-derived by splitting that text on a character the data also
contains.** Probing the class found nine more instances the report did not
mention, including two that silently *delete* data rather than mangle it.
**Source**: `ailang messages` `d730708b` (docparse → user, 2026-08-12), plus
`44003cd1` from email-parse, which is the same class in `eml_parser`.

## 1. The reported four, reproduced

Environment: AILANG v0.33.0-41-g65f287107, `ailang_parse` 0.32.0, local `./bin/docparse`.

### R1 — CSV ignores RFC 4180 quoting

```
$ cat rt.csv
name,tags,count
Alpha,"Headings, paragraphs, tables",9
Beta,"quoted ""inner"" text",3

$ ./bin/docparse rt.csv        # headers: 3 columns
rows: [["Alpha", "\"Headings", "paragraphs", "tables\"", "9"],
       ["Beta", "quoted \"\"inner\"\" text", "3"]]
```

A 3-column table with a 5-cell row, orphaned quote characters welded to the data,
and `""` never unescaped. This is corruption in `outputFormat=blocks`, not a
rendering artifact. [`csv_parser.ail:49`](../../../docparse/services/csv_parser.ail#L49)
splits on the delimiter with no quote state; [`csv_parser.ail:55-66`](../../../docparse/services/csv_parser.ail#L55-L66)
strips outer quotes afterwards, which is the wrong order and cannot recover the
field boundaries that were already lost.

### R2 — multi-paragraph table cells shatter markdown tables

```
$ ./bin/docparse data/test_files/tables.docx
| Simple

Multiparagraph | Table

Full |
| --- | --- |
```

The cell text is *correct*: [`docx_parser.ail:646-647`](../../../docparse/services/docx_parser.ail#L646-L647)
joins a cell's paragraphs with `\n`, which is the truth about the document. The
defect is entirely in the emitter — [`output_formatter.ail:539-543`](../../../docparse/services/output_formatter.ail#L539-L543)
writes cell text raw into a line-oriented, pipe-delimited grammar.

Round-tripping that markdown back through `--convert .docx` produces exactly what
the report predicted:

```
TABLE headers=['Simple'] rows=[]        # degenerate 1x0
text : 'Multiparagraph | Table'         # cell content leaked to body
text : 'Full |'
```

### R3 — md→docx drops all inline formatting

```
$ ./bin/docparse inline.md --convert inline.docx
<w:r><w:t>This is **bold**, this is *italic*, and this is `code`.</w:t></w:r>
<w:r><w:t>---</w:t></w:r>
<w:r><w:t>After the rule. A [link](https://ailang.dev) too.</w:t></w:r>
```

**Broader than reported**: links are lost too, and that one is not a missing
feature — `InlineRun.href` exists, `LinkBlock` exists, and `docx_generator` already
writes real `w:hyperlink` elements ([`docx_generator.ail:248`](../../../docparse/services/docx_generator.ail#L248)).
The generator is starved, not incapable. Every generator that can render runs
(docx, pptx, odt, odp, html, qmd) receives zero from this path, because
[`markdown_parser.ail:18-23`](../../../docparse/services/markdown_parser.ail#L18-L23)
never produces any.

### R4 — XLSX heading inversion and `{merged}` leakage

```
$ ./bin/docparse data/test_files/challenge/challenge_formulas.xlsx
### Sheet
# Revenue
| Financial Summary FY2026 {colspan=4} |  {merged} |  {merged} |  {merged} |
```

Two independent defects. The sheet-name heading is emitted at level 1
([`xlsx_parser.ail:508`](../../../docparse/services/xlsx_parser.ail#L508)) while the
section label is a hardcoded `### Sheet`
([`output_formatter.ail:504`](../../../docparse/services/output_formatter.ail#L504)) —
so the container sits three levels below its own content, and the literal word
"Sheet" discards the sheet name the parser already resolved. Separately,
`{colspan=N}` / `{merged}` are appended into cell *text*
([`output_formatter.ail:551-557`](../../../docparse/services/output_formatter.ail#L551-L557))
with no reader anywhere in the codebase, so they survive into every downstream
consumer as literal characters.

## 2. The generalisation

Every one of the four violates the same rule:

> **A structured value may be rendered into a text channel, but it must never be
> recovered from one.** If the writer flattens `(a, b)` into `"a<sep>b"`, some
> reader will split on `<sep>`, and `<sep>` will occur inside `a`.

The Block ADT already has fields for all of this — `InlineRun`, `TableCell.colSpan`,
`TableCell.merged`, `ImageBlock`, `LinkBlock`, `SectionBlock.kind`. The defects are
not gaps in the model. They are places where a producer bypassed the model and
wrote into `text`, or where a consumer re-derived from `text` what was sitting
right there as a field.

Once stated that way, the class is enumerable. Below, **[R]** = in the original
report, **[N]** = found while generalising.

### Class A — in-band delimiters

| # | Site | Defect | Effect |
|---|---|---|---|
| A1 **[R]** | `csv_parser.ail:49` | split ignores quotes | column explosion |
| A2 **[N]** | `csv_parser.ail:55-66` | `""` never unescaped | `quoted ""inner"" text` |
| A3 **[N]** | `csv_parser.ail:29` | splits on `\n` before parsing fields | **row loss**: `1,"line one\nline two"` → two rows, one with a single cell |
| A4 **[R]** | `output_formatter.ail:539` | cell `\n` written raw into pipe row | table shatters |
| A5 **[N]** | `output_formatter.ail:539` | cell `\|` written raw | verified: cell `a \| b` emits `\| 2 \| a \| b \|` → 3 columns from 2 |
| A6 **[N]** | `markdown_parser.ail:259` | `filter(length > 0)` drops empty cells | **silent column shift**: `\| 1 \| \| 3 \|` → `["1","3"]`, so `3` lands under header `b` |
| A7 **[N]** | `markdown_parser.ail:256` | escaped `\|` splits the cell | `pipe \\\| inside` → two cells |
| A8 **[N]** | `markdown_parser.ail:246-249` | `contains(line, "---")` classifies any row containing `---` as a separator | **row deletion**: `\| 2024---2025 \| fiscal \|` vanishes entirely |
| A9 **[R]** | `output_formatter.ail:551-557` | `{colspan=N}`/`{merged}` appended to cell text, no reader exists | literal tokens in all output |
| A10 **[R‑eml]** | `eml_parser.ail:421,450` | `[attachment: name, mime]` split on comma by consumers | 41/8326 rows have a filename stored as `mime_type` |
| A11 **[N]** | `eml_parser.ail:407,414` | `"${filename} (${mimeType})"` | same shape, parens instead of comma |
| A12 **[N]** | `epub_parser.ail:207`, `ods_parser.ail:86`, `odp_parser.ail:79` | section identity packed into `kind` as `"chapter:X"`, `"sheet:X"`, `"slide:X"` while `output_formatter.ail:502-512` dispatches on exact equality | verified: **ODS sheets and ODP slides render with no label and no separator at all** — sheet/slide boundaries are invisible in markdown, while PPTX gets `---` and XLSX gets `### Sheet` |
| A13 **[N]** | 6 generators + `output_formatter.ail:459` | `[Image: desc]` placeholder written, never read | an image round-trips to a literal text paragraph |
| A14 **[N]** | `tex_parser.ail:900-902` | `\textbf{x}` → `**x**` **into `TextBlock.text`** | verified: `.tex --convert .docx` emits literal asterisks — R3 with a different producer |
| A15 **[N]** | `output_formatter.ail:437-439` | `**Author:** X` written into the markdown body | verified: re-parses as literal asterisks in every md→X conversion |

### Class B — fields that exist but are never populated

| # | Site | Defect |
|---|---|---|
| B1 **[R]** | `markdown_parser.ail` | emits zero `InlineRun`s — the sole cause of R3 |
| B2 **[N]** | `markdown_parser.ail` | no link parsing, though `InlineRun.href`, `LinkBlock` and DOCX hyperlink generation all exist |
| B3 **[N]** | `markdown_parser.ail` | no images, code fences, blockquotes, or thematic breaks (documented at lines 18‑23, but the consequence — silent literal passthrough — is not) |
| B4 **[N]** | `odp_parser.ail`, `rtf_parser.ail`, `tex_parser.ail` | carry real inline formatting in the source and emit no runs. `odp_generator` *writes* runs, so **ODP→ODP loses formatting the model could hold** |
| B5 **[R]** | `xlsx_parser.ail:508` + `output_formatter.ail:504` | level‑1 heading nested under a hardcoded `### Sheet` label that also discards the sheet name |

Parsers emitting `InlineRun` today: docx, html, odt, pptx. Not: csv, eml, epub,
markdown, odp, ods, rtf, tex.

### The shared consequence: markdown is a lossy pivot

`renderMarkdown` ([`output_formatter.ail:427`](../../../docparse/services/output_formatter.ail#L427))
is the only markdown writer, `parseMarkdown` is the only reader, and they are used
as inverses by `--convert` ([`main.ail:397`](../../../docparse/main.ail#L397)). They
are not inverses. A4–A9, A13, A15 and B1–B3 all sit on that one path, which is
also the path every AI-generated document takes.

## 3. Why nothing caught this

The office suite scores **structural counts and text Jaccard against JSON
goldens** — 99 files, none of them markdown. `benchmarks/office/golden/` contains
only `*.json`. So:

- **Nothing scores the markdown emitter at all.** A4, A5, A9, A13, A15 are
  invisible to every existing check.
- **Nothing round-trips.** No suite parses its own output. R2's degenerate 1x0
  table survives a green benchmark run.
- A1–A3 *are* covered by `ailang_formats.csv.json` — but the golden was generated
  from the buggy parser, so it encodes the corruption as expected output.

This is the lesson of [`v0_30_0_golden_drift.md`](../../implemented/v0_30_0/v0_30_0_golden_drift.md)
again: a check that cannot fail on a defect is not covering it.

## 4. Proposed fixes

Ordered by damage, not by effort. A3, A6 and A8 lose data outright and should go
first regardless of where they sit in the class.

### P0 — stop losing data

1. **Real CSV reader** (A1–A3). Replace `csvParseLine` with a character-level
   state machine over the whole content: quote state, `""` → `"`, embedded
   newlines and delimiters inside quotes. Field-level `trim` must only apply to
   unquoted fields — quoted whitespace is significant.
2. **Markdown table reader** (A6–A8). Split on unescaped `|` only, honour `\|`,
   preserve empty cells (drop only the leading/trailing empties that `|`-fencing
   produces), and detect separators structurally — every cell matches
   `:?-+:?` — instead of `contains(line, "---")`.

### P1 — make the markdown channel escaped and invertible

3. **Escape on write** (A4, A5). One `mdEscapeCell`: `|` → `\|`, newline → `<br>`
   (the report's suggestion, and what every markdown table dialect that supports
   multi-paragraph cells uses). Applied in `renderCellsMd`/`renderSepMd`.
4. **Cell metadata out of cell text** (A9). `{colspan=N}`/`{merged}` are already a
   Pandoc-ish convention with no reader. Either teach `mdParseTableRow` to consume
   them — restoring the roundtrip they were clearly meant to provide — or drop
   them from `cellTextMd` and keep span topology in JSON only. Recommend the
   former: the intent was right, only the reader is missing.
5. **Inline runs in the markdown parser** (B1–B3, and A15 falls out for free).
   Parse `**`/`*`/`` ` ``/`~~`/`[text](url)`/`![alt](url)` into `InlineRun`s and
   `LinkBlock`/`ImageBlock`. Every generator already consumes them. This is the
   single highest-leverage item: it fixes md→docx, md→pptx, md→odt, md→html and
   md→qmd simultaneously, and it is what makes `--convert` through markdown
   non-destructive.
6. **Thematic breaks** (R3, second half). A `---` line is a document-structure
   signal; it currently becomes a literal paragraph. Needs a representation
   decision — see Open questions.

### P2 — section identity as data

7. **`SectionBlock` gains a `name` field** (A12, B5). `{kind: "chapter", name: "Introduction"}`
   replaces `{kind: "chapter:Introduction"}`. Additive, same shape as the
   `InlineRun` rollout in v0.30.0: omit `name` when empty and existing JSON stays
   byte-identical. Then `renderSectionMd` labels every container consistently —
   sheets, slides and chapters all get a heading carrying their real name, and
   ODS/ODP stop rendering as an unbroken stream.
8. **Fix the heading inversion** (B5). With (7), the sheet name belongs to the
   section, not to a level‑1 `HeadingBlock` inside it. Container label and content
   headings then nest correctly by construction.
9. **Structured attachment metadata** (A10, A11). Option (a) from the email-parse
   report: `filename` and `mimeType` as fields, not a marker string to be
   re-split. Requires a Block-level decision (fields on `SectionBlock`, or a
   dedicated variant) — coordinate with email-parse, since they are the consumer.
10. **TeX runs** (A14) and **ODP/RTF runs** (B4). Route inline formatting into
    `InlineRun` instead of markers-in-text. Mechanical once (5) establishes the
    pattern.

### Contracts

The class is expressible as contracts, which is the durable fix:

- `renderTableMd`: emitted row line count == 1 (catches A4 by construction).
- `mdParseTableRow`: cell count == header cell count for every row of a table
  (catches A6, A7).
- `csvParseLine`: for a table, all rows have equal length (catches A1–A3).
- Roundtrip: `parseMarkdown(renderMarkdown(doc))` preserves block count, table
  dimensions and heading levels.

### Test plan

A **roundtrip suite** is the missing coverage, not more goldens:
`parse(f) → render(md) → parse(md)` and assert block count, table dimensions,
heading level sequence, and run presence. Run it over the existing 99 office
files. It fails today on every file with a table.

Golden churn to expect: `ailang_formats.csv.json` changes under P0 (correctly —
the current golden encodes the corruption), and any file with merged cells changes
under P1.4. Regenerate with `bash benchmarks/generate_golden.sh` and review the
diff rather than accepting it.

## 5. Open questions

1. **Thematic break representation.** No Block variant fits. Options: a
   `TextBlock` with `style: "hr"`, a new variant, or `SectionBlock(kind: "break")`
   — which would then unify with PPTX's `---` slide separator, currently an
   unreadable in-band marker itself (A12's neighbour).
2. **`{colspan}` reader vs. removal** (P1.4). Recommending the reader, but that
   makes the markdown dialect non-standard in a way consumers must opt into.
3. **A9/A13 breadth.** Fixing the `[Image: ...]` placeholder means deciding what
   an image *is* in a text channel. Markdown has `![alt](src)`; DOCX/ODT/PPTX
   generators writing a bracketed placeholder is a separate (and arguably
   correct-for-now) choice.

## 6. What shipped, and what the round-trip suite then found

Implementation notes worth keeping, because two of them are findings in their
own right.

### Three more instances, found by the new suite

`benchmarks/roundtrip_check.py` did what §3 said was missing, and immediately
failed on files nobody had reported:

- **A16 — a heading containing a newline.** `pandoc_basic.pptx` has the title
  "Everworkervenn\ndiagram". Written into a `#` heading it ends the line early
  and leaks "diagram" as a stray paragraph — R2's bug, in a different
  single-line construct. Fixed with `mdOneLine` on headings and list items.
- **A17 — row fitting broke spanned tables.** The GFM fix (P0.2) padded rows to
  the *number* of header cells, but in a table with merged cells a 2-cell row
  can be exactly as wide as a 3-cell header. Width is now the sum of the
  colSpans.
- **A18 — GFM truncation deletes data.** `tables-with-incomplete-rows.docx` has
  a 1-column header over 2-column rows; truncating to the header width dropped a
  cell from every row. We pad short rows and leave wide rows alone: a
  ragged-wide row is still all of the document's data, and this whole document
  is about not silently losing any.

### The markdown parser was quadratic, and so was the fix

Two rewrites, both driven by measurement:

| inline scanner | 41KB document |
|---|---|
| none (before this work) | 2.0s |
| index-based (`charAt`/`substring`) | 16.9s |
| per-character `foldChars` state machine | 15.0s |
| **`split`-based (shipped)** | **4.2s** |

`charAt(s, i)` is **O(i)**, not O(1) — confirmed by micro-benchmark: summing
character codes by index costs 32ms at 2,000 characters and 593ms at 16,000, so
per-access cost itself grows with length. Any index-based scan of a string is
therefore quadratic. `foldChars` is genuinely linear (~3µs/char) but consing
into a record field each step costs ~17µs/char, which is still far too slow for
a per-character tokenizer in the interpreter.

The shipped scanner peels one marker token at a time with `split`, so
allocation scales with the number of segments rather than the number of
characters, and the hot loop stays in native code. 2x the no-inline-parsing
baseline is the honest price of parsing formatting that was previously ignored.

Related fixes made along the way: `mdJoinLines` now uses `join` instead of
folding with `"${acc} ${line}"` (quadratic in paragraph length), and the
per-line `listLength(...) == 0` checks became pattern matches (O(n) → O(1)).

Large markdown remains slow for reasons that predate this work — the round-trip
suite skips the three files whose rendered markdown exceeds 64KB and says so on
every run. That is worth its own ticket, not a silent cap.

### Coverage gap closed

`generate_golden.sh` never globbed `data/test_files/challenge/*.{docx,pptx,xlsx,html}`,
so those goldens could not be regenerated by the tool that is supposed to
regenerate them — and five test files had no golden at all. Both fixed; the
suite now scores 104 files.

## 7. Deferred, with reasons

- **A13 (`[Image: ...]` placeholder)** — needs a decision about what an image
  *is* in a text channel before it can be fixed rather than moved. Markdown
  images are now read (`![alt](src)` on its own line becomes an ImageBlock);
  the placeholder written by the DOCX/ODT/PPTX generators is untouched.
- **A10/A11 (attachment metadata as fields)** — the attachment `SectionBlock`
  now carries the filename in `name`, which is additive and gives email-parse a
  structured field to migrate to. The `[attachment: name, mime]` *text* marker
  is deliberately unchanged: email-parse parses it today, and changing the block
  shape under a downstream consumer is their call to schedule, not ours.

## 8. Not proposed

- No changes to the Block ADT beyond the additive `SectionBlock.name`.
- No workarounds for AILANG itself — none of these are toolchain bugs. Every one
  is a docparse-side serialisation choice.
- No attempt to make markdown a *complete* pivot. The goal is that what markdown
  can represent survives the trip, and what it cannot is not silently mangled.
