# v0.9.0 — AI-Native Service Interface

## The Reframe

The question is not "how can a signed-in user try the API from the browser?"

The question is:

> **How can a human or agent discover, authorize, invoke, verify, replay, and repair use of the API with minimal ambiguity?**

The browser playground is a thin renderer over a machine-readable service model. The service model is the product.

## AILANG Axiom Alignment

| AILANG Axiom | API Manifestation |
|--------------|-------------------|
| **Machines are primary readers** | Capability manifest is the source of truth; playground generates from it |
| **Authority must be explicit** | Per-endpoint auth metadata; device flow for agent credential acquisition |
| **Execution must be replayable and auditable** | Request IDs, determinism flags, golden examples, replay hints |
| **Failure must be representable** | Typed error taxonomy with bounded codes, retryability, suggested fixes |
| **Cost is part of meaning** | Per-endpoint cost metadata, response-level quota counters, estimation endpoint |
| **Contracts as specifications** | Input/output/error schemas per endpoint; golden examples as API-level contracts |
| **Effects as capabilities** | Endpoint capability declarations (which effects each endpoint requires) |

## Architecture: Capability Manifest as Product Surface

```
                    ┌──────────────────────────────┐
                    │   Capability Manifest (JSON)  │
                    │   /api/v1/capabilities         │
                    │                                │
                    │  endpoints[]                   │
                    │    input_schema                │
                    │    output_schema               │
                    │    error_schema                │
                    │    auth                        │
                    │    cost                        │
                    │    determinism                 │
                    │    examples[]                  │
                    └──────────┬───────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐  ┌─────▼──────┐  ┌──────▼──────┐
    │ Browser        │  │ AI Agent   │  │ MCP/A2A     │
    │ Playground     │  │ (Claude,   │  │ Tool        │
    │ (renders from  │  │  GPT, etc) │  │ Definition  │
    │  manifest)     │  │            │  │             │
    └────────────────┘  └────────────┘  └─────────────┘
```

The browser playground should not hand-maintain per-endpoint HTML forms. It should render itself from the capability manifest. This is the single biggest architectural change.

---

## P0: Core Infrastructure

### 1. Capability Manifest Endpoint

```
GET /api/v1/capabilities
```

Single discovery point. Returns the full machine-readable service contract.

