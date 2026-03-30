# DocParse v0.11.0 — User-Defined Structured Extraction

**Status**: PLANNED — FAST-TRACK (2026-03-24)
**Theme**: Let users specify the output schema they want — DocParse uses AI to extract exactly that structure from any document
**Depends on**: v0.7.0 (API server), v0.8.0 (API keys for metering)
**Priority**: HIGH — competitive pressure from Eagle-Doc and field extraction SaaS market; existing demo in ailang-demos proves the pattern works

## Motivation

Today DocParse extracts documents into its built-in Block ADT (Text, Heading, Table, Image, etc.). This is great for general-purpose parsing, but real-world users often want *specific* structures:

- **Invoice processing**: extract `{vendor, date, line_items: [{description, qty, unit_price}], total}`
- **Resume parsing**: extract `{name, email, experience: [{company, role, dates}], skills: [string]}`
- **Contract analysis**: extract `{parties: [string], effective_date, termination_clause, payment_terms}`
- **Scientific papers**: extract `{title, authors, abstract, sections: [{heading, body}], references}`
- **Meeting notes**: extract `{date, attendees, action_items: [{owner, task, due}], decisions}`

The Block ADT is an intermediate representation. Structured extraction is the *final mile* — turning parsed content into the exact shape the user's downstream system needs.

### Why DocParse Is Uniquely Positioned

1. **We already parse the document** — Office formats are parsed deterministically, PDFs via AI. The hard extraction work is done.
2. **We already have AI integration** — `callJsonSimple` and `callJson` with schema validation are battle-tested in `direct_ai_parser.ail`, `ai_generator.ail`, and `layout_ai.ail`.
3. **We already have the API** — `serve-api` with key management, OpenAPI spec, and Unstructured compatibility.
4. **Block ADT as context** — Instead of asking AI to extract from raw file bytes, we feed it our already-parsed structured blocks. This is cheaper, faster, and more accurate than raw extraction.

### Existing Prior Art in AILANG

The `ai_generator.ail` module already demonstrates the core pattern:
- System prompt defines a JSON schema for blocks
- `callJsonSimple()` returns structured JSON
- Pattern matching parses JSON into typed AILANG values

The `layout_ai.ail` module uses `callJson(prompt, schemaString)` with explicit JSON Schema for table inference. This is exactly the pattern we need — but user-supplied instead of hardcoded.

### Prior Art: ailang-demos DocParse Demo

**The structured extraction pattern has already been demonstrated in the `ailang-demos` repo.** The original DocParse demo in `sunholo-data/ailang-demos` included structured output extraction — parsing documents and then extracting domain-specific fields (e.g., contract obligations, invoice line items) via AI. This means:

1. **The core pattern is proven** — not theoretical; it ran in the WASM browser demo
2. **Implementation should be fast** — port the existing demo logic into `schema_extractor.ail`
3. **The two-stage pipeline works** — demo proved that parse → AI extract is viable and effective
4. **User demand exists** — the demo was created specifically because users wanted structured output from parsed documents

This significantly de-risks v0.11.0 and makes it a candidate for fast-tracking ahead of other planned versions.

### Competitive Pressure: Eagle-Doc and Field Extraction SaaS

Eagle-Doc (eagle-doc.com) and similar services (Nanonets, Rossum, Mindee) charge for AI-based field extraction from PDFs — invoices, receipts, contracts, bank statements. They offer:
- Pre-built extraction models for common document types
- 95%+ claimed accuracy with zero configuration
- Structured JSON output with domain-specific fields

DocParse's v0.11.0 directly competes with this market segment, with key advantages:
- **Office format support** — none of the field extraction SaaS tools parse DOCX/PPTX/XLSX
- **Two-stage pipeline** — deterministic parse first means AI does less work (cheaper, more accurate)
- **User-defined schemas** — JSON Schema, not just pre-built models
- **Self-hostable** — not cloud-locked
- **Pluggable AI** — user chooses their model (Gemini, Claude, Ollama)

## Design

### Two-Stage Architecture

