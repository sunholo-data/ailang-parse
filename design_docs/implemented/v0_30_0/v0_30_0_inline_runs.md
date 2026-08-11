# Inline Runs — representing formatting inside a paragraph

**Status**: DONE (2026-08-11, shipped in v0.30.0) — all five phases complete. DOCX, HTML, PPTX and ODT parse *and* generate runs for text, headings and list items; ODP and QMD generate them; all four SDKs expose them.
**Theme**: `TextBlock` has no sub-paragraph structure, so bold-inside-a-sentence is unrepresentable. Add it additively, and stop silently discarding the formatting the DOCX parser already has in hand.
**Follows**: [`v0_29_0_docx_generation_fidelity.md`](../v0_29_0/v0_29_0_docx_generation_fidelity.md) — P2 of that doc's scope, split out as promised because it is a data-model change rather than generator work.

## Problem

```ailang
export type Block = TextBlock({text: string, style: string, level: int})
```

[`document.ail:45`](../../../docparse/types/document.ail#L45). A paragraph is a
flat string. There is nowhere to say "these four words are bold", so **no
generator can emit inline formatting** — this is the ceiling identified in
v0.29.0, and it is in the type, not in any generator.

Two consequences, both visible today:

1. **DOCX→DOCX loses all character formatting.** A bolded clause comes back as
   plain text.
2. **Markdown→DOCX leaks syntax.** `**bold**` reaches Word as four literal
   asterisks, because the markers survive as text with nothing to interpret them.

## What actually exists today

This is not virgin ground, and the existing convention has to be understood
before replacing it.

### There is already an inline-formatting representation: Markdown markers

`html_parser` deliberately encodes inline formatting into the paragraph text
([`html_parser.ail:459`](../../../docparse/services/html_parser.ail#L459)):

```ailang
-- Markers chosen for compatibility with CommonMark / Pandoc /
-- typical LLM consumption.
pure func htmlInlineWrap(node: XmlNode, tag: string, text: string) -> string {
  if tag == "strong" || tag == "b" then "**${text}**"
  else if tag == "em" || tag == "i" then "*${text}*"
  else if tag == "code" || tag == "kbd" || tag == "samp" then "`${text}`"
  else if tag == "del" || tag == "s" then "~~${text}~~"
  else if tag == "mark" then "==${text}=="
  ...
```

So HTML formatting **is** captured — as syntax inside `text`. 11 of the 93
golden files encode markers this way. This is a deliberate product decision
serving the "LLM-ready markdown" use case, and any design that silently changes
`text` breaks it.

### But only HTML does it, and DOCX discards formatting entirely

| Parser | Inline formatting |
|---|---|
| `html_parser` | captured, as Markdown markers in `text` |
| `markdown_parser` | markers pass through untouched — and inline formatting is listed under *"Does NOT handle (yet)"* ([`markdown_parser.ail:20`](../../../docparse/services/markdown_parser.ail#L20)) |
| `docx_parser` | **discarded**. `extractRunText` concatenates run text; `w:rPr` is read only for font names ([`docx_parser.ail:308`](../../../docparse/services/docx_parser.ail#L308)) |
| `pptx`/`odt`/`tex` | discarded |

The DOCX row is the important one. `w:rPr` carries `w:b`, `w:i`, `w:u`,
`w:strike`, `w:vertAlign`, `w:color`, `w:highlight` — the parser walks straight
past all of it. **We are not missing a type so much as throwing away data we
already have parsed.**

### Blast radius, measured

- **75** `TextBlock({...})` construction sites across 15 modules — heaviest in
  `eml_parser` (19), `html_parser` (12), `direct_ai_parser` (8), `orchestrator` (7).
- **No `mkText` helper exists.** `document.ail` has `mkImage`/`mkImageFull`/
  `mkTable`/`mkTableFull` precisely so that adding fields does not force every
  call site to pass empties — but `TextBlock` never got one. Adding a field today
  therefore breaks all 75 sites at once.
- Public JSON shape: `{"type": "text", "text": ..., "style": ..., "level": ...}`
  ([`output_formatter.ail:82`](../../../docparse/services/output_formatter.ail#L82)),
  consumed by 93 goldens, `unstructured_compat`, `a2ui_formatter`, `chunker`, the
  hosted API, and 3 SDKs. The Go SDK's `Block` is a flat struct with
  `omitempty` fields per variant ([`sdks/go/types.go:10`](../../../sdks/go/types.go#L10)),
  so an optional field is genuinely additive there.

## Design options

### Option A — structured `runs`, additive

```ailang
export type InlineRun = {
  text: string, bold: bool, italic: bool, underline: bool,
  strike: bool, code: bool, vertAlign: string  -- "" | "superscript" | "subscript"
}
TextBlock({text: string, style: string, level: int, runs: [InlineRun]})
```

`text` stays exactly as it is — the concatenation, markers and all — so every
existing consumer is untouched. `runs` is empty when a parser has no formatting
information, and generators use it only when non-empty.

- **For**: lossless and unambiguous; extensible to colour/highlight/font without
  another breaking change; makes DOCX→DOCX round-trip actually work; JSON
  consumers get structure instead of a string to re-parse.
- **Against**: 75 construction sites; JSON grows; every generator needs a
  run-rendering path.

### Option B — formalise the Markdown-marker convention

Keep `text` as the only representation, document the marker vocabulary as the
contract, teach `docx`/`odt`/`pptx` parsers to emit markers, and give generators
a shared `parseInlineMarkers(text) -> [Run]`.

- **For**: no ADT, JSON, SDK or golden change; preserves LLM-readable output;
  half-built already.
- **Against**: **ambiguous and lossy in ways that produce wrong output.**
  `2 * 3 * 4` round-trips to *italic* " 3 ". A Windows path or a
  `snake_case_name` becomes emphasis. Escaping is required, and escaping changes
  `text`, which was the thing we were protecting. Markdown also cannot express
  underline, colour, highlight, superscript or font changes, so DOCX formatting
  is still lost — it only *looks* like it solves the problem. And every generator
  must implement a Markdown inline parser, which is plausibly more total code
  than Option A.

### Recommendation: Option A

The ambiguity in B is not a rough edge, it is a correctness bug that fires on
ordinary text (`2 * 3`, `file_name_here`), and B still cannot carry the
DOCX formatting that motivated the work. B's real virtue — LLM-readable `text` —
is fully retained by A, because A does not touch `text`.

Explicitly **not** doing: making `text` the plain concatenation when `runs` is
populated. That would strip markers from HTML output, regress 11 goldens, and
break the documented CommonMark-compatibility promise. `text` and `runs` are
allowed to disagree; `text` is for reading, `runs` is for rendering. That
redundancy is the price of not breaking consumers, and it should be stated in the
ADT comment so nobody "fixes" it later.

## Migration

The 75-site problem is sequencing, not scale. Phase 1 makes the rest cheap.

**Phase 1 — `mkText`, no behaviour change** (~half day). Add
`mkText(text, style, level) -> Block` to `document.ail` following the existing
`mkImage` precedent, and mechanically migrate all 75 sites. Pure refactor:
identical output, goldens must not move. Land and verify on its own.

**Phase 2 — the field** (~half day). Add `runs: [InlineRun]` with `mkText`
defaulting it to `[]`. Only `mkText` and `output_formatter` change. JSON gains
`"runs"` only when non-empty (`omitempty` semantics), so goldens without
formatting are byte-identical.

#### Phases 1–2 outcome (2026-08-10) — DONE

Both landed and the sequencing hypothesis held exactly: **phase 2's field
addition broke one function.** The compiler flagged `mkText` and nothing else,
where before phase 1 it would have flagged all 75 sites.

Phase 1 migrated 72 sites mechanically and 3 multi-line ones by hand
(`a2ui_formatter`, `xlsx_parser`, `pptx_parser`). `TextBlock` stays imported
everywhere — it is still needed in `match` patterns.

Behaviour-neutrality was measured, not assumed. Parsing all 58 golden-backed
files before phase 1 and after phase 2:

```
baseline(pre-P1) vs post-P2   JSON identical: 58   differing: 0
                              markdown identical: 58   differing: 0
"runs" present in output:     0 files
```

Phase 2 also added `mkTextRuns` and `plainRun`, and the serialisation was
exercised directly rather than left untested — a field that only ever
round-trips empty proves nothing:

```json
{"type":"text","text":"no runs here","style":"normal","level":0}
{"type":"text","text":"plain bold bit x2","style":"normal","level":0,
 "runs":[{"text":"plain "},{"text":"bold bit","bold":true},
         {"text":"2","vertAlign":"superscript"}]}
```

`runs` is omitted when empty and each flag only appears when true, so a plain
paragraph costs nothing and the pre-InlineRun JSON shape is preserved exactly.

Office suite 100.0%; `verify_generated.py` all-pass including L2b; 35 modules
clean.

**Unrelated finding worth its own ticket:** 8 of the 58 files already differ
from their committed goldens on *unmodified* code — `gutenberg_alice`,
`gutenberg_moby_dick`, `image_vml`, `lo_image_mimetype`, `officeparser.odp`,
`officeparser.odt`, `pandoc_inline_images`, `test.tsv`. Not caused by this work,
and invisible to the office benchmark, which scores similarity rather than
byte-equality.

> **Diagnosis corrected (2026-08-11).** This was filed as "golden drift" and read
> as *the goldens are stale*. That was wrong, and the wrong word cost time: it
> framed the fix as regenerating goldens when the actual job was fixing parser
> code. Most of these were **live regressions**, and the goldens were right all
> along — see [`v0_30_0_golden_drift.md`](./v0_30_0_golden_drift.md), where all 8
> are resolved.

**Phase 3 — parsers, one per increment.** Independent and individually
shippable, highest value first:

1. `docx_parser` — `w:rPr` → runs. The data is already in hand; this is the
   whole point.
2. `html_parser` — emit runs *alongside* the existing markers.
3. `pptx_parser` — `a:rPr` (`b="1"`, `i="1"`).
4. `odt_parser` — `text:span`, which needs automatic-style resolution to know
   what a style name means; genuinely harder, do it last.

#### Phases 3–4 for DOCX (2026-08-10) — DONE

Shipped together, per this doc's own risk note that phase 3 alone produces JSON
nobody renders.

`docx_parser` builds runs from `w:rPr`; `childNodeRuns` mirrors `childNodeText`'s
tag handling exactly (same inclusions, same `w:del`/`w:moveFrom` skips) so `runs`
and `text` describe the same content. Toggle semantics are honoured: a bare
`<w:b/>` is ON but `<w:b w:val="0"/>` is OFF, and `w:u` is treated as a style
name where `w:val="none"` is off — not as a toggle. `docx_generator` renders
runs back as `w:rPr`, emitting children in the CT_RPr schema order
(rFonts, b, i, strike, u, vertAlign) rather than the order they were written in.

Full DOCX→DOCX round-trip, verified end to end in both directions:

| | bold | italic | underline | strike | superscript | subscript |
|---|---|---|---|---|---|---|
| parsed to runs | yes | yes | yes | yes | yes | yes |
| regenerated `w:rPr` | yes | yes | yes | yes | yes | yes |
| python-docx reads back | yes | yes | yes | yes | yes | yes |
| **LibreOffice renders** | yes | yes | yes | yes | yes | yes |

`runs` is emitted only when a paragraph actually contains formatting, so all 58
pre-existing golden-backed files remain byte-identical to the original
pre-phase-1 baseline.

**The corpus had no coverage for this.** Only two test files contain run
formatting at all, and neither exercises the new path: `table_header_rowspan.docx`
has all 17 instances inside table cells (`TableCell`, no runs field), and
`image_vml.docx` has one in `w:pPr` (paragraph-mark properties, correctly
ignored) and one inside a `Heading1` paragraph, which becomes a `HeadingBlock` —
also no runs field. So the feature would have shipped with zero regression
coverage. Added `data/test_files/inline_formatting.docx` + golden, covering all
six formats plus an explicit `<w:b w:val="0"/>` that must NOT read as bold.
Office suite is now 100.0% across 59 files.

**Known limitation, unchanged:** only `TextBlock` carries runs, so formatting
inside a heading or a list item is still discarded. Giving `HeadingBlock` and
`ListBlock` runs is a further ADT change, deliberately not bundled here.

**Unrelated stdlib bug found while building the test file:**
`std/xml.getText` returns `""` for a whitespace-only text node, so
`<w:t xml:space="preserve"> </w:t>` is dropped. Word splits runs at every
formatting boundary and the separator space routinely lands in its own run, so
mixed-formatting paragraphs extract as `"plain bolditalic"`. This is in
unmodified text-extraction code and predates this work. Reported per policy
rather than worked around: `msg_20260810_211710_b5373208`, GitHub issue #646.
The test file attaches its spaces to adjacent runs so its golden tests runs
rather than being hostage to that bug.

**Phase 4 — generators, one per increment.** `docx_generator` first (`w:rPr` in
runs), then `html_generator` (`<strong>`/`<em>`), then odt/pptx. Each falls back
to today's plain-text path when `runs` is empty, so partial completion is a
working state throughout.

#### Phases 3–4 for HTML (2026-08-10) — DONE

`html_parser` now emits runs **alongside** the existing Markdown markers, not
instead of them. `htmlInlineWrap`'s output in `text` is untouched; runs carry the
same formatting structurally with clean text. Formatting is inherited down the
tree, so `<strong><em>x</em></strong>` yields one run that is both bold and
italic rather than two nested ones. `html_generator` renders runs back as nested
inline elements, preferring runs over `text` precisely because `text` holds
markers that would otherwise be escaped into literal `**bold**`.

This is the text/runs divergence the design predicted, working as intended:

```
text:  'plain then **bold** then *italic* then under then ~~struck~~ then `mono`'
runs:  'plain then '(plain) 'bold'[bold] ' then '(plain) 'italic'[italic]
       ' then '(plain) 'under'[underline] ' then '(plain) 'struck'[strike]
       ' then '(plain) 'mono'[code]
```

Note `under` has no marker in `text` — `htmlInlineWrap` has no `<u>` case — but
does carry `underline` in runs. Runs are strictly richer than the marker
vocabulary, which is the point.

**It closes the leak that motivated the whole P2 line.** HTML→DOCX previously
delivered four literal asterisks to Word; it now produces real bold, italic,
underline, strike, superscript and subscript. HTML→HTML emits semantic
`<strong>`/`<em>`/`<del>`/`<code>`/`<sup>`/`<sub>` instead of escaped markers,
and re-parsing the generated HTML yields byte-identical runs (19/19), so the
round-trip is stable rather than merely lossy-in-one-direction.

Six golden files changed, and every one is identical except for **added `runs`** —
`text` and all structure verified unchanged. Two are EPUBs (which parse XHTML
internally) and gained 183 and 256 formatted blocks, so this exercises real
prose, not just the synthetic fixture.

**`--eval` went 56/58 → 59/59, zero failures.** The two long-standing Gutenberg
EPUB failures were never a recursion problem: their goldens predated the v0.15.0
LinkBlock feature, so a block the parser now correctly types as `link` was still
`text` in the golden. The misleading note in `bin/docparse` has been corrected.

Six pre-existing drift files remain deliberately untouched, since this work did
not affect them: `image_vml.docx`, `lo_image_mimetype.odt`, `officeparser.odp`,
`officeparser.odt`, `pandoc_inline_images.docx`, `test.tsv`. One cause is already
clear: **`test.tsv` reports `format: "csv"` where the golden says `"tsv"`, which
is a real regression** and wants its own ticket.

> **Correction (2026-08-11).** This section originally also called
> `officeparser.odt` a stale golden predating the image `src` field, and judged
> it "harmless". Both halves were wrong. Its golden had been *regenerated after*
> ODF image resolution broke, so it recorded the broken value (`dataLength` 16 —
> the length of the ZIP href, not the image) as though it were correct. It was
> matching its golden precisely because both were wrong. See
> [`v0_30_0_golden_drift.md`](./v0_30_0_golden_drift.md) §1.

#### Phases 3–4 for PPTX (2026-08-10) — DONE

DrawingML needed different code rather than a copy of the DOCX path, and this is
the trap worth recording: **where WordprocessingML puts each run property in its
own child element under `w:rPr`, DrawingML carries them as attributes on
`a:rPr`** — `b="1" i="1" u="sng" strike="sngStrike" baseline="30000"`. None of the
DOCX toggle logic transfers. `baseline` is signed thousandths of a percent, so
positive is superscript and negative is subscript, and `u`/`strike` name a style
where `"none"`/`"noStrike"` are the off states.

Round-trip verified through python-pptx for all six formats. Two corpus files
gained runs (`pandoc_basic.pptx` 8 blocks, `poi_comment.pptx` 9), each identical
apart from the added field.

`poi_sampleshow.pptx` has an italic run that correctly produces nothing: it sits
in a `subTitle` placeholder, which maps to `HeadingBlock`. Same limitation as
DOCX headings — noted again because it will keep coming up until `HeadingBlock`
and `ListBlock` gain runs.

Added `data/test_files/pptx_inline_formatting.pptx` + golden, since the corpus
covered only bold. Office suite 100.0% across 60 files; `--eval` 60/60.

**Field evidence for the `std/xml` whitespace bug (issue #646):** `poi_comment.pptx`
extracts as `"Access toFinancefor Local Governments"` — the whitespace-only
`<a:t> </a:t>` runs between words are dropped, producing empty runs and jammed
words. This is a real corpus file, not a synthetic case, and it shows the bug
corrupts output on both DOCX and PPTX paths.

#### HeadingBlock and ListBlock runs (2026-08-10) — DONE

Prioritised ahead of ODT because the "only TextBlock carries runs" limitation had
been hit three times running — DOCX headings, `image_vml.docx`, and
`poi_sampleshow.pptx` — and headings and bullets are exactly where presentation
formatting lives. Fixing it lit up all three formats already wired, where ODT
would have added a fourth.

Same phased approach: `mkHeading`/`mkList` added and all 33 construction sites
migrated first (24 heading, 9 list), verified byte-identical across 60 files,
then the fields added. `HeadingBlock` gains `runs: [InlineRun]`.

`ListBlock` gains `itemRuns: [[InlineRun]]`, a **parallel array** to `items`:
`itemRuns[i]` holds the runs for `items[i]`, and it is either empty or exactly
the same length as `items`. A record-per-item would enforce that in the type, but
`items: [string]` is consumed by the SDKs, `unstructured_compat`, `a2ui` and
every generator, so changing its shape is breaking where a parallel field is
additive. The invariant is documented on `mkListRuns` and both generators walk
the two lists together rather than indexing, so a short or absent `itemRuns`
degrades to plain text instead of mis-pairing formatting with the wrong item.

The alignment hazard is real and was hit immediately: `htmlParseList` filters
empty `<li>` elements, so building texts and runs as separate lists and filtering
only the texts would silently shift `itemRuns` out of alignment the moment any
item was blank. Text and runs are now carried together through the filter.

Wired end to end: `docx_parser`, `html_parser` and `pptx_parser` populate
heading/item runs; `docx_generator` and `html_generator` render them. The two
cases that previously dropped formatting now carry it — `image_vml.docx`'s bold
`Heading1` and `poi_sampleshow.pptx`'s italic `subTitle`.

Three goldens changed, each verified identical apart from the added fields.
`image_vml.docx`'s golden was also stale (`dataLength` 0 vs 19728 — it predates
VML image extraction), so that drift is now resolved too. Office suite 100.0%
across 60 files; `--eval` 60/60.

#### PPTX generation + ODT parsing (2026-08-10) — DONE, with one gap

**PPTX generation** closed the parse/generate asymmetry: headings and list items
now render runs. Headings keep their larger size and stay bold by default — that
is the title look this generator has always produced — while italic/underline/
strike/baseline come from the run. The bullet/number prefix stays a plain leading
run; DrawingML has real autonumbering via `a:buChar`/`a:buAutoNum`, but this
generator has always written the marker as text and changing that is a separate
concern.

**ODT parsing** is the third dialect and needed a third approach. Formatting is
not on the run at all: `<text:span text:style-name="T2">` names a style, and the
properties live in a `<style:style style:name="T2">` elsewhere in the document.
So the span cannot be interpreted without first indexing the styles — the map is
built once per document and threaded through the walk, which is why
`odtProcessNode`/`odtProcessChildren`/`odtProcessFrame` all gained a parameter. A
per-span linear scan would have been O(spans x styles).

Working on the real `officeparser.odt`: **bold, italic, bold-italic (nested
composition), underline and strike** all extract correctly.

**The superscript/subscript gap reported here did not reproduce.** Re-checked on
a clean tree at `bb34837`: `officeparser.odt` yields
`{"text":"script","vertAlign":"superscript"}` and the matching `"subscript"`,
and `odtBuildStyles` indexes all 626 `style:style` elements with no duplicate
names. The earlier observation appears to have been made against an
intermediate build. No code change was needed.

Two further limitations, both deliberate: `style:parent-style-name` chains are
not resolved (automatic styles — what LibreOffice and Word emit for direct
formatting — carry properties inline, so the common case is covered), and ODT
generation does not yet render runs.

#### ODF whitespace elements (2026-08-10) — DONE

Found while confirming the superscript report above: the same paragraph
extracted as `"Here is somebold,italic,bold-italic,underlinedandstruck outtext."`
**Every space was missing**, in `text` and in `runs` alike.

ODF does not preserve whitespace in the XML (§6.1.2–6.1.4). Spaces, tabs and
line breaks are carried as *elements*:

```xml
<text:p>Here is some<text:s/><text:span text:style-name="T5">bold,</text:span></text:p>
```

`std/xml.getText` concatenates descendant *text*, so `<text:s/>` contributes
nothing and the words jam together. All three ODF parsers used raw `getText`, so
all three were affected. LibreOffice emits `<text:s/>` at most span boundaries:
`officeparser.odt` has 66 of them plus 17 `<text:tab/>`, `officeparser.odp` 8,
`officeparser.ods` 1.

**This is not ailang-core #646 and is not blocked on it.** #646 is about
whitespace-only *text nodes* being dropped. Here the whitespace is an empty
*element*, and no fix to `getText` could help — nothing about `<text:s/>` says
"space" unless the caller knows ODF. Every space in the affected paragraph is a
`text:s`, so this was fully fixable locally.

New `docparse/services/odf_text` exports `odfText` (a drop-in `getText`
replacement that maps `text:s` → *n* spaces per `text:c`, `text:tab` → tab,
`text:line-break` → newline) and `odfWhitespace` (the same mapping for one node,
so the run walker shares it rather than re-deriving it). Wired into
`odt_parser` (headings, paragraphs, table cells, list items, and the run walk),
`odp_parser` and `ods_parser`. Metadata lookups keep plain `getText` — ODF
whitespace elements do not occur in `dc:title` and friends.

Verified against an independent oracle rather than against itself: a Python
reference implementation of ODF whitespace expansion agrees with the parser on
**all 43** text/heading blocks of `officeparser.odt`.

The two goldens that moved were updated **surgically** — only `text`, `runs`,
`items` and `itemRuns` copied from the new output, everything else left alone —
so the committed diff is provably whitespace-only (block counts, types and
formatting flags all unchanged) and the unrelated image drift below stays
visible rather than being silently baked in.

New fixture `data/test_files/odt_whitespace.odt` + golden, because the corpus
could not cover this: `text:tab` appears in `officeparser.odt` only inside the
table-of-contents, which the parser skips, so tabs and line breaks had **zero**
coverage. The fixture exercises `text:s`, `text:c="4"`, `text:tab`,
`text:line-break`, whitespace inside formatted spans, list items and table cells.
LibreOffice renders it as ground truth and the parser matches it exactly,
including `'before\tafter a tab'` and `'item  two'`.

Office suite 100.0% across 61 files; `--eval` 61/61; `verify_generated.py`
all-pass including L2b; 36 modules clean.

**Follow-up worth considering:** runs now fragment at every whitespace element —
`"“Add Books”"[bold]` followed by `" "[bold]`. Correct but verbose, and DOCX/PPTX
fragment the same way for their own reasons. Coalescing adjacent runs with
identical formatting would be a cross-format change of its own.

#### ODT generation (2026-08-11) — DONE

The third dialect again needed a third approach, and it is the inverse of the
parser's problem: **ODF cannot put formatting on the run**. Each distinct
combination needs its own `<style:style>` in `office:automatic-styles`, and the
span references it by name.

Rather than thread a counter through the block walk to mint `T1`, `T2`, …, the
style name is **derived from the formatting itself** (`ARb`, `ARbi`, `ARp`…).
The same combination therefore always yields the same name, so the set dedupes
with a single `mapFromList` at the end, and — since `mapValues` is sorted by key
— the generated XML is deterministic for a given document. The
`office:automatic-styles` block previously held two hardcoded styles, `Bold` and
`Italic`, that nothing referenced; they are gone.

Wired for text, headings and list items. `itemRuns` is walked alongside `items`
with the same degrade-to-plain-text rule the DOCX generator uses, so a short or
absent `itemRuns` cannot mis-pair formatting with the wrong item.

**Generation had the mirror image of the whitespace bug.** ODF collapses
whitespace on read, so a leading, trailing or repeated space must be *written*
as `<text:s/>`. Runs make this acute: splitting at formatting boundaries
routinely leaves a run that is nothing but a space, which would vanish entirely.
`odf_text` now carries `odfEncodeText` next to `odfText` — the same rules in
both directions — and **all three ODF generators use it**, since ODP and ODS
write `<text:p>` content too and had the identical exposure.

Verified through an independent implementation rather than against ourselves.
DOCX → our parser → our ODT generator → **LibreOffice** → DOCX → python-docx:

| | bold | italic | underline | strike | superscript | subscript |
|---|---|---|---|---|---|---|
| survives LibreOffice | yes | yes | yes | yes | yes | yes |

Whitespace round-trips byte-identically through **all three** ODF generators —
4-space run, tab, line break and the double space in `'item  two'` — and
LibreOffice reads our generated file exactly as it reads the hand-built fixture.

**Run segmentation is not preserved, per-character formatting is.** Re-parsing
our own output splits `'plain then '` into `'plain then'` + `' '`, because
`<text:s/>` becomes its own run. Text is identical and per-character formatting
is identical; only the boundaries move. That is the coalescing follow-up, not a
loss.

Office suite 100.0% across 61 files; `--eval` 61/61; `verify_generated.py`
all-pass; 36 modules clean.

#### ODT list items (2026-08-11) — DONE

The last parse-side gap. `odtParseList` now builds `{text, runs}` pairs and
filters them **together**, following the rule `html_parser` established: build
texts and runs as separate lists, filter only the texts, and `itemRuns` shifts
out of alignment the moment an item is blank.

That hazard is not hypothetical here, so the fixture provokes it — a blank
`<text:list-item>` sits third of seven. The parser drops it and the remaining
six stay correctly paired, which the golden now locks in. The invariant is
checked directly rather than by eye: **every item's runs concatenate to exactly
that item's own text.**

Plain lists keep emitting `mkList`, so a list with no formatting anywhere does
not start carrying `[[],[],[]]`.

New fixture `data/test_files/odt_inline_formatting.odt` + golden, since no
corpus ODT had a formatted list item — `officeparser.odt` has 14 list items and
**none** contains a span. LibreOffice validates the fixture, and ODT→ODT now
round-trips list formatting: items identical, per-character formatting
identical. LibreOffice reads all six formats back out of our generated file.

Office suite 100.0% across 62 files; `--eval` 62/62; **0 of 62** goldens differ
from current output; `verify_generated.py` all-pass; 36 modules clean.

**Phase 5 — SDKs.** Additive optional field in Python/JS/Go; no consumer breaks.
Note this now means two fields: `runs` on text/heading blocks and `itemRuns` on
list blocks.

## Definition of done

Per phase, holding the v0.29.0 bar — parse-side goldens cannot catch
generator-side defects, so renderer verification is mandatory:

- Phase 1: goldens byte-identical; 35 modules type-check clean.
- Phase 2: goldens byte-identical for documents with no formatting.
- Phase 3: a DOCX with bold/italic/underline yields runs with the right flags and
  offsets; `text` unchanged.
- Phase 4: LibreOffice **renders** bold and italic from a generated DOCX, and
  python-docx reports `run.bold is True` — not merely that the file opens.
- Throughout: `verify_generated.py` all-pass (including the L2b parts check),
  office suite at 100.0%.

## Risks

- **Scope creep into a styling engine.** `runs` should carry character
  formatting, not paragraph layout, tabs, or fonts-as-design. Colour and
  highlight are deliberately deferred to a later field addition, which the
  additive shape makes cheap.
- **`text`/`runs` divergence.** Nothing enforces that `runs` concatenates to
  `text` once markers are involved, and for HTML they deliberately differ. A
  contract asserting equality would be wrong; the ADT comment must say so.
- **Phase 3 without Phase 4 is invisible.** Parser work produces JSON nobody
  renders yet. Sequence at least `docx_parser` + `docx_generator` in the same
  release so the round-trip is demonstrable.
- **AI-generated blocks.** `direct_ai_parser` and `ai_generator` construct
  `TextBlock`s from model output (8 and 3 sites); they should keep `runs: []`
  rather than being asked to invent formatting.

## Open items — start here

State as of 2026-08-11. Phases 1–4 are complete across all four formats, both
directions — the matrix below is full. Everything listed after it is unstarted.

**Coverage matrix** (parse / generate):

| | text | heading | list |
|---|---|---|---|
| DOCX | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| HTML | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| PPTX | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| ODT  | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |

### In this doc's scope

1. **Phase 5, SDKs** — additive optional fields in Python/JS/Go. Now **two**
   fields: `runs` on text/heading blocks, `itemRuns` on list blocks. The Go
   `Block` struct (`sdks/go/types.go`) is flat with `omitempty`, so this is
   genuinely additive.
2. **`style:parent-style-name` chains** are not resolved (deliberate; automatic
   styles cover direct formatting).
3. **Colour and highlight** were deliberately left out of `InlineRun`. The
   additive shape makes adding them cheap when wanted.
4. **Coalescing adjacent same-formatting runs** — see the follow-up note in the
   ODF whitespace section. Cross-format, affects DOCX/PPTX/HTML too.

*(The former item 1, ODT superscript/subscript, did not reproduce — see the ODT
parsing section above.)*

### Unrelated issues found along the way

- **All golden drift is now resolved** — spun out into
  [`v0_30_0_golden_drift.md`](./v0_30_0_golden_drift.md) and fixed there. **Four**
  defects, none of them staleness, three of them live regressions: ODF images had
  stopped resolving (dropped in the v0.28.0 `main.ail` → orchestrator refactor),
  `test.tsv` reported `format: "csv"`, `mediaMimeType` lacked `.svg`/`.webp`, and
  `orchEmail` had the identical hardcode to the `test.tsv` one — eml/mbox
  reported `format: "email"` against goldens saying `"eml"`/`"mbox"`. **0 of 62**
  office-suite files now differ from golden.

  Two separate blind spots let these live. The office benchmark reported 100.0%
  throughout, before and after, because it scores similarity rather than
  byte-equality. And the fourth was outside the suite altogether: **16 eml/mbox
  goldens sit in `benchmarks/office/golden/` that no suite reads.** 12 of them
  still differ and need triage — at least one looks like a further regression
  (`MIME-Version` no longer emitted), so they must not be bulk-regenerated.
- **ailang-core [#646](https://github.com/sunholo/ailang/issues/646)** —
  `std/xml.getText` returns `""` for whitespace-only text nodes, so
  `<w:t xml:space="preserve"> </w:t>` is dropped and mixed-formatting paragraphs
  extract as `"plain bolditalic"`. Confirmed corrupting real corpus files on
  both DOCX and PPTX paths (`poi_comment.pptx` →
  `"Access toFinancefor Local Governments"`). Blocked upstream.
- **ailang-core [#644](https://github.com/sunholo/ailang/issues/644)** —
  `std/zip` has no in-memory archive builder, so browser-side document
  generation is impossible. Blocks item 9 of
  [`v0_29_0`](../v0_29_0/v0_29_0_docx_generation_fidelity.md).
