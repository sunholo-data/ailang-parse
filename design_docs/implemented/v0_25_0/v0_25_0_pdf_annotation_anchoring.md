# PDF Annotation Anchoring — resolving what a highlight covers

**Status**: IMPLEMENTED (2026-08-06, v0.25.0)
**Theme**: A PDF highlight reports the text it covers, and the default backend stops discarding annotations entirely.
**Follows**: [`v0_24_0_comments_all_formats.md`](../v0_24_0/v0_24_0_comments_all_formats.md)

## Problem

v0.24.0 gave PDF annotations the shared `CommentBlock` shape but left them
`anchored: false`, on the grounds that mapping `/QuadPoints` to text needed
positional extraction we didn't have. Investigating that turned up three
separate defects, only one of which was the known limitation.

### 1. The default backend dropped every annotation (worst)

`extractAnnotations` was called in exactly two places, both on the **AI** path
(`parsePdf`, `parsePdfResult`). The external-backend path — which includes
`pdftotext`, **the default** — never called it. So annotation support existed
only if you explicitly opted into the AI backend. On a default run, a
reviewer's comments vanished with no warning.

### 2. Every page number was off by one

```ailang
pure func pdfannIsPage(block: string) -> bool =
  contains(block, "/Type /Page") || contains(block, "/Type/Page")
```

`/Type /Page` is a prefix of `/Type /Pages`, the page-tree node **every** PDF
has. That node was counted as a page, so real pages started at 2. The bug was
invisible while nothing consumed page numbers; it became load-bearing the moment
anchoring needed to match an annotation's page against a word's page.

### 3. Highlights carried no text (the known gap)

A text-markup annotation stores *where* it sits, never *what* it covers. The
words belong to the page content stream, so "which clause did the reviewer
highlight" requires intersecting quads with word positions.

### 4. `/ObjStm` bail-out was far too broad

```ailang
if pdfannHasCompressedObjects(content) then []
```

Any `/ObjStm` anywhere in the file returned zero annotations. But object streams
are ubiquitous (any Word or LaTeX export uses them) while the annotations
themselves usually are **not** inside one — Preview and Acrobat append
highlights as plain objects in an incremental save. The common real-world shape
(export a PDF, highlight it in Preview) returned nothing despite the annotations
sitting in plain sight.

## Design

### Word positions from the adapter

New `words` mode in `adapter.py` runs `pdftotext -bbox` and returns word-level
boxes. The flip from pdftotext's top-left origin to PDF user space's bottom-left
happens **once, in the adapter**, next to the tool that defines the convention —
rather than leaving a coordinate flip for every caller to get wrong.

`words` is not a document backend; it returns no blocks, so it is exempt from
the adapter's "extracted no content is a failure" guard.

### Geometry in AILANG

`pdfannAnchorText` intersects an annotation's quad bounding box with the words
on its page. Membership is tested by **word centre point**, not by overlap: a
highlight drawn slightly wide clips the neighbouring word's edge, and
any-overlap would then pull in a word the reviewer never marked. Requiring the
centre inside the region makes one-word-too-many the harder failure to hit.

Anything unresolvable — no quads (point annotations), a highlight over an image,
a page whose words weren't extracted — stays `anchored: false` with the page
number as a locator. Same rule as the DOCX side: never dress up a guess as a
span.

### Honest incompleteness instead of silence

`scanAnnotations` returns `{annotations, mayBeIncomplete}`. The scan always
runs; `mayBeIncomplete` is true when `/ObjStm` is present, and the CLI prints a
note. Returning what we can see plus a warning strictly beats returning nothing.

Reading *inside* object streams remains unimplemented. `std/deflate.inflateZlib`
exists and would handle the decompression, but locating the stream bytes is the
blocker: offsets computed on the lossy UTF-8 string the scanner uses do not map
to byte offsets, and the authoritative source of offsets is the xref — which in
these files is itself a compressed stream.

## Verification

Gap coverage **60% → 64%** (24 checks).

| Check | Result |
|-------|--------|
| PDF Highlight Anchors (§12.5.6.10) | 100% — 3/3, including correct page numbers |
| PDF Annotations with Object Streams (§7.5.7) | 100% — 2/2 recovered alongside `/ObjStm` |

Fixtures are generated in two passes: emit the page, ask `pdftotext` where the
glyphs actually landed, then re-emit with `/QuadPoints` taken from those
measured boxes. Hand-computing Helvetica metrics would produce quads that look
right but sit a few points off — a fixture whose quads don't really cover the
words it claims to would validate nothing.

Output:

```
[text] The Seller shall indemnify the Buyer against all claims.
[comment:Laura] on "page 1: shall indemnify" → This indemnity is far too broad.
```

## Non-Goals

- Reading annotations inside `/ObjStm` (see above).
- Highlights over scanned/image-only pages — no text layer, so nothing to anchor
  to. These degrade to unanchored with the page number.
- Writing annotations back into a PDF.
