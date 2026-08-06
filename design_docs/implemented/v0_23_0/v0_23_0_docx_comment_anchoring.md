# DOCX Comment Anchoring — join `w:id` between `document.xml` and `comments.xml`

**Status**: IMPLEMENTED (2026-08-06, v0.23.0)
**Theme**: Every extracted comment carries the exact span of document text it annotates.
**Priority**: P1 — daily workflow for a customer's legal reviewer; current behaviour is worse than not supporting comments.
**Estimated**: ~1.5 days
**Upstream request**: `aitana-labs/platform` — `docs/design/v6.23.0/word-comment-anchoring.md` (2026-08-06 ONE UAT)
**Touches**: `docx_parser.ail`, `types/document.ail`, all Block-matching generators, `docparse_browser.ail` (WASM), goldens, SDK type defs

## Problem

`parseDocxComments` ([`docx_parser.ail:504`](../../../docparse/services/docx_parser.ail)) reads
`word/comments.xml` and emits each `w:comment` as
`SectionBlock(kind: "comment")` containing a single author-prefixed `TextBlock`.
It never opens `document.xml`, so the anchor is not merely unimplemented — it is
structurally unreachable.

Verified against `data/test_files/challenge/challenge_comment_ranges.docx`:

```
[text:Normal] The project deadline is March 15 and we need to prepare.
[text:Normal] The budget allocation needs to be reviewed by the finance team.
[text:Normal] Please review the technical specification before the meeting.
[comment] [Alice Smith] This deadline seems too tight
[comment] [Bob Jones]   Need to increase by 15%
[comment] [Alice Smith] Missing API section
```

Increase *what* by 15%? An agent handed this list will infer a target from
proximity or topic. A confidently misattributed legal objection — the right
comment pinned to the wrong clause — is materially worse than "comments are not
supported", because the reader gets no signal that it was a guess.

The existing gap check `check_docx_comment_ranges`
([`eval_gaps.py:597`](../../../benchmarks/office/eval_gaps.py), spec §17.13.1)
scores this **0/3** today.

### Three root causes

| # | Location | Problem |
|---|----------|---------|
| 1 | [`docx_parser.ail:504-534`](../../../docparse/services/docx_parser.ail) | `parseDocxComments` reads only `comments.xml`; the `w:id` join has no second side |
| 2 | [`docx_parser.ail:211-224`](../../../docparse/services/docx_parser.ail) | `childNodeText` has no arm for `w:commentRangeStart` / `w:commentRangeEnd` / `w:commentReference` — they fall through to `""` |
| 3 | [`docx_parser.ail:146-161`](../../../docparse/services/docx_parser.ail) | the body walk is a stateless `flatMap`; comment ranges are stateful (open at one node, close at a later one, possibly a different paragraph) and cannot be expressed in that shape |

## Verified data model

A probe module over `data/test_files/comments.docx` confirms `std/xml` preserves
document order and exposes the markers as siblings of runs:

```
w:p:[w:r, w:commentRangeStart#0, w:r, w:commentRangeEnd#0, w:rREF0, w:r]
w:p:[w:r, w:commentRangeStart#1, w:r]                        ← range opens…
w:p:[w:r, w:commentRangeEnd#1, w:rREF1, w:r]                 ← …closes in the next paragraph
w:p:[…, w:commentRangeStart#3, w:commentRangeStart#4, w:r,
      w:commentRangeEnd#3, w:rREF3, w:commentRangeEnd#4, w:rREF4,
      w:bookmarkStart#5, w:bookmarkEnd#5]                    ← nested ranges + id-space collision
```

Consequences for the implementation:

- **`w:bookmarkStart` also carries `w:id`, in a separate numbering space.** Keying
  on the attribute without checking the tag mis-anchors silently. This is the
  most likely way to ship a quiet bug here.
- **`w:commentReference` sits inside a `w:r`**, not as a paragraph-level sibling.
  The walk must look one level down.
- **`comments.docx` is a better fixture than the challenge file**: cross-paragraph
  range (id 1), nested/overlapping ranges (3 inside 4), multi-paragraph comment
  bodies, and threading via `commentsExtended.xml` (comment 4 replies to 3,
  linked `w14:paraId` → `w15:paraIdParent`).

## Design

### Block shape — `CommentBlock` inside the existing `SectionBlock` wrapper

A new `Block` ADT variant carries the typed fields; the existing
`SectionBlock(kind: "comment")` wrapper is retained so consumers reading
`type: "section", kind: "comment"` keep working. Blast radius is the same
mechanical variant addition as `LinkBlock` (commit `5639148`, 13 `.ail` files).

```
CommentBlock({
  id: string,              -- w:id, for join/debug
  author: string,
  date: string,
  text: string,            -- comment body, paragraphs joined
  anchorText: string,      -- the exact annotated span; "" when unanchored
  anchorKind: string,      -- "range" | "point" | "none"
  anchored: bool,
  anchorBlockIndex: int,   -- index into the body block list; -1 when unanchored
  parentId: string,        -- w:id of the parent comment for replies; "" otherwise
  resolved: bool           -- w15:done
})
```

JSON emitted by `output_formatter`:

```json
{"type":"section","kind":"comment","blocks":[
  {"type":"comment","id":"2","author":"Bob Jones","date":"2026-03-29T22:27:00Z",
   "text":"Need to increase by 15%","anchorText":"budget allocation",
   "anchorKind":"range","anchored":true,"anchorBlockIndex":2,
   "parentId":"","resolved":false}]}
```

Rejected alternatives:

- *Nested `TextBlock` with a `CommentAnchor` style* — zero ADT change, but
  consumers must string-parse and there is nowhere honest to put `anchored`.
