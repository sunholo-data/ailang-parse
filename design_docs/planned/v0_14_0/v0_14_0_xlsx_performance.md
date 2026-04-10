# XLSX Parser Performance — Design Doc

**Status:** Planned  
**Version:** v0.14.0  
**Date:** 2026-04-10  
**Author:** Claude Code + Mark  

## Problem

The XLSX parser is the performance bottleneck for large spreadsheets:

| File | Size | Rows | Cells | Time |
|------|------|------|-------|------|
| poi_many_merges.xlsx | 829KB | 50,000 | 140,000 | **5.27s** |
| xlsx_usda_food_atlas.xlsx | 8.7MB | ~10,000 | ~400,000+ (11 sheets) | **>20s** |
| docx_10mb.docx (for comparison) | 10MB | — | — | 0.47s |
| pptx_generated_20mb.pptx | 11MB | — | — | 0.78s |

DOCX and PPTX parse 10-20x faster despite similar file sizes. The XLSX parser is 10-50x slower than competitors on the same files (Kreuzberg: 82ms, Pandoc: 1.68s for poi_many_merges.xlsx).

## Root Cause Analysis

CPU profile of `poi_many_merges.xlsx` (5.45s total):

| Function | Flat | Cum | Analysis |
|----------|------|-----|----------|
| `runtime.madvise` | 51.2% | 51.2% | Memory pressure — GC thrashing from excessive allocations |
| `memclrNoHeapPointers` | 17.1% | 17.1% | Zeroing new allocations |
| `FallbackResolver.ResolveValue` | 11.5% | 14.8% | Per-cell function dispatch overhead |
| `Environment.Clone` | 0.2% | 13.9% | Cloning environment per function call (lambda in map) |
| `listMapImpl` | — | 13.1% | List map creating new list node per cell |
| `mallocgc` | 0.4% | 21.7% | Total allocation pressure |

**The problem is not parsing — it's the functional data structures.** Each cell goes through:
1. `map(\cell. parseXlsxCell(...), cells)` — allocates a closure + environment clone per cell
2. `parseXlsxCell` — allocates 3-5 temporary values (option wrapping, string copies)
3. `flatMap` over rows — re-allocates the entire row list
4. Result: 140,000 cells x ~10 allocations = ~1.4M allocations → GC dominates

### poi_many_merges.xlsx specifics
- 50,000 rows x 3 cells = 140,000 cells
- 50,000 merge ranges (each checked per cell)
- Parser correctly caps at 5,000 rows via `parseElements(xml, "row", 5000)`, BUT:
  - `loadSharedStrings` processes ALL strings (up to 100K cap)
  - `parseElements` still parses the XML to find the first 5,000 `<row>` elements

### xlsx_usda_food_atlas.xlsx specifics
- 11 sheets, largest has 3,146 rows x 68 columns = 213,861 cells
- Shared strings table is likely very large (all text cells)
- Total across all sheets: ~400K+ cells

## Proposed Solutions

### P0: Reduce allocation pressure in cell parsing

**Approach:** Replace `map(\cell. parseXlsxCell(...), cells)` with `parseFold` or a purpose-built fold that builds the result list without per-cell closures.

```ailang
-- Current: allocates closure + env clone per cell
pure func parseXlsxCells(cells, ss) = map(\cell. parseXlsxCell(cell, ss), cells)

-- Proposed: use parseFold to stream cells without intermediate list
-- (Requires AILANG stdlib support for fold-based cell parsing)
```

**Expected impact:** ~30-40% reduction. Eliminates `Environment.Clone` (13.9% cum) and reduces `listMapImpl` allocations.

**Blocked by:** AILANG runtime — `map` with closures is the idiomatic pattern. This needs either:
- A `parseFold` variant that operates on child elements directly
- Or an AILANG runtime optimisation for known-pure map closures (avoid env clone)

### P1: Stream rows instead of collecting

**Approach:** Use `parseFold` at the row level to build the table block incrementally instead of collecting all rows then building.

```ailang
-- Current: parseElements returns [XmlNode], then map over all rows
let parsedRows = match parseElements(xml, "row", 5000) {
  Ok(rowNodes) => parseXlsxRows(rowNodes, sharedStrings),
  ...
}

-- Proposed: fold directly from XML stream to table rows
let parsedRows = match parseFold(xml, "row", 5000, [], \acc, rowNode.
  let cells = parseXlsxRow(rowNode, sharedStrings) in
  if listLength(cells) > 0 then cells :: acc else acc
) { ... }
```

**Expected impact:** ~10-20% reduction. Avoids holding all row XmlNodes in memory simultaneously.

### P2: Cap shared strings more aggressively

**Current:** 100K string cap. For files like USDA food atlas with 200K+ unique strings, this still processes 100K strings into a `Map[int, string]`.