```
Stage 1: Parse (deterministic)          Stage 2: Extract (AI-powered)
┌─────────────────────────┐             ┌─────────────────────────────┐
│  Document (any format)  │             │  Parsed Blocks + Schema     │
│         │               │             │         │                   │
│    format_router        │             │   schema_extractor.ail      │
│         │               │             │         │                   │
│    [Block ADT]  ────────┼────────────>│   callJson(blocks, schema)  │
│                         │             │         │                   │
│  (existing pipeline)    │             │   Validated JSON output     │
└─────────────────────────┘             └─────────────────────────────┘
```

Stage 1 is the existing DocParse parse pipeline — zero changes needed. Stage 2 is new: it takes the Block ADT output and a user-supplied JSON Schema, then uses AI to extract matching structured data.

This two-stage approach has key advantages:
- **Deterministic first pass**: Tables, headings, metadata are already extracted correctly
- **AI does less work**: It's transforming structured text, not OCR-ing pixels
- **Cheaper**: Block text is much smaller than base64-encoded file content
- **Auditable**: Users can see both the raw blocks AND the extracted structure

### User-Supplied Schema

Users provide a JSON Schema (draft 2020-12 or 7) describing their desired output:

```json
{
  "type": "object",
  "properties": {
    "vendor": {"type": "string"},
    "invoice_number": {"type": "string"},
    "date": {"type": "string", "format": "date"},
    "line_items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "description": {"type": "string"},
          "quantity": {"type": "number"},
          "unit_price": {"type": "number"}
        },
        "required": ["description", "quantity", "unit_price"]
      }
    },
    "total": {"type": "number"}
  },
  "required": ["vendor", "line_items", "total"]
}
```

### Extraction Prompt Strategy

The extraction prompt combines:
1. **The parsed blocks** — serialized as compact JSON (the existing `output_formatter` already does this)
2. **The user's schema** — included verbatim so the AI knows the target shape
3. **Optional extraction hints** — user-provided natural language guidance ("the vendor name is usually in the top-left", "dates are in DD/MM/YYYY format")
4. **Validation rules** — "Return ONLY valid JSON matching the schema. No markdown fencing. Compact format."

```ailang
func extractWithSchema(blocks: [Block], schema: string, hints: string) -> string ! {AI} {
  let blockJson = blocksToCompactJson(blocks);
  let prompt = "You are a structured data extractor.\n\n" ++
    "DOCUMENT CONTENT (parsed blocks):\n" ++ blockJson ++ "\n\n" ++
    "TARGET SCHEMA:\n" ++ schema ++ "\n\n" ++
    (if hints != "" then "EXTRACTION HINTS:\n" ++ hints ++ "\n\n" else "") ++
    "Extract the requested data from the document content. " ++
    "Return ONLY valid compact JSON matching the schema. " ++
    "If a field cannot be determined, use null. " ++
    "For arrays, include all matching items found in the document.";
  callJson(prompt, schema)
}
```

### Schema Templates (Built-in Library)

For common use cases, provide pre-built schema templates that users can reference by name:

| Template | Schema | Fields |
|----------|--------|--------|
| `invoice` | Invoice extraction | vendor, date, line_items, subtotal, tax, total, currency |
| `resume` | Resume/CV parsing | name, email, phone, experience[], education[], skills[] |
| `contract` | Contract analysis | parties[], effective_date, term, payment_terms, clauses[] |
| `receipt` | Receipt scanning | merchant, date, items[], subtotal, tax, total, payment_method |
| `table` | Generic table extraction | headers[], rows[][], metadata |
| `form` | Form field extraction | fields: [{label, value, type}] |
| `meeting_notes` | Meeting minutes | date, attendees[], agenda[], action_items[], decisions[] |

Templates are stored as JSON Schema files under `docparse/schemas/` and loaded at startup.

### Validation & Retry

After extraction, validate the output against the schema:

1. **JSON parse** — handle truncation with existing `repairJsonArray` from `direct_ai_parser`
2. **Schema validation** — check required fields, types, array constraints
3. **Retry on failure** — one retry with error feedback appended to prompt
4. **Graceful degradation** — return partial result with `_extraction_warnings` field

