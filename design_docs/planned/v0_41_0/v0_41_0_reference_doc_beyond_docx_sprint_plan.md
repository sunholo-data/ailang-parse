# Sprint Plan — M-REFDOC-FORMATS (`--reference-doc` beyond DOCX)

**Sprint JSON**: `.ailang/state/sprints/sprint_M-REFDOC-FORMATS.json`
**Design doc**: [`v0_41_0_reference_doc_beyond_docx.md`](v0_41_0_reference_doc_beyond_docx.md)
**Target**: v0.41.0 · **Mode**: sequential · **Created**: 2026-09-07

## Why this order

The design doc ranks the **PPTX theme tier** first, gated on **Spike 0**
(re-measure E2b outside LibreOffice). **Spike 0 has now been run and it passes**
— see the design doc's Spike 0 block for the table. Keynote applies the theme
font to our non-placeholder text boxes on the theme alone, and the master's
`<p:txStyles>` carries colour on top. LibreOffice reached the same conclusion by
a different route (theme alone insufficient there, `txStyles` required). Both
engines agree that carrying the parts restyles the output.

So the PPTX work leads, as the design doc ranked it, and as the original request
asked ("at minimum include powerpoint").

Sequential, and the dependencies are real:

- **M1 → M2**: the template supplies `<p:sldSz>`, so the slide size has to be a
  parameter before a template can set it. M1 is that plumbing and ships a
  defect fix (hardcoded 4:3) on its own.
- **M3 → M4**: a template's `Heading_20_1` cannot bind to output that names no
  style.
- **M5** is independent; it sits late because it is small.
- **M6** is the gate.

**PowerPoint itself is still untested** — not installed on the studio, no
licence available. Two engines agreeing plus OOXML spec alignment makes this
low risk, and M6's render assertion is the standing guard. If a PowerPoint
machine becomes available, re-run
`scratchpad/spike0/run_spike0.sh`'s artifacts there before the release.

**A hard constraint that shapes M3 and M6**: `benchmarks/office/golden/*.json`
embed an absolute `filename` canonicalised to `/Users/mark/dev/sunholo/...`.
Running `generate_golden.sh` on this checkout rewrites all ~73 of them to
`/Users/voightkampff/...`. The scorer ignores the path, so those are noise —
but they bury the real deltas. Every golden update below therefore uses the
single-file path: `git checkout benchmarks/office/golden/`, regenerate the one
file, sed the path back, copy it in.

## M1 — PPTX slide size becomes a parameter (prerequisite)

`pptx_generator.ail:350` hardcodes 4:3; two of eight in-repo fixtures are 16:9.
Generating a 4:3 deck in 2026 is a defect on its own, and M2 needs `sldSz` to be
settable before a template can supply it.

| Step | Detail | Files |
|---|---|---|
| 1.1 | `pptxPresentation` takes `cx`/`cy`; `16:9` → `12192000x6858000`, `4:3` → `9144000x6858000 type="screen4x3"` | `pptx_generator.ail` |
| 1.2 | **Default changes to 16:9.** This moves generated PPTX bytes; call it out in the CHANGELOG rather than absorbing it | " |
| 1.3 | `--slide-size 16:9\|4:3`; any other value is an error listing the accepted two, writing nothing | `bin/docparse`, `main.ail` |
| 1.4 | Checkpoint: `--check`, `--test`, `verify_generated.py` PPTX stage | — |

**Done when**: default output is 16:9, `--slide-size 4:3` restores the previous
geometry exactly, and an invalid value writes nothing.

## M2 — PPTX `--reference-doc` (the theme tier)

Spike 0's payoff. Carry the template's look; keep our shape tree. Explicitly
**not** placeholder binding — that is a separate, larger sprint (deferred below).

