# DocParse v0.13.0 — Built-in Embedding Generation

**Status**: PLANNED
**Theme**: Leverage existing AI API key infrastructure to optionally generate embeddings alongside parsed output
**Depends on**: v0.7.0 (API server), v0.8.0 (API keys/tiers), v0.13.0 chunking (for chunk-level embeddings)
**Priority**: MEDIUM — reduces integration friction for RAG pipelines; unique differentiator when combined with structural parsing

## Motivation

The typical RAG pipeline today looks like:

```
Document → Parse (DocParse) → Chunk (manual) → Embed (separate API call) → Index (vector DB)
```

DocParse currently handles step 1. With chunking (v0.13.0), we handle steps 1-2. Embeddings would let us handle steps 1-3 in a single API call:

```
Document → DocParse (parse + chunk + embed) → Index (vector DB)
```

### Why This Makes Sense for DocParse

1. **We already have AI API keys** — Users configure Gemini, Claude, or Ollama for PDF parsing. The same credentials work for embedding models. Zero additional setup.

2. **AILANG's AI effect abstracts the provider** — Same `--ai` flag that powers PDF parsing can route to embedding models. No new infrastructure needed.

3. **Structural context improves embeddings** — We can embed not just the chunk text but include heading paths, section types, and metadata. A chunk embedded as "Methodology > Data Collection: We surveyed 500 participants..." retrieves better than just "We surveyed 500 participants..."

4. **Competitive gap** — No document parser ships built-in embeddings. Users always need a separate embedding step. This is a genuine differentiator:
   - Unstructured: No embeddings (users use LangChain/LlamaIndex after)
   - Docling: No embeddings (outputs DoclingDocument, user embeds)
   - LlamaParse: No embeddings (outputs Markdown, user embeds via LlamaIndex)
   - Chunkr: No embeddings (chunks only)

5. **Revenue opportunity** — Embedding calls consume AI credits. This increases per-document revenue for Pro/Business tiers while adding genuine value.

### What Users Get

```bash
# One command: parse → chunk → embed → JSON with vectors
./bin/docparse report.docx --chunk --embed --ai gemini-2.5-flash

# Output includes vectors ready for vector DB insertion
```

No need to install `sentence-transformers`, configure OpenAI embeddings, or write glue code. Parse and embed in one shot.

## Design

### Embedding Model Selection

The embedding model is **independently selectable** from the parsing AI model. Users may want Gemini for PDF parsing but OpenAI for embeddings (or vice versa). The `--embed-model` flag controls this explicitly.

#### Supported Embedding Models

