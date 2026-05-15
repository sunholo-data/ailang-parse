# Design Doc: SDKs v0.7.0 — Chunk Extras, Image Emission, Comments, Table-Cell Escaping

**Status**: Planned
**Date**: 2026-05-16
**Author**: Mark + Claude
**Source**: Two follow-up messages from `multivac-system-services` after the v0.6.0 migration:
- `msg_20260515_183500_d9476a0d` — migration ack. 115 LOC → 25 LOC + 230 LOC → 40 LOC across two chunker files. `FlattenPolicy` holds up. One soft suggestion (`extras` field on `ChunkMetadata`).
- `msg_20260516_012720_2ed63396` — end-to-end field findings against `docparse.ailang.sunholo.com`. Track-changes flow validated; three gaps identified on real DOCX samples.

---

## Problem

The v0.6.0 `FlattenPolicy` covers the common RAG-ingestion case but hits four limits in production use:

1. **`ChunkMetadata` is fixed-shape, no extension point.** Consumers who want to embed extras (`image_data_length`, audio mime, per-tenant tags) have to either subclass `Chunk` (loses `to_dict()` JSON-friendliness) or carry a second parallel dict. multivac flagged this as nice-to-have.

2. **Images are invisible to free-tier consumers.** `pandoc_inline_images.docx` returned 3 blocks → 2 text chunks, **zero image chunks**, even with `embed_images=True`. Reason: free-tier (no AI) means `ImageBlock.description` is empty, and the SDK's `_flatten_blocks` currently drops empty-description images. So there is no consumer-controllable path to image content at all without going to a paid AI flow — and a consumer who wants to OCR locally, fingerprint by `mime+data_length`, or just *count* images has no signal.

3. **Comments come back as plain text blocks.** `comments.docx` returns 9 generic `text` blocks. The chunker has no way to tell body text from a comment. This is parser-side — the `CommentBlock` ADT variant is scoped as part of [v0_19_0_comment_threading.md](../v0_19_0/v0_19_0_comment_threading.md) but hasn't shipped yet. The SDK can land its half of the change now (a `CommentBlock` variant + an `embed_comments` policy knob) so consumers don't need a second SDK upgrade once the parser catches up.

4. **Table cells with internal newlines wreck the row-prefix format.** Real samples (`docx-hdrftr.docx`, `pandoc_table_list.docx`) emit cells containing `\n` — the resulting `"h1 | h2\nc1 | c2"` is ambiguous. Same applies to cells containing `|`. Today, this silently corrupts ~3% of table-row chunks in multivac's corpus.

All four are SDK-only fixes (Python), with the comments one designed to dovetail with parser work that's already designed in v0.19.0.

---

## Non-Goals

- **Per-call `describe=True` for AI image captions.** Multivac flagged this as an alternative to (2), but it requires a docparse-API surface change ("force AI captioning on a free tier? reject? burn AI quota for the call?"), tier-policy work, and price-coupling discussion. Scoped to a separate v0.21+ doc; this doc only ships the SDK-side "always emit ImageBlock" path so consumers can decide locally.
- **Subclassing `Chunk` or `ChunkMetadata`.** The `extras` field is the official extension point — discoverable, JSON-friendly, no inheritance gymnastics.
- **Cross-SDK parity for v0.6.0 features.** Porting Python's `parse_gs_uri` / `flatten` / `RetryPolicy` to JS + Go is its own sprint, tracked separately. v0.7.0 is Python-only enhancement.
- **Comment write-back / threading reconciliation in the SDK.** That's a generator-side concern. SDK reads what the parser emits.
- **General-purpose table-flattening DSL.** Two narrow knobs (`on_table_cell_newlines`, `on_table_cell_pipes`) cover the observed bugs. Anything more goes through the existing `Callable[[Block, ChunkMetadata], List[Chunk]]` escape hatch.

---

## Part 1: `ChunkMetadata.extras` — open-ended consumer fields

### Shape

```python
@dataclass
class ChunkMetadata:
    block_type: str = ""
    section_path: List[str] = field(default_factory=list)
    block_index: int = 0
    # ... existing optional fields (table_id, row_index, change_author, etc.) ...
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = { ... existing ... }
        if self.extras:
            out["extras"] = dict(self.extras)
        return out
```

### How callbacks populate it

The `on_table` callable (and the future `on_image` / `on_comment` callables — see Part 3) get a fresh `ChunkMetadata` and can mutate `.extras` before returning chunks. No new entry point; the existing escape hatch grows naturally:

```python
def my_table(b: Block, md: ChunkMetadata) -> List[Chunk]:
    md.extras["tenant_id"] = "acme"
    md.extras["confidence"] = 0.93
    return [Chunk(text=..., metadata=md)]
```

### Why a dict and not typed slots

The whole point is consumer extensibility for fields we *won't* anticipate. Locking the type means we ship a v0.7.1 every time someone adds a custom tag. Documented as "JSON-friendly values please — these end up in Pinecone/Vertex metadata."