| Step | Detail | Files |
|---|---|---|
| 2.1 | `pptx_template.ail`: `PptxRefDoc { active, entries, layouts, sldSzCx, sldSzCy, defaultTextStyle, themeRelId }` + `pptxTplNone()`. One value type, both paths (L5) | new |
| 2.2 | `pptxTplLoad(path) ! {FS}` — carry `ppt/theme/*`, `ppt/slideMasters/*`, `ppt/slideLayouts/*` and their `_rels`, `ppt/tableStyles.xml`, and `ppt/media/*` | " |
| 2.3 | Parse each layout's `<p:ph type= idx=>` into `layouts[].phs` **now**, though only the deferred binding sprint consumes it — reading it proves at load time that the template is one we could later bind to (L4) | " |
| 2.4 | Rewrite `presentation.xml`: `sldMasterIdLst` from the template, `sldSz` from the template (overridden by an explicit `--slide-size`), `defaultTextStyle` lifted | `pptx_generator.ail` |
| 2.5 | Rewrite `[Content_Types].xml` overrides and `presentation.xml.rels` for the carried part set; each `slideN.xml.rels` targets a real carried layout | " |
| 2.6 | **Drop our hardcoded `<a:rPr sz b>` and `<a:pPr algn>` in reference mode only** (L3) — emitting both keeps our look while appearing to honour the template. Non-template path byte-identical (L6) | " |
| 2.7 | Error, writing nothing, if the template is unreadable, not a PPTX, or has no master — naming which (L2) | `pptx_template.ail` |
| 2.8 | Checkpoint: `--check`, `--test`, `--prove` | — |

**Done when**: generating under `pandoc_basic.pptx` yields a deck whose theme,
masters and layouts are the template's, at the template's 16:9, and whose text
renders in the template's fonts — the Spike 0 measurement, as a fixture.

## M3 — ODT headings name a style (default output; prerequisite)

Today `odt_generator.ail:71` emits `<text:h text:outline-level="N">` with no
`text:style-name`. Measured (design doc E1a): a template defining
`Heading_20_1` at 55pt red is **ignored** — LibreOffice falls back to its own
built-in heading. With the attribute added (E1b), the template's style applies.
Body paragraphs already carry `text:style-name="Standard"` and already bind.

This changes **default, no-template output**, so our own minimal `styles.xml`
(`odt_generator.ail:164`, one `Standard` style) must gain the heading styles in
the same milestone — otherwise every generated ODT names a style nothing
defines, which is lesson L2 reintroduced on the default path.

| Step | Detail | Files |
|---|---|---|
| 3.1 | `odfStyleDefs() -> [{name: string, xml: string}]` — `Standard`, `Heading_20_1..6`, `List_20_Bullet`, `List_20_Number`. Mirrors `docxStyleDefs()` (`docx_generator.ail:811`) so M2 can inject only the names a template lacks | `odt_generator.ail` |
| 3.2 | `odtMinimalStyles()` builds `<office:styles>` from `odfStyleDefs()` instead of the hardcoded single-style literal | " |
| 3.3 | `HeadingBlock` emits `text:style-name="Heading_20_${level}"`; clamp level to 1..6 so a level-7 heading names a style that exists | " |
| 3.4 | List items name `List_20_Bullet` / `List_20_Number` to match | " |
| 3.5 | Contract: `ensures` that every style name the body references appears in `odfStyleDefs()` — a property that is FALSE for the 1.3 bug if the clamp is dropped (rules: write contracts that can be false) | " |
| 3.6 | Checkpoint: `./bin/docparse --check`, `--test` | — |

**Done when**: a generated ODT names `Heading_20_N` on every heading, our
`styles.xml` defines every name the body references, and
`soffice --convert-to html` shows the heading rendering differently from body
text. Office suite back to 100% with only genuinely-changed goldens touched.

**Risk**: golden churn. ODT goldens are parse-side, and the parser reads
`text:h` by outline level, not style name — so the churn should be **zero**.
If any ODT golden moves, that is a finding about the parser, not a rubber-stamp.

## M4 — ODT `--reference-doc`

ODF puts styles and the master page in one part, so the DOCX `<w:sectPr>` lift
has no equivalent — carrying `styles.xml` brings page geometry, headers and
footers with it. This is the half that makes ODT genuinely easier than DOCX.

| Step | Detail | Files |
|---|---|---|
| 4.1 | `odf_template.ail`: `OdfRefDoc { active, entries, stylesXml, headingIds, listIds }` + `odfTplNone()`. One value type, both paths (L5) | new |
| 4.2 | `odfTplLoad(path) ! {FS}` — read the ODT, carry `styles.xml` verbatim, carry `Pictures/*` and `Configurations2/*`, keep `mimetype` first and STORED | " |
| 4.3 | Heading id resolution **read from the template** (L4): match `style:family="paragraph"` on `style:name`, then `style:display-name`, then `style:default-outline-level`. Never assume `Heading_20_N` exists | " |
| 4.4 | Error, writing nothing, if the template is unreadable, is not an ODF package, or resolves no level-1 heading style — naming which (L2) | " |
| 4.5 | Generator: under a template, emit the resolved ids and inject only the `odfStyleDefs()` names the template does not already define | `odt_generator.ail` |
| 4.6 | CLI: `--reference-doc` accepted for `.odt` output; reference/output format mismatch is an error naming both | `bin/docparse`, `main.ail` |
| 4.7 | `--table-style` / `--reference-section` with `.odt` output error explicitly as DOCX-only | " |
| 4.8 | Checkpoint: `--check`, `--test`, `--prove` | — |

