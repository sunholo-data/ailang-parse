# `--reference-doc` for PPTX: what master slides would actually require

**Status**: PLANNED (2026-08-31) — answers a question; scopes the work; no
commitment implied by filing.
**Source**: ailang message `inbox_1788155557570_f8f91f6c` from `aitana-platform` —
"Question: is a --reference-doc equivalent planned for .pptx (master slides)?"
**Follows**: [`v0_39_0_reference_doc_followups.md`](../../implemented/v0_39_0/v0_39_0_reference_doc_followups.md)
**deferred item 6** — "ODT/PPTX templates: same mechanic, different packages.
PPTX is bigger (layout ids). Each deserves its own doc." This is that doc for PPTX.

## The question, and the short answer

They asked three things, and framed the stakes precisely: *"The answer decides
whether deck generation is an afternoon of work for us or a quarter, so we would
rather ask than assume."*

1. **Is slide templating on the roadmap?** Yes — as a deferred item with a
   recorded reason, not as scheduled work. It is not scheduled today.
2. **Same `--reference-doc` flag extended to pptx, or something separate?** Same
   flag. The user-facing concept ("style my output after this file") is
   identical, and splitting it into `--reference-deck` would make the CLI worse.
   The implementation shares almost nothing with the DOCX path, which is an
   internal fact and should not surface as a second flag.
3. **Is there an intended workaround today?** No good one. See "What we can
   honestly say about workarounds" — the honest answer is that generating into a
   pptx that already carries the master **does not work today either**, and the
   reason is the finding below.

**And the finding that actually answers their question**: carrying a customer's
master into our output would, on its own, change **almost nothing**. The blocker
is not the template plumbing. It is that our generated slides do not inherit
from a master at all.

## Verified current state

Read against the working tree at `d5ec0bd`.

| # | Claim | Evidence |
|---|---|---|
| P1 | `--reference-doc` is DOCX-only; `main.ail` routes it solely to `generateDocxWithReference` | `docparse/main.ail:360,435`; `bin/docparse:135` documents "DOCX output only" |
| P2 | The PPTX generator synthesises its own master, one layout and a theme, as hardcoded strings | `docparse/services/pptx_generator.ail:60-64, 371-381` |
| P3 | It emits exactly **one** layout, `type="blank"`, containing an empty `spTree` | `pptx_generator.ail:371` |
| P4 | **Generated slides use free-floating text boxes, not placeholders** | `unzip -p out.pptx ppt/slides/slide1.xml` → `<p:cNvSpPr txBox="1"/>`, explicit `<a:xfrm><a:off x="457200" y="1200000"/>`, hardcoded `<a:rPr sz="2800" b="1"/>`. No `<p:ph>` element anywhere |
| P5 | Slide size is hardcoded 4:3 | `pptx_generator.ail:350` — `<p:sldSz cx="9144000" cy="6858000" type="screen4x3"/>` |
| P6 | Real templates carry many layouts per master | `data/test_files/*.pptx`: 22 layouts / 2 masters in the Office-authored files (11 each) |
| P7 | The `docx_template.ail` machinery does not generalise | 533 lines built around `word/styles.xml`, `word/theme/theme1.xml`, `<w:sectPr>` lifting and `<w:tblStyle>` binding. None of those parts or elements exist in a PPTX package |

**P4 is the whole answer.** A `<p:sp>` with `txBox="1"`, an absolute `<a:xfrm>`
and a hardcoded `sz="2800" b="1"` ignores the master's title placeholder
completely. Swap in a customer's `slideMaster1.xml` and the deck's fonts,
colours, logo placement and text geometry stay exactly as they are — because
nothing in the slide references the master's styling. The output would carry a
branded master that has no effect on a single visible pixel.

This also explains their customer's report that generating PowerPoint "didn't
work". It is not a mystery and not a misuse of the flag: there is no mechanism to
bind generated slides to a master, and there is nothing they could have done
differently.

## What the work actually is

Two halves, and the conventional intuition about which is harder is wrong.

### Half A — carry the template's parts (the easy half)

Directly analogous to `docxTplLoad`: read `ppt/slideMasters/*`,
`ppt/slideLayouts/*` (and their `_rels`), `ppt/theme/*`, `ppt/tableStyles.xml`,
plus embedded media the master references, and emit them in place of the
synthesised strings. Rewrite `presentation.xml`'s `sldMasterIdLst` and
`[Content_Types].xml` overrides to match. Add `<p:sldSz>` from the template
(P5 — otherwise a customer's 16:9 deck comes out 4:3, which is a visible
failure on its own and worth fixing regardless of this feature).

