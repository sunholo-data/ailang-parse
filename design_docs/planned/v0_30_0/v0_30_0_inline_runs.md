# Inline Runs — representing formatting inside a paragraph

**Status**: PARTIAL — phases 1–2 implemented 2026-08-10; phases 3–5 planned
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
`officeparser.odt`, `pandoc_inline_images`, `test.tsv`. Pre-existing golden
drift, not caused by this work, and invisible to the office benchmark (which
scores similarity rather than byte-equality) — so the goldens are staler than
the 100.0% headline suggests.

**Phase 3 — parsers, one per increment.** Independent and individually
shippable, highest value first:

1. `docx_parser` — `w:rPr` → runs. The data is already in hand; this is the
   whole point.
2. `html_parser` — emit runs *alongside* the existing markers.
3. `pptx_parser` — `a:rPr` (`b="1"`, `i="1"`).
4. `odt_parser` — `text:span`, which needs automatic-style resolution to know
   what a style name means; genuinely harder, do it last.

**Phase 4 — generators, one per increment.** `docx_generator` first (`w:rPr` in
runs), then `html_generator` (`<strong>`/`<em>`), then odt/pptx. Each falls back
to today's plain-text path when `runs` is empty, so partial completion is a
working state throughout.

**Phase 5 — SDKs.** Additive optional field in Python/JS/Go; no consumer breaks.

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