| Provider | Model | Dimensions | Modality | Notes |
|----------|-------|------------|----------|-------|
| **Google** | `text-embedding-005` | 768 | Text | Free tier: 1,500 RPM. Solid general-purpose default. |
| **Google** | `gemini-embedding-001` | 768/3072 | **Multimodal** (text + image) | Newest. Configurable dimensions. Can embed images from ImageBlocks directly — no OCR step needed. |
| **OpenAI** | `text-embedding-3-small` | 1536 | Text | Best price/performance. $0.02/1M tokens. |
| **OpenAI** | `text-embedding-3-large` | 3072 | Text | Highest quality text embeddings. $0.13/1M tokens. Configurable dimensions (256-3072). |
| **Anthropic** | `voyage-3` | 1024 | Text | Via Voyage AI (Anthropic's embedding partner). Strong multilingual. |
| **Anthropic** | `voyage-multimodal-3` | 1024 | **Multimodal** (text + image) | Embeds text and images in same vector space. |
| **Ollama** | `nomic-embed-text` | 768 | Text | Free, local, fast. Good for dev/testing. |
| **Ollama** | `mxbai-embed-large` | 1024 | Text | Free, local, higher quality. |
| **Ollama** | `llava` / `bakllava` | 4096 | **Multimodal** | Local multimodal — embeds images too. |
| **Cohere** | `embed-v4.0` | 1024 | **Multimodal** (text + image) | Strong retrieval-optimized embeddings. |
| **OpenAI-compat** | Any | Varies | Varies | Any endpoint implementing OpenAI's `/v1/embeddings` API |

#### Model Selection Logic

```bash
# Explicit model selection (always takes priority)
./bin/docparse report.docx --chunk --embed --embed-model text-embedding-3-small

# Auto-detect from --ai provider (convenience default)
./bin/docparse report.docx --chunk --embed --ai gemini-2.5-flash
#   → auto-selects gemini-embedding-001 (same provider)

./bin/docparse report.docx --chunk --embed --ai ollama
#   → auto-selects nomic-embed-text (same provider)

# Mix providers: parse with Gemini, embed with OpenAI
./bin/docparse scan.pdf --chunk --embed --ai gemini-2.5-flash --embed-model text-embedding-3-large

# Mix providers: parse with Ollama, embed with Voyage
./bin/docparse scan.pdf --chunk --embed --ai granite-docling --embed-model voyage-3
```

**Auto-detection defaults** (when `--embed-model` is not specified):

| `--ai` provider | Default embedding model | Why |
|-----------------|------------------------|-----|
| `gemini-*` | `gemini-embedding-001` | Multimodal, newest Google model |
| `claude-*` | `voyage-3` | Anthropic's recommended embedding partner |
| Ollama models | `nomic-embed-text` | Most widely installed local model |
| OpenAI-compat | `text-embedding-3-small` | Best value OpenAI embedding |
| No `--ai` flag | `text-embedding-005` | Free Google model, no key needed with ADC |

#### API Key Routing

Each provider needs its own API key. DocParse already manages multiple AI providers — embedding uses the same key infrastructure:

| Provider | Environment Variable | Notes |
|----------|---------------------|-------|
| Google | `GOOGLE_API_KEY` or ADC | Same key as Gemini parsing |
| OpenAI | `OPENAI_API_KEY` | New — needed only if using OpenAI embeddings |
| Anthropic/Voyage | `ANTHROPIC_API_KEY` or `VOYAGE_API_KEY` | Voyage uses Anthropic's key by default |
| Cohere | `COHERE_API_KEY` | New — needed only if using Cohere |
| Ollama | None (local) | No key needed |

The API server inherits keys from environment. For the hosted DocParse API, users don't need provider keys — DocParse acts as the proxy and bills via the tier system.

#### Multimodal Embeddings

This is a key differentiator. Models like `gemini-embedding-001`, `voyage-multimodal-3`, and `embed-v4.0` can embed images directly — they don't need OCR or image descriptions.

When a multimodal embedding model is selected and the document contains `ImageBlock`s:

1. **Text chunks** — embedded as text (normal)
2. **Image blocks** — embedded as images using the multimodal model, producing vectors in the same embedding space
3. **Mixed chunks** (text + image) — text is embedded as text, images embedded as images, then averaged or concatenated (configurable)

This means a search for "revenue chart" can match an actual chart image, not just text mentioning revenue.

```bash
# Multimodal: embed both text and images from a PPTX
./bin/docparse slides.pptx --chunk --embed --embed-model gemini-embedding-001 --ai gemini-2.5-flash

# Images in chunks get their own embeddings
# Response includes: embedding_modality: "text" or "image" per chunk
```

**Fallback**: If a text-only embedding model is selected and the document has images, the image's `description` field (from ImageBlock) is embedded as text instead. No error — graceful degradation.

#### Custom Dimensions

Some models support configurable output dimensions (trading quality for index size):

```bash
# OpenAI text-embedding-3-large at 256 dims (smallest, fastest retrieval)
./bin/docparse report.docx --chunk --embed --embed-model text-embedding-3-large --embed-dimensions 256

# Gemini embedding at 768 dims (default) vs 3072 (max quality)
./bin/docparse report.docx --chunk --embed --embed-model gemini-embedding-001 --embed-dimensions 3072
```

Not all models support this — the embedder validates and falls back to model default if unsupported.

### New AILANG Module: `docparse/services/embedder.ail`

```ailang
module docparse/services/embedder

import docparse/types/document (Block, ParsedDocument)
import docparse/services/chunker (Chunk)

-- Embedding configuration
export type EmbedConfig = {
  model: string,              -- embedding model name
  dimensions: int,            -- output vector dimensions (0 = model default)
  includeHeadingPath: bool,   -- prepend heading path to text before embedding
  includeSectionKind: bool,   -- prepend section kind
  batchSize: int              -- how many texts to embed per API call
}

-- An embedded chunk
export type EmbeddedChunk = {
  chunk: Chunk,
  embedding: [float],
  embeddingModel: string,
  dimensions: int
}

-- Embed a list of chunks
export func embedChunks(chunks: [Chunk], config: EmbedConfig) -> [EmbeddedChunk] ! {AI}

-- Embed a single text (utility)
export func embedText(text: string, config: EmbedConfig) -> [float] ! {AI}

-- Embed full document (parse + chunk + embed pipeline)
export func embedDocument(doc: ParsedDocument, chunkStrategy: ChunkStrategy, embedConfig: EmbedConfig) -> [EmbeddedChunk] ! {AI}
```

### Context-Enhanced Embedding

The key differentiator: we don't just embed raw text. We prepend structural context:

```
Raw chunk text:
"We surveyed 500 participants across 3 regions."

Context-enhanced text (what we actually embed):
"[Methodology > Data Collection] We surveyed 500 participants across 3 regions."
```

This leverages the hierarchy metadata (v0.13.0) to improve retrieval relevance. The heading path acts as a semantic prefix that helps the embedding model understand the chunk's role in the document.

Configuration options:
- `includeHeadingPath: true` — prepend `[heading > path]` (default: true)
- `includeSectionKind: true` — prepend `[body]`, `[header]`, `[notes]` etc. (default: false)
- Neither — embed raw chunk text only

### API Integration

Extend `/api/v1/parse` and `/api/v1/chunk` with embedding parameters:

```
POST /api/v1/parse
Content-Type: multipart/form-data

file: <document>
chunk: true
chunk_strategy: auto
max_tokens: 512
embed: true
embed_model: gemini-embedding-001  # optional, auto-detected from AI config
embed_dimensions: 768              # optional, model default (0 = model default)
embed_multimodal: true             # embed images directly if model supports it
include_heading_path: true         # prepend heading context
```

Response:
```json
{
  "format": "docx",
  "filename": "report.docx",
  "metadata": { ... },
  "blocks": [ ... ],
  "chunks": [
    {
      "id": 0,
      "text": "Introduction\nThis report covers...",
      "token_count": 245,
      "metadata": {
        "heading_context": "Introduction",
        "section_kind": "body"
      },
      "embedding": [0.0234, -0.0891, 0.0456, ...],
      "embedding_model": "gemini-embedding-001",
      "embedding_dimensions": 768,
      "embedding_modality": "text"
    }
  ],
  "total_chunks": 12,
  "elapsed_ms": 1250
}
```

### Dedicated Embedding Endpoint

```
POST /api/v1/embed
Content-Type: application/json

{
  "texts": ["text 1", "text 2", ...],
  "model": "text-embedding-005",
  "dimensions": 768
}
```

Response:
```json
{
  "embeddings": [
    [0.0234, -0.0891, ...],
    [0.0567, 0.0123, ...]
  ],
  "model": "text-embedding-005",
  "dimensions": 768,
  "total_tokens": 156,
  "elapsed_ms": 340
}
```

This standalone endpoint lets users embed arbitrary text using their DocParse API key — useful for query embedding at retrieval time.

### CLI Integration

```bash
# Full pipeline: parse → chunk → embed
./bin/docparse report.docx --chunk --embed --ai gemini-2.5-flash

# Custom embedding model
./bin/docparse report.docx --chunk --embed --embed-model nomic-embed-text --ai ollama

# Output as JSONL (one chunk per line, ready for vector DB bulk insert)
./bin/docparse report.docx --chunk --embed --jsonl --ai gemini-2.5-flash

# Embed without chunking (one embedding per block)
./bin/docparse report.docx --embed --ai gemini-2.5-flash
```

### Batching and Rate Limits

Embedding APIs have rate limits and batch efficiently:

- **Google embedding API**: 250 texts per batch, 1,500 RPM free tier
- **Ollama**: No rate limit (local), but sequential
- **OpenAI-compat**: Varies

The embedder batches texts into groups of `batchSize` (default: 50) and makes concurrent API calls respecting rate limits. For a 100-chunk document with batch size 50, that's 2 API calls.

### Cost Impact

| Model | Cost per 1M tokens | Typical doc (50 chunks × 200 tokens = 10K tokens) | Monthly (1K docs = 10M tokens) |
|-------|-------------------|--------------------------------------|-------------------|
| Google `text-embedding-005` | Free (1,500 RPM) | $0 | $0 |
| Google `gemini-embedding-001` | $0.01/1M tokens | $0.0001 | $0.10 |
| OpenAI `text-embedding-3-small` | $0.02/1M tokens | $0.0002 | $0.20 |
| OpenAI `text-embedding-3-large` | $0.13/1M tokens | $0.0013 | $1.30 |
| Voyage `voyage-3` | $0.06/1M tokens | $0.0006 | $0.60 |
| Voyage `voyage-multimodal-3` | $0.12/1M tokens | $0.0012 | $1.20 |
| Cohere `embed-v4.0` | $0.10/1M tokens | $0.001 | $1.00 |
| Ollama (any) | $0 (local) | $0 | $0 |

Embedding cost is negligible — typically <1% of the AI parsing cost for PDFs. For Office documents (which have zero parsing cost), embeddings are the only AI cost. Even the most expensive model (OpenAI large) costs $1.30/month at 1K documents.

### Billing & Credits Integration

This section covers billing for all v0.13.0 features (chunking, hierarchy, embeddings) since they form a single pipeline.

#### Updated Credits Table

The existing credits system ([v0_9_0_agent_friendly_api.md](../v0_9_0/v0_9_0_agent_friendly_api.md)) defines `office_parse: 1`, `pdf_parse: 3`, `document_generate: 10`. v0.13.0 adds:

| Operation | Credits | Our Cost | Rationale |
|-----------|---------|----------|-----------|
| `office_parse` | 1 | ~$0 | Existing — deterministic, zero AI cost |
| `pdf_parse` | 3 | ~$0.001 | Existing — AI model call |
| `chunk` (any strategy except similarity) | **0** | ~$0 | CPU-only, negligible. Bundled free with parse. |
| `chunk_similarity` | **2** | ~$0.001 | Requires embedding API call for similarity grouping |
| `hierarchy` | **0** | ~$0 | CPU-only metadata enrichment. Free. |
| `embed_text` (per batch of 50 chunks) | **1** | $0–0.001 | One embedding API call per batch |
| `embed_multimodal` (per batch of 50 chunks) | **2** | $0.001–0.005 | Multimodal models cost more per token |
| `embed_standalone` (per call to `/api/v1/embed`) | **1** | $0–0.001 | Query-time embedding, same as text batch |
| `document_generate` | 10 | ~$0.01 | Existing — AI prompt → document |

**Key design decisions:**

1. **Chunking and hierarchy are free** — These are CPU operations on already-parsed data. Making them free encourages adoption and makes the full pipeline attractive. The value capture happens at parse time (existing credits) and embed time (new credits).

2. **Embeddings are cheap but not free** — Even though Google's `text-embedding-005` is free to us, we charge 1 credit per batch because: (a) we're providing the infrastructure, (b) we need to meter usage for capacity planning, (c) the standalone `/api/v1/embed` endpoint has value independent of parsing.

3. **Multimodal costs 2x** — Multimodal embedding models (Gemini, Voyage, Cohere) cost 2-10x more per token than text-only models. The 2 credit cost covers this spread.

#### Composite Pipeline Pricing

Full pipeline credit costs for common scenarios:

| Scenario | Parse | Chunk | Hierarchy | Embed | Total Credits |
|----------|-------|-------|-----------|-------|---------------|
| DOCX → parse only | 1 | — | — | — | **1** |
| DOCX → parse + chunk | 1 | 0 | — | — | **1** |
| DOCX → parse + chunk + hierarchy | 1 | 0 | 0 | — | **1** |
| DOCX → parse + chunk + embed (50 chunks, text) | 1 | 0 | 0 | 1 | **2** |
| DOCX → parse + chunk + embed (100 chunks, text) | 1 | 0 | 0 | 2 | **3** |
| DOCX → parse + chunk + embed (50 chunks, multimodal) | 1 | 0 | 0 | 2 | **3** |
| PDF → parse + chunk + embed (50 chunks, text) | 3 | 0 | 0 | 1 | **4** |
| PDF → parse + chunk (similarity) + embed | 3 | 2 | 0 | 1 | **6** |
| Standalone embed (50 texts) | — | — | — | 1 | **1** |

**Competitive comparison** (for parse + chunk + embed of a 10-page DOCX):

| Service | Cost | Notes |
|---------|------|-------|
| **DocParse** | 2 credits (~$0.0025) | 1 parse + 1 embed batch |
| **Unstructured + OpenAI embed** | $0.30 + $0.002 = **$0.302** | $0.03/page × 10 + embedding |
| **LlamaParse + OpenAI embed** | $0.0125 + $0.002 = **$0.015** | No-AI mode + embedding |
| **Chunkr + OpenAI embed** | $0.05–0.10 + $0.002 = **$0.052–0.102** | Chunking + embedding |

DocParse is **10-100x cheaper** for the full pipeline on Office documents because parse + chunk + hierarchy are essentially free.

#### Tier Access

| Tier | Chunking | Hierarchy | Embedding Models | Embed Calls/Day |
|------|----------|-----------|-----------------|-----------------|
| **Free** | All strategies | Yes | Google `text-embedding-005` only (free model) | 50 batches |
| **Pro** (EUR 29) | All strategies | Yes | All models (Google, OpenAI, Voyage, Cohere, Ollama) | 2,000 batches |
| **Business** (EUR 99) | All strategies | Yes | All models + custom endpoints | Unlimited |
| **Enterprise** | All strategies | Yes | All models + custom + private models | Unlimited |

**Why restrict free tier to `text-embedding-005`**: It's the only model with zero marginal cost to us (Google's free tier). Allowing OpenAI/Voyage/Cohere on free tier would mean we pay for embeddings with no revenue. Users who want premium embedding models are deriving enough value to justify Pro.