Mechanically fiddlier than DOCX because the part count is variable and the rels
graph is real, but it is the same kind of work, and `docx_template.ail`'s shape
(load once, carry an immutable descriptor, drop parts the output replaces)
transfers.

### Half B — bind slides to layouts (the hard half, and the new design surface)

This is what DOCX never needed. Three problems, none of them plumbing:

1. **Placeholder-bound shapes.** Replace the absolutely-positioned text boxes of
   P4 with `<p:sp>` carrying `<p:nvPr><p:ph type="title"/></p:nvPr>` and
   `<p:ph type="body" idx="1"/>`, dropping the explicit `xfrm` and `rPr` so
   geometry and typography come from the layout. This is a rewrite of
   `pptxSlideXml`, and it changes the **default, no-template** output too —
   which means every PPTX golden and every `verify_generated.py` PPTX assertion
   moves with it. Not a bolt-on.
2. **Layout selection per slide.** A template offers ~11 layouts (P6); each
   generated slide must pick one by intent — title slide, title + content,
   section header, blank. Today every slide is the same shape. This needs a
   mapping from our `Block` stream to a layout intent, plus a resolution rule
   for templates whose layouts are named in another language or not named at
   all (match by `type` attribute first, then name, then ordinal).
3. **Placeholder-index agreement.** A body placeholder's `idx` is defined by the
   layout, not by convention. Binding to `idx="1"` because the built-in Office
   layouts usually use it will silently mis-render against a hand-built master —
   the exact class of customer template this feature exists to serve. The index
   must be read from the chosen layout.

### Honest size

Half A alone is a focused sprint and produces **no visible improvement** — that
is the trap worth naming, because it is the version of this feature that looks
finished and satisfies nobody. Half B is a second sprint and carries a full
golden rebase across every PPTX fixture. Two sprints together, with the risk
concentrated in B3, where the failure mode is silent mis-rendering rather than a
crash.

So: not an afternoon, not a quarter.

## What we can honestly say about workarounds

Their option 3 was "generate into a .pptx that already carries the master".
**That does not work today**, and P4 is why: even if the container carried the
master, the slides we write into it would not reference it. Offering this as a
workaround would send them down a path that cannot succeed.

Their current decision — scope PowerPoint out, ship `.docx` first because it is
the only format with a templating story — is the right call on today's facts, and
the reply should say so plainly rather than leaving them to infer it.

The nearest real thing we could offer, if deck branding becomes urgent before
this is scheduled: **splice mode** (v0_39_0 deferred item 7) is arguably a better
fit for PPTX than for DOCX. Inserting generated slides into a customer's existing
deck sidesteps Half B entirely — the deck's own slides already bind to its
master, and new slides can be cloned from an existing slide's shape tree rather
than synthesised. Different feature, different doc, but worth naming as the
cheaper path to the same customer outcome.

## Recommendation

Do not schedule this on the strength of one question. Two things change that:

- **P5 (hardcoded 4:3) should be fixed now regardless.** It is small, it is
  independent, and generating a 4:3 deck in 2026 is a defect in its own right.
- **Half B has value without any template.** Placeholder-bound slides render
  better in PowerPoint even against our own synthesised master — better text
  autofit, correct behaviour in outline view, working "Reset Slide". If PPTX
  generation quality is worth investing in at all, B1 is the first move, and it
  is the prerequisite for templating whenever that lands. That ordering makes
  the investment useful before the feature is complete, which is the opposite of
  starting with Half A.

## Verification log

| Claim | How verified |
|---|---|
| P1 | `grep -n reference-doc docparse/main.ail bin/docparse` |
| P2, P3, P5 | Read `pptx_generator.ail:55-70, 337-381` |
| P4 | Generated `nest.pptx` from markdown, `unzip -p ... ppt/slides/slide1.xml` — inspected the shape tree |
| P6 | `for f in data/test_files/*.pptx; do unzip -l "$f" \| grep -c slideLayout; done` |
| P7 | Read `docparse/services/docx_template.ail` export surface (17 exports, all `word/`-part specific) |