```json
{
  "service": "docparse",
  "version": "0.8.0",
  "base_url": "https://api.parse.sunholo.com",
  "protocol": "a2a/0.3",
  "auth": {
    "schemes": [
      {
        "id": "api_key",
        "type": "apiKey",
        "in": "body",
        "name": "apiKey",
        "prefix": "dp_",
        "description": "API key for data endpoints (parse, formats, unstructured)"
      },
      {
        "id": "firebase_bearer",
        "type": "http",
        "scheme": "bearer",
        "issuer": "YOUR_GCP_PROJECT.firebaseapp.com",
        "description": "Firebase ID token for key management endpoints"
      }
    ],
    "device_flow": {
      "request_url": "/api/v1/auth/device",
      "poll_url": "/api/v1/auth/device/poll",
      "approve_url": "https://www.sunholo.com/docparse/approve.html"
    }
  },
  "endpoints": [
    {
      "id": "parse",
      "path": "/api/v1/parse",
      "method": "POST",
      "description": "Parse any document into structured content blocks",
      "auth": { "required": true, "scheme": "api_key" },
      "input_schema": {
        "type": "object",
        "properties": {
          "filepath": { "type": "string", "description": "File path on server or sample_id" },
          "sample_id": { "type": "string", "description": "ID from /api/v1/samples" },
          "outputFormat": {
            "type": "string",
            "enum": ["blocks", "markdown", "html", "a2ui"],
            "default": "blocks"
          }
        },
        "oneOf": [
          { "required": ["filepath"] },
          { "required": ["sample_id"] }
        ]
      },
      "output_schema": {
        "type": "object",
        "properties": {
          "result": { "type": "string", "description": "JSON-encoded parse output" },
          "meta": { "$ref": "#/definitions/response_meta" }
        }
      },
      "error_codes": ["INVALID_API_KEY", "QUOTA_EXCEEDED", "INPUT_NOT_FOUND", "UNSUPPORTED_FORMAT", "PARSE_FAILED", "INVALID_ARGUMENT"],
      "cost": {
        "unit": "request",
        "estimated_class": "small",
        "quota_scope": "daily",
        "ai_required_for": ["pdf", "png", "jpg", "gif", "tiff", "webp", "wav", "mp3", "mp4"]
      },
      "determinism": {
        "replayable": true,
        "sources_of_variance": ["ai_model_version (PDF/image only)"]
      },
      "examples": [
        {
          "id": "parse_docx_blocks_basic",
          "request": { "sample_id": "sample_docx_basic", "outputFormat": "blocks" },
          "expected": { "status": 200, "response_shape": { "blocks": "array", "metadata": "object" } }
        }
      ]
    },
    {
      "id": "formats",
      "path": "/api/v1/formats",
      "method": "GET",
      "description": "List all supported input, output, and generation formats",
      "auth": { "required": false },
      "cost": { "unit": "none", "quota_scope": "none" },
      "determinism": { "replayable": true, "sources_of_variance": [] }
    },
    {
      "id": "health",
      "path": "/api/v1/health",
      "method": "GET",
      "description": "Service health, version, uptime",
      "auth": { "required": false },
      "cost": { "unit": "none", "quota_scope": "none" },
      "determinism": { "replayable": true, "sources_of_variance": ["uptime_ms"] }
    },
    {
      "id": "unstructured",
      "path": "/general/v0/general",
      "method": "POST",
      "description": "Drop-in Unstructured.io API replacement",
      "auth": { "required": true, "scheme": "api_key" },
      "input_schema": {
        "type": "object",
        "properties": {
          "path": { "type": "string" },
          "strategy": { "type": "string", "enum": ["auto", "hi_res", "fast"], "default": "auto" }
        },
        "required": ["path"]
      },
      "cost": { "unit": "request", "quota_scope": "daily" },
      "determinism": { "replayable": true, "sources_of_variance": [] }
    },
    {
      "id": "samples",
      "path": "/api/v1/samples",
      "method": "GET",
      "description": "List available sample documents for testing",
      "auth": { "required": false },
      "cost": { "unit": "none", "quota_scope": "none" },
      "determinism": { "replayable": true, "sources_of_variance": [] }
    },
    {
      "id": "estimate",
      "path": "/api/v1/estimate",
      "method": "POST",
      "description": "Estimate cost and latency before parsing — no auth required",
      "auth": { "required": false },
      "input_schema": {
        "type": "object",
        "properties": {
          "path": { "type": "string" },
          "outputFormat": { "type": "string", "enum": ["blocks", "markdown", "html", "a2ui"] }
        },
        "required": ["path"]
      },
      "cost": { "unit": "none", "quota_scope": "none" },
      "determinism": { "replayable": true, "sources_of_variance": [] }
    },
    {
      "id": "pricing",
      "path": "/api/v1/pricing",
      "method": "GET",
      "description": "Machine-readable pricing tiers and credit costs",
      "auth": { "required": false },
      "cost": { "unit": "none", "quota_scope": "none" }
    },
    {
      "id": "keys_usage",
      "path": "/api/v1/keys/usage",
      "method": "POST",
      "description": "Usage counters and quota limits for a key",
      "auth": { "required": true, "scheme": "firebase_bearer" },
      "cost": { "unit": "none", "quota_scope": "none" }
    }
  ],
  "definitions": {
    "response_meta": {
      "type": "object",
      "properties": {
        "request_id": { "type": "string", "description": "Unique request identifier for replay/audit" },
        "elapsed_ms": { "type": "number" },
        "quota_used": { "type": "integer" },
        "quota_remaining": { "type": "integer" },
        "replayable": { "type": "boolean" },
        "sample_id": { "type": "string", "description": "If request used a sample, its ID" }
      }
    },
    "error_response": {
      "type": "object",
      "properties": {
        "error": {
          "type": "object",
          "properties": {
            "code": { "type": "string", "enum": ["INVALID_API_KEY", "QUOTA_EXCEEDED", "INPUT_NOT_FOUND", "UNSUPPORTED_FORMAT", "PARSE_FAILED", "INVALID_ARGUMENT", "INTERNAL_ERROR", "AUTHORIZATION_PENDING", "DEVICE_CODE_EXPIRED"] },
            "message": { "type": "string" },
            "retryable": { "type": "boolean" },
            "suggested_fix": { "type": "string" }
          },
          "required": ["code", "message", "retryable"]
        }
      }
    }
  },
  "tool_definitions": {
    "mcp": "/mcp/",
    "a2a": "/.well-known/agent.json",
    "openapi": "/api/_meta/openapi.json"
  }
}
```

