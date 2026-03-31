# Large File Performance — XLSX & PPTX (Confirmed)

**Status:** Planned
**Priority:** P2 (not launch-blocking, but impacts pricing claims)
**Date:** 2026-03-31

## Context

Stress testing with real-world files revealed that DOCX parsing scales well (10 MB in 1.7s, 21 MB in 5s), but XLSX parsing has serious performance and memory issues. PPTX has architectural risks at scale due to recursive slide processing.

### Test Results

| File | Size | Format | Time | Memory | Status |
|------|------|--------|------|--------|--------|
| docx_10mb.docx (TestFileHub) | 9.7 MB | DOCX | 1.7s | Normal | OK |
| docx_20mb.docx (TestFileHub) | 21 MB | DOCX | 5.1s | Normal | OK |
| xlsx_usda_food_atlas.xlsx (USDA) | 8.7 MB | XLSX | 4–7 min | 1.1 GB | Problem |
| poi_many_merges.xlsx | 829 KB | XLSX | OK | OK | OK |
| pptx_generated_20mb.pptx | 10.8 MB | PPTX | 1m 42s | High | Slow |
| pptx_generated_50mb.pptx | 50.1 MB | PPTX | Killed (lagging hard) | Very high | Problem |

The XLSX parser consumed 1.1 GB of RAM during testing, requiring manual `kill`. The PPTX parser completed 60 slides (10.8 MB) in 1m42s but had to be killed on 200 slides (50 MB) due to severe system lag — confirming the recursive slide loading and image extraction issues are real, not theoretical.

## Problem 1: XLSX Shared Strings (Parser)

**File:** `docparse/services/xlsx_parser.ail`, line 49–58

The shared strings table (`xl/sharedStrings.xml`) is loaded entirely into memory via `parse(xml)` before any row processing begins. For the 8.7 MB USDA file, the shared strings XML alone decompresses to ~100 MB+ of XML, all parsed into an in-memory DOM tree, then converted to a `[string]` array.

```ailang
func loadSharedStrings(filepath: string) -> [string] ! {FS} {
  let xml = readZipEntry(filepath, "xl/sharedStrings.xml");  -- entire XML in memory
  if length(xml) == 0 then []
  else match parse(xml) {                                     -- full DOM parse
    Ok(root) => {
      let items = findAll(root, "si");                        -- walk entire tree
      extractSharedStrings(items)                             -- build [string] array
    },
    Err(_) => []
  }
}
```

**Impact:** Memory scales linearly with unique string count. A typical 8 MB XLSX has 50K–200K shared strings.

### Fix Options

1. **Use `parseElements` for streaming** — same approach used for rows (line 126). Parse `<si>` elements one at a time instead of the full DOM:
   ```ailang
   let items = parseElements(xml, "si", 500000);  -- streaming, bounded
   ```

2. **Lazy shared string resolution** — only parse shared strings referenced by cells in the first 5000 rows (current cap). Requires two-pass or deferred lookup.

3. **AILANG stdlib enhancement** — request a SAX-style `parseStream` that yields elements without building a full tree.

## Problem 2: XLSX Row Cap (Parser)

**File:** `docparse/services/xlsx_parser.ail`, line 126

```ailang
let parsedRows = match parseElements(xml, "row", 5000) {
```

Sheets are silently truncated at 5000 rows. The USDA Food Atlas has sheets with 3,000+ rows of county-level data across 12+ sheets. No warning is emitted when truncation occurs.

### Fix Options

1. **Increase cap** to 50,000 or 100,000 (requires Go codegen bug to be fixed first — see line 182 comment)
2. **Emit a warning block** when truncation occurs so the user knows data was cut
3. **Make configurable** — accept a `max_rows` parameter

## Problem 3: XLSX String Index Lookup (Generator)

**File:** `docparse/services/xlsx_generator.ail`

The generator uses `xlsxStringIndex()` which does a linear O(n) search through the entire string array for every cell. For a document with 100K cells and 50K unique strings, this is ~5 billion string comparisons.

### Fix Options

