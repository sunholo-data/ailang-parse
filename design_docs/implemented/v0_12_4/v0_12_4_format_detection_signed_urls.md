# DocParse v0.12.4 — Robust Format Detection for Signed URLs

**Status**: IMPLEMENTED — Layers 1 & 2 shipped in ailang-parse v0.12.4 (2026-04-27). Layer 3 (api_server.ail wiring) and Layer 4 (parseDocxStrict) tracked in the downstream `docparse` repo.
**Theme**: Fix DOCX/PPTX/XLSX misclassification when files arrive via signed URL fetch
**Depends on**: v0.7.0 (API server), v0.8.0 (sourceUrl ingestion)
**Priority**: HIGH — Production bug from aitana-platform v6 (msg_20260427_173916_463d1f6b). All Office formats consumed via signed GCS URLs are silently degrading to flat-text output.

## Implementation Notes (post-ship)

- Layers 1 + 2 in `docparse/services/format_router.ail`. New exports: `sniffFormat`, `resolveFormat`, `ResolvedFormat`. Smoke test in `scripts/test_format_sniffing.ail` covers 8 formats happy-path plus the bug-repro case (DOCX with extension stripped). Office structural benchmark unchanged at 99.4% mean across 56 files.
- Sniffer uses a base64-prefix table for non-ZIP magic bytes (PDF/PNG/JPG/GIF/WAV/WEBP/MP3) since `readFileBytes` returns base64-encoded data. ZIP-based formats reuse `std/zip` `readEntry` to peek at `mimetype` / `[Content_Types].xml`. No raw-byte inspection needed.
- Inline `tests [...]` skipped on the new functions per the AILANG bug policy in `CLAUDE.md` (test harness can't apply stdlib-calling pure functions). Coverage lives in the smoke test instead.

## Problem

DOCX files served from GCS via signed URL are being parsed but the structured DOCX parser (`parseDocx`) is not invoked for them. Output is a flat list of `{type:text, style:Normal, level:0}` blocks with empty metadata, even though the upstream `Content-Type` is correct and the URL filename ends in `.docx`.

### Reported Symptoms (aitana-platform v6)

- File: `VOLUNTEERS for WEbsite-1.docx` (14250 bytes), also `claim_incident_summary.docx`
- Source: signed GCS URL from `gs://aitana-documents-bucket`
- GCS `Content-Type`: `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (correct)
- URL path: ends in `.docx`, spaces URL-encoded as `%20`
- Request IDs: `req_26635303ffdb74b1`, `req_f3c38aca821af767`

Response shape:

```json
{
  "format": "zip-office",
  "metadata": {"title":"", "author":"", "created":"", "modified":"", "pageCount":0},
  "blocks": [
    {"type":"text", "style":"Normal", "level":0, "text":""},
    {"type":"text", "style":"Normal", "level":0, "text":"Volunteers needed..."},
    ...
  ]
}
```

22 flat blocks, many empty (the structured DOCX parser would normally collapse empty `<w:p>` runs).

### Reporter's Diagnosis (Incomplete)

The reporter inferred from the `format: "zip-office"` response field that `officeType()` returned something other than `"word"`, causing the `apiParseByFormat` dispatch at [api_server.ail:299](../../../../sunholo/docparse/docparse/services/api_server.ail) to fall through.

This is **not** the actual root cause. `format: "zip-office"` is the *internal category* — that's what gets stored on the response document regardless of which Office subtype was dispatched. The dispatch decision uses `officeType(ext)` separately, and for any genuine `.docx` extension that path returns `"word"` and routes to `apiParseDocx`.

## Actual Root Cause Analysis

The signed-URL ingestion path in [api_server.ail:535](../../../../sunholo/docparse/docparse/services/api_server.ail#L535) (`fetchSourceUrl`) builds the local path like:

```ailang
let basename = sourceUrlBasename(url);
let localPath = "/tmp/docparse-url-${ts}-${basename}";
let _ = writeFile(localPath, resp.body);
```

`sourceUrlBasename` strips the query string and takes the last path segment, but does **not** URL-decode it. For a signed URL ending in `VOLUNTEERS%20for%20WEbsite-1.docx?X-Goog-Signature=...`, the basename becomes `VOLUNTEERS%20for%20WEbsite-1.docx` (still percent-encoded).

When `parseFile` later calls `getExtension(localPath)`, [format_router.ail:113](../../../docparse/services/format_router.ail#L113) does `split(filename, ".")` and takes the last segment after `toLower`. That still yields `"docx"` for this exact case — so extension detection alone is **not** the failure.

The most likely actual failure modes (we need repro to confirm which one fires):

1. **Binary corruption via `resp.body` round-trip.** `httpRequest` returns the body as a string. Writing a binary ZIP through the AILANG string type can mangle non-UTF-8 byte sequences depending on the runtime path. The DOCX parser then opens a corrupted ZIP, fails to find expected parts (`word/document.xml`, `docProps/core.xml`), and degrades silently. This explains both empty metadata and flat unstructured paragraphs.
2. **Extension lost on alternate URL shapes.** If the signed URL embeds the filename in a query parameter (`?response-content-disposition=attachment;filename=foo.docx`) instead of the path, `sourceUrlBasename` returns the bucket-internal storage key (often a UUID with no extension), `getExtension` returns `""`, `detectFormat("")` returns `"unknown"`, and dispatch fails entirely. The response shape would not match exactly, but partial flows could still produce a flat-blocks fallback.
3. **DOCX parser tolerates the corrupted ZIP.** If a partial ZIP read still yields some `<w:p>` elements (perhaps from a malformed central directory recovery path), the parser could emit raw paragraphs without the styling/heading/table-detection passes — matching the "raw `<w:p>` elements not collapsed" symptom exactly.

All three are real classes of bug we want closed regardless of which one fires here.

## Design

The fix has three layers, each independently valuable.

### Layer 1 — `format_router.ail`: Magic-Byte Content Sniffing

Add a content-aware detector as a fallback for when extensions are missing, ambiguous, or untrusted. New exported function:

```ailang
-- Inspect the first ~4KB of a file to identify its format.
-- Used as a fallback when extension-based detection returns "unknown",
-- and as a sanity check when extension says "zip-office" so we can
-- distinguish docx/pptx/xlsx from generic zips.
export func sniffFormat(filepath: string) -> string ! {FS}
```

Detection rules (priority order):

| Magic / Signature                            | Returned Format |
| -------------------------------------------- | --------------- |
| `25 50 44 46 2D` (`%PDF-`)                   | `"pdf"`         |
| `89 50 4E 47 0D 0A 1A 0A`                    | `"image"` (png) |
| `FF D8 FF`                                   | `"image"` (jpg) |
| `50 4B 03 04` + `[Content_Types].xml` member | see ZIP rules   |
| ZIP + `mimetype` member starts `application/vnd.oasis.opendocument` | `"zip-odf"` |
| ZIP + `mimetype` member `application/epub+zip` | `"epub"`      |
| `52 49 46 46` … `57 41 56 45`                | `"audio"` (wav) |
| `49 44 33` (id3) or `FF FB`                  | `"audio"` (mp3) |

ZIP-with-`[Content_Types].xml` rules (read the file via existing `readZipMember`):

- Member contains `wordprocessingml.document.main+xml` → returns `"docx"` (specific, not category)
- Member contains `presentationml.presentation.main+xml`  → `"pptx"`
- Member contains `spreadsheetml.sheet.main+xml`          → `"xlsx"`
- Otherwise generic ZIP → `"unknown"`

Note the return value here is the *specific* extension-equivalent (`"docx"`), not the internal category (`"zip-office"`). Callers compose with the existing `detectFormat` for routing.

### Layer 2 — `format_router.ail`: Composite Resolver

A new entry point that combines extension + content sniffing with a clear precedence:

```ailang
-- Resolve format from either filename, content, or both.
-- Precedence:
--   1. If extension is recognized AND sniffed format is consistent or absent, use extension.
--   2. If extension is missing/unknown, fall back to sniffed format.
--   3. If extension says "zip-office" but sniff says docx/pptx/xlsx, prefer the sniffed
--      specific subtype (this catches the bug where temp files lose their extension).
export func resolveFormat(filepath: string) -> ResolvedFormat ! {FS}

export type ResolvedFormat = {
  ext: string,            -- e.g. "docx" — what officeType() will key on
  format: string,         -- e.g. "zip-office" — what detectFormat() returns
  source: string          -- "extension" | "content" | "both"
}
```

`source` is surfaced in API response headers (`X-AilangParse-FormatSource`) so callers can tell when we had to fall back to sniffing.

### Layer 3 — `api_server.ail` (Private Repo): Wire In + Decode + Surface

Three changes in [api_server.ail](../../../../sunholo/docparse/docparse/services/api_server.ail):

**3a. URL-decode in `sourceUrlBasename`** so percent-encoded filenames produce a clean basename. This alone won't fix the bug for URLs that don't carry the filename in the path, but it removes one variable from the failure space and makes temp paths human-readable for debugging.

**3b. Replace ad-hoc extension lookups with `resolveFormat`.** Every site that currently does:

```ailang
let ext = getExtension(filepath);
let format = detectFormat(ext);
```

becomes:

```ailang
let resolved = resolveFormat(filepath);
let ext = resolved.ext;
let format = resolved.format;
```

This applies to four sites: lines 162-163, 228-229, 283, 676-678, 776-777, 820-821, 1026-1027.

**3c. Surface the actual subtype in the response.** Add `subtype` to `ParsedDocument` (or expose via response header `X-AilangParse-Subtype: docx`) so consumers don't have to reverse-engineer the internal category. This addresses the reporter's confusion directly — they should see `"docx"` somewhere in the response, not just `"zip-office"`.

### Layer 4 — Defensive: DOCX Parser Failure Surfacing

Today `parseDocx` on a corrupt ZIP returns whatever it can extract without signaling that anything went wrong. Add an explicit failure surface:

```ailang
export func parseDocxStrict(filepath: string) -> Result<[Block], DocxParseError> ! {FS}
```

Where `DocxParseError` is one of `ZipReadFailed | MissingDocumentXml | MissingContentTypes | EmptyDocument`. The existing `parseDocx` becomes a thin wrapper that returns `[]` on error for backwards compat, while the API server uses `parseDocxStrict` and surfaces a 422 with the parse error code in the body — so the next time aitana-platform hits this, the error tells them exactly what's wrong instead of silently producing empty paragraphs.

## Test Plan

New test files in `data/test_files/format_detection/`:

1. `docx_no_extension` — a valid `.docx` renamed to a path with no `.` (sniffer must catch it)
2. `docx_url_encoded.docx` — a valid `.docx` whose path includes `%20` literals (encoding survives extension extraction)
3. `corrupt_zip.docx` — a deliberately truncated `.docx` (should hit `parseDocxStrict` error path, not silent flat-text)
4. `wrong_extension.txt` — a valid `.docx` with `.txt` extension (sniffer overrides extension)
5. `generic_zip.zip` — a zip that is *not* a docx (sniffer must return `"unknown"`, not pretend it's docx)

Inline `tests` on `sniffFormat` and `resolveFormat`. Integration test in `benchmarks/quick_check.sh` that runs the suite end-to-end.

Office structural benchmark must still pass at 100% — the new path is opt-in via `resolveFormat`, existing extension-only callers are unchanged.

## Migration & Compatibility

- `detectFormat`, `officeType`, `getExtension` are unchanged — pure additions.
- `resolveFormat`/`sniffFormat` are new exports, opt-in.
- `parseDocxStrict` is additive; existing `parseDocx` keeps current behavior.
- API response gains `X-AilangParse-Subtype` and `X-AilangParse-FormatSource` headers; existing fields unchanged. SDK consumers ignore unknown headers.

## Out of Scope

- Format detection for in-memory bytes (no filepath). Will be a follow-up once we have a repro showing the WASM path needs it.
- Re-encoding `resp.body` from bytes for the URL fetch path — that's a runtime/transport concern, not a format-detection one. Filed separately if Layer 1 sniffing reveals the ZIP itself is being corrupted in transit.
- Content-Type-header-based detection. We don't trust upstream `Content-Type` because half the public web mislabels Office files as `application/octet-stream`. Magic bytes are the source of truth.

## Resolution Linkage

Reply to message `msg_20260427_173916_463d1f6b` once Layers 1-3 ship, with:

- Confirmation that DOCX-from-signed-URL now produces structured output
- Note that the reporter's diagnosis was off (`format: "zip-office"` is correct, but they should look at the new `subtype` field/header)
- The new `X-AilangParse-FormatSource: content` header will show when sniffing kicked in, helpful for their debugging
