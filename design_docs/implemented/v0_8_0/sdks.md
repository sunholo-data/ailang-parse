# DocParse SDKs — Client Libraries Design

**Status**: Implemented — Python v0.1.3 (PyPI), JS v0.1.3 (npm), Go module shipped
**Theme**: Thin HTTP wrappers for Python, JavaScript/TypeScript, and Go — Unstructured-client compatible
**Depends on**: v0.8.0 (API server, key management)

## Motivation

DocParse has a REST API deployed on Cloud Run with 13 parse formats, 8 generate formats, and per-user API key management. Users currently interact via curl or raw HTTP. SDKs reduce friction for the three most common integration languages and provide a migration path from Unstructured's client libraries.

## Design Principles

1. **Thin wrappers** — SDKs are HTTP clients, not reimplementations. All parsing happens server-side.
2. **Unstructured-compatible** — Accept the same constructor args as `unstructured-client` so migration is a one-line change.
3. **Zero heavy dependencies** — Use only the language's standard HTTP library (or minimal, well-known alternatives).
4. **Type-safe** — Full type definitions for request/response shapes.
5. **Sync + async** — Python and JS offer both synchronous and async interfaces.

## SDK Specifications

### Python — `ailang-parse`

**Install:** `pip install ailang-parse`

**Dependencies:** `requests` (sync), `httpx` (async, optional)

**Usage:**
```python
from ailang_parse import DocParse

client = DocParse(api_key="dp_a1b2c3d4...")

# Parse a file (upload)
result = client.parse("report.docx")
print(result.blocks)       # List[Block]
print(result.metadata)     # DocMetadata
print(result.markdown)     # str

# Parse with output format
result = client.parse("report.docx", output_format="markdown")

# Convert between formats
client.convert("input.docx", "output.html")

# Unstructured compatibility
from ailang_parse import UnstructuredClient
client = UnstructuredClient(
    server_url="https://api.parse.sunholo.com"
)
elements = client.general.partition(file="report.docx")
# Returns List[Element] in Unstructured format
```

**Unstructured migration:**
```python
# Before
from unstructured_client import UnstructuredClient
client = UnstructuredClient(server_url="https://api.unstructured.io")

# After — one import change
from ailang_parse import UnstructuredClient
client = UnstructuredClient(
    server_url="https://api.parse.sunholo.com"
)
# All existing code works unchanged
```

**Types:**
```python
@dataclass
class Block:
    type: str              # "text", "heading", "table", "image", etc.
    text: str
    level: int             # heading level (1-6) or 0
    style: str             # "normal", "bold", "track-insert", etc.
    cells: List[List[Cell]]  # for table blocks
    children: List[Block]    # for section blocks

@dataclass
class ParseResult:
    status: str
    filename: str
    format: str
    blocks: List[Block]
    metadata: DocMetadata
    markdown: str          # pre-rendered markdown

@dataclass
class DocMetadata:
    title: str
    author: str
    created: str
    modified: str
    page_count: int

@dataclass
class KeyInfo:
    key_id: str
    label: str
    tier: str
    created: str
    active: bool

@dataclass
class UsageInfo:
    requests_today: int
    pages_this_month: int
    total_requests: int
    total_pages: int
    quota: QuotaInfo
```

**Key management:**
```python
# Generate a key (requires Firebase auth token)
key = client.keys.generate(label="my-app", auth_token="...")
print(key.raw_key)  # dp_a1b2c3d4... (shown once)

# List keys
keys = client.keys.list(auth_token="...")

# Revoke
client.keys.revoke(key_id="abc123", auth_token="...")

# Usage stats
usage = client.keys.usage(key_id="abc123", auth_token="...")
print(usage.requests_today, "/", usage.quota.requests_per_day)
```

**Package structure:**
```
docparse/
├── __init__.py          # DocParse client class
├── client.py            # HTTP client, retry logic
├── types.py             # Block, ParseResult, etc.
├── compat.py            # UnstructuredClient wrapper
├── keys.py              # Key management methods
└── py.typed             # PEP 561 marker
```

### JavaScript / TypeScript — `@ailang/parse`

**Install:** `npm install @ailang/parse`

**Dependencies:** None (uses native `fetch`)

**Usage:**
```typescript
import { DocParse } from '@ailang/parse';

const client = new DocParse({ apiKey: 'dp_a1b2c3d4...' });

// Parse a file
const result = await client.parse(file);  // File or Blob
console.log(result.blocks);
console.log(result.markdown);

// Parse from URL or path (server-side)
const result = await client.parseFile('report.docx');

// Unstructured compatibility
import { UnstructuredClient } from '@ailang/parse/compat';
const client = new UnstructuredClient({
  serverUrl: 'https://api.parse.sunholo.com'
});
const elements = await client.general.partition({ file: blob });
```

**Types (TypeScript):**
```typescript
interface Block {
  type: 'text' | 'heading' | 'table' | 'image' | 'list' | 'section' | 'change' | 'audio' | 'video';
  text: string;
  level: number;
  style: string;
  cells?: Cell[][];
  children?: Block[];
}

interface ParseResult {
  status: string;
  filename: string;
  format: string;
  blocks: Block[];
  metadata: DocMetadata;
  summary: Summary;
}

interface DocParseOptions {
  apiKey: string;
  baseUrl?: string;  // default: Cloud Run URL
  timeout?: number;  // default: 30000ms
}
```