**Why chunking/hierarchy are unrestricted**: They cost us nothing. Restricting them on free tier would just frustrate users and push them to competitors. Better to let free users get the full structural pipeline and only gate on AI operations (parsing PDFs, embedding).

#### Usage Tracking Updates

The Firestore usage schema ([v0_8_0](../v0_8_0/v0_8_0_api_keys_cloud_deployment.md)) needs new fields:

```
usage_logs/{auto_id}
  ├── ... (existing fields)
  ├── chunks_generated: int       # number of chunks created
  ├── chunk_strategy: string      # "auto:structure", "fixed", etc.
  ├── embeddings_generated: int   # number of vectors created
  ├── embed_model: string         # "gemini-embedding-001", etc.
  ├── embed_tokens: int           # total tokens sent to embedding API
  └── embed_modality: string      # "text", "multimodal", "mixed"
```

The `/api/v1/keys/usage` response should include:

```json
{
  "requests_today": 45,
  "pages_this_month": 230,
  "embed_batches_today": 12,
  "credits_used_today": 57,
  "quota": {
    "requests_per_day": 5000,
    "pages_per_month": 10000,
    "embed_batches_per_day": 2000
  }
}
```

#### `/api/v1/pricing` Update

The machine-readable pricing endpoint ([v0_9_0_agent_friendly_api.md](../v0_9_0/v0_9_0_agent_friendly_api.md)) should include v0.13.0 operations:

```json
{
  "credits": {
    "office_parse": 1,
    "pdf_parse": 3,
    "image_parse": 3,
    "document_generate": 10,
    "chunk": 0,
    "chunk_similarity": 2,
    "hierarchy": 0,
    "embed_text_batch": 1,
    "embed_multimodal_batch": 2,
    "embed_standalone": 1
  },
  "embed_models": {
    "text-embedding-005": { "provider": "google", "tier_required": "free", "dimensions": 768, "multimodal": false },
    "gemini-embedding-001": { "provider": "google", "tier_required": "pro", "dimensions": [768, 3072], "multimodal": true },
    "text-embedding-3-small": { "provider": "openai", "tier_required": "pro", "dimensions": 1536, "multimodal": false },
    "text-embedding-3-large": { "provider": "openai", "tier_required": "pro", "dimensions": [256, 3072], "multimodal": false },
    "voyage-3": { "provider": "anthropic", "tier_required": "pro", "dimensions": 1024, "multimodal": false },
    "voyage-multimodal-3": { "provider": "anthropic", "tier_required": "pro", "dimensions": 1024, "multimodal": true },
    "embed-v4.0": { "provider": "cohere", "tier_required": "pro", "dimensions": 1024, "multimodal": true },
    "nomic-embed-text": { "provider": "ollama", "tier_required": "free", "dimensions": 768, "multimodal": false }
  }
}
```

