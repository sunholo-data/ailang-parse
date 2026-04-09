# `blocks_to_markdown` standalone helper

**Status**: PLANNED (2026-04-08)
**Source**: Aitana Labs Python SDK feedback (2026-04-09), item #4
**Target version**: v0.10.0 SDK

## Goal

> "We have a `parse_outcome` that holds a `list[Block]` from the SDK. We then want to render those blocks back to Markdown to feed into our LLM pipeline. Today we wrote our own renderer because the SDK doesn't expose one — but the AILANG side already has `renderMarkdown()`. Could we get a `blocks_to_markdown(blocks, ...)` helper in each SDK?"

A standalone, network-free helper that takes a `list[Block]` and returns a Markdown string. Useful for:

- Re-rendering after client-side block manipulation (filtering, redacting, splitting).
- Caching block trees and rendering on demand without re-hitting the API.
- LLM context preparation.

## Background

In v0.4.6 we fixed [#2 markdown raw-string handling](v0_10_0_async_sdk.md) so callers can ask the API for `outputFormat="markdown"` and get a `ParseResult.text` back. That covers the "render once at parse time" case. It does **not** cover:

- Filtering blocks before rendering (e.g. drop all `image` blocks for an LLM that can't see them).
- Re-using a cached `list[Block]` across multiple render passes.
- Offline rendering with no API key / no network.

The AILANG side has the canonical renderer in [docparse/services/output_formatter.ail](../../../docparse/services/output_formatter.ail) — `renderMarkdown(blocks: List[Block]): String`.

## Design

### The cross-SDK API surface

```python
from ailang_parse.render import blocks_to_markdown

md = blocks_to_markdown(
    blocks,
    include_metadata=False,        # Prepend a YAML frontmatter block
    annotate_merged_cells=True,    # Mark merged table cells with `[merged]`
    show_tracked_changes=True,     # Render `change` blocks inline
    heading_style="atx",           # "atx" (#) vs "setext" (===)
)
```

```ts
import { blocksToMarkdown } from "@ailang/parse/render";

const md = blocksToMarkdown(blocks, { includeMetadata: false });
```

```go
md := docparse.BlocksToMarkdown(blocks, docparse.RenderOptions{
    IncludeMetadata: false,
})
```

```r
md <- ailangparse::blocks_to_markdown(blocks, include_metadata = FALSE)
```

### Source-of-truth question

Two implementation strategies:

#### Option A — port the AILANG `renderMarkdown` logic into each SDK

Each SDK reimplements the renderer in its native language. Pros:

- Pure offline, no network round-trip.
- Caller never burns AI quota.
- Fast — no HTTP latency.

Cons:

- Four reimplementations to keep in sync with the AILANG source.
- Drift risk: a tweak to AILANG's renderer (e.g. how merged cells are marked) won't reach SDKs without a port.
- Test surface multiplies — every renderer behavior needs golden tests in every language.

#### Option B — call the parse endpoint with `output_format="markdown"`

The SDK helper is a thin wrapper that POSTs the blocks back to the API with `outputFormat="markdown"` and unwraps `ParseResult.text`. Pros:

- One implementation (AILANG side, already exists).
- Renderer changes propagate automatically to all SDKs.
- Tiny code in SDKs.

Cons:

- Requires network + API key.
- Counts against request quota.
- Higher latency (HTTP round-trip per render).
- The current parse endpoint takes a *file*, not a `list[Block]` — it would need a sibling endpoint `/api/v1/render` that accepts blocks and returns a string.

**Recommendation**: do Option A. Aitana already wrote their own renderer, signaling that offline rendering matters more to users than implementation simplicity matters to us. The test surface is bounded (one golden corpus shared across SDKs).

### Test strategy

A shared golden corpus lives at `data/test_files/render_golden/`:

- `blocks_simple.json` — text + headings
- `blocks_table_merged.json` — tables with merged cells and headers
- `blocks_changes.json` — tracked changes (insertions + deletions)
- `blocks_nested_lists.json` — nested ordered/unordered lists
- `blocks_section_recursive.json` — sectioning with nested children

Each file pairs an input JSON with an expected `expected.md`. Each SDK runs the same corpus through its renderer and asserts byte-equality with `expected.md`. Drift between SDKs becomes a test failure.

## Open questions

1. **What rendering options matter?** Aitana mentioned `include_metadata`, `annotate_merged_cells`, `show_tracked_changes`. The AILANG renderer does not currently take options — it always renders with a fixed shape. Adding options means exposing them on the AILANG side first or only in SDKs. Decision needed.
2. **Do we need an HTML renderer too?** Same shape (`blocks_to_html`). Probably yes, but Aitana did not ask for it. Defer until requested.
3. **Should we expose the AILANG renderer via WASM?** Long-term, the cleanest solution to "keep in sync" is to compile `renderMarkdown` to WASM and call it from each SDK. This is a much larger project — out of scope for v0.10.0 but worth a follow-up design doc.

## Out of scope

- HTML rendering (defer).
- PDF rendering (Quarto integration is the answer — see `v0_10_0_quarto_integration.md`).
- Custom themes / templates.
- WASM-based renderer sharing (separate doc).