**Done when**: generating under an ODT whose `Heading_20_1` is 55pt red
produces a document that renders 55pt red (the E1b measurement, as a fixture),
and a template with no heading styles is refused with nothing written.

## M5 — HTML `--reference-doc`

`html_generator.ail:38` is one hardcoded `<style>` literal. Replacing it is the
cheapest item in the design doc.

| Step | Detail | Files |
|---|---|---|
| 5.1 | `.css` reference → its contents replace the built-in stylesheet | `html_generator.ail`, `main.ail` |
| 5.2 | `.html` reference → our body is spliced at a documented marker; absent marker is an error naming it (L2 — silently appending would look like success) | " |
| 5.3 | Document the class contract (`section-slide`, `section-header`, `merged`, `level-N`, `ins`/`del`) — it is what a house stylesheet writes against | `docs/` |
| 5.4 | Checkpoint: `--check`, `--test` | — |

**Done when**: a CSS reference fully replaces the built-in styles, an HTML
reference without the marker is refused, and the class names are documented.

## M6 — Verification, and the render gate

The blind spot this sprint must not fall into (rules: "anything generated needs
its structure read BACK"): styling adds a variant where the output is
structurally perfect and ignores the template entirely — E1a **is** that
document. So the assertions check **binding**, and one checks **rendering**.

| Step | Detail | Files |
|---|---|---|
| 6.1 | `L7 RefOdtDefault` — every `text:style-name` in a no-template ODT is defined in its own `styles.xml`. This is M1's regression guard | `verify_generated.py` |
| 6.2 | `L7 RefOdt` — generate under the E1 template; assert headings name the template's id AND `soffice --convert-to html` shows its font-size | " |
| 6.3 | `L7 RefMismatch` — wrong-format, unreadable, and heading-less references each exit non-zero and write nothing | " |
| 6.4 | `L7 SlideSize` — default 16:9, `--slide-size 4:3` exact, bad value refused | " |
| 6.5 | Commit the E1 template as a fixture (`data/test_files/odt-styled-template.odt`) rather than synthesizing per run — no in-repo ODT has real heading styles except `officeparser.odt` | `data/test_files/` |
| 6.6 | CI: add LibreOffice to the benchmark job **in this commit**, not after the first red run (the poppler lesson: the one thing no other job covers is the one CI has never installed) | `.github/workflows/` |
| 6.7 | All four suites: office 100%, roundtrip, verify_generated, failure_check | — |

**Done when**: all four suites green, the render assertion actually fails if the
`text:style-name` from M1.3 is reverted (verified by reverting it once), and CI
installs LibreOffice.

## Deferred, with reasons

- **PPTX placeholder binding** (rank 6) — its own sprint; rebases every PPTX
  golden. Sprint 1 of that work is the prerequisite for real templating.
- **ODP** (rank 7) — needs both halves; no cheap tier (`odp_generator.ail:170`
  is absolute-positioned frames with no `presentation:class`).
- **XLSX / ODS** (ranks 8–9) — ruled out in the design doc. Their cells carry no
  style names, so a template moves the default font or nothing at all.
- **MCP / WASM surfaces** — inherited gap, owned by
  `v0_40_0_convert_reference_doc_api.md`.

## Estimates

Velocity basis: the v0.39.0 `--reference-doc` sprint was 1 088 insertions across
5 files in `docparse/`; the last 14 days ran 42 commits / 8 664 insertions.

| Milestone | Impl LOC | Test/bench LOC |
|---|---|---|
| M1 PPTX slide size | 40 | 20 |
| M2 PPTX reference-doc (theme tier) | 380 | 60 |
| M3 ODT heading binding | 70 | 30 |
| M4 ODT reference-doc | 300 | 60 |
| M5 HTML reference-doc | 110 | 30 |
| M6 verification + CI | 20 | 280 |
| **Total** | **920** | **480** |

~1 400 LOC. Larger than the v0.39.0 sprint (1 088), because Spike 0 passing
pulled the PPTX theme tier back in. **5–6 days.** Risk: **low-to-medium** —
every milestone has a measured basis, and the only residual uncertainty is
PowerPoint, guarded by M6's render assertion.