### Compatibility

Additive. Existing `to_dict()` output is unchanged when `extras` is empty (the field is omitted, not emitted as `"extras": {}`).

---

## Part 2: Always emit `ImageBlock`, with mime+placeholder fallback

### Current behaviour (v0.6.0)

```python
elif bt == "image" or bt == "ImageBlock":
    if policy.embed_images and (b.description or b.transcription):
        out.append(Chunk(text=..., metadata=...))
```

The `or b.transcription` is the only escape from the "drop if empty" rule. For DOCX images without OCR, both are empty — chunk is dropped.

### Target behaviour

When `embed_images=True`, *always* emit an `ImageBlock` chunk. Text content tier-order:

1. `description` (AI caption) if present
2. `transcription` (OCR / audio) if present
3. Synthetic placeholder: `f"[image: {mime}, {data_length} bytes]"`

The placeholder is intentionally machine-readable so consumers can detect "no AI caption available" cheaply and route to a local OCR step if they want. Metadata always carries `image_mime` and a new `image_data_length` so the consumer doesn't have to parse the placeholder string.

```python
elif bt == "image" or bt == "ImageBlock":
    if policy.embed_images:
        text = (b.description or b.transcription
                or f"[image: {b.mime or 'unknown'}, {b.data_length} bytes]")
        md = ChunkMetadata(
            block_type="image",
            section_path=...,
            block_index=idx,
            image_mime=b.mime or None,
        )
        md.extras["image_data_length"] = b.data_length
        md.extras["image_has_description"] = bool(b.description)
        out.append(Chunk(text=text, metadata=md))
```

### Why not a separate `emit_empty_images: bool` knob

Three knobs is one too many. `embed_images=True` already means "I want image chunks" — the natural reading is "even when there's no caption," not "only when AI captioned." This change makes the policy do what its name says.

### Migration

Behaviour change: free-tier consumers who set `embed_images=True` will now get placeholder chunks for every image. Mitigation: clearly noted in CHANGELOG under "Behaviour changes." Consumers who want the v0.6.0 behaviour (skip empty) can write a one-line filter:

```python
chunks = [c for c in result.flatten(policy)
          if c.metadata.block_type != "image" or c.metadata.extras.get("image_has_description")]
```

---

## Part 3: `CommentBlock` + `embed_comments` policy knob

### Coupling with parser work

The actual parser-side change — extracting comments from `word/comments.xml` as `CommentBlock` instead of folding them into body text — is designed in [v0_19_0_comment_threading.md](../v0_19_0/v0_19_0_comment_threading.md). That work is `Planned`. The SDK landing this part of v0.7.0 *before* the parser ships costs nothing (no parser output → no comment chunks) and means consumers don't need a second SDK upgrade once the parser catches up.

### Block-side

```python
@dataclass
class Block:
    # ... existing fields ...
    # CommentBlock (parser ships this in a future docparse module version)
    resolved: bool = False  # threading: is the comment resolved?
    # Reuses existing `author`, `date`, `text` fields from ChangeBlock/TextBlock.
```

`Block.from_dict` already absorbs unknown fields gracefully via the recursive section walker; nothing more needed there. The `type` discriminator gains a `"comment"` value.

### Policy-side

```python
@dataclass
class FlattenPolicy:
    # ... existing fields ...
    embed_comments: bool = False
```

Default off, same as `embed_changes`. Most RAG pipelines don't want comments in the embed corpus; legal-review tools (Stella, contract negotiation tooling) will explicitly enable.

### Flatten-side

```python
elif bt == "comment" or bt == "CommentBlock":
    if policy.embed_comments and b.text:
        md = ChunkMetadata(
            block_type="comment",
            section_path=...,
            block_index=idx,
            change_author=b.author or None,  # reuse the field — same semantics
        )
        md.extras["resolved"] = b.resolved
        md.extras["date"] = b.date or None
        out.append(Chunk(text=b.text, metadata=md))
```

`change_author` is reused on purpose. Comments and tracked changes both have an author; consumers building "who said what" retrieval will index on a single field rather than special-casing `comment_author` vs `change_author`.

### Why not reuse `ChangeBlock(change_type="comment")`

Tempting, but it loses the `resolved` semantic and conflates two different document objects. Threaded resolution status (`resolved: true`) is meaningful for comments, meaningless for tracked changes. Two block types, one field-shape overlap.

---

## Part 4: Table-cell escaping knobs

### Shape

```python
@dataclass
class FlattenPolicy:
    # ... existing fields ...
    on_table_cell_newlines: str = "preserve"   # "preserve" | "escape" | "space"
    on_table_cell_pipes:    str = "preserve"   # "preserve" | "escape" | "space"
```

Validated to one of the three literal strings at construction (raise `ValueError` for typos — cheap, prevents silent miscoding). `Literal` typing in the docstring; no `Literal` import to keep py3.8 compatibility.

### Semantics

For each cell's text, transform before joining with `" | "`:

| Mode | Newline behaviour | Pipe behaviour |
|------|-------------------|----------------|
| `"preserve"` (default) | leave as-is — v0.6.0 behaviour | leave as-is |
| `"escape"` | `\n` → `\\n` (literal backslash + n; round-trippable) | `|` → `\\|` |
| `"space"` | `\n` → `" "` (lossy, retrieval-friendly) | `|` → `" "` (lossy) |

Applied independently — a consumer can `escape` newlines while leaving pipes untouched.

### Default choice

`"preserve"` keeps v0.6.0 behaviour. Migration-safe. The README will recommend `"space"` for embedding workloads and `"escape"` for round-trippable structured retrieval.

### Why not a callback

`Callable[[str], str]` on each cell is the obvious "more general" answer, but it pushes the wrong cognitive load: every consumer would write the same `replace("\n", " ")` lambda. The three-mode enum gives 90% of consumers a working answer with zero code; the existing `on_table` callable still covers the remaining 10%.

---

## Cross-SDK parity

| Part | Python (v0.7.0) | JS / Go |
|------|------------------|---------|
| 1. `ChunkMetadata.extras` | v0.7.0 | follows JS/Go `flatten` port (separate sprint) |
| 2. Always-emit ImageBlock | v0.7.0 | same |
| 3. `CommentBlock` + `embed_comments` | v0.7.0 (forward-compat, awaits parser) | same |
| 4. Table-cell escape knobs | v0.7.0 | same |

JS + Go don't have `flatten()` yet (planned in the v0.6.0 design doc for a follow-up sprint), so v0.7.0 is Python-only by definition. When JS/Go port `flatten()`, they pick up the v0.7.0 shape, not the v0.6.0 one.

---

## Risks and migration

- **Image emission behaviour change.** Free-tier callers with `embed_images=True` will see new placeholder chunks. Mitigation: CHANGELOG entry, one-line filter recipe in README. The v0.6.0 behaviour was effectively "silently drop" — arguably the buggier choice.
- **`extras` becoming a junk drawer.** If consumers dump arbitrary objects in there and downstream Pinecone/Vertex chokes, that's on them; the README sets expectations ("JSON-serializable values only"). We don't `json.dumps` it for them.
- **`CommentBlock` shipping before parser.** Zero runtime cost — the flatten branch is dead code until the parser produces `type: "comment"` blocks. The `Block` dataclass gains one field (`resolved`) that's harmless when unset.
- **`Literal`-type validation at policy construction.** Adds a `if x not in {...}: raise ValueError(...)` in `__post_init__`. Tiny, but it's the only place `FlattenPolicy` raises today; balance is worth it because the wrong value would otherwise corrupt output silently.

---

## Acceptance criteria

- [ ] `ChunkMetadata.extras` exists, omitted from `to_dict()` when empty
- [ ] `flatten(FlattenPolicy(embed_images=True))` emits chunks for empty-description images with `extras["image_data_length"]` and a placeholder text
- [ ] `FlattenPolicy(embed_comments=True)` plus a synthetic `Block(type="comment", text="...", author="A", resolved=False)` produces a `block_type="comment"` chunk with `change_author="A"`, `extras["resolved"]=False`
- [ ] `FlattenPolicy(on_table_cell_newlines="space")` flattens a real table-row with internal newlines into a clean `" | "`-separated string
- [ ] `FlattenPolicy(on_table_cell_pipes="escape")` round-trips `"a|b"` as `"a\\|b"` inside the row text
- [ ] `FlattenPolicy(on_table_cell_newlines="bogus")` raises `ValueError` at construction, not at flatten time
- [ ] CHANGELOG entry under "Behaviour changes" for image emission
- [ ] Python tests: ≥8 new cases covering all of the above
- [ ] Existing 122 Python tests still pass

---

## Out of scope (revisit later)

- **`describe=True` for AI image captions.** Real product question; needs API-side work; tracked separately.
- **JS + Go port of `flatten()`** (including v0.7.0 shape). Separate sprint.
- **Sentence/paragraph splitting inside text blocks.** v0.6.0 splits at the `max_chunk_chars` boundary on whitespace. Smarter splitting (sentence boundaries, semantic chunking) is a separate design.
- **Per-table caption emission.** When tables have captions in the original document, those currently land as separate text blocks; emitting them as `ChunkMetadata.extras["table_caption"]` would tighten retrieval. Plausible v0.8.0.

---

## References

- v0.6.0 ergonomics doc: [v0_20_0_sdk_ergonomics.md](v0_20_0_sdk_ergonomics.md)
- Parser-side comment work: [../v0_19_0/v0_19_0_comment_threading.md](../v0_19_0/v0_19_0_comment_threading.md) — gates Part 3 from doing anything in practice but not from shipping
- Migration ack: `msg_20260515_183500_d9476a0d`
- Field-test wishlist: `msg_20260516_012720_2ed63396`
- Implementation files: [sdks/python/ailang_parse/types.py](../../../sdks/python/ailang_parse/types.py) (flatten + policy live here)
