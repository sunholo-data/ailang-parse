# XLSX Deep Performance — Shared Strings & Large Spreadsheets

**Status:** Partially resolved (2026-04-01)
**Priority:** P2 — current caps handle 99%+ of business use cases
**Date:** 2026-03-31, updated 2026-04-01

## What Changed (2026-04-01)

`std/map`, `parseFold`, and `scanFold` all landed in the AILANG stdlib. Applied across 3 files:

### xlsx_parser.ail — Shared strings loading
- **Before:** `readZipEntry` → 100 MB XML string → `parseElements` → `[XmlNode]` → `Array[string]` → `arrayGetOpt` (O(1))
- **After:** `scanFold` streams directly from ZIP → accumulates `[(int, string)]` pairs → `mapFromList` → `Map[int, string]` → `mapLookup` (O(1))
- **Win:** No 100 MB XML string materialization. No intermediate `[XmlNode]` list. `scanFold` pipes `zip.Open()` directly into `xml.NewDecoder`.
- **Cap:** 100K shared strings (fold skips accumulation beyond cap, O(1) per skipped element)

### xlsx_parser.ail — Worksheet row parsing
- **Kept:** `readZipEntry` + `parseElements(xml, "row", 5000)` for worksheets
- **Why not scanFold:** `parseElements` has early termination at `maxResults` — it stops parsing XML after 5000 rows. `scanFold` must scan the entire XML stream even when capped. For sheets with >5000 rows, `parseElements` is significantly faster.

### xlsx_generator.ail — String index lookup
- **Before:** `xlsxStringIndex(strings, cell, 0)` — O(n) linear scan per cell, O(n²) total
- **After:** `mapFromList` builds `Map[string, int]` once, `mapLookup(stringIndex, cell)` — O(1) per cell
- **Win:** Generator scales linearly with cell count instead of quadratically

### docparse_browser.ail — Browser adapter
- Updated to build `Map[int, string]` from parsed shared strings list (matching new `parseSheetXml` signature)

## Benchmark Results

### USDA Food Atlas (8.7 MB, 200K+ shared strings, 12 sheets × 3000 rows)

| Approach | Time | Memory | Notes |
|----------|------|--------|-------|
| Original (Array + parseElements) | 7+ min | 1.1 GB → OOM killed | Crashed |
| parseFold + Map (--max-memory 512MB) | 17+ min | 590 MB | Completed but slow (aggressive GC) |
| scanFold + Map (no cap, no max-memory) | ~1:30 | ~4.7 GB peak | Fast but huge memory |
| scanFold + Map + 100K string cap | **~1:30** | **~1.5 GB peak** | Current approach |
| scanFold + 50K row cap (no string cap) | 46 min | High | Row cap too high |
| scanFold + 10K row cap (no string cap) | 24 min | High | Still too slow |

**Conclusion:** The 100K shared string cap is the key performance control, not the row cap. The USDA file's 200K+ strings are the bottleneck — the cap cuts processing in half and bounds memory.

### Normal files (<1 MB)
All XLSX benchmarks at 100% — no regressions. Small files complete in 3-4 seconds (dominated by AILANG compilation overhead).

## Current Limits

| Limit | Value | Rationale |
|-------|-------|-----------|
| Shared strings | 100K | Bounds memory for string table. 99%+ of business spreadsheets have <10K unique strings |
| Rows per sheet | 5K | `parseElements` early termination. Keeps per-sheet time bounded |
| Slides (PPTX) | 500 | Similar rationale |
| File size | Tier-based (10/50/200 MB) | API-level guard |

### What the caps cover
- **Typical business spreadsheet** (500-5K rows, <1K strings): Parses fully, seconds
- **Large business report** (10K-50K rows, 5K-20K strings): First 5K rows per sheet, all strings, <30s
- **Enterprise data export** (50K+ rows, 50K+ strings): First 5K rows, all strings up to 100K, warning if truncated
- **Extreme edge case** (USDA-level, 200K+ strings): 100K cap with warning, ~1:30

### Users hitting caps
- Truncation warning emitted as a `TextBlock` with `style: "warning"`
- Warning recommends CSV format for large datasets (CSV skips ZIP/XML/shared-strings overhead entirely)

## Remaining Opportunities

### Early termination for scanFold (AILANG feature request)
`scanFold` must scan the entire XML stream even when the fold function stops accumulating. An `scanFoldUntil` variant that accepts a predicate to stop scanning would:
- Allow higher row caps without performance penalty
- Reduce shared strings processing time when cap is hit (stop at 100K instead of scanning remaining 100K+)

### Configurable limits per context
Currently caps are hard-coded. Future options:
- **API:** Env var `DOCPARSE_MAX_ROWS=5000` read via Env effect
- **CLI:** Command-line arg `--max-rows 50000` for power users with local resources
- **WASM:** JS controls data passed to parser — no AILANG-side cap needed

Not implemented yet — tier-based file size limits are the primary resource control.

### Two-pass loading (Option B from original design)
With `std/map` now available, the two-pass approach is feasible:
1. Scan worksheet cells → collect referenced string indices
2. Stream shared strings → only load referenced ones

This would be the proper fix for extreme files but adds complexity. Worth revisiting if customer demand warrants it.

## Files

- `docparse/services/xlsx_parser.ail` — Parser (scanFold shared strings, parseElements rows)
- `docparse/services/xlsx_generator.ail` — Generator (Map-based string index)
- `docparse/services/docparse_browser.ail` — Browser adapter (Map-based shared strings)