#### `/api/v1/estimate` Update

The cost estimation endpoint should account for the full pipeline:

```
POST /api/v1/estimate
{
  "args": ["report.docx"],
  "chunk": true,
  "embed": true,
  "embed_model": "gemini-embedding-001"
}

// Response
{
  "estimated_credits": 2,
  "breakdown": {
    "parse": 1,
    "chunk": 0,
    "embed": 1
  },
  "format": "docx",
  "strategy": "deterministic",
  "chunk_strategy": "auto:structure",
  "estimated_chunks": 45,
  "embed_model": "gemini-embedding-001",
  "embed_batches": 1,
  "ai_required": false,
  "estimated_ms": 1500
}
```

### AILANG AI Effect Integration

The embedding call routes through AILANG's existing AI effect:

```ailang
-- In embedder.ail
func callEmbedding(texts: [string], model: string) -> [[float]] ! {AI} = {
  -- Uses std/ai with a special embedding prompt format
  -- AILANG runtime routes to the correct provider based on model name
  let prompt = "EMBED:" ++ join("\n---\n", texts);
  let result = callJsonSimple(prompt);
  decode(result)
}
```

> **Note**: This depends on AILANG adding embedding support to the AI effect. If not available, we can use direct HTTP calls to embedding APIs via the Net effect as a fallback. File AILANG feedback if needed.

