# DocParse v0.13.0 — Hierarchy Metadata

**Status**: PLANNED
**Theme**: Add parent-child relationships and document hierarchy to Block ADT output
**Depends on**: v0.3.0 (Block ADT), v0.7.0 (API server)
**Priority**: MEDIUM — improves RAG retrieval quality and enables structural navigation; competitors (Docling, Unstructured) are adding this

## Motivation

DocParse currently outputs a flat `[Block]` list. There's no way to know that paragraph 5 belongs to heading 2, or that a table sits inside a specific section. This hierarchy information exists in the original documents — we just don't expose it.

Why this matters:

1. **RAG retrieval context** — When a chunk matches a query, the retriever should know the heading path ("Introduction > Background > Related Work") to provide context to the LLM. Without hierarchy, the heading is just another block in the list.

2. **Structural navigation** — API consumers want to say "give me everything under heading 'Methodology'" or "find all tables in section 3". A flat list requires post-hoc inference.

3. **Chunking quality** — The chunking module (v0.13.0) needs hierarchy to implement `ByStructure` properly. Heading hierarchy determines where chunks start and end.

4. **Competitive parity** — Docling's `DoclingDocument` has a hierarchical document model. Unstructured's elements have `parent_id` fields. We need at least parity.

### What We Already Have

The Block ADT already has partial hierarchy:

- **SectionBlock** wraps blocks in named sections (headers, footers, speaker notes)
- **HeadingBlock** has a `level` field (1-6) implying nesting
- **ListBlock** has `items` (flat — no nested list support yet)

But there's no explicit parent-child linkage between blocks. A HeadingBlock at level 2 followed by TextBlocks doesn't formally "own" those TextBlocks.

## Design

### Approach: Enrichment Layer (Not ADT Change)

Rather than modifying the Block ADT (which would break all 23 service modules), add a **hierarchy enrichment layer** that annotates blocks with relationships.

This keeps the core ADT simple and backward-compatible. Hierarchy is opt-in.

### New Types

```ailang
module docparse/services/hierarchy

import docparse/types/document (Block, ParsedDocument)

-- A block annotated with hierarchy information
export type AnnotatedBlock = {
  block: Block,
  index: int,              -- position in flat block list
  parentIndex: int,        -- index of parent block (-1 for root)
  depth: int,              -- nesting depth (0 = root level)
  headingPath: [string],   -- breadcrumb trail: ["Introduction", "Background"]
  sectionKind: string,     -- "body", "header", "footer", "notes", "sheet:<name>"
  children: [int]          -- indices of direct children
}

-- Hierarchical document view
export type DocumentTree = {
  document: ParsedDocument,
  annotatedBlocks: [AnnotatedBlock],
  rootIndices: [int]       -- top-level block indices
}

-- Build hierarchy from flat block list
export func buildHierarchy(doc: ParsedDocument) -> DocumentTree

-- Query helpers
export func getChildren(tree: DocumentTree, blockIndex: int) -> [AnnotatedBlock]
export func getSubtree(tree: DocumentTree, blockIndex: int) -> [AnnotatedBlock]
export func findByHeadingPath(tree: DocumentTree, path: [string]) -> [AnnotatedBlock]
export func getBlocksInSection(tree: DocumentTree, sectionKind: string) -> [AnnotatedBlock]
```

### Hierarchy Construction Rules

The `buildHierarchy` function walks the flat `[Block]` list and infers parent-child relationships:

1. **HeadingBlock creates a scope** — All subsequent blocks until the next heading of equal or higher level are children of that heading.

   ```
   Heading L1 "Introduction"     → depth 0, parent -1
     Text "This report..."       → depth 1, parent 0
     Text "We analyzed..."       → depth 1, parent 0
     Heading L2 "Background"     → depth 1, parent 0
       Text "Prior work..."      → depth 2, parent 3
       Table [...]               → depth 2, parent 3
     Heading L2 "Scope"          → depth 1, parent 0
       Text "This covers..."     → depth 2, parent 5
   Heading L1 "Methodology"      → depth 0, parent -1
   ```

2. **SectionBlock is a natural parent** — Its contained `blocks` are already children. Assign `sectionKind` from the SectionBlock's `kind` field.

3. **ListBlock items** — Currently flat strings. Mark with `sectionKind: "list"`. Future: support nested list items if AILANG gets recursive types.

4. **ChangeBlock and comment blocks** — Attach to the nearest preceding content block as siblings at the same depth. They annotate content, not structure.

5. **TableBlock** — Standalone at current depth. Tables don't have children.

6. **Root level** — Blocks before the first heading, or blocks not inside any section, are root-level (depth 0, parent -1).

