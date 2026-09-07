# `--reference-doc` beyond DOCX: ODT, PPTX, HTML — and what the DOCX work taught us

**Status**: PLANNED (2026-09-07) — a build plan, ranked by verified payoff per
unit of work. Nothing here is scheduled by filing it.
**Baseline**: `ed8f82f`, v0.40.0. Target: v0.41.0.
**Follows**: [`v0_39_0_reference_doc_followups.md`](../../implemented/v0_39_0/v0_39_0_reference_doc_followups.md)
deferred item 6 ("ODT/PPTX templates: same mechanic, different packages… Each
deserves its own doc").
**Supersedes the recommendation in**: [`v0_40_0_pptx_reference_doc.md`](../v0_40_0/v0_40_0_pptx_reference_doc.md).
That doc's scoping answer stands and its P1–P7 all re-verified at `ed8f82f`.
Its *recommendation* — "do not schedule; Half A alone produces no visible
improvement" — is revised by **E2 below**, a measurement it did not have.
**Related**: [`v0_40_0_convert_reference_doc_api.md`](../v0_40_0/v0_40_0_convert_reference_doc_api.md)
owns the hosted/MCP surface for whatever this ships (deferred item 4).

---

## The headline

Three findings decide the whole shape of this work, and two of them are new.

- **The DOCX template feature was cheap because `docx_generator` already spoke
  in style names.** It emits `<w:pStyle w:val="Heading1"/>`
  (`docparse/services/docx_generator.ail:251`) and `ListParagraph` (`:657`).
  Carrying `styles.xml` therefore *bound to something*. **No other generator
  does this.** ODT headings, ODP frames, ODS cells and PPTX shapes all carry
  either direct formatting or nothing at all. Carrying a template's parts into
  any of them, on its own, would style nothing.
- **ODT is one step from working** (E1). A template's `Standard` paragraph style
  *already* binds to our body text today — measured. Its `Heading 1` does not,
  because we emit `<text:h>` with no `text:style-name`. Adding the attribute
  makes it bind. That is the cheapest visible win in the repo.
- **PPTX has a cheap tier that the previous doc concluded did not exist** (E2).
  Swapping the theme's font alone changes nothing — as predicted. But a master
  carrying `<p:txStyles>` (with `<p:defaultTextStyle>` in `presentation.xml`)
  **does** restyle our free-floating text boxes: typeface and colour both
  followed. So "carry the parts" is not the no-op it was scoped as. Brand fonts
  and the brand palette land without any placeholder work.

So: PPTX is in, and it is cheaper than we told the customer. ODT is cheaper
still. HTML is nearly free. ODP, ODS and XLSX are not easy wins and should wait.

---

## Verified current state

Read and measured against the working tree at `ed8f82f` (v0.40.0).
Re-verified after rebasing onto v0.40.0 — `docx_generator.ail` moved under it
(commit `70cdec0`), so its line numbers below are the post-rebase ones; no other
generator changed.

### What ships today

| # | Claim | Evidence |
|---|---|---|
| C1 | `--reference-doc`, `--reference-section`, `--table-style` are DOCX-only; `main.ail` routes them solely to `generateDocxWithReference` | `docparse/main.ail:365,440`; `bin/docparse:135` says "DOCX output only" |
| C2 | `docx_template.ail` is 533 lines, 17 exports, every one of them `word/`-part specific (`stylesXml`, `numberingXml`, `sectPr`, `tableStyleId`) | `grep '^export' docparse/services/docx_template.ail` |
| C3 | The DOCX generator binds content to **named styles**, not direct formatting | `docx_generator.ail:251` (`<w:pStyle w:val="Heading${level}"/>`), `:657` (`ListParagraph`) |
| C4 | Generators are small: odt 175, odp 193, ods 154, html 254, xlsx 292, pptx 398 lines (docx: 1293) | `wc -l docparse/services/*_generator.ail` |

### Where each generator's output would bind — or wouldn't

| # | Format | Claim | Evidence |
|---|---|---|---|
| C5 | ODT | Headings are emitted as `<text:h text:outline-level="N">` with **no `text:style-name`**; body paragraphs *do* carry `text:style-name="Standard"` | `odt_generator.ail:71` vs `:77` |
| C6 | ODT | The generated `styles.xml` defines exactly one style, `Standard`, and no master page | `odt_generator.ail:164` |
| C7 | PPTX | Slides contain **zero `<p:ph>` elements**; every shape is `<p:cNvSpPr txBox="1"/>` with an absolute `<a:xfrm>` and hardcoded `<a:rPr sz="2800" b="1"/>` | generated `t.pptx`, `unzip -p … ppt/slides/slide1.xml` → `grep -c 'p:ph'` = **0** |
| C8 | PPTX | Slide size is hardcoded 4:3; **2 of 8** in-repo fixtures are 16:9 (`cx="12192000"`) | `pptx_generator.ail:350`; `unzip -p data/test_files/*.pptx ppt/presentation.xml` |
| C9 | PPTX | We synthesise one master, **one** layout (`type="blank"`, empty `spTree`) and a theme, as hardcoded strings; real decks carry 2 masters and 2–22 layouts | `pptx_generator.ail:370,377,397`; fixture survey |
| C10 | PPTX | Our master has no `<p:txStyles>` and `presentation.xml` has no `<p:defaultTextStyle>` | `pptx_generator.ail:350,377` |
| C11 | ODP | Frames are `<draw:frame draw:style-name="tf1" svg:x="2cm" svg:y="${idx*3}cm">` — absolute geometry, an automatic style, **no `presentation:class`**, no master-page binding | `odp_generator.ail:170,185` |
| C12 | ODS | Cells are `<table:table-cell><text:p>…` — **no style name on any cell or row** | `ods_generator.ail:142` |
| C13 | XLSX | Cells emit no `s=` attribute, so every cell resolves to `cellXfs` index 0; `styles.xml` defines one font (Calibri 11) | `xlsx_generator.ail:214,292` |
| C14 | HTML | The stylesheet is one hardcoded `<style>` string literal | `html_generator.ail:38` |

### New measurements (the spikes)

Run in the session scratchpad; commands in the verification log. Rendering was
via LibreOffice `soffice --headless --convert-to html`, which resolves the style
chain and emits the computed properties — see the caveat under E2.

| # | Experiment | Result |
|---|---|---|
| **E1a** | Generated an ODT from markdown; replaced `styles.xml` with a template defining `Standard` at **9pt** and `Heading_20_1` at **55pt red**; rendered | Body text rendered **9pt** — *the template's paragraph style already binds*. Heading rendered **16pt, not red** — the template's `Heading 1` was ignored; LibreOffice fell back to its own built-in heading. `grep -c 55pt` = 0. |
| **E1b** | Same file, one edit: `<text:h>` → `<text:h text:style-name="Heading_20_1">` | Heading rendered **55pt `#ff0000`**. The template's style bound. |
| **E2a** | Generated a PPTX; changed the theme's `majorFont`/`minorFont` typeface Calibri → **Courier New**; rendered | No Courier New anywhere. Text stayed Liberation Sans. **Carrying the theme alone changes nothing** — confirms the v0_40_0 doc's P4 reasoning. |
| **E2b** | Same file; added `<p:txStyles>` (title/body/other, Courier New + `#FF0000`) to the master **and** `<p:defaultTextStyle>` to `presentation.xml` | Both text boxes rendered **Courier New, `#ff0000`**. **A real master's text styles do reach our non-placeholder shapes.** Explicit `sz`/`b` on our runs stayed ours, as expected. |

**E2b is the finding that changes the plan.** The v0_40_0 doc concluded Half A
would "carry a branded master that has no effect on a single visible pixel". That
is true of the *theme* (E2a) but false of the *master's text styles* (E2b) —
and every Office-authored template has them. Fonts, text colour, and (via
`<p:bg>`) the slide background follow the brand without touching a placeholder.

**Caveat, and it is load-bearing**: E2b was measured in LibreOffice.
PowerPoint's and Keynote's inheritance for non-placeholder shapes must be
confirmed before Sprint 2 is committed — see Spike 0 in the plan. If PowerPoint
disagrees, PPTX drops back to the v0_40_0 doc's assessment and Sprint 2 becomes
placeholder binding from the start.

---

## Lessons from the DOCX work

These are not general advice. Each one is a specific thing that cost time or
shipped a defect in the `--reference-doc` sprint, restated as a rule for this work.

### L1 — Carrying parts is not the feature. Binding output to them is.

DOCX templating worked on day one because C3 was already true: the generator
emitted `Heading1` and `ListParagraph`, so a carried `styles.xml` had something
to attach to. Every other format fails C3. **For each format, the first question
is not "can we carry the parts" but "what in our output would change if we
did".** E1a/E2a/E2b are that question asked and answered. Any format where the
answer is "nothing" is not an easy win no matter how simple the zip surgery is.

### L2 — A dangling style reference renders as body text, silently. Never as an error.

The comment at `docx_generator.ail:929-944` records the sharpest version of
this: omitting the `styles.xml` *relationship* (while still declaring the part
in `[Content_Types].xml`) made every `<w:pStyle w:val="HeadingN"/>` resolve to
nothing and every heading render as body text. It went unnoticed because pandoc
pattern-matches styleIds heuristically instead of resolving the part — so one
consumer appeared to work.

**v0.40.0 added a second instance of this while this doc was being written.**
`docxStyleDefs()` (`docx_generator.ail:811`) now returns styles as `(id, xml)`
pairs rather than one blob, so reference mode injects **only the ids the
template does not already define** — the template's `Heading1` wins, a missing
`ListParagraph` still gets filled in, "and the two paths cannot disagree about
what the set of styles is". Its comment names the invariant outright: *"A
missing style definition here is the same class of bug as the orphaned
styles.xml: the reference resolves to nothing."* Commit `70cdec0` then made "0
template parts carried" say **why**, because the silent-correct case and the
silent-broken case looked identical.

**That pair — id-keyed merge, and a loud reason when nothing is carried — is
the pattern to copy, not reinvent, for ODT (Sprint 2 step 2) and PPTX.**

Applied here: **validate at load, fail loudly, write nothing.** If
`--reference-doc theme.pptx` names a deck with no master, or `--reference-doc
house.odt` has no `Heading_20_1`, that is an error with a message naming what
was missing — not a silent fall-through to default look. This is the same
property `failure_check.py` guards: *a file on disk means the document was
produced as asked* (see `.claude/rules/benchmarks.md`).

### L3 — Direct formatting alongside a style reference silently defeats the template.

Item 3 of the v0.39.0 sprint had to *drop* the hardcoded `<w:tblBorders>` when
emitting `<w:tblStyle>`, because emitting both keeps our look while appearing to
honour the template (`docx_generator.ail:532`).

Applied here, in order of how much it will hurt:
- **ODT**: emitting `text:style-name="Heading_20_1"` is not enough if we also
  emit an automatic style overriding it.
- **PPTX**: our runs carry `sz="2800" b="1"` (C7). Under a brand master those
  sizes override the master's `titleStyle`. Sprint 2 must decide, explicitly and
  per property, which of `sz`, `b`, `algn` we surrender to the template. The
  default answer is **surrender all of them in reference mode** — a template
  whose title is 40pt light grey should produce a 40pt light grey title.
- The no-template path keeps every one of them (L6).

### L4 — A convention-guess constant passes the suite by luck.

`isOrderedList` decided bullet-vs-numbered with `numId != "1"` and scored 100%
because pandoc happens to assign bullets numId 1 (C8 of the v0.39.0 doc). The
fix was to *resolve* the value from the document rather than assume the
convention.

Applied here, and this is the single highest-risk item in the whole plan:
**a body placeholder's `idx` is defined by its layout, not by convention.**
Binding to `idx="1"` because built-in Office layouts usually use it will render
correctly against every Microsoft-authored fixture we own and silently
mis-render against a hand-built customer master — which is precisely the
template this feature exists to serve. `idx` and `type` must be **read from the
chosen layout**. Same for ODT: pick the heading style by resolving
`style:display-name`/`style:name` in the template, never by assuming
`Heading_20_1` exists.

### L5 — One value type covers both paths, so there is no second code path to drift.

`DocxRefDoc` with `active: bool` and a `docxTplNone()` constructor
(`docx_template.ail:36,52`) meant every consumer branched on one field.
Replicate exactly: `OdfRefDoc`, `PptxRefDoc`, each with `active` and a `…None()`
constructor. No `Option[Template]` threaded through generators, no parallel
"withTemplate" entry points.

### L6 — The default output stays byte-identical.

`numIdBase 1 / absNumIdBase 0` were chosen specifically so the no-template path
reproduced the ids the generator had always emitted. The office goldens then
proved it.

Applied here with one honest exception: **the ODT heading fix (E1b) changes
default output** — every generated ODT gains `text:style-name`, and our own
minimal `styles.xml` must gain the heading styles to match (C6), or we
reintroduce L2 in the no-template path. That golden churn is the price of the
feature and must be listed in the CHANGELOG, not absorbed quietly. Everything
else — PPTX, HTML — stays byte-identical without a flag.

### L7 — No suite scores appearance, and "it opens" passes structurally invalid output.

`.claude/rules/benchmarks.md` names this as *the* blind spot: three defects in a
row reached a release through green suites, because parse-side goldens and
"does python-docx open it" both pass through broken output. `verify_generated.py`
exists because malformed DOCX table geometry shipped twice while LibreOffice
tolerated what Word did not.

Styling adds a *new* variant of the same blind spot: a document can be
structurally perfect and still ignore the template entirely (E1a is exactly
that document — valid ODT, valid styles.xml, zero styling applied). So the
assertions must check **binding**, not presence:

- not "the output contains the template's `Heading_20_1` definition" —
  **"every `<text:h>` names a style the carried `styles.xml` defines"**;
- not "the output contains a slideMaster" — **"every shape's layout reference
  resolves to a layout the carried master lists, and every `<p:ph idx>` we emit
  appears in that layout"**;
- plus, for the tier that claims a visible effect, one **render assertion**:
  `soffice --headless --convert-to html` and grep the computed font/colour.
  E1a/E1b/E2a/E2b are already that check, run by hand; they become fixtures.

`soffice` is on the dev machine (`/opt/homebrew/bin/soffice`) and is a CI
install away — the same call `failure_check.py` made for `pdftotext`, and the
same lesson: **the one thing no other job covers is the one CI will not have
installed.** Add it to the benchmark job in the same commit, not after the first
red run.

### L8 — Name the deferred surfaces at design time.

v0.39.0 deferred MCP (item 4) and browser/WASM (item 5) and *recorded why*:
`mcpConvert` has a fixed 4-arg signature that cannot receive a local path, and
`docxPartsFor` is `pure` while a template needs `FS`. Both are still open and
now belong to `v0_40_0_convert_reference_doc_api.md`.

Every format this doc adds inherits both gaps. Say so up front (see Non-goals)
rather than discovering per-format that the hosted API cannot reach the feature.

### L9 — Write contracts that can be false.

`.claude/rules/ailang-coding.md`: an audit found 13 postconditions that could
not fail. For this work the meaningful ones are shaped like *"in reference mode,
the output declares no style id that the carried styles part does not define"* —
a property that is false for the bug L2 describes. `ensures { listLength(result)
>= 0 }` is a comment; write it as one. And reach for `requires` — e.g.
`requires { active implies length(stylesXml) > 0 }`.

---

## Ranked plan

Effort is a rough sprint count for one implementer. "Payoff" is what a customer
sees, and only E-backed claims are called verified.

| Rank | Work | Effort | Payoff | Status of evidence |
|---|---|---|---|---|
| **1** | **PPTX `--reference-doc`, theme tier** — carry theme, master(s), layouts, `sldSz`, presentation defaults | ~1 sprint | Brand fonts, palette, background, correct aspect ratio | **Verified (E2b)**, pending Spike 0 |
| **2** | **ODT heading style binding** (no flag; fixes default output too) | ~2 days | Headings finally look like headings; prerequisite for 3 | **Verified (E1a/E1b)** |
| **3** | **ODT `--reference-doc`** — carry `styles.xml` + master page | ~0.5 sprint | Full house style on generated ODT | **Verified (E1a)** — body already binds |
| **4** | **PPTX `--slide-size 16:9\|4:3`** (independent of any template) | ~2 hours | 4:3 in 2026 is a defect on its own | C8 |
| **5** | **HTML `--reference-doc style.css`** | ~2 days | Branded HTML output; the cheapest thing here | C14 |
| **6** | **PPTX placeholder binding** (the v0_40_0 "Half B") | ~1–2 sprints | Correct autofit, outline view, working "Reset Slide"; templates render *properly*, not just in brand fonts | C7, C9 |
| 7 | ODP `--reference-doc` | ~1–2 sprints | Same as 1+6, for the ~5% of users who want ODP | C11 — needs both halves, no cheap tier |
| 8 | XLSX `--reference-doc` | ~0.5 sprint | Default font + theme only; header rows stay unemphasised | C13 — cheap but shallow, misleading as "template support" |
| 9 | ODS `--reference-doc` | ~1 sprint | Nothing, until cells carry style names | C12 |

**Recommended cut: 1–5.** That is one sprint plus change, it includes
PowerPoint, and every item in it has a measured visible effect. **6** is the
follow-on sprint and the thing that makes PPTX templating *correct* rather than
*branded*; it should be scheduled but not bundled, because it rebases every PPTX
golden (L6/L7).

**7–9 are explicitly not in scope.** 8 and 9 deserve the reasoning written down:
XLSX would let us claim template support for a feature that only moves the
default font (C13), and ODS would let us claim it for one that moves nothing
(C12). Both are the failure L1 warns about, dressed as progress. If a customer
asks, the honest answer is "cells would need to carry named styles first".

---

## Design

### CLI surface

One flag, dispatched on the **output** extension:

```
docparse notes.md --convert deck.pptx  --reference-doc brand.pptx
docparse notes.md --convert memo.odt   --reference-doc house.odt
docparse notes.md --convert page.html  --reference-doc house.css
docparse notes.md --convert deck.pptx  --slide-size 16:9
```

Agreeing with `v0_40_0_pptx_reference_doc.md`'s answer 2: **the same flag**. The
user-facing concept is identical ("style my output after this file"); that the
implementations share almost nothing is an internal fact and must not surface as
`--reference-deck`.

Rules, all of them errors that write nothing (L2):

- Reference format must match output format (`.pptx` template → `.pptx` output).
  A `.docx` reference for `.pptx` output is a mistake, not a conversion request.
  `verify_generated.py` already asserts the DOCX case of this
  (`L6 RefDoc: PASS (non-DOCX reference refused)`) — extend the stage, don't
  write a new one.
- Unreadable, non-archive, or structurally unusable template (no master; no
  `styles.xml`) → error naming what was missing.
- `--table-style` and `--reference-section` stay DOCX-only and error if combined
  with a non-DOCX output, with a message saying so.
- `--slide-size` is independent of `--reference-doc`; with both, the template's
  `sldSz` wins unless `--slide-size` is given explicitly.

### Module layout

```
docparse/services/docx_template.ail    (unchanged)
docparse/services/pptx_template.ail    (new)
docparse/services/odf_template.ail     (new — ODT now, ODP later)
docparse/services/pkg_template.ail     (new — the shared 15%)
```

**Do not generalise `docx_template.ail`.** C2: its 17 exports are all
`word/`-part specific, and a `Template` abstraction over `styles.xml` +
`slideMaster` + `styles.xml`(ODF) would be three unrelated things behind one
name. What *does* generalise is the byte-level carry: open the archive, list
entries, drop the parts we regenerate, carry the rest verbatim as base64,
rewrite `[Content_Types].xml` and `_rels`. Extract exactly that into
`pkg_template.ail` — a first consumer plus a second one is enough evidence that
it is shared; a third is not required to justify it.

Following L5, each format gets one record with `active`:

```
type PptxRefDoc = {
  active: bool,
  entries: [{name: string, data: string}],   -- carried verbatim
  masterIds: [string],                        -- from sldMasterIdLst
  layouts: [{id: string, kind: string, name: string, phs: [{typ: string, idx: string}]}],
  themeRelId: string,
  sldSzCx: int, sldSzCy: int,
  defaultTextStyle: string
}
```

`layouts[].phs` exists from Sprint 1 even though only Sprint 3 consumes it —
it is read from the layout XML (L4), so parsing it early costs nothing and
proves at load time that the template is one we can eventually bind to.

### Sprint 1 — PPTX theme tier

Carry `ppt/theme/*`, `ppt/slideMasters/*`, `ppt/slideLayouts/*` and their
`_rels`, `ppt/tableStyles.xml`, and every `ppt/media/*` the master references.
Rewrite `presentation.xml` (`sldMasterIdLst`, `sldSz`, `defaultTextStyle` lifted
from the template) and `[Content_Types].xml`. Our slides keep their current
shape tree; each `slideN.xml.rels` points at a chosen layout — Sprint 1 picks
layout ordinal 0 and records that as a placeholder decision Sprint 3 replaces.

Per L3, reference mode drops our hardcoded `<a:rPr sz b>` and `<a:pPr algn>` so
the master's text styles govern. That is what E2b measured.

### Sprint 2 — ODT (items 2 + 3) and HTML (item 5)

ODT, in order:

1. Emit `text:style-name="Heading_20_N"` on `<text:h>` (E1b).
2. Add `Heading_20_1..6`, `List_20_Bullet`, `List_20_Number`, `Table_20_Contents`
   to our minimal `styles.xml` (C6), so the *no-template* path still resolves
   (L2, L6). This is the golden churn. Structure it as an **`odfStyleDefs()`
   returning `(name, xml)` pairs**, mirroring `docxStyleDefs()`
   (`docx_generator.ail:811`) exactly: under a template, inject only the names
   the template does not define, so its `Heading_20_1` wins and an absent
   `List_20_Bullet` is still filled in. Same function shape, same invariant,
   one fewer thing to get wrong.
3. `--reference-doc house.odt`: carry the template's `styles.xml` whole (it
   already contains `office:master-styles`, so headers/footers and page geometry
   come along for free — the ODF equivalent of the DOCX `<w:sectPr>` lift, and
   genuinely easier), plus `Pictures/*` and `Configurations2/*` if present.