**Proposed:** 
- Reduce cap to 50K (still covers 99% of business spreadsheets)
- Or use lazy loading: only resolve shared strings when cells reference them
- Or use `parseFold` with early termination when cap is reached (current `scanFold` already does this)

**Expected impact:** Small for most files. Significant for USDA-type files with huge string tables.

### P3: Report to AILANG core — runtime optimisations

These are AILANG runtime issues, not parser bugs:

1. **`Environment.Clone` in pure map:** Pure functions should not need environment cloning. Report as optimisation opportunity.
2. **`FallbackResolver` overhead:** 11.5% flat time in value resolution suggests the resolver is doing unnecessary work for simple variable lookups.
3. **Map allocation:** `listMapImpl` could reuse list nodes for in-place transformation of pure maps.

**Action:** File via `ailang messages send ailang-core` with profiling data.

## Comparison with competitors

| Tool | poi_many_merges.xlsx | Approach |
|------|---------------------|----------|
| Kreuzberg | 82ms | Rust, zero-copy parsing |
| MarkItDown | 1.07s | Python openpyxl, lazy row iterator |
| Pandoc | 1.68s | Haskell, streaming |
| Unstructured | 1.57s | Python, partition_xlsx |
| Docling | 3.54s | Python, full DOM |
| **AILANG Parse** | **5.50s** | AILANG, functional + parseFold (blocked by XML scan cost) |

The gap is architectural: competitors use mutable iterators or streaming. AILANG's immutable functional style creates allocation pressure at scale.

## Success Criteria

- poi_many_merges.xlsx (829KB, 50K rows): < 2.0s (from 5.27s)
- xlsx_usda_food_atlas.xlsx (8.7MB, 11 sheets): < 10s (from >20s)
- No regression on standard XLSX benchmarks (currently 100%)
- No quality regression (merged cells, formulas, shared strings still correct)

## Implementation Order

1. P3 first — report to AILANG core (no code changes in docparse)
2. P1 — stream rows with parseFold (low risk, moderate impact)
3. P0 — reduce cell allocation (highest impact, needs AILANG stdlib support)
4. P2 — tune shared string cap (marginal gains)

## Implementation Progress (2026-04-10)

### Done

1. **P3: Reported to AILANG core** — GitHub issues #154 (runtime optimisations: Environment.Clone, FallbackResolver, listMapImpl) and #155 (parseFold early termination)
2. **P2: Reduced shared string cap** — 100K → 50K. Minimal impact on poi_many_merges (no shared strings in that file).
3. **P1: Switched to parseFold for rows** — Replaced `parseElements(xml, "row", 5000)` + `parseXlsxRows` with `parseFold(xml, "row", init, xlsxFoldRow)`. Avoids materializing all row XmlNodes in memory. Named fold function carries `sharedStrings` in accumulator to avoid closure capture.
4. **P0: Replaced map+lambda with direct recursion for cells** — `parseXlsxCells` now uses pattern-match recursion instead of `map(\cell. parseXlsxCell(cell, ss), cells)`. `parseXlsxRows` similarly replaced `flatMap` with recursion.

### Results

| Change | poi_many_merges.xlsx | Impact |
|--------|---------------------|--------|
| Baseline (v0.13.x) | 5.27s | — |
| + parseFold rows + 50K cap + recursion | 5.50s | **No measurable improvement** |

### Root Cause Refined

The recursion/fold changes didn't help because **the bottleneck is XML scanning, not cell processing**:

- `poi_many_merges.xlsx` has a single sheet with 7.1MB of uncompressed XML (50K rows + 50K merge ranges)
- `parseFold` must scan the entire 7.1MB to find `<row>` tags, even though the fold function stops accumulating after 5K rows
- The XML tokenizer itself is where GC pressure comes from (string allocations during XML token parsing), not from our fold/map functions
- Direct recursion vs `map+lambda` makes no difference because `Environment.Clone` happens in all function calls, not just closures

### What's needed from AILANG core

1. **`parseFoldLimit(xml, tag, maxElements, init, f)`** — stop XML scanning after N matches (GitHub #155). Would cut poi_many_merges from scanning 50K rows to 5K rows → ~10x less XML work.
2. **Runtime: eliminate `Environment.Clone` for pure functions** (GitHub #154). 13.9% cumulative CPU.
3. **Runtime: optimize `FallbackResolver`** (GitHub #154). 11.5% flat CPU on simple variable lookups.

Without these AILANG core changes, XLSX performance on large files cannot improve significantly at the parser level.

## Open Questions

- Should we add an XLSX-specific benchmark suite (separate from office structural)?
- Should large XLSX files (>5MB) emit a warning suggesting CSV format for better performance?