This is the product. Everything else — browser playground, Swagger UI, SDK examples — renders from this.

### 2. Named JSON Request Bodies (Replace Positional Args)

**Current** (serve-api convention):
```json
{"args": ["data/test_files/sample.docx", "blocks"]}
```

**Target**:
```json
{
  "path": "data/test_files/sample.docx",
  "outputFormat": "blocks"
}
```

`args` is positional and semantically weak. Named fields are:
- Easier for agents to infer and repair
- Not brittle to ordering changes
- Self-documenting in request logs
- Compatible with schema validation

**Migration path**: Accept both formats during transition. The capability manifest documents the named format. The `args` format remains as a serve-api fallback but is not advertised.

> **AILANG implication**: This may require `serve-api` to support named parameter binding alongside positional `args`. If serve-api can't do named params natively, we can handle the mapping in each endpoint function by accepting a JSON object arg and destructuring it.

### 3. Typed Error Taxonomy

Every endpoint documents a bounded set of error codes. Agents receive structured failures, not opaque strings.

```json
{
  "error": {
    "code": "UNSUPPORTED_FORMAT",
    "message": "File type '.docm' is not supported",
    "retryable": false,
    "suggested_fix": "Convert to .docx (remove macros). Supported: docx, pptx, xlsx, csv, md, odt, odp, ods, html, epub, pdf, png, jpg"
  }
}
```

**Full error code set**:

| Code | Retryable | When |
|------|-----------|------|
| `INVALID_API_KEY` | No | Key missing, malformed, or revoked |
| `QUOTA_EXCEEDED` | Yes (after reset) | Daily request or monthly page limit hit |
| `INPUT_NOT_FOUND` | No | File path doesn't exist on server |
| `UNSUPPORTED_FORMAT` | No | File extension not in supported list |
| `PARSE_FAILED` | Yes (maybe) | Parser error (corrupt file, encoding issue) |
| `INVALID_ARGUMENT` | No | Missing required field, bad enum value |
| `AI_UNAVAILABLE` | Yes | AI backend down (PDF/image parsing) |
| `AUTHORIZATION_PENDING` | Yes (poll) | Device flow: user hasn't approved yet |
| `DEVICE_CODE_EXPIRED` | No | Device flow: code timed out |
| `INTERNAL_ERROR` | Yes | Server bug |

`suggested_fix` is specifically for LLM consumption. Agents can't Google errors — the fix must be in the response.

### 4. Response Metadata on Every Response

Every successful response includes a `meta` block:

```json
{
  "result": "...",
  "meta": {
    "request_id": "req_01H3X...",
    "elapsed_ms": 14,
    "quota_used": 13,
    "quota_remaining": 47,
    "quota_resets_at": "2026-03-27T00:00:00Z",
    "replayable": true,
    "sample_id": "sample_docx_basic"
  }
}
```

Plus HTTP headers:

```http
X-Request-Id: req_01H3X...
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 47
X-RateLimit-Reset: 1711929600
```

**Why both?** Headers for HTTP-level tooling (proxies, monitoring). Body for agent logic. Agents should not have to choose between parsing headers and parsing bodies.

### 5. Sample Listing Endpoint

```
GET /api/v1/samples
```

```json
{
  "samples": [
    {
      "id": "sample_docx_basic",
      "path": "data/test_files/sample.docx",
      "label": "DOCX: Basic document",
      "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "tags": ["docx", "basic", "deterministic"],
      "expected_formats": ["blocks", "markdown", "html", "a2ui"],
      "ai_required": false
    },
    {
      "id": "sample_docx_tables",
      "path": "data/test_files/tables.docx",
      "label": "DOCX: Tables with merged cells",
      "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "tags": ["docx", "tables", "merged-cells", "deterministic"],
      "expected_formats": ["blocks", "markdown", "html", "a2ui"],
      "ai_required": false
    },
    {
      "id": "sample_docx_comments",
      "path": "data/test_files/comments.docx",
      "label": "DOCX: Comments & Track Changes",
      "tags": ["docx", "comments", "track-changes", "deterministic"],
      "ai_required": false
    },
    {
      "id": "sample_pptx_show",
      "path": "data/test_files/poi_sampleshow.pptx",
      "label": "PPTX: Presentation with slides",
      "tags": ["pptx", "deterministic"],
      "ai_required": false
    },
    {
      "id": "sample_xlsx_basic",
      "path": "data/test_files/pandoc_basic.xlsx",
      "label": "XLSX: Spreadsheet",
      "tags": ["xlsx", "deterministic"],
      "ai_required": false
    },
    {
      "id": "sample_csv",
      "path": "data/test_files/test.csv",
      "label": "CSV: Basic",
      "tags": ["csv", "deterministic"],
      "ai_required": false
    },
    {
      "id": "sample_markdown",
      "path": "data/test_files/pandoc_planets.md",
      "label": "Markdown: Planets table",
      "tags": ["markdown", "tables", "deterministic"],
      "ai_required": false
    },
    {
      "id": "sample_odt",
      "path": "data/test_files/test.odt",
      "label": "ODT: OpenDocument Text",
      "tags": ["odt", "deterministic"],
      "ai_required": false
    },
    {
      "id": "sample_html",
      "path": "data/test_files/test.html",
      "label": "HTML: Basic",
      "tags": ["html", "deterministic"],
      "ai_required": false
    }
  ]
}
```

