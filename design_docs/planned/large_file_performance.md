# Large File Performance — XLSX, PPTX, DOCX

**Status:** Mostly resolved (2026-04-01)
**Priority:** P3 — remaining work is edge-case optimization
**Date:** 2026-03-31, updated 2026-04-01

## Summary

All three Office formats now handle files within their pricing tier limits. The key remaining limitation is extreme XLSX files (200K+ unique strings) which hit the 100K shared string cap.

## Current Performance

| File | Size | Format | Time | Status |
|------|------|--------|------|--------|
| docx_10mb.docx | 9.7 MB | DOCX | 11.6s | OK |
| poi_many_merges.xlsx | 829 KB | XLSX | <5s | OK |
| pandoc_basic.xlsx | 13 KB | XLSX | <4s | OK |
| pptx_generated_20mb.pptx | 10.8 MB | PPTX | 23s | OK |
| xlsx_usda_food_atlas.xlsx | 8.7 MB | XLSX | ~1:30 | OK (100K string cap, warning emitted) |

## Fixes Applied

### 2026-03-31 — PPTX and XLSX initial fixes
- **PPTX:** Conditional image extraction (skip eager base64 when AI disabled) + 500-slide cap
  - 50 MB / 200 slides: SIGKILL → 9.4s
  - 11 MB / 60 slides: 1m42s → 23s (4.4x faster)
- **XLSX:** `parseElements` streaming for shared strings, `Array[string]` with O(1) lookup, 100K cap with warning

### 2026-04-01 — std/map, parseFold, scanFold integration
- **XLSX parser:** `scanFold` for shared strings (zero-copy ZIP→XML streaming, no 100 MB string materialization), `Map[int, string]` for O(1) cell resolution, `mapFromList` for bulk map construction
- **XLSX generator:** `Map[string, int]` for O(1) string-to-index lookup (was O(n²) linear scan)
- **Browser adapter:** Updated to use `Map[int, string]` for shared strings

### Current caps

| Limit | Value | Rationale |
|-------|-------|-----------|
| Shared strings (XLSX) | 100K | Bounds memory for string table. 99%+ of business spreadsheets have <10K |
| Rows per sheet (XLSX) | 5K | `parseElements` early termination bounds per-sheet parse time |
| Slides (PPTX) | 500 | Bounds slide processing time |
| File size | Tier-based (10/50/200 MB) | API-level guard |

## Architecture Decisions

### Why hybrid streaming (scanFold for strings, parseElements for rows)

- **Shared strings:** Must process ALL strings (or up to cap) — `scanFold` is ideal because it streams from ZIP without materializing the XML string (~100 MB for large files)
- **Worksheet rows:** Only need first 5K — `parseElements` is better because it has early termination at `maxResults`, so it stops parsing XML after 5K `<row>` elements. `scanFold` must scan the entire XML stream even when capped.

### Why not higher row caps

Tested 10K and 50K row caps on the USDA file:
- 5K rows: ~1:30
- 10K rows: 24 min
- 50K rows: 46 min

The scaling is non-linear because `parseElements` still processes all XML up to the cap, and more rows means more cell resolution against the shared strings map. The 5K cap is the sweet spot.

### Why not full scanFold for everything

Tested full `scanFold` for both shared strings AND worksheet rows. Problems:
- `scanFold` can't stop early — must scan entire XML stream per entry
- For worksheets with >5K rows, `parseElements` + early termination is faster
- Full scanFold approach took 8+ minutes vs 1:30 with hybrid

## Remaining Opportunities (P3)

1. **`scanFoldUntil`** — AILANG feature request for early-termination fold. Would allow higher caps without penalty.
2. **Configurable caps** — Env vars (`DOCPARSE_MAX_ROWS`, `DOCPARSE_MAX_STRINGS`) for power users. Not implemented; tier-based file size limits are the primary control.
3. **Two-pass loading** — Scan cells first, only load referenced shared strings. Feasible now with `std/map`. Worth it if customer demand warrants.
4. **Row truncation warning** — Emit warning block when 5K row cap is hit (shared string truncation warning already implemented).

## Test Files

In `data/test_files/stress/` (gitignored):

| File | Size | Source |
|------|------|--------|
| docx_10mb.docx | 9.7 MB | TestFileHub GitHub |
| xlsx_usda_food_atlas.xlsx | 8.7 MB | USDA ERS |
| poi_many_merges.xlsx | 829 KB | POI test suite |
| pptx_generated_20mb.pptx | 10.8 MB | Generated (python-pptx) |

See [xlsx_deep_performance.md](xlsx_deep_performance.md) for detailed XLSX analysis and benchmark data.
