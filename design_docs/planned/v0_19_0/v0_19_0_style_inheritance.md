# Design Doc: DOCX Style Inheritance Chain Resolution (v0.19.0)

**Status**: Planned
**Date**: 2026-05-06
**Author**: Mark + Claude
**Source**: Gap analysis vs [stella/stella](https://github.com/stella/stella) (OSS AI legal workspace). Stella resolves `basedOn` style chains but uses a shallow spread that loses properties past 2 levels and doesn't cascade `w:tblPr` or `w:numPr` from styles. AILANG Parse goes further — it doesn't parse `word/styles.xml` at all, extracting only the style name string. Closing this gap is essential for legal documents, which rely on nested numbered styles (Article → Section → Clause) for structure.

---

## Problem

`docparse/services/docx_parser.ail` calls `extractParagraphStyle(p)` to get the style name string (`"Heading1"`, `"BodyText"`, `"ListNumber"`, etc.) but never opens `word/styles.xml`. This means:

1. **Numbering context is lost.** A paragraph with style `"ListNumber2"` has its list level and numbering definition (`w:numId`, `w:ilvl`) stored in the style, not the paragraph. Without resolving the style, the parser can't determine it's a list item — so it emits a `TextBlock` instead of a `ListBlock`. Legal contracts use 4–6 nested numbering levels (Article 1 → 1.1 → 1.1(a) → (i)); losing this collapses the entire clause hierarchy.

2. **Style inheritance is blind.** A paragraph using `"ContractBodyIndent"` (basedOn `"ContractBody"` basedOn `"Normal"`) has font, size, spacing, and run formatting set by ancestor styles. Without resolving the chain, `docparse` emits no formatting metadata. This doesn't break AI text extraction, but it breaks the `--convert` pipeline and any consumer trying to faithfully reconstruct structure.

3. **Table style inheritance is missing.** A table referencing `w:tblStyle="TableGrid"` inherits cell borders, padding, and conditional row/column formatting from the style. Without resolving it, table blocks carry no border or shading metadata — indistinguishable from a borderless table.

4. **`w:docDefaults` is never applied.** The document-wide default font and paragraph properties (baseline for all content) are ignored. This is usually benign but causes incorrect results when styles omit properties that are only set in docDefaults.

The root cause is simple: OOXML splits "what a paragraph looks like" across three layers (direct formatting → paragraph style → basedOn chain → docDefaults), and `docparse` currently only sees the top layer (direct formatting) plus the style name string.

This was confirmed as a gap in Stella too — their shallow `{ ...parent, ...child }` spread works for 1-level inheritance but silently drops properties in 3+ level chains when intermediate styles define partial overrides.

---

## Non-Goals

- Full CSS-style cascade for rendering. We resolve into a `StyleProps` record stored on each block; we do not produce a visual rendering.
- Conditional table formatting (`w:cnfStyle` flags for first/last row, banded columns). That is a rendering concern — we store the flags, not the computed visual output.
- Character styles applied mid-run (bold, italic, font). These are run-level properties already captured from `w:rPr`; this doc covers paragraph and table styles only.
- Custom XML schemas (`w:customXml`). Out of scope.
- Themes (`word/theme/theme1.xml`). Colour and font theme resolution is a rendering concern, not structural.
- Round-tripping style definitions through `--convert`. Style names are preserved in output; the resolved properties inform block metadata, not the style definition itself.

---

## Part 1: Parse `word/styles.xml` into a style map

### Data model

```ailang
type RunProps = {
  bold:         Option[bool],
  italic:       Option[bool],
  fontSize:     Option[int],    -- half-points (divide by 2 for pt)
  fontFace:     Option[string],
  color:        Option[string], -- hex RGB
  underline:    Option[bool],
  strikethrough:Option[bool],
}

type ParaProps = {
  alignment:    Option[string], -- "left" | "center" | "right" | "justify"
  indentLeft:   Option[int],    -- twentieths of a point
  indentRight:  Option[int],
  spaceBefore:  Option[int],
  spaceAfter:   Option[int],
  numId:        Option[int],    -- list numbering definition ID
  ilvl:         Option[int],    -- list indentation level (0-based)
  outlineLevel: Option[int],    -- 0-8, maps to heading hierarchy
}

type TblProps = {
  borderStyle:  Option[string],
  cellMargin:   Option[int],
  shading:      Option[string],
}

type StyleDef = {
  id:           string,         -- w:styleId
  name:         string,         -- w:name w:val (human-readable)
  kind:         string,         -- "paragraph" | "character" | "table" | "numbering"
  basedOn:      Option[string], -- parent styleId
  runProps:     RunProps,
  paraProps:    ParaProps,
  tblProps:     Option[TblProps],
}

type StyleMap = Map[string, StyleDef]
```

### Parsing algorithm

```
1. Open word/styles.xml from the zip
2. For each w:style element:
   a. Extract w:styleId, w:type, w:name
   b. Extract w:basedOn w:val (parent)
   c. Parse w:rPr into RunProps
   d. Parse w:pPr into ParaProps (including w:numPr → numId + ilvl)
   e. Parse w:tblPr into TblProps if kind == "table"
3. Also parse w:docDefaults → RunProps + ParaProps as the zero-level baseline
4. Return StyleMap
```

### Chain resolution

```
resolveStyle(styleId, styleMap, visited):
  if styleId in visited → error (cycle detected, return baseline)
  def = styleMap[styleId]
  if def.basedOn is None → merge(docDefaults, def)
  else → merge(resolveStyle(def.basedOn, styleMap, visited ∪ {styleId}), def)

merge(parent, child):
  -- field-level: child wins where set (Some), parent fills where child is None
  RunProps {
    bold:     child.runProps.bold ?? parent.runProps.bold,
    italic:   child.runProps.italic ?? parent.runProps.italic,
    ...
  }
  -- same for ParaProps, TblProps
```

This is a **field-level merge**, not a shallow record spread — the fix for Stella's exact bug where `{ ...parent, ...child }` drops any parent field that the child omits entirely vs. explicitly sets to None.

---

## Part 2: Enrich block metadata with resolved style props

### Current `TextBlock` shape

```ailang
TextBlock({text: string, style: string, level: int})
```

`style` is the raw style name; `level` is the heading level inferred by `headingLevelFromStyle`. No other style metadata surfaces.

### Target enrichment

Add an optional `props` field to carry resolved properties:

```ailang
type BlockProps = {
  runProps:  RunProps,
  paraProps: ParaProps,
}

TextBlock({text: string, style: string, level: int, props: Option[BlockProps]})
ListBlock({text: string, style: string, level: int, numId: int, ilvl: int, props: Option[BlockProps]})
```

`props` is `None` when styles.xml is absent (some minimal DOCX don't include it) or when the style is unknown. Consumers should treat `None` as "no additional metadata available" and continue working.

### List detection from style

Currently `docparse` detects list items only from inline `w:numPr` in the paragraph's `w:pPr`. After style resolution, a second path exists: if the resolved `ParaProps.numId` is set, the paragraph is a list item regardless of whether it has inline `w:numPr`. This closes the most impactful legal-document gap (contract article/section/clause numbering defined entirely via styles, not inline).

```
resolvedNumId = paragraph.inline_numPr ?? resolvedStyle.paraProps.numId
resolvedIlvl  = paragraph.inline_ilvl  ?? resolvedStyle.paraProps.ilvl ?? 0
if resolvedNumId is Some → emit ListBlock
else → emit TextBlock or HeadingBlock (unchanged)
```

---

## Part 3: Table style resolution

Currently `TableBlock` carries `headers`, `rows`, and `mergedCells` but no style metadata. After this doc:

1. When a table has `w:tblStyle`, resolve the style to `TblProps`.
2. Store resolved border style and cell margin on `TableBlock.props`.
3. `w:cnfStyle` flags (conditional formatting per row/cell) are stored as an opaque string on the cell — resolution into visual properties is out of scope (rendering concern).

---

## Part 4: `--styles` CLI flag for debug output

Expose the resolved style map for debugging complex documents:

```bash
./bin/docparse contract.docx --styles
# emits JSON style map with resolved (not raw) properties
# shows basedOn chain for each style
```

Useful when a consumer reports unexpected list detection or heading levels — lets them see exactly what the parser resolved.

---

## Implementation plan

| Step | File(s) | Effort |
|------|---------|--------|
| Add type definitions (`StyleDef`, `RunProps`, `ParaProps`, etc.) | `docparse/types/document.ail` | 0.5 day |
| Parse `word/styles.xml` + `w:docDefaults` into `StyleMap` | `docparse/services/docx_parser.ail` | 1.5 days |
| Field-level chain resolution with cycle detection | `docparse/services/docx_parser.ail` | 1 day |
| Enrich `TextBlock` / `ListBlock` with resolved `BlockProps` | `docparse/services/docx_parser.ail` | 0.5 day |
| List detection from resolved style `numPr` | `docparse/services/docx_parser.ail` | 0.5 day |
| Table style resolution → `TableBlock.props` | `docparse/services/docx_parser.ail` | 0.5 day |
| `--styles` debug flag | `docparse/services/output_formatter.ail` + `docparse/main.ail` | 0.5 day |
| Golden tests (legal contract with 4-level numbering) | `benchmarks/office/golden/` + new test DOCX | 1 day |
| **Total** | | **~6 days** |

---

## Test corpus

- `data/test_files/style_chain_deep.docx` — styles with 4-level basedOn chain; assert correct font/indent at each level
- `data/test_files/style_list_from_style.docx` — list numbering defined only in style (no inline `w:numPr`); assert `ListBlock` emitted correctly
- `data/test_files/legal_contract_numbered.docx` — real contract with Article/Section/Clause hierarchy; assert 4 list levels with correct `numId`/`ilvl`
- `data/test_files/style_cycle.docx` — artificial cycle in basedOn; assert no crash, baseline applied
- `data/test_files/style_minimal.docx` — no `word/styles.xml`; assert graceful degrade, blocks have `props: None`
- Golden: `benchmarks/office/golden/style_chain_deep.json`, `benchmarks/office/golden/legal_contract_numbered.json`

---

## Acceptance criteria

- [ ] `word/styles.xml` is parsed for all DOCX inputs (graceful degrade if absent).
- [ ] `basedOn` chains resolved field-by-field (not shallow spread); 4-level chain produces correct props at each level.
- [ ] Cycle in `basedOn` does not crash; falls back to `docDefaults`.
- [ ] List items whose `numPr` is defined only in the style (not inline) are emitted as `ListBlock`, not `TextBlock`.
- [ ] Legal contract with Article/Section/Clause numbering produces `ListBlock` nodes with correct `ilvl` (0/1/2/3).
- [ ] `TableBlock.props` carries resolved border style and cell margin when `w:tblStyle` is set.
- [ ] `--styles` flag emits valid JSON with resolved (not raw) style properties.
- [ ] No regression on existing golden outputs (styles-unaware path preserved for docs without styles.xml).
- [ ] Type-check clean: `ailang check docparse/`.