- *Extra fields on `SectionBlock`* — 40 construction sites across 18 files, 36 of
  which would pass `""` / `false` for fields meaningless to headers, footers,
  slides and sheets.

### Emission — splice once at the anchor

Each comment appears **exactly once**, immediately after the body block holding
its range end. Unanchored comments remain in a trailing group.

The upstream design doc asks for inline placement *in addition to* the trailing
list. We deviate deliberately: duplication doubles comment tokens in agent
context on exactly the documents (long contracts, heavily annotated) where
context is scarcest, and it would double the comment count in `eval_office`.
Note this back to the platform repo when filing.

### Algorithm

`docxCollectAnchors(root) -> Map[string, Anchor]` — one extra pass over
`document.xml`, no model calls, sub-second parse budget preserved.

A `foldl` over body nodes threading:

```
{ open:     Map[string, [string]]   -- id -> reversed text fragments, still collecting
, done:     Map[string, Anchor]     -- id -> finalized anchor
, blockIdx: int                     -- current body block index
}
```

Per node, in document order:

- `w:commentRangeStart` → `open[id] = []`, record `blockIdx` as the anchor's start
- any text-bearing child (`w:r`, `w:ins`, `w:hyperlink`, `w:smartTag`, `w:sdt`) →
  append its `childNodeText` to **every** currently-open id. Nested and
  overlapping ranges fall out for free.
- `w:commentRangeEnd` → move `open[id]` to `done[id]`, reversing and joining
- `w:r` containing `w:commentReference` for an id never opened → point anchor:
  attach the containing paragraph text, `anchorKind: "point"`
- end of paragraph with ids still open → append `"\n"` to each, so cross-paragraph
  ranges read correctly
- `w:tbl` → recurse `w:tc` → `w:p` with state intact, so table-spanning ranges work

Per the repo's string/list perf rule, fragments accumulate as `[t] ++ parts` and
are reversed at close — never `concat(parts, [t])` inside the fold.

### Degradation

Every case that cannot be resolved with certainty produces `anchored: false`,
`anchorKind: "none"`, `anchorBlockIndex: -1` and a parser warning. Never a
proximity guess. That covers: a `w:id` in `comments.xml` with no range in
`document.xml`, a range with no matching comment body, a malformed or missing
`w:id`, and an unterminated range at end of body.

### Threading

`commentsExtended.xml` keys on the **last** `w:p`'s `w14:paraId` of each comment
body, mapping to `w15:paraIdParent` and `w15:done`. Resolution: build
`lastParaId -> commentId` from `comments.xml`, then `parentId` per comment.
Replies inherit their parent's anchor.

## Implementation Plan

### Phase 1a — anchor collection (~4h)
- [x] `docxCollectAnchors` fold with `open`/`done`/`blockIdx` state
- [x] Handle `commentRangeStart` / `End` / `Reference`, guarded on **tag**, not `w:id` alone
- [x] Recurse into `w:tbl` → `w:tc` → `w:p` preserving state
- [x] Paragraph-boundary newline for still-open ranges

### Phase 1b — join, splice, degrade (~2h)
- [x] `parseDocxComments` reads `document.xml` alongside `comments.xml`, joins on `w:id`
- [x] `CommentBlock` variant + all Block-matching generators (~13 files, mechanical)
- [x] Splice each comment after its anchor block; unanchored comments trail
- [x] Parser warnings for every unresolved id

### Phase 1c — threading (~1h)
- [x] Read `commentsExtended.xml`; map last-`paraId` → `paraIdParent` → `parentId`
- [x] Surface `resolved` from `w15:done`

### Phase 2 — fixtures & benchmarks (~2h)
- [x] `comments.docx` covers overlapping / cross-paragraph / threaded — add to office suite
- [x] New fixture: orphaned `w:id` (comment body with no range, range with no body)
- [x] New fixture: range spanning table cells
- [x] `check_docx_comment_ranges` 0/3 → 3/3
- [x] Regen goldens; confirm no office-suite regression

### Phase 3 — surfaces (~2h)
- [x] `docparse_browser.ail:104` takes `comments.xml` as a bare string — needs a
      two-argument signature to receive `document.xml`, or the WASM demo silently
      keeps the unanchored behaviour
- [x] `ailang.toml` version + CHANGELOG
- [x] SDK type defs (Python, JS, Go)
- [x] `ailang messages send docparse` back to the platform repo, noting the
      splice-once deviation

## Non-Goals

- Writing comments back into a `.docx` — read-only.
- Tracked changes (`w:ins` / `w:del`) — already extracted as `ChangeBlock`;
  anchoring them is the same correlation problem and the likely follow-up.
- ODT (`office:annotation`), PPTX (`ppt/comments/`) and XLSX (`xl/comments*.xml`)
  have **no comment extraction at all** today. Separate gaps; XLSX is already
  tracked as `check_xlsx_comments` in `eval_gaps.py`.

## Rollback

Strictly additive on the wire — old consumers still match
`type: "section", kind: "comment"`. Rollback is pinning the previous
`ailang-parse` version; platform-side reads are null-safe against the old shape.

## Success Criteria

- [x] `check_docx_comment_ranges` scores 3/3
- [x] `comments.docx` — all 5 comments anchored, including the cross-paragraph
      range (id 1), the nested pair (3/4), and 4-replies-to-3
- [x] An orphaned comment reports `anchored: false` and is attached to nothing
- [x] Office suite stays at 100%; parse stays sub-second
- [ ] Platform confirms an agent quotes the anchored clause rather than guessing
      (platform-side, tracked in `aitana-labs/platform`)
