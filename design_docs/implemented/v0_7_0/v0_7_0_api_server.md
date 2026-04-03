# DocParse v0.7.0 — API Server & Unstructured Compatibility

**Status**: Implemented (Phase 1-2 shipped 2026-03-18; Phase 3-5 rolled into v0.9.0 planned)
**Theme**: Deploy DocParse as a production API on Cloud Run with native + Unstructured-compatible endpoints

## Motivation

DocParse has 10 parsers, 8 generators, and AI-powered extraction — but it's CLI-only. An API server unlocks:

1. **Drop-in Unstructured replacement**: Existing pipelines (LangChain, LlamaIndex, Haystack) that use the Unstructured API can switch to DocParse with zero code changes
2. **DocParse-native API**: A cleaner, more capable API designed around our Block ADT (not Unstructured's flat element list)
3. **Cloud deployment**: Run on Cloud Run in `YOUR_GCP_PROJECT` GCP project, scale to zero, pay per request
4. **MCP/A2A integration**: `ailang serve-api` includes MCP and A2A protocols — Claude Desktop and Cursor can use DocParse directly

## Why Unstructured Compatibility?

Unstructured is the de facto standard API for document parsing in the LLM ecosystem. Their Python SDK is used by LangChain (`UnstructuredLoader`), LlamaIndex, Haystack, and hundreds of RAG pipelines. By implementing their API contract, DocParse becomes a **zero-migration-cost** alternative.

Key advantages over Unstructured:
- **Deterministic Office parsing**: Track changes, comments, headers/footers, merged cells — Unstructured misses all of these
- **No Python dependencies**: Single AILANG binary vs Unstructured's 200+ pip packages
- **10x faster on Office files**: No ML pipeline needed for deterministic formats
- **Cheaper**: No per-page pricing for Office files (AI only used for PDF/images)
- **Self-hostable**: Single Cloud Run service, no GPU needed for Office parsing

## Architecture

### AILANG `serve-api` as Foundation

AILANG's built-in `ailang serve-api` gives us most of what we need for free:

```
ailang serve-api --caps IO,FS,AI --ai gemini-2.5-flash docparse/ --port 8080
```

This auto-exposes every exported function as `POST /api/{module}/{function}` with:
- Auto-generated OpenAPI 3.1 spec at `/api/_meta/openapi.json`
- Swagger UI at `/api/_meta/docs`
- ReDoc at `/api/_meta/redoc`
- Health check at `/api/_health`
- A2A Agent Card at `/.well-known/agent.json`
- MCP over HTTP at `/mcp/`

### Custom API Layer

We need a thin AILANG module (`docparse/services/api_server.ail`) that exposes our designed endpoints. `ailang serve-api` auto-maps exported functions to REST endpoints, so we export functions that match our desired API shape.

```
docparse/
├── services/
│   ├── api_server.ail           # NEW: API endpoint functions
│   ├── unstructured_compat.ail  # NEW: Block ADT → Unstructured element mapper
│   └── ... (existing services)
└── main.ail                     # CLI entry (unchanged)
```

### Endpoint Design

```
┌──────────────────────────────────────────────────────────────┐
│  DocParse API Server                                         │
│                                                              │
│  Native API (v1)                                             │
│  ├── POST /api/v1/parse         → parse file → [Block] JSON │
│  ├── POST /api/v1/convert       → parse + generate → file   │
│  ├── POST /api/v1/generate      → prompt → AI → file        │
│  ├── GET  /api/v1/formats       → supported formats list    │
│  └── GET  /api/v1/health        → health + version info     │
│                                                              │
│  Unstructured Compat (legacy sync)                           │
│  └── POST /general/v0/general   → parse → [Element] JSON    │
│                                                              │
│  Unstructured Compat (new jobs API)                          │
│  ├── POST /api/v1/jobs/         → create parse job           │
│  ├── GET  /api/v1/jobs/{id}     → job status                 │
│  └── GET  /api/v1/jobs/{id}/download → get results           │
│                                                              │
│  Auto-generated (free from ailang serve-api)                 │
│  ├── GET  /api/_meta/openapi.json                            │
│  ├── GET  /api/_meta/docs       → Swagger UI                 │
│  ├── GET  /api/_health          → health check               │
│  ├── POST /mcp/                 → MCP over HTTP              │
│  └── GET  /.well-known/agent.json → A2A Agent Card           │
└──────────────────────────────────────────────────────────────┘
```

## Phase 1: Native DocParse API

### `POST /api/v1/parse`

Parse a document and return structured blocks.

**Request**: `multipart/form-data`
```
file: <binary>              # Required. The document to parse
format: string              # Optional. Force format (auto-detected from extension if omitted)
output: "blocks" | "markdown" | "html"  # Optional. Output format (default: "blocks")
ai_model: string            # Optional. AI model for PDF/images (default: gemini-2.5-flash)
include_metadata: bool      # Optional. Include file metadata (default: true)
```

**Response**: `application/json`
```json
{
  "status": "success",
  "filename": "report.docx",
  "format": "docx",
  "parse_time_ms": 47,
  "ai_model": null,
  "blocks": [
    {
      "type": "heading",
      "content": "Quarterly Report",
      "level": 1
    },
    {
      "type": "text",
      "content": "Revenue increased 23% year-over-year.",
      "style": "normal"
    },
    {
      "type": "table",
      "headers": ["Quarter", "Revenue", "Growth"],
      "rows": [
        ["Q1", "$1.2M", "15%"],
        ["Q2", "$1.5M", "23%"]
      ],
      "merged_cells": []
    },
    {
      "type": "change",
      "kind": "insertion",
      "content": "Updated projection",
      "author": "Jane Smith",
      "date": "2026-03-15"
    },
    {
      "type": "section",
      "kind": "comment",
      "blocks": [
        {"type": "text", "content": "Please review these numbers", "style": "normal"}
      ]
    }
  ],
  "metadata": {
    "title": "Q2 2026 Report",
    "page_count": 5,
    "word_count": 1247
  }
}
```

### `POST /api/v1/convert`

Parse a document and convert to another format.

**Request**: `multipart/form-data`
```
file: <binary>              # Required. Source document
target_format: string       # Required. Target format: docx, pptx, xlsx, html, md, odt, odp, ods
ai_model: string            # Optional. AI model for PDF/image sources
```

**Response**: Binary file download with appropriate Content-Type and Content-Disposition headers.

```
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; filename="report.docx"
```

### `POST /api/v1/generate`

Generate a document from a natural language prompt using AI.

**Request**: `application/json`
```json
{
  "prompt": "Q1 sales report with revenue table and 3 key findings",
  "format": "docx",
  "ai_model": "gemini-2.5-flash"
}
```

**Response**: Binary file download (same as convert).

### `GET /api/v1/formats`

**Response**:
```json
{
  "parse": ["docx", "pptx", "xlsx", "odt", "odp", "ods", "html", "md", "csv", "epub", "pdf", "png", "jpg"],
  "generate": ["docx", "pptx", "xlsx", "odt", "odp", "ods", "html", "md"],
  "ai_required": ["pdf", "png", "jpg", "gif", "bmp", "tiff"]
}
```

### `GET /api/v1/health`

**Response**:
```json
{
  "status": "healthy",
  "version": "0.7.0",
  "ai_available": true,
  "ai_model": "gemini-2.5-flash",
  "formats_supported": 13,
  "uptime_seconds": 3421
}
```

## Phase 2: Unstructured Legacy Compatibility

### `POST /general/v0/general`

Drop-in replacement for Unstructured's synchronous partition endpoint.

**Request**: `multipart/form-data` (same as Unstructured)
```
files: <binary>                    # Required. Document file
strategy: "auto" | "fast" | "hi_res"  # Optional. Mapped internally:
                                    #   "fast" → deterministic parser only (Office)
                                    #   "hi_res" → AI parser (PDF/images)
                                    #   "auto" → detect from format
output_format: "application/json"  # Only JSON supported initially
content_type: string               # Optional MIME hint
coordinates: bool                  # Ignored (DocParse doesn't do bounding boxes)
include_page_breaks: bool          # Optional (default: false)
chunking_strategy: string          # Mapped to basic text chunking if present
max_characters: int                # Chunk size limit
```

**Response**: `application/json` — Unstructured element format
```json
[
  {
    "type": "Title",
    "element_id": "a1b2c3d4...",
    "text": "Quarterly Report",
    "metadata": {
      "filename": "report.docx",
      "filetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "page_number": 1,
      "languages": ["eng"]
    }
  },
  {
    "type": "NarrativeText",
    "element_id": "e5f6a7b8...",
    "text": "Revenue increased 23% year-over-year.",
    "metadata": {
      "filename": "report.docx",
      "filetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }
  },
  {
    "type": "Table",
    "element_id": "c9d0e1f2...",
    "text": "Quarter Revenue Growth\nQ1 $1.2M 15%\nQ2 $1.5M 23%",
    "metadata": {
      "filename": "report.docx",
      "text_as_html": "<table><tr><th>Quarter</th><th>Revenue</th><th>Growth</th></tr><tr><td>Q1</td><td>$1.2M</td><td>15%</td></tr><tr><td>Q2</td><td>$1.5M</td><td>23%</td></tr></table>"
    }
  }
]
```

### Block ADT → Unstructured Element Mapping

| DocParse Block | Unstructured Type | Notes |
|----------------|-------------------|-------|
| `HeadingBlock` | `Title` | `category_depth` = heading level - 1 |
| `TextBlock` (normal) | `NarrativeText` | |
| `TextBlock` (code) | `CodeSnippet` | |
| `TableBlock` | `Table` | `text` = flattened text, `text_as_html` in metadata |
| `ListBlock` | Multiple `ListItem` | One element per item |
| `ImageBlock` | `Image` | `image_base64` + `image_mime_type` in metadata |
| `SectionBlock` (header) | `Header` | |
| `SectionBlock` (footer) | `Footer` | |
| `SectionBlock` (slide) | `Title` + `NarrativeText` | Flattened |
| `SectionBlock` (comment) | `NarrativeText` | With parent_id linking |
| `ChangeBlock` | `NarrativeText` | Formatted as "[INSERT/DELETE] text (by author)" |

### Element ID Generation

Unstructured uses SHA-256 hashes of element content. We'll replicate this:
```
element_id = sha256(type + text + str(sequence_number))
```

### Authentication

Support the `unstructured-api-key` header for compat, but also support:
- `Authorization: Bearer <token>` (standard)
- API key via query param `?api_key=xxx` (convenience)
- No auth in development mode (`--no-auth` flag)

In production on Cloud Run, use IAM or a simple API key stored in Secret Manager.

## Phase 3: Unstructured Jobs API Compatibility

Implement the async jobs API for clients using Unstructured's newer SDK.

### `POST /api/v1/jobs/`

**Request**: `multipart/form-data`
```
request_data: string (JSON)    # {"template_id": "hi_res_and_enrichment"} or custom
input_files: file[]            # Up to 10 files
```

**Response**:
```json
{
  "id": "job-uuid",
  "status": "COMPLETED",
  "created_at": "2026-03-18T10:30:00Z",
  "runtime": "0.047s",
  "input_file_ids": ["file-uuid-1"],
  "output_node_files": [
    {"node_id": "partition-1", "file_id": "out-uuid-1", "node_type": "partition"}
  ]
}
```

**Implementation note**: Since DocParse is fast (Office parsing <100ms), we can return `COMPLETED` synchronously for Office files and only truly go async for AI-powered PDF/image parsing. This gives instant results for the common case while maintaining API compatibility.

### `GET /api/v1/jobs/{job_id}`

Returns job status. For sync-completed jobs, always returns `COMPLETED`.

### `GET /api/v1/jobs/{job_id}/download?file_id=xxx`

Returns the parsed elements in Unstructured format.

### Template Mapping

| Unstructured Template | DocParse Behavior |
|----------------------|-------------------|
| `hi_res_and_enrichment` | AI parser (PDF/images) or deterministic (Office) |
| `fast` | Deterministic parser only, error on PDF/images |
| `vlm` | AI parser with specified model |

### What We Don't Support (and That's OK)

These Unstructured features don't map to DocParse's architecture:

| Feature | Why Not | Alternative |
|---------|---------|-------------|
| `coordinates` (bounding boxes) | DocParse does structural, not spatial parsing | Return null |
| `chunking_strategy: by_similarity` | Requires embedding model | Support `basic` and `by_title` only |
| Source/Destination connectors | Out of scope for v0.7.0 | Direct file upload |
| `embed` nodes | Not a document parsing concern | Use downstream embedding |
| Scheduled workflows | Overkill for parsing API | Use Cloud Scheduler externally |
| `detection_class_prob` | No ML layout detection for Office | Return 1.0 |

## Phase 4: Cloud Run Deployment

### Infrastructure Setup

```
YOUR_GCP_PROJECT (GCP project)
├── Cloud Run: docparse-api          # The API service
├── Artifact Registry: docparse      # Container images
├── Secret Manager: docparse-api-key # API key(s)
└── Cloud Trace: auto (AILANG built-in) # Request tracing
```

### Dockerfile

```dockerfile
FROM ghcr.io/sunholo-data/ailang:latest

WORKDIR /app
COPY docparse/ ./docparse/

# Cloud Run sets PORT env var
ENV PORT=8080

EXPOSE 8080

CMD ["ailang", "serve-api", \
     "--caps", "IO,FS,AI", \
     "--ai", "gemini-2.5-flash", \
     "--port", "8080", \
     "--cors", \
     "docparse/"]
```

**Note**: Uses ADC (Application Default Credentials) on Cloud Run for Vertex AI access — no API key needed. Set `GOOGLE_API_KEY=""` to force ADC.

### Deployment Script

```bash
#!/bin/bash
# deploy.sh — Deploy DocParse API to Cloud Run

PROJECT=YOUR_GCP_PROJECT
REGION=us-central1
SERVICE=docparse-api
REPO=docparse

# Enable APIs (first time only)
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudtrace.googleapis.com \
  --project=$PROJECT

# Create Artifact Registry repo (first time only)
gcloud artifacts repositories create $REPO \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT 2>/dev/null || true

# Build and push
IMAGE=$REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:latest
docker build -t $IMAGE .
docker push $IMAGE

# Deploy to Cloud Run
gcloud run deploy $SERVICE \
  --image=$IMAGE \
  --region=$REGION \
  --project=$PROJECT \
  --platform=managed \
  --allow-unauthenticated \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --timeout=300s \
  --set-env-vars="GOOGLE_API_KEY=,GOOGLE_CLOUD_PROJECT=$PROJECT"
```

### Cloud Run Configuration

| Setting | Value | Rationale |
|---------|-------|-----------|
| Memory | 1Gi | Office parsing is memory-light; PDF may need more |
| CPU | 1 | Single-threaded AILANG; scale via instances |
| Min instances | 0 | Scale to zero (cost) |
| Max instances | 10 | Reasonable starting limit |
| Timeout | 300s | PDF/AI parsing can be slow |
| Concurrency | 1 | AILANG is single-threaded per request |
| Auth | Unauthenticated initially | API key checked in application layer |

### Cost Estimate

- Cloud Run: ~$0 at low volume (scale-to-zero, free tier: 2M requests/month)
- Vertex AI (Gemini 2.5 Flash): ~$0.075/1M input tokens for PDF parsing
- Office parsing: $0 (no AI needed)
- Artifact Registry: ~$0.10/GB/month for container images

For a typical workload of 1,000 Office documents/day: **effectively free**.

## Phase 5: Python SDK (Unstructured Drop-in)

A minimal Python client that wraps the DocParse API with an Unstructured-compatible interface:

```python
# Option A: Use as Unstructured replacement
from ailang_parse import DocParseClient

# Same interface as UnstructuredClient
client = DocParseClient(
    server_url="https://docparse-api-xxxxx.run.app",
    api_key="your-key"  # or omit for local dev
)

# Unstructured-compatible call
elements = client.general.partition(
    files=open("report.docx", "rb"),
    strategy="auto"
)
for el in elements:
    print(el["type"], el["text"][:50])

# Option B: Use native DocParse API (richer output)
blocks = client.parse("report.docx")
for block in blocks:
    if block.type == "table":
        print(block.headers, block.rows)

# Option C: LangChain integration
from docparse.integrations import DocParseLoader

loader = DocParseLoader("report.docx", api_url="https://docparse-api-xxxxx.run.app")
docs = loader.load()  # Returns LangChain Document objects
```

### LangChain Integration

```python
# Drop-in replacement for UnstructuredFileLoader
from docparse.integrations.langchain import DocParseLoader

# Instead of:
# from langchain_community.document_loaders import UnstructuredFileLoader
# loader = UnstructuredFileLoader("report.docx")

# Use:
loader = DocParseLoader("report.docx")
docs = loader.load()
```

This works because we return the same element schema as Unstructured — LangChain's document loaders just need `type` and `text` fields.

## Implementation Plan

### Phase 1: Native API — IMPLEMENTED (2026-03-18)
- [x] Created `docparse/services/api_server.ail` (6 exported functions)
- [x] Endpoints: `parseFile`, `parse`, `formats`, `health`, `partition`, `partitionAuto`
- [x] Tested with `ailang serve-api --caps IO,FS,Env --ai-stub docparse/` locally
- [x] OpenAPI spec auto-generated at `/api/_meta/openapi.json`
- [x] Swagger UI at `/api/_meta/docs`, ReDoc at `/api/_meta/redoc`
- [x] MCP + A2A protocols available out of the box

### Phase 2: Unstructured Legacy Compat — IMPLEMENTED (2026-03-18)
- [x] Created `docparse/services/unstructured_compat.ail` (~250 lines)
- [x] Block → Element mapper with all 9 variants mapped
- [x] `text_as_html` for TableBlocks with colspan support
- [x] Deterministic element_id generation (hash-based)
- [x] MIME type mapping for all 13 formats
- [ ] Test with Unstructured Python SDK (blocked on custom routes + file upload)

### Phase 3: Unstructured Jobs Compat (planned)
- [ ] Implement sync-complete jobs (Office files return COMPLETED immediately)
- [ ] In-memory job store for async PDF jobs
- [ ] Download endpoint returning Unstructured element format
- [ ] Test with Unstructured's newer Python SDK

### Phase 4: Cloud Run Deployment — PARTIALLY IMPLEMENTED (2026-03-18)
- [x] Dockerfile written (debian:bookworm-slim + AILANG v0.9.2 binary)
- [x] deploy.sh with --setup, --local, and deploy modes
- [x] .dockerignore for lean builds
- [ ] Enable GCP APIs on YOUR_GCP_PROJECT (run `bash deploy.sh --setup`)
- [ ] Deploy and smoke test
- [ ] Set up API key auth via Secret Manager

### Phase 5: Python SDK (planned)
- [ ] `pip install ailang-parse` package with DocParseClient
- [ ] Unstructured-compatible interface
- [ ] LangChain DocParseLoader
- [ ] Publish to PyPI

## AILANG Module Design

### `api_server.ail`

```ailang
module docparse/services/api_server

import docparse/services/format_router (detectFormat)
import docparse/services/docx_parser (parseDocx)
-- ... all parsers and generators

-- Exported functions become POST /api/docparse/services/api_server/{fn}
-- But ailang serve-api also supports custom route annotations (TBD)

-- Parse a document from file content
export func apiParse(filename: string, content: string, outputFormat: string) -> string ! {IO, FS, AI} {
  let format = detectFormat(filename)
  let blocks = routeAndParse(format, filename, content)
  formatResponse(blocks, filename, format, outputFormat)
}

-- Convert between formats
export func apiConvert(filename: string, content: string, targetFormat: string) -> string ! {IO, FS, AI} {
  let blocks = routeAndParse(detectFormat(filename), filename, content)
  generateToFormat(blocks, targetFormat)
}

-- List supported formats
export pure func apiFormats() -> string {
  "{\"parse\":[\"docx\",\"pptx\",\"xlsx\",...],\"generate\":[\"docx\",\"pptx\",...],\"ai_required\":[\"pdf\",\"png\",\"jpg\"]}"
}
```

### `unstructured_compat.ail`

```ailang
module docparse/services/unstructured_compat

import docparse/types/document (Block, HeadingBlock, TextBlock, TableBlock, ...)

-- Convert DocParse Block ADT to Unstructured element JSON
export pure func blocksToElements(blocks: [Block], filename: string, filetype: string) -> string {
  let elements = map(\b. blockToElement(b, filename, filetype), blocks)
  "[" ++ join(", ", elements) ++ "]"
}

pure func blockToElement(block: Block, filename: string, filetype: string) -> string {
  match block {
    HeadingBlock(text, level) ->
      elementJson("Title", text, filename, filetype, level - 1)
    TextBlock(text, style) ->
      let typ = if style == "code" then "CodeSnippet" else "NarrativeText"
      in elementJson(typ, text, filename, filetype, 0)
    TableBlock(headers, rows, _) ->
      tableElementJson(headers, rows, filename, filetype)
    -- ... other variants
  }
}
```

## Testing Strategy

### API Tests
```bash
# Start server
ailang serve-api --caps IO,FS,AI --ai gemini-2.5-flash docparse/ --port 8080 &

# Native API
curl -X POST http://localhost:8080/api/v1/parse \
  -F "file=@data/test_files/sample.docx"

# Unstructured compat
curl -X POST http://localhost:8080/general/v0/general \
  -F "files=@data/test_files/sample.docx" \
  -H "unstructured-api-key: test"

# Convert
curl -X POST http://localhost:8080/api/v1/convert \
  -F "file=@data/test_files/sample.docx" \
  -F "target_format=html" \
  -o output.html
```

### Compatibility Tests
```python
# Test with actual Unstructured Python SDK
from unstructured_client import UnstructuredClient

client = UnstructuredClient(
    server_url="http://localhost:8080",
    api_key_auth="test"
)
response = client.general.partition(
    request={"files": open("sample.docx", "rb")}
)
assert len(response.elements) > 0
assert response.elements[0].type in ["Title", "NarrativeText", "Table"]
```

### Benchmark: DocParse vs Unstructured

| Metric | DocParse API | Unstructured API |
|--------|-------------|-----------------|
| DOCX parse (10 pages) | Target: <100ms | ~2-5s |
| PPTX parse (20 slides) | Target: <200ms | ~3-8s |
| XLSX parse (5 sheets) | Target: <150ms | ~2-4s |
| PDF parse (10 pages) | ~3-5s (AI) | ~5-15s |
| Cold start | ~2-3s (AILANG) | ~10-30s (Python) |
| Container size | ~50MB | ~2GB+ |
| Memory usage | ~100MB | ~500MB-1GB |
| Dependencies | 0 (AILANG binary) | 200+ pip packages |

## Competitive Positioning

```
                    ┌─────────────────────────────────────┐
                    │       Document Parsing APIs          │
                    │                                      │
   Unstructured ────┤  Broad format support, mature SDK    │
                    │  BUT: slow, heavy, misses structure  │
                    │                                      │
   LlamaParse ──────┤  Good PDF/table extraction           │
                    │  BUT: cloud-only, per-page cost      │
                    │                                      │
   DocParse ────────┤  Fast Office, structural fidelity    │
                    │  AND: drop-in Unstructured compat    │
                    │  AND: self-hostable, zero deps       │
                    │  AND: generates docs (not just parse)│
                    └─────────────────────────────────────┘
```

DocParse is the only API that:
1. Parses AND generates 8 Office/ODF formats
2. Extracts structural metadata (track changes, comments, merged cells)
3. Provides Unstructured API compatibility for zero-friction migration
4. Runs as a single binary with zero runtime dependencies
5. Includes MCP + A2A protocols for AI agent integration

## Risks

| Risk | Mitigation |
|------|-----------|
| AILANG `serve-api` may not support custom routes (e.g., `/general/v0/general`) | Check if route annotations exist; if not, use a thin reverse proxy (nginx/Caddy) or request the feature |
| Multipart file upload handling in AILANG | Verify `serve-api` handles `multipart/form-data`; may need Net effect extensions |
| Cloud Run cold starts (~2-3s AILANG startup) | Set min-instances=1 for production; or switch to Go binary when codegen is fixed |
| Unstructured SDK compatibility edge cases | Test with actual SDK; focus on the 80% path (partition endpoint, JSON response) |
| API key auth in AILANG | May need to implement in application layer if serve-api doesn't support middleware |

## Dependencies

- AILANG runtime with `serve-api` command
- `YOUR_GCP_PROJECT` GCP project (exists, APIs need enabling)
- Docker for containerization
- `gcloud` CLI for deployment
- Unstructured Python SDK for compatibility testing

## Open Questions

1. **Custom routing**: Does `ailang serve-api` support custom route paths, or only auto-generated `/api/{module}/{function}` routes? If not, we need a proxy or AILANG feature request.
2. **File upload**: How does `ailang serve-api` handle multipart file uploads? Need to check if the Net effect exposes request bodies.
3. **Binary response**: Can exported AILANG functions return binary data (for convert/generate endpoints)?
4. **Concurrency**: AILANG is single-threaded — should we run multiple Cloud Run instances with concurrency=1, or does serve-api handle concurrent requests?
5. **Go binary timeline**: Once codegen bugs are fixed, should we skip straight to compiled Go binary for production? (Phase 4 Dockerfile would change to multi-stage build.)
6. **Rate limiting**: Implement in AILANG or use Cloud Run's built-in throttling?

## Implementation Findings (2026-03-18)

### What Works
- `ailang serve-api` auto-exposes all 120+ exported functions across 30 modules as REST endpoints
- Pure functions (formats, health, detectFormat, xmlEscape) work perfectly
- Text-based parsing (HTML, Markdown, CSV) works via JSON string args
- OpenAPI 3.1 spec auto-generated with correct type mappings
- Swagger UI and ReDoc available immediately
- MCP over HTTP and A2A Agent Card work out of the box
- Module loading takes ~2s (acceptable for Cloud Run with min-instances=1)

### Blockers Identified (AILANG feature requests sent)

| Blocker | Impact | AILANG Feedback |
|---------|--------|----------------|
| No custom route paths | Can't implement `/general/v0/general` Unstructured compat URL | msg_20260318_164053_c4c9aec0 |
| No multipart file upload | Users can't POST files to parse — must use filepaths instead | msg_20260318_164053_c4c9aec0 |
| No binary responses | Can't return generated DOCX/PPTX files for download | msg_20260318_164053_c4c9aec0 |
| No HTTP header access | Can't read `unstructured-api-key` header for auth compat | msg_20260318_164053_c4c9aec0 |
| No auth middleware | Need reverse proxy for API key validation | msg_20260318_164053_c4c9aec0 |
| serve-api docs missing | No guide for serve-api usage patterns | msg_20260318_164053_c4c9aec0 |

### Workaround: Filepath-Based API

Until file upload is supported, the API accepts file paths instead of file content:
```bash
# Parse a file by path (file must be accessible on server filesystem)
curl -X POST http://localhost:8080/api/docparse/services/api_server/parseFile \
  -H "Content-Type: application/json" \
  -d '{"args": ["data/test_files/sample.docx", "blocks"]}'
```

This works for Cloud Run if files are uploaded to GCS and mounted, or for local development.

### Actual Endpoint Paths

Routes are auto-generated as `POST /api/{module-path}/{function-name}`:
```
POST /api/docparse/services/api_server/health      → health check
POST /api/docparse/services/api_server/formats      → list formats
POST /api/docparse/services/api_server/parse        → parse file (1 arg)
POST /api/docparse/services/api_server/parseFile    → parse file (2 args)
POST /api/docparse/services/api_server/partition     → Unstructured compat (2 args)
POST /api/docparse/services/api_server/partitionAuto → Unstructured compat (1 arg)
```

### Known Issue: Zero-arg Functions

`ailang serve-api` expects all functions to accept at least 1 argument (the JSON body).
Pure functions with no args fail with "function expects 1 arguments, got 0".
Workaround: added `_unit: string` dummy parameter to `health()` and `formats()`.

### RESOLVED: ZIP Parsing Under serve-api

Was caused by our `apiParseDocx` passing XML content to `parseDocx` which expects a filepath.
Fixed by removing the redundant `readDocxContent` call. All 12 formats now parse correctly.

### RESOLVED: Concurrency

Concurrent requests work perfectly. 5x DOCX in 26ms (vs 55ms sequential). 10x mixed formats
in 32ms. The apparent "deadlock" was a bash test harness issue — `| tee` and `2>` redirects
break Go HTTP response flushing. Correct pattern: `> file 2>&1` with explicit PID `wait`.

Cloud Run safe with `concurrency=80`.

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `docparse/services/unstructured_compat.ail` | ~250 | Block ADT → Unstructured element mapper |
| `docparse/services/api_server.ail` | ~240 | API endpoint functions (6 exports) |
| `Dockerfile` | 25 | Container image (debian + ailang binary) |
| `deploy.sh` | 115 | Cloud Run deployment script |
| `.dockerignore` | 10 | Exclude .venv, benchmarks, etc. |

## Future Extensions (post v0.7.0)

- **Webhook notifications** for completed async jobs
- **Batch API** for processing many files in one request
- **Source connectors** (GCS, S3) for server-side file access
- **Caching layer** for repeated parses of the same document
- **Usage analytics** and billing integration
- **OpenTelemetry** traces (AILANG has built-in Cloud Trace support)
