# XLSX Deep Performance Fix — Shared Strings & Large Spreadsheets

**Status:** Planned
**Priority:** P1 post-launch (blocks large XLSX support; DOCX and PPTX are fine)
**Date:** 2026-03-31
**Depends on:** Potentially `std/map` in AILANG stdlib, or AILANG core team help with streaming XML

## Context

The PPTX performance issue was fully resolved (50 MB in 9.4s) by skipping eager image extraction. XLSX remains broken for large files — an 8.7 MB XLSX (USDA Food Atlas) OOMs at ~2 GB RAM and gets SIGKILLed.

We already applied `parseElements` streaming for shared strings (replacing full DOM `parse()`), but it made only a marginal difference. The root problem is that ALL shared strings must be held in a `[string]` array for random-access cell resolution via `nth(sharedStrings, idx)`.

## The Real Problem: Random-Access String Table

XLSX stores text in a shared string table (`xl/sharedStrings.xml`) and cells reference strings by index:

```xml
<!-- xl/sharedStrings.xml (can be 100+ MB decompressed for an 8.7 MB file) -->
<sst count="200000">
  <si><t>County Name</t></si>     <!-- index 0 -->
  <si><t>Population</t></si>      <!-- index 1 -->
  <si><t>Adams County</t></si>    <!-- index 2 -->
  ...200,000 more...
</sst>
```

```xml
<!-- xl/worksheets/sheet1.xml -->
<row>
  <c r="A1" t="s"><v>0</v></c>   <!-- lookup sharedStrings[0] = "County Name" -->
  <c r="B1" t="s"><v>1</v></c>   <!-- lookup sharedStrings[1] = "Population" -->
</row>
```

Current parser flow:
1. `readZipEntry("xl/sharedStrings.xml")` → decompress entire XML to a string (~100 MB)
2. `parseElements(xml, "si", 500000)` → build [XmlNode] list of all `<si>` elements
3. `extractSharedStrings(items)` → map to `[string]` of 200K strings
4. For each cell: `nth(sharedStrings, idx)` → O(n) list traversal

**Memory at step 3:** ~100 MB decompressed XML + 200K XmlNode items + 200K output strings = ~1.5-2 GB.

Even if we stream the XML parsing, ALL 200K strings must live in memory simultaneously because cells reference them by arbitrary index. This is the fundamental constraint.

## Fix Options

### Option A: Cap Shared Strings + Truncation Warning (Quick Win)

Limit shared strings to 50,000. Cells referencing strings beyond the cap get empty text. Emit a warning block.

```ailang
func loadSharedStrings(filepath: string) -> [string] ! {FS} {
  let xml = readZipEntry(filepath, "xl/sharedStrings.xml");
  if length(xml) == 0 then []
  else match parseElements(xml, "si", 50000) {
    Ok(items) => extractSharedStrings(items),
    Err(_) => []
  }
}
```

**Pros:** 1-line change (500000 → 50000). Immediately bounds memory.
**Cons:** Lossy — cells referencing strings >50K get empty text. Most large spreadsheets have >50K unique strings, so data loss is likely. Not a real fix, just a safety valve.

### Option B: Two-Pass — Scan Cells First, Load Only Referenced Strings

Pass 1: Stream through worksheet XML, collect all shared string indices referenced by cells.
Pass 2: Stream through shared strings XML, only extract strings at referenced indices.

```ailang
-- Pass 1: collect referenced string indices from all sheets
func collectReferencedIndices(filepath: string, entries: [string]) -> [int] ! {FS}

-- Pass 2: load only the strings we need (skip the rest during streaming)
func loadReferencedStrings(filepath: string, indices: [int]) -> [string] ! {FS}
```

**Pros:** Only loads strings actually used. If sheets have 5000-row cap, only ~5000 × columns unique indices are needed.
**Cons:**
- Requires two ZIP reads (sheets then shared strings)
- Need sorted index list for efficient lookup during pass 2
- Still need random-access resolution — would need a sparse array or map
- **Blocked by:** No `std/map` (hashmap) in AILANG stdlib. Could use a sorted list + binary search, but AILANG doesn't have built-in binary search either.

### Option C: AILANG Stdlib Enhancement — `std/map` or `parseStream`

Request from AILANG core team:

1. **`std/map`** — A hashmap type would allow O(1) string lookups and enable lazy loading:
   ```ailang
   import std/map (empty, insert, lookup)
   -- Build map lazily during cell resolution, not upfront
   ```

2. **`parseStream` / SAX-style API** — Process XML elements one at a time without holding the full result in memory:
   ```ailang
   -- Process each <si> element with a callback, never holding all in memory
   parseStream(xml, "si", \si. extractSiText(si))
   ```

3. **`std/array`** — A random-access array type (vs linked list) would make `nth` O(1) instead of O(n), reducing the cost of the current approach even if all strings are in memory.

**Pros:** Proper fix that scales to any size.
**Cons:** Depends on AILANG core team. Timeline unknown.

### Option D: Hybrid — Cap + Stream with Warning (Best Pragmatic Fix)

Combine options:
1. Set shared strings cap at 100,000 (handles 95%+ of spreadsheets)
2. When cap is hit, emit a warning block: "Large spreadsheet truncated — N shared strings loaded of M total"
3. Apply the row cap warning too (existing 5000-row cap, currently silent)
4. Request `std/map` from AILANG core for the proper fix

```ailang
func loadSharedStrings(filepath: string) -> {strings: [string], truncated: bool, total: int} ! {FS} {
  let xml = readZipEntry(filepath, "xl/sharedStrings.xml");
  if length(xml) == 0 then {strings: [], truncated: false, total: 0}
  else match parseElements(xml, "si", 100000) {
    Ok(items) => {
      let strings = extractSharedStrings(items);
      let count = listLength(strings);
      -- If we got exactly 100000, there are probably more (truncated)
      {strings: strings, truncated: count == 100000, total: count}
    },
    Err(_) => {strings: [], truncated: false, total: 0}
  }
}
```

**Pros:** Bounded memory, transparent to user, works now, no stdlib changes needed.
**Cons:** May need record type changes to thread the truncation info through. More than a 1-line fix but still manageable (~20 lines).

## Recommendation

**Immediate (Option D):** Cap at 100K shared strings with truncation warning. This handles the USDA file (which has ~200K strings — we'd get the first 100K, covering most of the data). Bounds memory to ~500 MB worst case.

**Request from AILANG core (Option C):** File a feature request for `std/map` (hashmap) and `std/array` (random-access). These are general-purpose needs, not just for XLSX. A hashmap would unblock the proper lazy-loading fix AND the generator's O(n²) string index problem.

**Long-term (Option B + C):** Once `std/map` is available, implement two-pass loading with a hashmap for O(1) string resolution. This is the only approach that truly scales to arbitrarily large XLSX files.

## Related Issues

- **XLSX row cap (5000):** Silent truncation. Should emit warning block. Blocked by Go codegen bug for increasing the limit.
- **XLSX generator O(n²):** `xlsxStringIndex()` does linear search per cell. Blocked by `std/map`.
- **AILANG `readZipEntry`:** Decompresses entire entry to a string. For 100 MB+ entries, this alone is a problem. Would benefit from streaming ZIP entry reading in the stdlib.

## Files

- `docparse/services/xlsx_parser.ail` — Parser (shared strings loading, row parsing)
- `docparse/services/xlsx_generator.ail` — Generator (string index lookup)
- `docparse/services/zip_extract.ail` — ZIP entry reading
