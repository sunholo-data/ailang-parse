# DocParse v0.13.0 — Built-in Document Chunking

**Status**: PLANNED
**Theme**: Add semantic and structural chunking to DocParse's output pipeline for RAG-ready document segments
**Depends on**: v0.3.0 (Block ADT with 9 variants), v0.7.0 (API server)
**Priority**: HIGH — Unstructured and Docling both ship built-in chunkers; this is the #1 feature gap for RAG pipelines

## Motivation

Today DocParse outputs a flat list of `[Block]`. Downstream consumers (LangChain, LlamaIndex, Haystack) must chunk this themselves before embedding/indexing. Every competitor in the RAG pipeline space now ships chunking:

- **Unstructured**: `chunk_by_title`, `chunk_by_page`, `chunk_by_similarity` — 5 chunking strategies
- **Docling**: `HybridChunker` — combines structural boundaries with token limits
- **Chunkr**: Layout-aware chunking is their entire product
- **LlamaParse**: Delegates to LlamaIndex's `SentenceSplitter` / `SemanticSplitter`

Users who pick DocParse over these tools must then write their own chunking code. That's friction we can eliminate.

### Why DocParse Chunking Is Better

1. **We have the Block ADT** — typed blocks (Heading, Table, List, Section, Change) give us structural boundaries that text-only chunkers miss
2. **We have SectionBlock** — headers/footers, speaker notes, and document sections are already grouped. This is natural chunk boundary information
3. **We have ChangeBlock** — track changes and comments can be included or excluded from chunks (nobody else offers this)
4. **We parse deterministically** — our structural parsing is exact, not ML-inferred. Chunk boundaries based on actual document structure, not guessed layout

### What Users Want

From competitive analysis and RAG pipeline patterns:

