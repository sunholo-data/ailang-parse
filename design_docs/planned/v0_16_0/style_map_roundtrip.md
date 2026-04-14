# StyleMap — Presentation Preservation for Round-Trip Editing

**Status**: Planned (v0.16.0 or later)
**Author**: design sketch, 2026-04-14
**Depends on**: v0.15.0 LaTeX parser shipped; v0.6.0 generators stable

## Problem

Today AILANG Parse deliberately extracts **semantic structure only**. The Block
ADT ([docparse/types/document.ail:22-30](../../../docparse/types/document.ail#L22-L30))
captures 9 variants — heading, text, table, list, image, section, change,
comment, (bibitem via style) — and drops everything presentational: fonts,
colors, margins, slide masters, cell formatting, CSS, LaTeX spacing and
alignment commands.

This is **correct for the current consumer base** (RAG pipelines, LLM document
generation, structural benchmarks) and is the competitive wedge versus
OCR-based parsers. But it means we cannot support one class of workflow:

> *Parse a document, edit one paragraph, regenerate a document that still
> looks like it came out of the original template.*

Consequence: generators currently emit AILANG's own default styling. A parsed
DOCX re-exported as DOCX loses the user's corporate template; a parsed PPTX
re-exported loses slide masters and theme; a parsed HTML loses the site's CSS.
For one-off RAG extraction this is fine. For "document editing as a service"
it's a dealbreaker.

## Non-problem

This is **not** about polluting the Block ADT with presentation fields.
Colors, fonts, CSS classes, and XML attributes do not belong on semantic
blocks — the current design is right for its consumers, and we should not
regress it.

## Proposal

Add an optional **StyleMap sidecar** to the `ParsedDocument`: a
format-specific, opaque bag of presentation metadata, separate from blocks.

### Shape

```ailang
type StyleMap = {
  format: string,            -- "docx" | "pptx" | "xlsx" | "html" | "tex" | ...
  artifacts: [StyleArtifact] -- opaque format-specific payloads
}

type StyleArtifact = {
  key: string,     -- e.g. "styles.xml", "theme1.xml", "preamble", "site.css"
  kind: string,    -- "xml" | "css" | "tex" | "opaque-bytes"
  content: string  -- raw source, passed through as-is
}

type ParsedDocument = {
  blocks: [Block],
  metadata: Metadata,
  style_map: Option[StyleMap]  -- NEW, optional
}
```

Blocks themselves stay unchanged. Presentation is **not** indexed by block id;
it's attached at the document level. A generator that receives a
`ParsedDocument` with `style_map: Some(…)` must either honor it or ignore it
— it is not load-bearing for correctness.

### What goes in each format's StyleMap

| Format | Artifacts captured |
|---|---|
| DOCX | `word/styles.xml`, `word/theme/theme1.xml`, `word/numbering.xml`, `word/settings.xml` |
| PPTX | `ppt/theme/theme*.xml`, `ppt/slideMasters/*.xml`, `ppt/slideLayouts/*.xml` |
| XLSX | `xl/styles.xml`, `xl/theme/theme*.xml` |
| ODT/ODP/ODS | `styles.xml` (top-level), `meta.xml` |
| HTML | inline `<style>` blocks, `<link rel="stylesheet">` refs, `class` attributes per block (indexed separately) |
| EPUB | per-chapter CSS, `META-INF/container.xml`, OPF manifest |
| LaTeX | preamble (everything before `\begin{document}`), `\newcommand` table, bibliography style |
| Markdown | N/A (markdown has no presentation layer worth preserving) |
| CSV | N/A |
| EML | N/A (HTML body already covered by HTML StyleMap pattern) |

For DOCX/PPTX/XLSX/ODT/ODP/ODS the artifacts are literally the XML files from
the zip container — we already decompress these in parsing, we just don't
currently surface them.

### Consumer model

Three tiers of consumer:

1. **RAG / semantic** — ignores `style_map` entirely. Zero behavior change
   versus today.
2. **Faithful regeneration** — passes `style_map` back to the generator.
   Generator rebuilds the document using original artifacts wherever
   possible, falling back to defaults for anything it can't map.
3. **Partial edit** — consumer mutates `blocks`, keeps `style_map` intact,
   regenerates. Template survives; content changes.

### Generator contract

Each generator declares which StyleMap artifacts it honors and which it
ignores. A v0.16.0 generator need not honor *everything* — the progression
can be:

- **v0.16.0**: DOCX + HTML round-trip (highest-value cases)
- **v0.17.0**: PPTX + ODT/ODP
- **v0.18.0**: XLSX (more complex; conditional formatting, formulas)
- **v0.19.0**: EPUB + LaTeX generator (LaTeX generator doesn't exist yet)

If an artifact is unsupported, the generator logs a warning and emits default
styling for that dimension. This is progressive; "partial round-trip" is
still better than "no round-trip."

## Why sidecar, not blocks-with-styles

Considered and rejected: adding `style: StyleRef` to every block.

- **Block ADT bloat**: every consumer now has to know about style refs, even
  if they don't care. Violates the current lean ADT principle.
- **Format coupling**: a `StyleRef` that means "this block uses `Heading2`
  from `styles.xml`" leaks DOCX-isms into the ADT. A `StyleRef` that is
  format-neutral ("emphasize, large, centered") throws away 95% of the
  fidelity that motivated the feature.
- **Serialization cost**: serializing blocks becomes 2-5× heavier for
  consumers who don't want it.

The sidecar model lets consumers opt into the weight.

## Impact on parsing pipeline

Low. Parsers already open and walk the zip containers (DOCX/PPTX/XLSX/ODT/
ODP/ODS/EPUB). Capturing the presentation XML is a matter of:

```
-- In docx_parser.ail after extracting document.xml
let stylesXml = readZipEntry(zip, "word/styles.xml") in
let themeXml = readZipEntry(zip, "word/theme/theme1.xml") in
…
-- Attach to ParsedDocument.style_map
```

Cost: ~10 extra lines per format parser, plus a shared `StyleMap` type in
`docparse/types/document.ail`.

**Important**: `style_map` is `Option[StyleMap]`, defaulting to `None`. Today's
consumers (including the CLI's JSON output, the WASM demo, every SDK) see no
change unless they explicitly opt in.

## Impact on generators

Bigger. Each generator that wants round-trip fidelity needs to:

1. Accept `StyleMap` as input (optional).
2. Write the XML artifacts back into the zip container (for Office/OpenDoc
   formats) or inject them into the output (for HTML/LaTeX).
3. Map blocks to the correct style references inside the preserved styles.

Step 3 is the hard part and is where the per-format complexity lives.

## Risks and open questions

- **Block → style mapping**: when regenerating, how does the generator know
  which `styles.xml` entry to use for a `HeadingBlock(level: 2)`? Option A:
  parsers record the original style name per block in a metadata field.
  Option B: generators pick a heuristic mapping (Heading1 → `Heading1` in
  StyleMap if present, else default). Both need design-time evaluation.

- **StyleMap size**: a DOCX `styles.xml` can be 50-500 KB. A DOCX with a
  complex corporate template plus theme is 1-3 MB of XML. SDKs will need to
  decide whether to transport this over the wire or cache it server-side.

- **Partial edits that touch headings**: if a user adds a new `HeadingBlock`
  not present in the original, the generator must map it to *some* style.
  Fallback heuristic (pick the nearest existing heading level) is probably
  good enough; needs user-testing.

- **Security**: arbitrary XML/CSS pass-through reopens some of the surface
  area deterministic parsing was designed to close. We should treat
  `StyleMap.artifacts[*].content` as untrusted for consumers. This is a
  documentation problem, not a code problem.

- **WASM**: a 3 MB StyleMap per document is fine in the browser if the user
  opts in, but should not be the default for the live demo. The current
  demo's block view is unaffected (it doesn't consume `style_map`).

## What this is not

- Not a CSS parser. We pass CSS through; we don't interpret it.
- Not a theme editor. Consumers change blocks; StyleMap is opaque.
- Not a competitive feature against Docling/LlamaParse/Unstructured. **None
  of them do this either** — they all convert *through* PDF, which destroys
  the source styling. This is a feature that unlocks a different product
  (edit-and-regenerate), not a better OCR score.

## Sequencing

1. **v0.15.0** (current): ship LaTeX parser, as already planned.
2. **v0.16.0**: introduce `StyleMap` type, capture artifacts in DOCX and HTML
   parsers, pass-through in DOCX and HTML generators. Demonstrate one-paragraph
   edit → regenerate with preserved template.
3. **v0.17.0**: PPTX + ODT/ODP.
4. **v0.18.0**: XLSX (harder — cell formatting, conditional formatting).
5. **v0.19.0**: EPUB, plus a LaTeX generator with preamble preservation.

Benchmark idea for v0.16.0: a new `roundtripbench/` — take 20 real-world
DOCX files (corporate templates, academic papers, government forms), parse
→ edit one paragraph → regenerate → diff against original. Success metric:
visual regression (pixel diff of rendered pages) below threshold. This is a
benchmark no competitor can run because no competitor preserves enough to
regenerate.

## Decision requested

Not asking for approval to build yet. Asking for:

1. Agreement that the sidecar-with-opaque-artifacts shape is the right
   architecture (versus Block-ADT pollution or a per-format ad-hoc hack).
2. Agreement that DOCX + HTML are the right starting points for v0.16.0.
3. Flagging of any users/customers who are already asking for round-trip;
   that would move this up the roadmap.

## References

- Block ADT: [docparse/types/document.ail](../../../docparse/types/document.ail)
- Current generator set: [docparse/services/](../../../docparse/services/)
  (`docx_generator.ail`, `pptx_generator.ail`, `xlsx_generator.ail`,
  `odt_generator.ail`, `odp_generator.ail`, `ods_generator.ail`,
  `html_generator.ail`, `qmd_generator.ail`, `ai_generator.ail`)
- v0.6.0 generation design:
  [design_docs/implemented/v0_6_0/v0_6_0_document_generation.md](../../implemented/v0_6_0/v0_6_0_document_generation.md)
- LaTeX parser (upstream for LaTeX StyleMap work):
  [design_docs/planned/v0_15_0/latex_parser.md](../v0_15_0/latex_parser.md)