Requests can then use either `"sample_id"` or `"path"`:

```json
{ "sample_id": "sample_docx_basic", "outputFormat": "blocks" }
```

Sample identities become stable. Agents can enumerate fixtures. Golden outputs can be attached.

---

## P1: Agent Onboarding & Discovery

### 6. Device Authorization Flow (RFC 8628)

```
Agent                          DocParse API                    User (browser)
  |                                |                               |
  |-- POST /api/v1/auth/device -->|                               |
  |   { "label": "claude-42" }   |                               |
  |                                |                               |
  |<-- device_code + user_code ---|                               |
  |    + verification_url          |                               |
  |                                |                               |
  |  (displays to user:)           |                               |
  |  "Visit https://www.sunholo   |                               |
  |   .com/docparse/approve.html  |                               |
  |   ?code=ABCD-1234"            |                               |
  |                                |                               |
  |                                |<-- User visits, signs in -----|
  |                                |    approves agent access       |
  |                                |                               |
  |-- POST /api/v1/auth/device/   |                               |
  |   poll                         |                               |
  |   { "device_code": "xxx" } -->|                               |
  |                                |                               |
  |<-- { "api_key": "dp_...",  ---|                               |
  |      "tier": "free" }         |                               |
```

**Endpoints**:

`POST /api/v1/auth/device` — Request authorization
```json
// Request
{ "label": "claude-session-42", "scope": "parse" }

// Response
{
  "device_code": "a1b2c3d4e5f6...",
  "user_code": "ABCD-1234",
  "verification_url": "https://www.sunholo.com/docparse/approve.html?code=ABCD-1234",
  "expires_in": 900,
  "interval": 5
}
```

`POST /api/v1/auth/device/poll` — Poll for approval
```json
// Request
{ "device_code": "a1b2c3d4e5f6..." }

// Pending
{ "error": { "code": "AUTHORIZATION_PENDING", "message": "User has not yet approved", "retryable": true, "suggested_fix": "Poll again after 5 seconds" } }

// Approved
{
  "status": "approved",
  "api_key": "dp_a1b2c3d4...",
  "key_id": "key_xxx",
  "tier": "free",
  "label": "claude-session-42"
}

// Expired
{ "error": { "code": "DEVICE_CODE_EXPIRED", "message": "Device code expired after 900s", "retryable": false, "suggested_fix": "Request a new device code via POST /api/v1/auth/device" } }
```

`docs/approve.html` — User approval page (static site, Firebase Auth)

### 7. Golden Examples with Expected Responses

For each endpoint, 1-3 canonical examples with input, expected status, response shape, and notes on variability. These live in the capability manifest and support:

- **Tool selection**: Agent knows what parse returns before calling it
- **Self-checking**: Agent can verify response matches expected shape
- **Regression testing**: Golden examples are API-level contracts
- **Repair after failures**: Agent knows what success looks like

```json
{
  "endpoint": "parse",
  "example_id": "parse_docx_blocks_basic",
  "request": {
    "sample_id": "sample_docx_basic",
    "outputFormat": "blocks"
  },
  "expected": {
    "status": 200,
    "response_shape": {
      "blocks": "array",
      "metadata": "object"
    },
    "deterministic": true,
    "notes": "Office formats always return identical output for same input"
  }
}
```

### 8. Generate Browser Playground from Manifest

The browser playground should fetch `/api/v1/capabilities` and render:

- Endpoint cards (from `endpoints[]`)
- Form fields (from `input_schema`)
- Auth indicators (from per-endpoint `auth`)
- Sample dropdowns (from `/api/v1/samples`)
- Error display (from `error_codes` + `error_schema`)
- Cost indicators (from `cost`)
- Determinism badges (from `determinism`)