### Heading Path (Breadcrumb)

Every block gets a `headingPath` — the chain of heading texts from root to the block's containing heading:

```
headingPath: ["Introduction", "Background"]  → this block is under Introduction > Background
headingPath: []                               → this block is before any heading
headingPath: ["Slide 3", "Speaker Notes"]     → PPTX slide 3, speaker notes section
```

This is the single most useful field for RAG — it gives every chunk its structural context.

### API Output

Add `?hierarchy=true` query parameter to `/api/v1/parse`:

```json
{
  "format": "docx",
  "filename": "report.docx",
  "metadata": { ... },
  "blocks": [ ... ],
  "hierarchy": {
    "annotated_blocks": [
      {
        "index": 0,
        "block_type": "Heading",
        "parent_index": -1,
        "depth": 0,
        "heading_path": [],
        "section_kind": "body",
        "children": [1, 2, 3]
      },
      {
        "index": 1,
        "block_type": "Text",
        "parent_index": 0,
        "depth": 1,
        "heading_path": ["Introduction"],
        "section_kind": "body",
        "children": []
      }
    ],
    "root_indices": [0, 7, 15]
  }
}
```

The `blocks` array stays unchanged for backward compatibility. `hierarchy` is only present when requested.

### CLI Integration

```bash
# Parse with hierarchy
./bin/docparse report.docx --hierarchy

# Query specific section
./bin/docparse report.docx --hierarchy --section "Methodology"

# Show heading tree (overview mode)
./bin/docparse report.docx --hierarchy --tree
# Output:
# Introduction
#   Background
#   Scope
# Methodology
#   Data Collection
#   Analysis
# Results
#   Table: Q1 Revenue
# Conclusion
```

### Integration with Chunking

The chunking module uses hierarchy metadata for the `ByStructure` strategy:

```
chunkByStructure(doc, maxTokens=512)
  → buildHierarchy(doc)
  → walk tree, group blocks under headings
  → split when token count exceeds limit
  → each chunk inherits headingPath from its blocks
```

This means `Chunk.metadata.headingContext` comes directly from `AnnotatedBlock.headingPath`.

### Format-Specific Considerations

| Format | Hierarchy Source |
|--------|-----------------|
| DOCX | Heading styles (Heading 1-6) define tree. Sections from headers/footers/comments. |
| PPTX | Each slide is a root node. Title shape → heading. Speaker notes → section. |
| XLSX/ODS | Each sheet is a root node. Merged header rows → headings. |
| HTML | `<h1>`-`<h6>` tags, `<section>`, `<article>`, `<header>`, `<footer>` |
| Markdown | `#`-`######` headings |
| EPUB | Chapter structure from spine + heading levels within chapters |
| ODT/ODP | Same as DOCX/PPTX (ODF heading styles) |
| CSV | No hierarchy (flat table) — single root with all rows |
| PDF | Inferred from AI output heading levels |

## Billing

Hierarchy metadata is **zero credits** — always free across all tiers. It's a CPU-only enrichment of already-parsed blocks (no AI calls). See [v0_13_0_embeddings.md](v0_13_0_embeddings.md#billing--credits-integration) for the full v0.13.0 credits table.

## Implementation Plan

1. **`hierarchy.ail`** — Core module: `buildHierarchy`, `AnnotatedBlock`, `DocumentTree` types
2. **Heading scope algorithm** — Walk blocks, track heading stack, assign parents
3. **SectionBlock unwrapping** — Flatten section blocks into annotated blocks with `sectionKind`
4. **Query helpers** — `getChildren`, `getSubtree`, `findByHeadingPath`
5. **API integration** — `?hierarchy=true` on `/api/v1/parse`
6. **CLI flags** — `--hierarchy`, `--tree`, `--section`
7. **Chunking integration** — Wire into `ByStructure` chunker
8. **Golden tests** — Generate hierarchy output for all 54 golden files, verify manually

## Metrics

- Every block must have a valid `parentIndex` (either -1 or a valid index)
- `headingPath` must be non-empty for all blocks after the first heading
- Round-trip: flattening the tree must produce the original block list
- Performance: <2ms overhead for hierarchy construction

## Risks

1. **Documents without headings** — Some documents (especially spreadsheets, CSV) have no heading structure. Result: all blocks are root-level. This is correct but not useful. The `BySection` chunking strategy handles this better.
2. **Inconsistent heading levels** — Documents that jump from H1 to H4. Decision: treat missing levels as implicit (H4 under H1 → depth 2, not depth 4).
3. **Recursive SectionBlocks** — If a SectionBlock contains another SectionBlock, handle recursively. Current parsers don't generate this, but the algorithm should handle it.