```ailang
func extractAndValidate(blocks: [Block], schema: string, hints: string) -> string ! {AI} {
  let result = extractWithSchema(blocks, schema, hints);
  match validateJson(result, schema) {
    Ok(valid) => valid,
    Err(errors) => {
      -- Retry with error context
      let retryHints = hints ++ "\nPrevious attempt had errors: " ++ join(", ", errors);
      extractWithSchema(blocks, schema, retryHints)
    }
  }
}
```

## CLI Interface

```bash
# Extract with inline schema
./bin/docparse invoice.pdf --extract --schema '{"type":"object",...}'

# Extract with schema file
./bin/docparse invoice.pdf --extract --schema-file schemas/invoice.json

# Extract with built-in template
./bin/docparse invoice.pdf --extract --template invoice

# Extract with hints
./bin/docparse invoice.pdf --extract --template invoice \
  --hints "Dates are in European DD/MM/YYYY format"

# Batch extraction (same schema across multiple files)
./bin/docparse invoices/*.pdf --extract --template invoice --output results/
```

## API Endpoints

### `POST /api/v1/extract`

Primary structured extraction endpoint.

**Request:**
```json
{
  "file": "<base64 or filepath>",
  "schema": { ... },
  "hints": "optional natural language guidance",
  "include_blocks": false
}
```

**Response:**
```json
{
  "result": {
    "vendor": "Acme Corp",
    "invoice_number": "INV-2026-0042",
    "date": "2026-03-15",
    "line_items": [
      {"description": "Widget A", "quantity": 100, "unit_price": 5.99},
      {"description": "Widget B", "quantity": 50, "unit_price": 12.50}
    ],
    "total": 1224.00
  },
  "blocks": [...],
  "module": "docparse/services/schema_extractor",
  "func": "extract",
  "elapsed_ms": 1230,
  "_extraction_confidence": 0.95
}
```

### `POST /api/v1/extract/template`

Extraction using a built-in template name.

**Request:**
```json
{
  "file": "<base64 or filepath>",
  "template": "invoice",
  "hints": "optional"
}
```

### `GET /api/v1/templates`

List available schema templates.

**Response:**
```json
{
  "templates": [
    {"name": "invoice", "description": "Invoice/bill extraction", "fields": 7},
    {"name": "resume", "description": "Resume/CV parsing", "fields": 6},
    ...
  ]
}
```

### `POST /api/v1/extract/batch`

Extract from multiple documents with the same schema. Returns an array of results.

## AILANG Modules

### New: `docparse/services/schema_extractor.ail`

Core extraction logic:

```ailang
module docparse/services/schema_extractor

import std/json (encode, decode, jo, ja, js, ji, jf, jb, kv, getString, getArray, getObject)
import std/string (join, split, substring)
import std/ai (callJson, callJsonSimple)
import docparse/services/output_formatter (blocksToJson)

-- Main extraction function
export func extractWithSchema(blocks: [Block], schema: string, hints: string) -> string ! {AI} {
  ...
}

-- Template-based extraction
export func extractWithTemplate(blocks: [Block], templateName: string, hints: string) -> string ! {AI, FS} {
  let schema = loadTemplate(templateName);
  extractWithSchema(blocks, schema, hints)
}

-- Schema validation (pure)
export pure func validateExtraction(json: string, schema: string) -> Result[string, [string]] {
  ...
}
```

### New: `docparse/schemas/` directory

Pre-built JSON Schema templates:

```
docparse/schemas/
├── invoice.json
├── resume.json
├── contract.json
├── receipt.json
├── table.json
├── form.json
└── meeting_notes.json
```

### Modified: `docparse/main.ail`

Add `--extract`, `--schema`, `--schema-file`, `--template`, `--hints` flags.

### Modified: `docparse/services/api_server.ail`

Add `/api/v1/extract`, `/api/v1/extract/template`, `/api/v1/templates` endpoints.

## SDK Integration

Building on v0.9.0 SDKs:

```python
from ailang_parse import DocParse

client = DocParse(api_key="dp_...")

# Schema-based extraction
invoice = client.extract("invoice.pdf", schema={
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "total": {"type": "number"},
        "line_items": {"type": "array", "items": {...}}
    }
})
print(invoice["vendor"])  # "Acme Corp"
print(invoice["total"])   # 1224.00

# Template-based extraction
invoice = client.extract("invoice.pdf", template="invoice")

# With hints
resume = client.extract("cv.pdf", template="resume",
    hints="This is a European CV, dates are DD/MM/YYYY")

# Batch extraction
invoices = client.extract_batch(
    ["inv1.pdf", "inv2.pdf", "inv3.pdf"],
    template="invoice"
)
```

## Competitive Landscape

| Tool | Custom Schema? | Two-Stage? | Office Deterministic? | Self-Hostable? |
|------|---------------|------------|----------------------|----------------|
| **DocParse** | JSON Schema + templates | Parse → Extract | Yes (our moat) | Yes |
| Eagle-Doc | No — pre-built models (invoice, receipt, etc.) | No | No (PDF/image only) | No |
| Unstructured | No — fixed element types | No | No | Yes |
| LlamaParse | "Parsing instructions" (NL only) | No | No | No |
| Docling | No — fixed DoclingDocument | No | Partial | Yes |
| Azure Doc Intelligence | Pre-built models only | No | No | No |
| AWS Textract | Queries (NL questions) | No | No | No |
| Nanonets | Pre-built + custom training | No | No | No |
| Mindee | Pre-built + custom | No | No | No |

**Our differentiation:**
1. **User-defined JSON Schema** — not just NL instructions or pre-built models
2. **Two-stage pipeline** — deterministic parse + AI extract is more accurate and cheaper than AI-from-scratch
3. **Template library** — ready-to-use schemas for common use cases
4. **Office format advantage** — tables, track changes, comments are already perfectly extracted before AI sees them

## Implementation Phases

### Phase 1: Core Extraction Engine
- `schema_extractor.ail` with `extractWithSchema` function
- Schema-in-prompt strategy using `callJson`
- JSON validation and retry logic
- CLI `--extract --schema` flag
- 5 test files with golden extraction outputs

### Phase 2: Template Library
- 7 built-in schema templates (invoice, resume, contract, receipt, table, form, meeting_notes)
- CLI `--template` flag
- Template loading from `docparse/schemas/`
- Template listing endpoint

### Phase 3: API Endpoints
- `POST /api/v1/extract` endpoint
- `POST /api/v1/extract/template` endpoint
- `GET /api/v1/templates` endpoint
- OpenAPI spec updates
- Metering integration with API key tiers

### Phase 4: Batch & Confidence
- Batch extraction endpoint
- Confidence scoring (field-level coverage metric)
- `include_blocks` option for debugging
- Extraction hints documentation

### Phase 5: Advanced Features
- Schema inference: "Here's a sample document, suggest a schema"
- Multi-document extraction: extract across a set of related documents
- Incremental schemas: extract additional fields from already-parsed results
- Extraction history/caching in Firestore

## Metering & Tier Impact

Structured extraction uses AI, so it counts against the user's AI budget:

| Tier | Extract Requests/Day | Notes |
|------|---------------------|-------|
| Free | 5 | Shared with parse AI budget |
| Pro | 500 | Separate from parse quota |
| Enterprise | Custom | Dedicated AI budget |

## Success Metrics

- Extract accuracy >90% on invoice/resume/receipt test sets
- Round-trip latency <3s for typical single-page Office documents
- Template coverage for top 5 enterprise use cases
- Zero regression on existing parse benchmarks (extraction is additive)

## Open Questions

1. **Schema complexity limits** — Should we cap schema depth/size to prevent prompt bloat?
2. **Streaming extraction** — For very large documents, should we extract page-by-page and merge?
3. **Schema versioning** — How do template schemas evolve without breaking clients?
4. **Confidence thresholds** — Should we return partial results or fail if confidence is below a threshold?