1. **Use a hashmap** for string-to-index lookup (O(1) per cell) — requires AILANG stdlib `std/map`
2. **Build index during collection** — `xlsxCollectAllStrings()` already walks all cells; build the index at the same time

## Problem 4: PPTX Recursive Slide Loading

**File:** `docparse/services/pptx_parser.ail`, line 70–84

```ailang
func parseSlides(filepath: string, entries: [string]) -> [Block] ! {FS} =
  match entries {
    [] => [],
    entry :: rest => {
      let xml = readZipEntry(filepath, entry);       -- full slide XML in memory
      let blocks = parseSlideXml(xml);
      let moreBlocks = parseSlides(filepath, rest);  -- recursive, all slides in memory
      ...
    }
  }
```

Each slide's full XML is loaded and parsed recursively. For a 200-slide deck with embedded images, all slide DOMs accumulate on the stack before any are returned.

**Confirmed:** 10.8 MB / 60 slides took 1m42s. 50 MB / 200 slides had to be killed — caused severe system lag. This is not theoretical; the recursive accumulation of slide DOMs and image data is a real problem above ~20 MB / ~80 slides.

### Fix Options

1. **Tail-recursive with accumulator** — process slides iteratively, freeing each slide's DOM after extracting blocks
2. **Bounded slide count** — add a configurable cap (e.g., 500 slides) with warning

## Problem 5: PPTX Image Extraction

**File:** `docparse/services/pptx_parser.ail`, line 287–297

```ailang
func extractPptxImages(filepath: string, entries: [string]) -> [Block] ! {FS} =
  match entries {
    [] => [],
    entry :: rest => {
      let imageData = readImageEntry(filepath, entry);  -- base64 image in memory
      ...
    }
  }
```

All images are read into memory as base64. A 50 MB PPTX that's 80% images would load ~40 MB of base64 data (~53 MB after encoding).

### Fix Options

1. **Lazy image loading** — return image references (paths) instead of data; load on demand
2. **Skip images by default** — only load when `describe` arg is passed (already partially done for AI descriptions)

## Priority Order

| # | Fix | Impact | Effort | Blocked? |
|---|-----|--------|--------|----------|
| 1 | XLSX shared strings streaming | High (fixes OOM) | Medium | No |
| 2 | PPTX lazy image loading | **High (confirmed OOM)** | Medium | No |
| 3 | PPTX tail-recursive slides | **High (confirmed)** | Low | No |
| 4 | XLSX truncation warning | Low (UX) | Low | No |
| 5 | XLSX generator hashmap | Medium (generator perf) | Medium | Needs std/map |
| 6 | XLSX row cap increase | Medium | Low | Go codegen bug |

## Recommendation

**For launch:** DOCX is the hero format and performs well at all tier sizes. XLSX and PPTX work fine for typical files (<1 MB). Document the known limitations:

- XLSX: best for spreadsheets under 5 MB / 50K rows. Large datasets may be slow.
- PPTX: works well for decks up to ~100 slides.

**Post-launch (P2):** Fix #1 (XLSX shared strings streaming) and Fix #2+#3 (PPTX image/slide loading) are both confirmed blockers for large file support. Fixing these would allow raising the Business tier file size limit above 50 MB.

## Test Files

Downloaded to `data/test_files/stress/` (gitignored, fetch on demand):

| File | Size | Source | Purpose |
|------|------|--------|---------|
| docx_10mb.docx | 9.7 MB | TestFileHub GitHub | Free tier validation |
| xlsx_usda_food_atlas.xlsx | 8.7 MB | USDA ERS | XLSX stress test |
| poi_many_merges.xlsx | 829 KB | POI test suite | Merged cell regression |
| pptx_generated_20mb.pptx | 10.8 MB | Generated (python-pptx) | PPTX stress test |
| pptx_generated_50mb.pptx | 50.1 MB | Generated (python-pptx) | PPTX OOM confirmation |

Larger files available from TestFileHub (20 MB, 50 MB DOCX) and World Bank WDI (78 MB XLSX zip).
PPTX files generated locally with `python-pptx` + `Pillow` (60/200 slides, 2 JPEG images per slide).