4. Resolve heading style ids from the template rather than assuming
   `Heading_20_N` (L4): match `style:family="paragraph"` on `style:name`, then
   `style:display-name`, then `style:default-outline-level`. Error if level 1 is
   unresolvable.

HTML: `--reference-doc x.css` replaces the literal at `html_generator.ail:38`;
a `.html` reference splices our body into it at a documented marker. Keep the
class names — they are the contract a house stylesheet writes against, so
document them in `docs/`.

### Sprint 3 — PPTX placeholder binding

The v0_40_0 doc's Half B, unchanged in substance, with L4 applied to B3. The
one addition: **layout intent mapping** should be derived from the block stream
(a slide whose only block is a heading → `title`; heading + body → `titleOnly`
or `obj`; table → `tbl` if the template offers one), resolved against the
layout's `type` attribute first, then its name, then ordinal. Non-English
layout names are why name matching is second, not first.

---

## Non-goals (recorded, with reasons)

- **XLSX, ODS, ODP** — ranks 7–9 above. Reasons given there.
- **MCP / hosted API** (L8) — `mcpConvert`'s fixed 4-arg signature cannot carry
  a local template path, and how a hosted API receives a template (upload?
  sample id? `gs://`?) is a design question. Owned by
  `v0_40_0_convert_reference_doc_api.md`.