1. **Fixed-size chunks** with overlap (simplest, most common)
2. **Structural chunks** that respect block boundaries (don't split a table across chunks)
3. **Semantic chunks** that group related content (heading + its paragraphs)
4. **Page-based chunks** (for PDF provenance tracking)
5. **Token-aware sizing** (not character count — LLM context windows are in tokens)

## Design

### New AILANG Module: `docparse/services/chunker.ail`

```ailang
module docparse/services/chunker

import docparse/types/document (Block, ParsedDocument)

-- Chunking strategy
export type ChunkStrategy = Auto({maxTokens: int, overlap: int})
                          | FixedSize({maxTokens: int, overlap: int})
                          | ByStructure({maxTokens: int, groupUnderHeadings: bool})
                          | BySection({maxTokens: int, includeMeta: bool})
                          | BySimilarity({maxTokens: int, threshold: float})

-- A document chunk with provenance
export type Chunk = {
  id: int,
  text: string,
  blocks: [Block],           -- original blocks in this chunk
  tokenCount: int,
  metadata: ChunkMetadata
}

export type ChunkMetadata = {
  startBlockIndex: int,
  endBlockIndex: int,
  headingContext: string,    -- nearest heading above this chunk
  sectionKind: string,       -- "body", "header", "footer", "notes", etc.
  hasTable: bool,
  hasChange: bool,
  hasComment: bool
}

-- Main entry point
export func chunkDocument(doc: ParsedDocument, strategy: ChunkStrategy) -> [Chunk]

-- Convenience functions
export func chunkAuto(doc: ParsedDocument, maxTokens: int, aiAvailable: bool) -> [Chunk]
export func chunkFixed(doc: ParsedDocument, maxTokens: int, overlap: int) -> [Chunk]
export func chunkByStructure(doc: ParsedDocument, maxTokens: int) -> [Chunk]
export func chunkBySection(doc: ParsedDocument, maxTokens: int) -> [Chunk]
```

### Chunking Strategies

#### 0. Auto (default)

The `Auto` strategy inspects the document and selects the best chunking approach automatically. This is the default when users pass `--chunk` without specifying a strategy.

**Decision logic:**

```
Auto(doc, aiAvailable) =
  1. Count headings:  hasHeadings  = any block is HeadingBlock
  2. Count sections:  hasSections  = any block is SectionBlock
  3. Check format:    isTabular    = format in {xlsx, ods, csv}
  4. Check format:    isSlides     = format in {pptx, odp}

  if isTabular:
      → BySection                  # each sheet/table is a natural chunk
  elif isSlides:
      → BySection                  # each slide is a natural chunk
  elif hasHeadings:
      → ByStructure                # heading hierarchy drives chunk boundaries
  elif hasSections and not hasHeadings:
      → BySection                  # sections exist but no headings (e.g. headers/footers only)
  elif aiAvailable and blockCount > 20:
      → BySimilarity               # no structure to exploit; use semantic grouping
  else:
      → FixedSize                  # fallback: simple token-based splitting
```

**Rationale for each decision:**

| Document type | Example | Strategy chosen | Why |
|---|---|---|---|
| DOCX/ODT with headings | Report, contract, paper | **ByStructure** | Headings define the document's logical structure — chunks align with the author's organization |
| PPTX/ODP | Slide deck | **BySection** | Each slide is a self-contained unit. Splitting across slides loses context. Speaker notes stay with their slide |
| XLSX/ODS/CSV | Spreadsheet | **BySection** | Each sheet is a logical unit. Row groups within sheets are kept together |
| Markdown/HTML with headings | Docs, blog posts | **ByStructure** | `#`/`<h1>` headings create the same heading hierarchy as Office docs |
| PDF (AI-parsed, has headings) | Scanned report | **ByStructure** | AI parser extracts heading levels — same logic applies |
| PDF (AI-parsed, no headings) | Scanned form, receipt | **BySimilarity** (if AI available) | No structural cues → semantic grouping is the best option |
| Plain text, EPUB without headings | Novel, raw text | **FixedSize** | No structure, no AI → token-based splitting is the only reliable option |

**Why Auto is the right default:**

- Users shouldn't need to know chunking strategies to get good results
- DocParse already knows the document format and block composition — the strategy choice is deterministic from that information
- Auto never picks a worse strategy than FixedSize (the baseline) — it can only improve on it
- The decision is logged in the response (`strategy_chosen` field) so users can see what was picked and override if needed

**API response includes the resolved strategy:**

```json
{
  "chunks": [...],
  "strategy_requested": "auto",
  "strategy_chosen": "structure",
  "strategy_reason": "Document has 8 headings across 3 levels"
}
```

#### 1. FixedSize (baseline)

Split document text into chunks of `maxTokens` tokens with `overlap` token overlap. Respects block boundaries — will not split mid-block unless a single block exceeds `maxTokens`.

```
[Block1: 100tok] [Block2: 200tok] [Block3: 150tok] [Block4: 300tok]
                                   ↓ maxTokens=400, overlap=50
[Chunk1: Block1+Block2 = 300tok] [Chunk2: Block2(last 50)+Block3+Block4(first 200) = 400tok] ...
```

Default: `maxTokens=512, overlap=50`

#### 2. ByStructure (recommended for Office docs)

Groups blocks under their nearest heading. A new chunk starts when:
- A HeadingBlock is encountered (at level ≤ current)
- Token count would exceed `maxTokens`
- A SectionBlock boundary is hit (e.g., header → body → footer)

This produces chunks like:
```
Chunk 1: "Introduction" heading + its 3 paragraphs + 1 list
Chunk 2: "Methodology" heading + 2 paragraphs + 1 table
Chunk 3: "Results" heading + 1 paragraph + 2 tables
```

Each chunk's `headingContext` field preserves the heading hierarchy for retrieval context.

#### 3. BySection

Uses SectionBlock boundaries as primary split points. Good for documents with distinct sections (speaker notes in PPTX, sheets in XLSX, header/footer content).

Track changes and comments get their own chunks (or are appended to the relevant content chunk based on `includeMeta`).

#### 4. BySimilarity (requires AI)

Uses embeddings to group semantically similar blocks. Requires `--ai` flag. Most expensive but best for documents without clear structural boundaries.

This strategy uses the embedding infrastructure from the companion embeddings feature (v0.13.0).

### Token Counting

AILANG doesn't have a tokenizer. Options:

1. **Approximate**: `tokenCount ≈ wordCount * 1.3` (good enough for most use cases)
2. **Exact via AI effect**: Call the model's tokenizer if available (Gemini and Claude expose token counts)
3. **Character-based fallback**: `tokenCount ≈ charCount / 4`

Start with option 1 (word-based approximation). Add exact counting as an enhancement.

### API Integration

New endpoint:

```
POST /api/v1/chunk
Content-Type: multipart/form-data

file: <document>
strategy: "auto"               # auto (default), fixed, structure, section, similarity
max_tokens: 512
overlap: 50
group_under_headings: true
include_changes: true          # include track changes in chunks
include_comments: true         # include comments in chunks
```

Response:
```json
{
  "chunks": [
    {
      "id": 0,
      "text": "Introduction\nThis report covers...",
      "token_count": 245,
      "metadata": {
        "start_block_index": 0,
        "end_block_index": 4,
        "heading_context": "Introduction",
        "section_kind": "body",
        "has_table": false,
        "has_change": false,
        "has_comment": false
      }
    }
  ],
  "total_chunks": 12,
  "strategy": "structure",
  "elapsed_ms": 3
}
```

Also add `?chunk=true&chunk_strategy=structure&max_tokens=512` query params to existing `/api/v1/parse` endpoint — returns parsed document + chunks in one call.

### CLI Integration

```bash
# Parse + chunk in one step (Auto picks best strategy per format)
./bin/docparse report.docx --chunk                        # auto → structure (has headings)
./bin/docparse slides.pptx --chunk                        # auto → section (slides)
./bin/docparse data.xlsx --chunk                          # auto → section (sheets)
./bin/docparse scan.pdf --chunk --ai gemini-2.5-flash     # auto → structure or similarity

# Override with explicit strategy
./bin/docparse report.docx --chunk --strategy fixed --max-tokens 1024 --overlap 100
./bin/docparse report.docx --chunk --strategy section

# Output chunks as JSON
./bin/docparse report.docx --chunk --json

# Pipe to embedding
./bin/docparse report.docx --chunk | ./embed.sh
```

### Unstructured API Compatibility

Map to Unstructured's chunking parameters in the compat endpoint:

```
POST /general/v0/general
chunking_strategy: "by_title"     → ByStructure
chunking_strategy: "by_page"      → BySection
chunking_strategy: "by_similarity" → BySimilarity
chunking_strategy: "basic"        → FixedSize
max_characters: 500               → maxTokens ≈ max_characters / 4
overlap: 100                      → overlap tokens
```

## Billing

Chunking is **zero credits** for all strategies except BySimilarity. See [v0_13_0_embeddings.md](v0_13_0_embeddings.md#billing--credits-integration) for the full credits table.

| Strategy | Credits | Rationale |
|----------|---------|-----------|
| Auto (resolves to non-similarity) | 0 | CPU-only |
| FixedSize | 0 | CPU-only |
| ByStructure | 0 | CPU-only |
| BySection | 0 | CPU-only |
| BySimilarity | 2 | Requires embedding API call for similarity grouping |
| Auto (resolves to similarity) | 2 | Inherits from BySimilarity |

**Why free**: Chunking is a CPU operation on already-parsed blocks. It costs us nothing. Charging for it would push users to chunk client-side (using LangChain/LlamaIndex splitters), which defeats the purpose of offering an integrated pipeline. The revenue capture happens at parse time (existing credits) and embed time (new credits). Free chunking makes the full pipeline more attractive than cobbling together separate tools.

**BySimilarity exception**: This strategy calls the embedding API to compute block similarity before grouping. The 2-credit cost covers the embedding API call, same as `embed_text_batch`.

## Implementation Plan

1. **`chunker.ail`** — Core chunking module with FixedSize and ByStructure strategies
2. **Token estimation** — Word-based approximation helper
3. **BySection strategy** — Uses SectionBlock boundaries
4. **API endpoint** — `POST /api/v1/chunk` + query params on `/parse`
5. **CLI flags** — `--chunk`, `--strategy`, `--max-tokens`, `--overlap`
6. **Unstructured compat** — Map chunking_strategy params
7. **BySimilarity** — Depends on embedding module; implement last
8. **Tests** — Chunk golden files with each strategy, verify no content loss

## Metrics

- Chunk count per strategy per test file (regression baseline)
- No content loss: `join(chunk.text for chunk in chunks) ≈ join(block.text for block in blocks)`
- Token count accuracy: within 10% of actual model tokenizer
- Performance: <5ms overhead for chunking a typical document

## Risks

1. **Token counting accuracy** — Word-based approximation varies by language (CJK is worse). Mitigate: expose `token_count` in output so users can verify.
2. **Table chunking** — Large tables shouldn't be split but may exceed `maxTokens`. Decision: keep tables whole and mark chunk as oversized rather than splitting rows.
3. **Track changes in chunks** — Should a deletion appear in the chunk? Default: include all changes with type annotation. Let users filter via `include_changes` param.