### Vector DB Output Formats

For convenience, support output formats that map directly to popular vector DBs:

```bash
# Pinecone format (JSONL with id, values, metadata)
./bin/docparse report.docx --chunk --embed --format pinecone --ai gemini-2.5-flash

# Weaviate format
./bin/docparse report.docx --chunk --embed --format weaviate --ai gemini-2.5-flash

# ChromaDB format
./bin/docparse report.docx --chunk --embed --format chroma --ai gemini-2.5-flash

# Generic JSONL (default)
./bin/docparse report.docx --chunk --embed --jsonl --ai gemini-2.5-flash
```

This is a stretch goal — start with generic JSONL and add DB-specific formats based on user demand.

## Implementation Plan

1. **AILANG AI effect check** — Verify/request embedding support in AI effect. Fallback: direct HTTP via Net effect.
2. **`embedder.ail`** — Core module: `embedText`, `embedChunks`, `EmbedConfig` types
3. **Provider routing** — Map `--ai` flag to default embedding model per provider
4. **Batching** — Batch texts for efficient API calls
5. **Context enhancement** — Prepend heading paths from hierarchy module
6. **API endpoints** — `embed` param on `/api/v1/parse`, standalone `/api/v1/embed`
7. **CLI flags** — `--embed`, `--embed-model`, `--jsonl`
8. **Tier enforcement** — Embed calls count toward AI quota
9. **Tests** — Verify embeddings are returned, correct dimensions, batch splitting works

## Metrics

- Embedding dimensions match model specification
- Batch splitting: N chunks with batch size B → ceil(N/B) API calls
- Context-enhanced embeddings improve retrieval (measure with a small eval set)
- Latency: <2s for a typical 50-chunk document (Google API)
- Cost tracking: embed token count reported in usage stats

## Risks

1. **AILANG AI effect may not support embeddings** — Fallback: use Net effect to call embedding APIs directly. This is more code but not blocked.
2. **Vector size in JSON responses** — A 768-dim float vector is ~6KB in JSON. 50 chunks = 300KB of vectors. For large documents, offer a binary format option or separate embedding download endpoint.
3. **Provider lock-in concerns** — Addressed: `--embed-model` is fully independent of `--ai`. Users can parse with Gemini and embed with OpenAI, or parse with Ollama and embed with Voyage. The two flags control different API calls.
4. **Rate limiting on free embedding APIs** — Google's free tier is generous (1,500 RPM) but could be hit with batch processing. Implement backoff.
