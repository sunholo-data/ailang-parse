# Design Doc: PDF Annotation Extraction (v0.13.0)

**Status**: Implemented (pending version bump + release)
**Date**: 2026-05-06
**Author**: Mark + Claude
**Source**: Real-world failure on a CPH University review where Muhammad Aswin Rangkuti ("Arwin") left 132 highlight comments across four PDFs. Gemini multimodal extraction (the current PDF path in `direct_ai_parser.ail`) saw none of them — annotations live in the PDF's `/Annots` object layer, not the rendered visual page that the model rasterises.

**Related**:
- Upstream feature request: [ailang#223](https://github.com/sunholo/ailang/issues/223) — `std/zip: expose raw zlib inflate/deflate primitives`. **Resolved 2026-05-06** — shipped as a new `std/deflate` module (commit `c48c3aa4`, target ailang v0.16.0) with `inflate`, `inflateZlib`, `deflate`, `deflateZlib` exports. v2 of this module (ObjStm support) is now buildable; see Limitations.

---

## Problem

PDF annotations (highlights, sticky notes, free-text comments, underlines) are first-class metadata stored as indirect objects in the PDF's object graph — typically referenced from each page's `/Annots` array. They are not part of the rendered page content, so any extraction path that goes through rasterisation (Gemini multimodal, OCR, headless rendering) drops them entirely.

The CPH-uni review made this concrete: across four annotated PDFs (`Students_Use_of_AI_in_Upper_Secondary_School_EN.pdf`, `generative_ai_upper_secondary_education_english_translation.pdf`, `translated_guide_to_physics_a_stx_july_2024.pdf`, `translated_physics_a_stx_august_2024_text_based.pdf`) Arwin's 132 highlight comments — the entire substantive value of the review pass — were silently absent from the parsed output.

The current PDF pipeline ([direct_ai_parser.ail:13](../../../docparse/services/direct_ai_parser.ail#L13)) uses Gemini File API multimodal extraction. There is no native PDF parsing in the codebase; `zip_extract.ail` only handles Office ZIP containers.

---

## Investigation

Pre-flight check across all four CPH-uni PDFs:

| File | `/Annot` | `/Highlight` | `/ObjStm` |
|---|---|---|---|
| Students_Use_of_AI…EN.pdf | 36 | 23 | **0** |
| generative_ai_upper_secondary…en.pdf | 18 | 14 | **0** |
| translated_guide_to_physics_a_stx_july.pdf | 59 | 46 | **0** |
| translated_physics_a_stx_august_2024.pdf | 30 | 19 | **0** |

Zero compressed object streams. Annotations are inline indirect objects, fully recoverable by string scanning. A representative annotation from `translated_guide_to_physics_a_stx_july_2024.pdf`:

```
838 0 obj
<< /C [ 0.980392 0.803922 0.352941 ] /Border [ 0 0 0 ]
   /DA (//Helvetica 12 Tf 0 g) /F 4
   /Subtype /Highlight /Type /Annot
   /Rect [ 64.9 198.0735 169.312 212.3745 ]
   /M (D:20260428093148Z00'00')
   /AP << /N 840 0 R >>
   /Contents (þÿ\000T\000h\000i\000s\000 \000c\000o\000u\000l\000d\000 …)
   /QuadPoints [ 64.9 212.3745 169.312 212.3745 …]
   /T (Muhammad Aswin Rangkuti) >>
endobj
```

Everything we need (`/Subtype`, `/Contents`, `/T`, `/M`, `/Rect`, `/QuadPoints`, page-association via `/Annots` arrays on `/Type /Page` objects) is reachable with string-level parsing. The `/Contents` payload is a PDF string literal — UTF-16BE with byte-order mark `þÿ` (0xFE 0xFF) and octal-escaped bytes — which decodes deterministically.

The producer in this case is macOS Quartz PDFContext (Preview / Skim), which writes inline annotations. Modern "optimised" PDFs from Adobe Distiller, web-export tools, or Google Docs export typically pack objects into compressed `/ObjStm` streams that need raw zlib inflate to read. That's a real limitation but not one any of the in-flight files trigger — see Limitations.

---

## Non-Goals

- **Full PDF parsing.** No content-stream interpretation, no font handling, no graphics state, no rendering. We do not extract page text from PDFs in this work — that path stays with the AI backend.
- **Recovering the highlighted source passage** ("the words under Arwin's yellow rectangle"). That requires intersecting `/QuadPoints` with the page content stream's text-positioning operators (`Tj`, `TJ`, `Tm`) — full text extraction, explicitly out of scope.
- **Compressed object streams.** PDFs that bundle annotation objects into `/ObjStm` are skipped with a clear diagnostic. Fixing this needs raw zlib inflate in the AILANG stdlib (see [ailang#223](https://github.com/sunholo/ailang/issues/223)).
- **Encrypted PDFs.** Reject with a clear error.
- **Linearised / fast-web-view PDFs.** Should work (the object structure is unchanged) but only one CPH-uni file is linearised and we'll exercise it in tests, not promise it.
- **Replacing the AI multimodal path.** Annotation extraction *augments* the existing pipeline; it does not substitute for it. The AI still produces the document body; annotations attach as additional `Comment` blocks.
- **Generating PDFs with annotations.** Read-only.

---

## Architecture

```
                ┌────────────────────────────────────┐
                │   PDF input                        │
                └──────────────┬─────────────────────┘
                               │
                ┌──────────────▼─────────────────────┐
                │  direct_ai_parser.parsePdfFile     │  (existing)
                │  → Document blocks via Gemini      │
                └──────────────┬─────────────────────┘
                               │ Document
                ┌──────────────▼─────────────────────┐
                │  pdf_annotations.extract           │  (NEW)
                │  • read raw bytes                  │
                │  • scan for /Subtype /<annot>      │
                │  • decode /Contents (UTF-16BE/lit) │
                │  • map to page index               │
                │  → List[Annotation]                │
                └──────────────┬─────────────────────┘
                               │ merge as Comment blocks
                ┌──────────────▼─────────────────────┐
                │  Document with annotations         │
                └────────────────────────────────────┘
```

New module: `docparse/services/pdf_annotations.ail`. Wired into the existing PDF entry point in `direct_ai_parser.ail` so callers see one merged `Document`.

---

## Implementation

### Module: `pdf_annotations.ail`

Public API:

```ailang
type Annotation = {
  subtype: string,        -- "Highlight" | "Text" | "FreeText" | "Underline" | "StrikeOut" | "Squiggly"
  contents: string,       -- decoded comment text (empty if no /Contents)
  author: string,         -- /T value (empty if absent)
  modified: string,       -- /M value, ISO-normalised when possible
  page: int,              -- 1-based page number, 0 if unmappable
  rect: [float, float, float, float]  -- /Rect bbox
}

func extractAnnotations(filepath: string) -> Result[List[Annotation], string] ! {FS}
func annotationsAsComments(anns: List[Annotation]) -> List[Block]   -- pure
```

### Algorithm (v1, inline annotations only)

1. **Read** the PDF as a base64 binary string via `std/fs.readFileBytes`.
2. **Detect ObjStm bail-out.** If the byte string contains `/ObjStm`, return `Ok([])` with a diagnostic logged via `std/io.eprintln` — don't error, just don't claim coverage we don't have.
3. **Scan obj blocks.** Find each `<num> <gen> obj … endobj` segment. Filter to those containing `/Type /Annot` *and* a recognised `/Subtype`. Each match yields one annotation.
4. **Field extraction** per matched object using stdlib regex / string ops:
   - `/Subtype` → keyword after the slash, up to whitespace
   - `/Contents` → PDF string literal (parens-balanced) or hex string (`<…>`)
   - `/T` → PDF string literal
   - `/M` → date string `D:YYYYMMDDHHMMSS…`
   - `/Rect` → 4 floats
5. **Decode `/Contents`.** PDF strings are tricky:
   - `(...)` literal: handle balanced parens, backslash escapes (`\n`, `\r`, `\t`, `\\`, `\(`, `\)`, `\<3-octal-digits>`), UTF-16BE with leading BOM `0xFE 0xFF`.
   - `<...>` hex: pairs of hex digits, optional whitespace.
   - When BOM is present, decode as UTF-16BE; otherwise treat as PDFDocEncoding (close enough to Latin-1 for round-trip in this scope; we'll iterate if a real-world file demands it).
6. **Page mapping.** Walk the file twice:
   - First pass: collect all `/Type /Page` objects in occurrence order, recording each page's annotation refs (parsed from inline `/Annots [ … ]` or resolved through one indirection `/Annots N 0 R` → array object).
   - Second pass: invert into `annotObjNum → pageIndex (1-based)`.
   - Annotations not in any page's `/Annots` get `page = 0`.
   *Note*: occurrence-order ≠ Pages-tree order in pathological cases. Walk the Pages tree (`/Type /Pages /Kids [ … ]` from the catalog `/Root /Pages`) when one of the test PDFs requires it. v1 starts with occurrence order and we only escalate if a fixture breaks.
7. **Date normalisation.** `D:20260428093148Z00'00'` → `2026-04-28T09:31:48Z`. Best-effort; pass through raw on parse failure.

### Wiring into `direct_ai_parser.ail`

After the existing AI extraction returns its `Document`:

```ailang
let aiDoc = parsePdfFile(filepath, …);
let annResult = pdf_annotations.extractAnnotations(filepath);
match annResult {
  Ok(anns) => mergeAnnotationsIntoDocument(aiDoc, anns),
  Err(_)   => aiDoc                  -- fail soft; AI output is still useful
}
```

`mergeAnnotationsIntoDocument` appends one `Comment` block per annotation, preserving page metadata, so downstream consumers (Quarto export, JSON output, SDKs) get them through the existing `Comment` schema with no shape changes.

### Output format

A new annotation produces a `Comment` block matching the existing DOCX comment shape:

```json
{
  "type": "Comment",
  "page": 12,
  "author": "Muhammad Aswin Rangkuti",
  "date": "2026-04-28T09:31:48Z",
  "text": "This could be important, can GAI formulate 'open-ended problem' for the experiment?",
  "annotation_kind": "Highlight"
}
```

`annotation_kind` is a new optional field; absent on DOCX-sourced comments. SDK schemas update as a minor.

---

## Tests

Fixtures: copy four CPH-uni PDFs into `data/test_files/pdf_annotations/` (with the client's permission for in-repo tests, otherwise into `data/test_files/local-only/` referenced from a separate fixture manifest).

Unit (inline AILANG `tests` blocks where the harness allows; otherwise via `main` runner):
- PDF string literal decoder: ASCII, escape sequences, octal escapes, UTF-16BE with BOM, balanced parens, hex string `<…>`.
- Date normaliser: `D:20260428093148Z00'00'`, `D:20240101000000+02'00'`, malformed pass-through.
- ObjStm bail-out: feed a known compressed-objects PDF, expect `Ok([])` and the diagnostic.

Integration:
- Each CPH-uni PDF: extracted annotation count matches expected per-file totals from the table above.
- One specific known annotation per file (memorised by content prefix) is recovered with correct author, page, and decoded text.
- One synthetic PDF with `/ObjStm` (e.g. re-saved through `pdfcpu optimize`) confirms graceful bail-out.

Benchmark:
- Add a `pdf_annotations` row to the office benchmark suite. Score = recovered/expected annotation count. Baseline 100% on inline-annotation PDFs.

---

## Limitations & Follow-Ups

1. **Compressed object streams unsupported in v1.** Was tracked by [ailang#223](https://github.com/sunholo/ailang/issues/223); **resolved 2026-05-06** with the new `std/deflate` module (target ailang v0.16.0). v2 — adding `/ObjStm` support — is now unblocked but not yet scheduled. v1 detects the situation and returns empty rather than partial data.
   - **What v2 needs**: parse the cross-reference table (classic ASCII or PDF 1.5+ xref-stream form) to find which objects live in which `/ObjStm`, `inflateZlib` each ObjStm body, parse its header (object-number/offset pairs), split out individual sub-objects, then feed them into the existing scanner. ~200-300 LOC on top of v1.
   - **When to schedule**: when a customer PDF triggers the bail-out path. Defer until real demand — none of the v1 fixture files need it.
   - **Dependency bump required**: `ailang.toml` `ailang = ">=0.12.0"` → `">=0.16.0"` once v0.16.0 tags.
2. **No highlighted source text.** v1 returns the comment Arwin wrote, not the words he highlighted. Adding the highlighted passage requires content-stream parsing — a separate, larger project.
3. **Encrypted PDFs rejected.** No plan to handle.
4. **Page mapping fallback.** If real-world fixtures require Pages-tree traversal beyond occurrence order, that's a follow-up patch — not a separate doc.
5. **Annotation-write.** Generating PDFs with annotations is out of scope. If a future use case demands it, scope a separate v0.X.0 doc.

---

## Acceptance criteria

- [x] `docparse/services/pdf_annotations.ail` module ships with public API above.
- [x] Wired into `direct_ai_parser.ail` so `./bin/docparse <pdf>` includes annotations.
- [x] All four CPH-uni PDFs produce expected annotation counts (132 total — verified, see Implementation Notes).
- [x] Annotation output uses `SectionBlock(kind: "annotation")` matching the existing DOCX comment shape — author, page, and subtype surfaced in the text prefix. *(Adjusted from the original "annotation_kind field" plan: extending the `Block` ADT was unnecessary. The kind information rides in the prefix string `[author, page N, Highlight] body`, which is the same shape DOCX comments use today and needs no SDK schema change.)*
- [x] ObjStm-only PDFs return empty annotations cleanly (verified: project-description.pdf returned 0).
- [ ] Office benchmark suite gains a `pdf_annotations` scoring row at 100%. *(Deferred — annotation extraction happens inside the AI-PDF path, which the office suite doesn't exercise. Add a fixture to a PDF benchmark suite when one exists.)*
- [x] Type-check passes (all 34 modules).

---

## Implementation notes (2026-05-06)

**Total recovered**: **132 annotations** across the four CPH-uni PDFs, exactly matching the count Arwin's review pass produced.

| File | Total | With comment text |
|---|---|---|
| Students_Use_of_AI…EN.pdf | 33 | 3 |
| generative_ai_upper_secondary…en.pdf | 17 | 1 |
| translated_guide_to_physics_a_stx_july.pdf | 55 | 4 |
| translated_physics_a_stx_august_2024.pdf | 27 | 3 |
| **Total** | **132** | **11** |

`project-description.pdf` (ObjStm-compressed) bails out cleanly with 0 annotations, as designed.

The "with comment text" count (11) is the subset where Arwin actually wrote a note alongside the highlight. The remaining 121 are bare highlights (yellow rectangle, no comment) — still recovered with their author, subtype, and page number.

**Things that surprised us during build:**

1. **AILANG has no hex literals.** `0xFFFD`, `0xFE` etc. are parser errors; everything had to be decimal.
2. **Lambdas can't reference other top-level helpers** in this AILANG version — `map(\a. helper(a.x), xs)` failed with "undefined variable: helper". Worked around by replacing `map(lambda)` with a top-level recursive helper that walks the list.
3. **`readFile` UTF-8-normalises non-UTF-8 bytes to U+FFFD.** PDF strings store the UTF-16BE BOM (0xFE 0xFF) as raw bytes in the source; those become two U+FFFD chars after read. The decoder detects this pattern (treats the first U+FFFD as 0xFE, subsequent ones as 0xFF) so BOM detection still triggers correctly. Quartz also writes most non-ASCII bytes as PDF octal escapes (`\000`, `\030`, `\035`) which survive UTF-8 normalisation perfectly, so the loss is limited to the BOM bytes and a successful UTF-16BE decode follows.
4. **`/T` string-matches before `/Type`.** Naïve `find(block, "/T")` lands on `/Type` first and loses the author. Fixed by `pdfannFindCompleteKey` which only matches a key when the next character is a PDF name terminator (whitespace, `(`, `<`, `[`, `/`, `>`).
5. **Page `/Annots` are indirect refs in real PDFs.** Quartz writes `/Annots 768 0 R`, not `/Annots [ ... ]`. The page-mapping path now resolves the indirect reference by re-scanning for the target object's body.
6. **Octal escapes for control chars matter.** Quartz writes curly quote bytes as `\030` and `\035` (octal for 0x18 and 0x1D — the second bytes of UTF-16BE encodings of U+2018 and U+201D). Decoded text comes out with proper typographic quotes.

**Files touched:**

- `docparse/services/pdf_annotations.ail` — new module (~330 lines).
- `docparse/services/direct_ai_parser.ail` — wired `extractAnnotations` + `annotationsAsBlocks` into `parsePdf`.
- `ailang.toml` — added `docparse/services/pdf_annotations` to exports.

**Verification:** `./bin/docparse --check` — all 34 modules clean. Office benchmark unchanged at 99.4% (no regression in non-PDF paths).