This means the playground HTML becomes a generic renderer. Adding a new endpoint to the API automatically adds it to the playground. No hand-maintained HTML forms.

### 9. Copy Formats (Beyond curl)

Export the current request in multiple formats:

1. **Copy JSON** — most portable for agents
2. **Copy curl** — most portable for humans
3. **Copy Python** — SDK call
4. **Copy TypeScript** — SDK call

JSON is the primary format. Agents pass JSON between tool calls — curl requires shell escaping which adds friction.

### 10. Cost Estimation & Pricing Endpoints

`POST /api/v1/estimate`:
```json
// Request
{ "path": "report.docx", "outputFormat": "blocks" }

// Response
{
  "estimated_credits": 1,
  "format": "docx",
  "strategy": "deterministic",
  "ai_required": false,
  "estimated_ms": 15,
  "meta": { "request_id": "req_..." }
}
```

`GET /api/v1/pricing`:
```json
{
  "tiers": {
    "free": { "price_eur": 0, "requests_per_day": 60, "pages_per_month": 500 },
    "pro": { "price_eur": 29, "requests_per_day": 5000, "pages_per_month": 10000 },
    "business": { "price_eur": 99, "requests_per_day": -1, "pages_per_month": 50000 }
  },
  "credits": {
    "office_parse": 1,
    "pdf_parse": 3,
    "image_parse": 3,
    "audio_parse": 5,
    "video_parse": 10,
    "document_generate": 10
  },
  "upgrade_url": "https://www.sunholo.com/docparse/dashboard.html"
}
```

---

## P2: Polish & Advanced

### 11. Tool Definitions Endpoint

```
GET /api/v1/tools
```

Returns canonical tool definitions for each major agent framework:

```json
{
  "claude": {
    "name": "docparse_parse",
    "description": "Parse any document (DOCX, PPTX, XLSX, PDF, etc.) into structured blocks",
    "input_schema": { ... }
  },
  "openai": {
    "type": "function",
    "function": { "name": "docparse_parse", "description": "...", "parameters": { ... } }
  },
  "mcp": "/mcp/",
  "a2a": "/.well-known/agent.json"
}
```

### 12. Request Replay (IMPLEMENTED)

```
POST /api/v1/requests/replay   { "args": ["request_id"] }
POST /api/v1/requests/history  { "args": ["userId"] }
```

