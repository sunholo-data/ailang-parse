# Comments Across Every Office Format — XLSX, PPTX, and PDF parity

**Status**: IMPLEMENTED (2026-08-06, v0.24.0)
**Theme**: Every format that carries review commentary returns it in one shape, anchored to whatever that format actually anchors to.
**Follows**: [`v0_23_0_docx_comment_anchoring.md`](../v0_23_0/v0_23_0_docx_comment_anchoring.md)

## Problem

v0.23.0 anchored DOCX comments. That left three inconsistencies:

1. **XLSX and PPTX had no comment extraction at all** — `xl/comments*.xml` and
   `ppt/comments/*` were never read. Meanwhile `docs/comments.html` advertised
   comment text, author, timestamp, cell references and slide numbers for both.
   We were publicly claiming two formats we did not parse.
2. **PDF annotations were the odd one out.** `pdf_annotations.ail` worked, but
   emitted `SectionBlock(kind: "annotation")` with a stringly-typed
   `[Author, page 3, Highlight] text` body — modelled, per its own comments, on
   "the existing DOCX comment shape" that v0.23.0 replaced.
3. **The `CommentBlock` model was DOCX-shaped.** `anchorKind` only knew
   `range` / `point` / `none`, which does not describe a cell or a slide.

## What each format actually anchors to

The interesting finding is that "anchor" means something different in each, and
pretending otherwise would invent precision:

| Format | Anchor | Correlation needed |
|--------|--------|--------------------|
| DOCX | Text span between `commentRangeStart`/`End` | Yes — body and comment live in different parts |
| XLSX | `ref="B5"` on the comment itself, plus that cell's value | **None** — the anchor is in the comment |
| PPTX | The slide (comments pin to an x/y point, not a text run) | Slide relationships |
| PDF | `/QuadPoints` page coordinates | Not resolvable without positional text extraction |

So `anchorKind` gains `cell` and `slide`, and PDF stays honestly `anchored: false`.

## Design

### XLSX (§18.7)

Two shapes, both read:

- `xl/comments1.xml` — legacy notes, `authorId` into an `authors` list. Also
  found nested as `xl/comments/comment1.xml` in the wild, so entries are matched
  by prefix rather than exact path.
- `xl/threadedComments/*.xml` — review threads, `personId` resolved via
  `xl/persons/*.xml`, `parentId` linking replies, `dT` timestamps.

**Deduplication matters.** Modern Excel writes *both*: the legacy part is a
compatibility shim whose author is a placeholder like `tc={guid}` and whose text
duplicates the thread. Reading both naively reports every comment twice, the
second time with a junk author. When a threaded comment exists for a cell, it
wins and the legacy copy is dropped.

The cell's own value is resolved as part of the anchor (`B2: 184000`) by
streaming `<c>` elements — O(1) memory, and only run for sheets that have
comments at all.

### PPTX (§19.3 + MS-PPTX modern)

Two shapes, both read:

- `ppt/comments/comment1.xml` — legacy `p:cm`, numeric `authorId` into
  `ppt/commentAuthors.xml`.
- `ppt/comments/modernComment_*.xml` — what current PowerPoint writes: `p188:cm`
  with GUID `authorId` into `ppt/authors.xml`. Supporting only the legacy shape
  would silently drop every comment made in a recent PowerPoint.

**Slide association comes from slide relationships**, not filename numbering.
The `poi_comment.pptx` fixture proves why: its two comment parts belong to
slides **3 and 7**. Matching `comment1.xml` → `slide1.xml` gets both wrong while
looking like it works.

Note the modern relationship type is singular
(`.../2018/8/relationships/modernComment`), not `modernComments` — the plural
guess silently matches nothing.

### PDF

`pdfannToBlock` now emits `CommentBlock` inside the existing
`SectionBlock(kind: "annotation")` wrapper. `anchored` is false and `anchorText`
carries only the page number as a locator. Real anchoring would need to map
`/QuadPoints` coordinates onto extracted text, which neither backend provides.

## Verification

Gap coverage **49% → 60%** (22 checks, up from 19). All seven comment checks pass:

| Check | Before | After |
|-------|--------|-------|
| XLSX Comments (§18.7) | 0% | 100% — 3/3 anchored to cell and value |
| XLSX Threaded Comments | new | 100% — 4/4 threading + dedup |
| PPTX Comments (§19.3) | new | 100% — 3/3 on the correct slide |
| PPTX Modern Comments | new | 100% — 3/3 |
| DOCX Comment Ranges | 100% | 100% |
| DOCX Comment Orphans | 100% | 100% |
| DOCX Ranges in Tables | 100% | 100% |

New fixtures: `challenge_threaded_comments.xlsx` (thread + legacy shim to catch
double-counting), `challenge_pptx_modern_comments.pptx` (2018 schema).

## Docs correction

`docs/comments.html` claimed PPTX and XLSX support that did not exist. Those
claims are now true, and the capability table was corrected where it still
overstated: XLSX timestamps, comment ids and threading are **threaded-only**;
XLSX anchor text is the *cell value*, not a document text span. Two factual
errors in the prose were fixed — DOCX threading is `commentsExtended.xml` and
not `w:commentReference`, and PPTX has two comment formats rather than one.

## Non-Goals

- Writing comments back into any format — read-only.
- ODF (`office:annotation` / `office:annotation-end`). The DOCX range-threading
  walk would port over almost directly, but no fixture in the repo contains a
  single ODF annotation and there is no demand signal yet.
- True PDF anchoring — needs positional text extraction.