- **Browser / WASM** (L8) — the pure entry points cannot do `FS`; templates
  would arrive as bytes from JS. Unscoped.
- **Splice mode** — inserting generated slides into an existing deck. Named in
  the v0_40_0 doc as arguably a better fit for PPTX than templating, since a
  deck's own slides already bind to its master. Different feature, different
  doc; do not conflate.
- **Editing or synthesising a template** — we carry what is there. No
  "generate a brand template from a colour".

---

## Verification plan

Nothing ships without all four standing suites (CLAUDE.md hard rule):
`run_benchmarks.py --suite office` at 100%, `roundtrip_check.py`,
`verify_generated.py`, `failure_check.py`.

**Spike 0 (blocks Sprint 1's commitment, ~half a day).** Re-run E2b's artifact
in **PowerPoint and Keynote**, not only LibreOffice. If non-placeholder shapes
do not inherit `<p:defaultTextStyle>` / `<p:otherStyle>` there, the theme tier
is worth nothing to most users and Sprint 1 merges into Sprint 3. Record the
result in this doc either way.

New `verify_generated.py` stages, each asserting **binding** (L7):

- `L7 RefPptx` — generate under `pandoc_basic.pptx` as template. Assert: the
  output's `sldSz` equals the template's (16:9 preserved); the carried master
  count and layout count match the template; every `slideN.xml.rels` layout
  target exists in the package; no `<a:rPr sz=…>` survives in reference mode.
- `L7 RefPptxRender` — `soffice --headless --convert-to html`, assert the
  template's `majorFont` typeface appears in the computed output. This is E2b
  as a fixture, and it is the only stage that can catch "carried but not
  applied".
- `L7 RefOdt` — every `<text:h>` in the output names a style the carried
  `styles.xml` defines; render-assert the template's heading size appears
  (E1b), and that E1a's failure mode — style-less `<text:h>` — cannot recur.
- `L7 RefOdtDefault` — **no-template** ODT still resolves every style it names,
  against our own `styles.xml`. This is the L2 regression guard for the golden
  churn in Sprint 2.
- `L7 RefMismatch` — extend the existing non-DOCX-reference refusal to all
  format pairs: wrong-format, unreadable, and master-less templates each exit
  non-zero and write nothing (`failure_check.py`'s property).

CI: add `libreoffice` to the benchmark job **in the same commit** as the first
render stage (L7's poppler lesson). Inline tests for the pure pieces — layout
`<p:ph>` extraction, heading-style resolution order, `sldSz` parsing,
out-of-range and absent cases — and `requires`/`ensures` per L9.

---

## Open questions

1. **Spike 0's answer.** Everything about Sprint 1's ranking depends on it.
2. **Does reference mode surrender `sz` and `b` on PPTX runs?** Proposed: yes
   (L3). It makes template output correct and non-template output unchanged,
   but a user who wanted "our layout, their fonts" loses the middle ground.
3. **Do we ship the ODT heading fix (rank 2) before, or with, ODT templating?**
   It is a defect fix in its own right and it moves goldens; shipping it alone
   makes the golden churn legible in one release rather than tangled with a
   feature.
4. **In-repo template fixtures.** DOCX reused `docx-hdrftr.docx`. PPTX can reuse
   `pandoc_basic.pptx` (22 layouts, 16:9). ODT has **no** in-repo file with
   real heading styles except `officeparser.odt` — E1's synthetic template
   should be committed as a fixture rather than rebuilt per run, the way the
   two-section DOCX variant is synthesized in `verify_generated.py`.

---

## Verification log

| Claim | How verified |
|---|---|
| C1 | `grep -n reference docparse/main.ail bin/docparse` |
| C2 | `grep '^export' docparse/services/docx_template.ail` → 17, all `word/`-specific; `wc -l` → 533 |
| C3 | Read `docx_generator.ail:251,657`; comment at `:929-944`; `docxStyleDefs` at `:811` |
| C4 | `wc -l docparse/services/*_generator.ail` |
| C5, C6 | Read `odt_generator.ail:63-115,164` (headings at `:71`); generated an ODT and read `content.xml` |
| C7 | Generated `t.pptx` from markdown; `unzip -p t.pptx ppt/slides/slide1.xml \| grep -c 'p:ph'` → **0**; shape tree shows `txBox="1"`, `<a:off x="457200" y="1200000"/>`, `sz="2800" b="1"` |
| C8 | `pptx_generator.ail:350`; `for f in data/test_files/*.pptx; do unzip -p "$f" ppt/presentation.xml \| grep -o 'sldSz[^/]*'; done` → 2 of 8 at `cx="12192000"` |
| C9 | Read `pptx_generator.ail:370,377,397`; `unzip -l data/test_files/*.pptx \| grep -c slideLayout` → 2–22, masters 2 |
| C10 | `grep txStyles\|defaultTextStyle docparse/services/pptx_generator.ail` → 0 hits |
| C11 | Read `odp_generator.ail:87-185` |
| C12 | Read `ods_generator.ail:142` |
| C13 | Read `xlsx_generator.ail:214,292` — no `s=` emitted on any `<c>` |
| C14 | Read `html_generator.ail:38` |
| E1a | Generated ODT; `zip`-replaced `styles.xml` with `Standard` 9pt + `Heading_20_1` 55pt `#ff0000`; `soffice --headless --convert-to html` → computed sizes `9pt` (body) and `16pt` (heading); `grep -c 55pt` = 0, no `#ff0000` |
| E1b | Same archive, `content.xml` edited to add `text:style-name="Heading_20_1"`; re-rendered → `font-size: 55pt`, `color: #ff0000` present |
| E2a | Generated PPTX; theme `typeface="Calibri"` → `"Courier New"`; re-zipped; rendered → no Courier New in computed output |
| E2b | Same base; added `<p:txStyles>` (title/body/other → Courier New, `#FF0000`) to `slideMaster1.xml` and `<p:defaultTextStyle>` to `presentation.xml`; rendered → `font-family:'Courier New'` ×2 and `color:#ff0000` ×2 in computed output |
| `soffice` availability | `which soffice` → `/opt/homebrew/bin/soffice` |
