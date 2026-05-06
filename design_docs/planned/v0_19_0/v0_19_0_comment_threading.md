# Design Doc: DOCX Comment Threading & Resolution (v0.19.0)

**Status**: Planned
**Date**: 2026-05-06
**Author**: Mark + Claude
**Source**: Gap analysis vs [stella/stella](https://github.com/stella/stella) (OSS AI legal workspace). Stella's Folio parser extracts comments as a flat list with no reply chains, no resolution status, and no UTC timestamps unless `commentsExtensible.xml` is present. AILANG Parse has the same flat-list limitation. Closing it makes `docparse` the correct AI context layer for threaded legal review workflows (contract negotiation, due-diligence annotation).

---

## Problem

`docparse` currently extracts comments from `word/comments.xml` as flat `SectionBlock(kind: "comment")` blocks with author-prefixed text:

```
[Alice Smith] Please review this clause before signing.
```

Four things are missing:

1. **Reply chains.** OOXML stores comment replies as sibling comments with a `w:paraId` parent reference in `word/commentsExtensible.xml`. Without this, a 6-message negotiation thread over a single clause appears as 6 disconnected comments. An LLM fed this context cannot tell who replied to whom or what was resolved.

2. **Resolution status.** `commentsExtensible.xml` carries a `<w15:resolved w15:val="1">` flag. Without it, the parser has no way to distinguish outstanding comments from resolved ones. In legal review, unresolved comments are open negotiation points; resolved ones are settled. Mixing them poisons the AI context.

3. **Positional anchor IDs.** `word/comments.xml` assigns each comment a `w:id`. Body text marks where a comment applies with `<w:commentRangeStart w:id="N">` / `<w:commentRangeEnd w:id="N">`. AILANG Parse currently discards these anchor IDs — the `SectionBlock` has no way to say "this comment is anchored to paragraph 12, runs 3–7." Without anchoring, an LLM cannot localize what each comment is about without re-reading the entire document.

4. **UTC timestamps.** `word/comments.xml` stores dates in local time without timezone. `commentsExtensible.xml` stores them as ISO-8601 UTC. Without the extended file, timestamps are unreliable for ordering a thread chronologically.

This gap was identified by comparing against Stella's comment parser (`commentParser.ts`), which also lacks threading and resolution — confirming it is a widely-unimplemented OOXML feature that represents a real differentiator opportunity.

---

## Non-Goals

- Rendering comment threads as a UI widget. The output is a structured AST; consumers build their own UI.
- Comment *write-back* (emitting `<w:comment>` from AILANG). Scoped separately as a follow-up to the write-back infrastructure in v0.18.0.
- Resolving comments automatically. We expose resolution status; we do not change it.
- Handling comments in headers, footers, footnotes, or text boxes. Body text only, matching the scope of `docparse`'s existing text extraction.
- Sentiment or intent analysis on comment text. That's the LLM's job once it has a clean thread.

---

## Part 1: Extend `CommentBlock` with threading metadata

### Current shape (inferred from `docparse/services/docx_parser.ail`)

```ailang
SectionBlock({kind: "comment", blocks: [
  TextBlock({text: "[Alice] Please review this clause.", style: "CommentText", level: 0})
]})
```

### Target shape

Add a `CommentBlock` variant to the block ADT (or enrich `SectionBlock` metadata — decision below):

```ailang
type CommentMeta = {
  id:          int,              -- w:id from comments.xml
  author:      string,
  initials:    string,
  date:        string,           -- ISO-8601 UTC if commentsExtensible present, else local
  parentId:    Option[int],      -- reply-to id; None = top-level comment
  resolved:    bool,             -- from commentsExtensible w15:resolved
  anchorStart: Option[int],      -- paragraph index where commentRangeStart falls
  anchorEnd:   Option[int],      -- paragraph index where commentRangeEnd falls
}

-- Augmented block (extend existing SectionBlock or add CommentBlock variant)
CommentBlock({
  meta:   CommentMeta,
  blocks: list[Block]            -- comment body paragraphs (unchanged)
})
```

**Decision: new variant vs. enriched SectionBlock.**
Prefer a dedicated `CommentBlock` variant. The `SectionBlock(kind: "comment")` pattern was a bootstrap convenience; a named variant makes pattern-matching unambiguous and avoids stringly-typed `kind` checks downstream. This is a minor breaking change to the block ADT — worth doing cleanly at v0.19.0.

---

## Part 2: Parse `word/commentsExtensible.xml`

This file (introduced in OOXML 2016, present in all modern Word versions) carries:
- `<w15:commentEx w15:paraId="…" w15:paraIdParent="…" w15:done="0|1">` — threading + resolution
- UTC `w:date` override per comment ID

### Algorithm

```
1. Open zip, check for word/commentsExtensible.xml (absent in old docs — ok, degrade gracefully)
2. Build extMap: Map[paraId, {parentParaId: Option[string], done: bool, utcDate: Option[string]}]
3. Also build paraIdToCommentId: Map[paraId, int] from word/comments.xml w:comment elements
   (each w:comment carries a w14:paraId attribute alongside w:id)
4. For each parsed comment:
   a. Look up paraId in extMap → resolved, parentParaId, utcDate
   b. If parentParaId present → resolve to parentCommentId via paraIdToCommentId
   c. Override date with utcDate if available
   d. Populate CommentMeta.parentId and CommentMeta.resolved
```

Graceful degradation: if `commentsExtensible.xml` absent, `resolved = false`, `parentId = None`, date from `comments.xml` (local time, noted in `CommentMeta.dateReliable: bool`).

---

## Part 3: Thread comment anchor IDs through body parsing

Currently `docparse/services/docx_parser.ail` skips `<w:commentRangeStart>` / `<w:commentRangeEnd>` during paragraph parsing (they have no text content). To anchor comments to body text positions:

1. During body parse, when `<w:commentRangeStart w:id="N">` is encountered, record `(commentId=N, paragraphIndex=currentParagraphIndex)` in a side table.
2. Same for `<w:commentRangeEnd>`.
3. After full parse, join side table into the comment blocks: set `anchorStart` / `anchorEnd` on each `CommentMeta`.

This is a two-pass operation (body text first, then join) or a single pass with a mutable accumulator. AILANG's effects model makes the mutable accumulator the cleaner path — use a fold with a state record `{paragraphIndex: int, anchorStarts: Map[int,int], anchorEnds: Map[int,int]}`.

---

## Part 4: Thread-tree output in `output_formatter.ail`

The block list is flat (document order). For AI consumption, add a `--threads` rendering mode that groups comment blocks into trees:

```
[Thread: clause 4.2 (paragraphs 12–13)] UNRESOLVED
  Alice Smith (2026-04-28T09:14:00Z): Please clarify "material adverse change" — too vague.
    Bob Jones (2026-04-28T11:02:00Z): Agreed. Suggest adding the LSTA MAC definition.
      Alice Smith (2026-04-29T08:45:00Z): Accepted. I'll redline it.

[Thread: signature block (paragraph 47)] RESOLVED
  Carol Wu (2026-04-27T16:30:00Z): Missing notarisation requirement for Schedule B.
    Bob Jones (2026-04-28T09:00:00Z): Fixed in latest draft.
```

CLI flag:

```bash
./bin/docparse contract.docx --threads
# emits threaded comment view to stdout

./bin/docparse contract.docx --threads --unresolved-only
# emits only unresolved threads (open negotiation points)
```

---

## Implementation plan

| Step | File(s) | Effort |
|------|---------|--------|
| Add `CommentBlock` variant to block ADT | `docparse/types/document.ail` | 0.5 day |
| Parse `commentsExtensible.xml` | `docparse/services/docx_parser.ail` | 1 day |
| Thread anchor IDs through body parse | `docparse/services/docx_parser.ail` | 1 day |
| Thread-tree formatter + CLI flags | `docparse/services/output_formatter.ail` | 0.5 day |
| Golden tests | `benchmarks/office/golden/` + new test DOCX | 0.5 day |
| **Total** | | **~3.5 days** |

---

## Test corpus

- `data/test_files/comment_threaded.docx` — 3-level reply chain, mix of resolved and unresolved
- `data/test_files/comment_no_ext.docx` — old Word format, no `commentsExtensible.xml` (graceful degrade)
- `data/test_files/comment_anchored.docx` — comment ranges spanning multiple paragraphs
- Golden: `benchmarks/office/golden/comment_threaded.json` — full thread tree with all metadata

---

## Acceptance criteria

- [ ] `CommentBlock` in parsed output carries `id`, `author`, `date` (UTC when available), `parentId`, `resolved`, `anchorStart`, `anchorEnd`.
- [ ] A 3-level reply chain is correctly represented with `parentId` links.
- [ ] `resolved: true` appears on comments marked done in `commentsExtensible.xml`.
- [ ] Documents without `commentsExtensible.xml` degrade gracefully: `resolved = false`, `parentId = None`, `dateReliable = false`.
- [ ] `--threads` renders a readable indented thread tree.
- [ ] `--threads --unresolved-only` omits fully-resolved threads.
- [ ] Anchor paragraphs match the paragraph index of the corresponding body text (golden test).
- [ ] Type-check clean: `ailang check docparse/`.