**Package structure:**
```
src/
├── index.ts             # DocParse class
├── client.ts            # fetch wrapper, error handling
├── types.ts             # Block, ParseResult, etc.
├── compat.ts            # UnstructuredClient
└── keys.ts              # Key management
```

**Build:** ESM + CJS dual output, TypeScript declarations included.

### Go — `ailang-parse-go`

**Install:** `go get github.com/sunholo-data/ailang-parse-go`

**Dependencies:** Standard library only (`net/http`, `encoding/json`)

**Usage:**
```go
package main

import (
    "fmt"
    "github.com/sunholo-data/ailang-parse-go"
)

func main() {
    client := docparse.New("dp_a1b2c3d4...")

    // Parse a file
    result, err := client.ParseFile(ctx, "report.docx")
    if err != nil {
        log.Fatal(err)
    }
    fmt.Println(result.Blocks)

    // Parse with options
    result, err = client.Parse(ctx, file, docparse.ParseOptions{
        OutputFormat: "markdown",
    })
}
```

**Types:**
```go
type Block struct {
    Type     string   `json:"type"`
    Text     string   `json:"text"`
    Level    int      `json:"level"`
    Style    string   `json:"style"`
    Cells    [][]Cell `json:"cells,omitempty"`
    Children []Block  `json:"children,omitempty"`
}

type ParseResult struct {
    Status   string      `json:"status"`
    Filename string      `json:"filename"`
    Format   string      `json:"format"`
    Blocks   []Block     `json:"blocks"`
    Metadata DocMetadata `json:"metadata"`
}

type Client struct {
    APIKey  string
    BaseURL string
    HTTP    *http.Client
}
```

**Package structure:**
```
ailang-parse-go/
├── client.go            # Client struct, HTTP methods
├── types.go             # Block, ParseResult, etc.
├── parse.go             # Parse/Convert methods
├── keys.go              # Key management
├── compat.go            # Unstructured compatibility
├── client_test.go       # Tests
└── go.mod
```

## API Mapping

All SDKs map to the same REST endpoints:

| SDK Method | HTTP | Endpoint |
|-----------|------|----------|
| `parse(file)` | POST | `/api/v1/parse` |
| `convert(file, target)` | POST | `/api/v1/convert` |
| `formats()` | GET | `/api/v1/formats` |
| `health()` | GET | `/api/v1/health` |
| `keys.list()` | POST | `/api/v1/keys/list` |
| `keys.revoke(keyId)` | POST | `/api/v1/keys/revoke` |
| `keys.rotate(keyId)` | POST | `/api/v1/keys/rotate` |
| `keys.usage(keyId)` | POST | `/api/v1/keys/usage` |
| Unstructured compat | POST | `/general/v0/general` |

## Error Handling

All SDKs use the same error model:

| HTTP Status | Error | SDK Behavior |
|-------------|-------|-------------|
| 200 | Success | Return parsed result |
| 400 | Bad request | Raise `DocParseError` with message |
| 401 | Invalid API key | Raise `AuthError` |
| 429 | Quota exceeded | Raise `QuotaError` with retry-after |
| 500 | Server error | Raise `ServerError`, retry once |

## Implementation Plan

### Phase 1: Python SDK
1. Create `sunholo-data/docparse-python` repo
2. Implement `DocParse` client with `requests`
3. Add `UnstructuredClient` compatibility wrapper
4. Type hints + `py.typed` marker
5. Publish to PyPI as `ailang-parse`

### Phase 2: JavaScript SDK
1. Create `sunholo-data/docparse-js` repo
2. Implement with native `fetch` (browser + Node 18+)
3. TypeScript types + dual ESM/CJS build
4. `UnstructuredClient` compat
5. Publish to npm as `@ailang/parse`

### Phase 3: Go SDK
1. Create `sunholo-data/ailang-parse-go` repo
2. Standard library HTTP client, context support
3. Full type definitions
4. Publish as Go module

### Phase 4: Documentation
1. README with quick start for each SDK
2. API reference generated from types
3. Migration guide from Unstructured
4. Examples directory in each repo

## Testing Strategy

Each SDK tested against the live Cloud Run endpoint:
- Parse all 13 formats (use test files from `data/test_files/`)
- Key management (generate, list, revoke, rotate, usage)
- Unstructured compatibility (same output as `unstructured-client`)
- Error handling (invalid key, quota exceeded, file not found)
- Timeout and retry behavior

## Success Criteria

1. `pip install ailang-parse && python -c "from ailang_parse import DocParse"` works
2. `npm install @ailang/parse && node -e "require('@ailang/parse')"` works
3. `go get github.com/sunholo-data/ailang-parse-go` works
4. All three SDKs parse a DOCX file and return identical Block structures
5. Unstructured migration is a one-line change in all three languages
6. Type definitions provide full IDE autocomplete