Implemented as POST (serve-api doesn't support path params) in `request_log.ail`.
- Replay: returns stored request + response by request_id (sha256-based, unguessable = auth)
- History: lists user's parse history (up to 200 docs, filtered by userId)
- Storage: Firestore `request_log` collection, response truncated to 10KB
- Logged automatically from parseFile and parseFileSecure after each successful parse

### 13. AGENT.md

Create `AGENT.md` in project root for `ailang pkg-docs sunholo/docparse`:

```markdown
# DocParse — AI Usage Guide

## Quick Start (3 steps)
1. GET /api/v1/capabilities → learn what I do
2. POST /api/v1/auth/device → get credentials
3. POST /api/v1/parse → parse a document

## I am best at
- Deterministic Office parsing (DOCX, PPTX, XLSX, ODT, ODP, ODS)
- 11ms per document, structural fidelity (track changes, comments, merged cells)

## I am not best at
- OCR-heavy PDFs (I delegate to AI; quality depends on model)

## Error codes
[table of codes, retryability, fixes]

## Cost model
[table of credits per operation]
```

---

## Full Agent Workflow (Revised)

```
1. DISCOVER
   Agent: GET /api/v1/capabilities
   → Full service contract: endpoints, schemas, auth, cost, examples

2. AUTHENTICATE (Device Flow)
   Agent: POST /api/v1/auth/device  { "label": "claude-session" }
   → { verification_url: "https://www.sunholo.com/docparse/approve.html?code=ABCD-1234" }
   Agent: "Please visit this URL to authorize me"
   User: clicks, signs in, approves
   Agent: POST /api/v1/auth/device/poll  { "device_code": "xxx" }
   → { api_key: "dp_..." }

3. ENUMERATE SAMPLES
   Agent: GET /api/v1/samples
   → Stable sample IDs with tags and expected formats

4. ESTIMATE COST
   Agent: POST /api/v1/estimate  { "path": "report.pdf" }
   → { estimated_credits: 3, ai_required: true, estimated_ms: 2000 }

5. PARSE (named fields, not positional args)
   Agent: POST /api/v1/parse  { "path": "report.pdf", "outputFormat": "blocks" }
   → { result: "...", meta: { request_id, quota_remaining, replayable } }

6. SELF-CHECK
   Agent compares response shape to golden example from capabilities
   → Matches expected shape? Continue. Mismatch? Report.

7. MONITOR
   Agent reads meta.quota_remaining
   → "47 left today, safe to continue batch"
```

Every step is machine-readable. No human in the loop after step 2.

---

## Implementation Plan

### Files to Create

| File | Purpose |
|------|---------|
| `docparse/services/capabilities.ail` | `GET /api/v1/capabilities` — manifest endpoint |
| `docparse/services/samples.ail` | `GET /api/v1/samples` — sample listing |
| `docparse/services/estimate.ail` | `POST /api/v1/estimate` — cost estimation |
| `docparse/services/pricing.ail` | `GET /api/v1/pricing` — machine-readable pricing |
| `docparse/services/device_auth.ail` | Device authorization flow (2 endpoints) |
| `docs/approve.html` | User approval page (Firebase Auth, minimal) |
| `AGENT.md` | AI usage guide for package consumers |

### Files to Modify

| File | Changes |
|------|---------|
| `docparse/services/api_server.ail` | Named param support on parse/unstructured, response meta block, error taxonomy, rate limit headers |
| `docparse/services/api_keys.ail` | Device code storage + approval in Firestore |
| `docs/api.html` | Playground renders from `/api/v1/capabilities` instead of hand-coded forms |
| `docs/js/firebase-app.js` | Support approve.html auth flow |

### Priority Order

| Priority | Item | Effort |
|----------|------|--------|
| **P0** | Capability manifest endpoint | Medium — JSON builder in AILANG |
| **P0** | Named JSON request bodies | Medium — param mapping in parse/unstructured endpoints |
| **P0** | Typed error taxonomy | Medium — update all error paths |
| **P0** | Response metadata (request_id, quota) | Medium — wrap all responses |
| **P0** | Sample listing endpoint | Small — static JSON from test files |
| **P1** | Device authorization flow | Large — Firestore state + polling + approval page |
| **P1** | Golden examples in manifest | Small — attach to capability JSON |
| **P1** | Playground renders from manifest | Large — rewrite api.html JS to be schema-driven |
| **P1** | Copy JSON / Python / TS formats | Small — template expansion |
| **P1** | Cost estimation + pricing endpoints | Medium — format detection + tier lookup |
| **P2** | Tool definitions endpoint | Small — static JSON |
| **P2** | Request replay endpoint | Medium — Firestore request log |
| **P2** | AGENT.md | Small — documentation |

### What to Deprioritize

These are fine but not the AI-first differentiator:
- Prism-highlighted pretty output
- Confirmation modal polish
- Mobile refinements beyond basic responsiveness
- Timing tab complexity beyond simple metadata

---

## Open Questions

1. **Named params vs args**: Can `serve-api` bind named JSON fields to function parameters, or do we destructure a JSON object arg? Need to check AILANG runtime support.
2. **Device-provisioned key expiry**: Auto-expire after 30 days? Or permanent like dashboard keys?
3. **Scoped keys**: Should device flow support `"scope": "parse"` to create parse-only keys?
4. **Rate limit headers**: Can `serve-api` inject custom HTTP headers? May need AILANG runtime support or a middleware pattern.
5. **Manifest caching**: Should `/api/v1/capabilities` be cached aggressively (it's mostly static) or regenerated per request?
6. **Request logging**: Where to store request/response pairs for replay? Firestore (expensive at scale) or ephemeral (Cloud Run memory)?

---

## Relationship to Existing Work

- **A2A Agent Card** (`/.well-known/agent.json`): Remains as the A2A-protocol-specific discovery point. The capability manifest is DocParse-specific and richer.
- **OpenAPI spec** (`/api/_meta/openapi.json`): Auto-generated by serve-api. The capability manifest adds cost, determinism, examples, and auth metadata that OpenAPI doesn't carry.
- **Browser Playground** (`docs/api.html`): Becomes a thin renderer over the manifest. Existing hand-coded forms are replaced by schema-driven generation.
- **MCP** (`/mcp/`): Auto-generated by serve-api. Agents using MCP get tool definitions for free. The capability manifest helps agents decide whether to use MCP or REST.
