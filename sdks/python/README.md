# AILANG Parse Python SDK

<!-- mcp-name: io.github.sunholo-data/parse -->

Python client and MCP server for the [AILANG Parse](https://www.sunholo.com/ailang-parse/) document parsing API. Parse 15 formats (including LaTeX/arXiv), generate 8 — zero dependencies for Office, pluggable AI for PDFs.

## Install

```bash
pip install ailang-parse
```

## MCP Server (Claude Desktop, Cursor, VS Code)

Run as a stdio MCP server that bridges to the hosted AILANG Parse API. Stdlib only — works in any Python >= 3.8 environment.

```json
{
  "mcpServers": {
    "ailang-parse": {
      "command": "uvx",
      "args": ["ailang-parse", "mcp"]
    }
  }
}
```

Add to `claude_desktop_config.json` (Claude Desktop), `.cursor/mcp.json` (Cursor), or `.vscode/settings.json` (VS Code). Provides 7 tools: parse, convert, formats, estimate, auth, auth-poll, and account.

## Quick Start

```python
from ailang_parse import DocParse

client = DocParse(api_key="dp_your_key_here")

# Parse a document
result = client.parse("report.docx")
print(f"{len(result.blocks)} blocks, format: {result.format}")

for block in result.blocks:
    if block.type == "heading":
        print(f"  H{block.level}: {block.text}")
    elif block.type == "table":
        print(f"  Table: {len(block.headers)} cols, {len(block.rows)} rows")
    elif block.type == "change":
        print(f"  {block.change_type} by {block.author}: {block.text}")
    else:
        print(f"  {block.type}: {block.text[:80]}")
```

## Parse Documents

```python
# Parse with different output formats
result = client.parse("report.docx")                        # Block ADT (default)
result = client.parse("report.docx", output_format="markdown")  # Markdown
result = client.parse("report.docx", output_format="html")      # HTML
result = client.parse("report.docx", output_format="markdown+metadata")  # Markdown with sections

# Upload a local file (multipart)
result = client.parse_file("local/report.docx")

# Parse from a signed URL (GCS, S3, Azure Blob — no local file needed)
result = client.parse_url(
    "https://storage.googleapis.com/bucket/doc.docx?X-Goog-Signature=...",
    output_format="markdown+metadata",
)

# Access structured data
print(result.status)          # "success"
print(result.filename)        # "report.docx"
print(result.format)          # "zip-office"
print(result.blocks)          # List[Block]
print(result.metadata.title)  # Document title
print(result.metadata.author) # Document author
print(result.summary.tables)  # Number of tables found

# markdown+metadata format includes sections
print(result.markdown)        # Full rendered markdown
for section in result.sections:
    print(f"  {section.heading}: {section.markdown[:60]}...")
```

## Response Metadata

Every parse result includes quota and request metadata from response headers:

```python
result = client.parse("report.docx")
meta = result.response_meta

print(meta.request_id)            # "req_abc123"
print(meta.tier)                  # "free", "pro", or "business"
print(meta.quota_remaining_day)   # Requests left today
print(meta.quota_remaining_month) # Requests left this month
print(meta.quota_remaining_ai)    # AI requests remaining
print(meta.format)                # Detected input format ("docx", etc.)
print(meta.replayable)            # Whether this request can be replayed
```

## Error Handling

Every error type carries the response headers — `request_id` for log
correlation, `replayable` for retry decisions, plus `details` and
`suggested_fix` from the response body:

```python
from ailang_parse import DocParse, DocParseError, AuthError, QuotaError

client = DocParse()
try:
    result = client.parse_file("report.docx")
except AuthError as e:
    log.error("auth: %s request_id=%s", e, e.request_id)
except QuotaError as e:
    log.error("quota tier=%s request_id=%s", e.tier, e.request_id)
except DocParseError as e:
    log.error("error: %s status=%d replayable=%s request_id=%s",
              e, e.status_code, e.replayable, e.request_id)
```

## Retries

Opt in to retries with `RetryPolicy`. `respect_replayable` honours the
server-provided `X-AilangParse-Replayable` header so 5xx responses the
server explicitly marks safe-to-retry are attempted again:

```python
from ailang_parse import DocParse, RetryPolicy

client = DocParse(retry=RetryPolicy(
    max_retries=3,
    retryable_statuses={502, 503, 504},
    respect_replayable=True,
))
```

## Parse from GCS

The `parse_gs_uri` convenience signs a `gs://` URI and parses it in one
call. Requires the `gcs` extra:

```bash
pip install 'ailang-parse[gcs]'
```

```python
result = client.parse_gs_uri(
    "gs://my-bucket/path/to/doc.pdf",
    ttl=900,
    output_format="markdown+metadata",
)
```

Auth defaults to Application Default Credentials; pass an explicit
`credentials=` (or `service_account_email=`) to override.

### Signing strategy (auto-detected)

- **JSON-key credentials** (`GOOGLE_APPLICATION_CREDENTIALS` pointing at
  an SA key file) → URL is signed locally with the private key. Fast,
  no extra API call.
- **Token-only credentials** (Cloud Run, GCE, GKE metadata server, or
  `gcloud auth application-default login`) → URL is signed via Google's
  IAM `SignBlob` API. No private key needed.

**Cloud Run setup (one-time):** the runtime service account needs
`roles/iam.serviceAccountTokenCreator` on **itself**:

```bash
SA="my-service@my-project.iam.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --member="serviceAccount:$SA" \
  --role="roles/iam.serviceAccountTokenCreator"
```

After the grant, `client.parse_gs_uri("gs://...")` works from any
Cloud Run service running as that SA with no further config.

For impersonation flows, pass an explicit
`service_account_email="signer@project.iam.gserviceaccount.com"`.

## RAG Chunking

`result.flatten(policy)` turns the Block ADT into JSON-friendly chunks
ready for an embedder. The default policy emits text, headings, table
rows (with header context), and lists — and tracks section ancestry:

```python
from ailang_parse import FlattenPolicy

chunks = result.flatten(FlattenPolicy(
    max_chunk_chars=4000,
    embed_images=True,             # always emits ImageBlock chunks (placeholder if no caption)
    embed_changes=True,            # ChangeBlock + author metadata -> chunk
    embed_comments=True,           # CommentBlock + author + resolved -> chunk
    on_table="row",                # "row" (default), "whole", or callable(block, meta) -> [Chunk]
    on_table_cell_newlines="space",  # "preserve" (default) | "escape" | "space"
    on_table_cell_pipes="escape",  # same modes — round-trippable structured retrieval
    section_path=True,
))

for c in chunks:
    embed(c.text, metadata=c.metadata.to_dict())
```

### Custom chunk metadata

Use `metadata.extras` to carry consumer-defined fields. The `on_table`
callable receives a mutable `ChunkMetadata` and can populate it:

```python
def my_table(block, md):
    md.extras["tenant_id"] = "acme"
    md.extras["confidence"] = 0.93
    return [Chunk(text=..., metadata=md)]

chunks = result.flatten(FlattenPolicy(on_table=my_table))
```

`extras` values should be JSON-serializable — they pass through to
Pinecone/Vertex/Chroma metadata unchanged.

### Image visibility

`embed_images=True` always emits an `ImageBlock` chunk. When the image
has no AI caption, the chunk text is a placeholder
(`"[image: image/png, 12345 bytes]"`) and
`metadata.extras["image_has_description"]` is `False`. To match the
v0.6.0 "skip empty" behaviour:

```python
chunks = [
    c for c in result.flatten(FlattenPolicy(embed_images=True))
    if c.metadata.block_type != "image"
    or c.metadata.extras.get("image_has_description")
]
```

## Supported Formats

```python
formats = client.formats()
print(formats.parse)       # ['docx', 'pptx', 'xlsx', 'odt', 'odp', 'ods', 'html', 'md', 'csv', 'epub', 'pdf', 'png', 'jpg']
print(formats.generate)    # ['docx', 'pptx', 'xlsx', 'odt', 'odp', 'ods', 'html', 'md']
print(formats.ai_required) # ['pdf', 'png', 'jpg', 'gif', 'bmp', 'tiff']
```

## Block Types

AILANG Parse returns 9 block types:

| Type | Fields | Description |
|------|--------|-------------|
| `text` | `text`, `style`, `level` | Paragraphs, code blocks |
| `heading` | `text`, `level` (1-6) | Document headings |
| `table` | `headers`, `rows` | Tables with merge tracking |
| `list` | `items`, `ordered` | Ordered/unordered lists |
| `image` | `description`, `mime`, `data_length` | Embedded images |
| `audio` | `transcription`, `mime` | Audio transcriptions |
| `video` | `description`, `mime` | Video descriptions |
| `section` | `kind`, `children` | Slides, sheets, headers/footers |
| `change` | `change_type`, `author`, `date`, `text` | Track changes |

### Table cells

Table cells can be simple strings or merged cells:

```python
for block in result.blocks:
    if block.type == "table":
        for cell in block.headers:
            print(f"  {cell.text} (colspan={cell.col_span}, merged={cell.merged})")
```

### Nested sections

Section blocks contain child blocks (slides, sheets, headers/footers):

```python
for block in result.blocks:
    if block.type == "section":
        print(f"Section: {block.kind}")  # "slide", "sheet", "header", "footer", etc.
        for child in block.children:
            print(f"  {child.type}: {child.text[:50]}")
```

## API Key Management

API key resolution (checked in order):
1. Explicit `api_key` parameter
2. `DOCPARSE_API_KEY` environment variable
3. Saved credentials in `~/.config/ailang-parse/credentials.json`

Use the device auth flow to get an API key. The user signs in once — the key is saved automatically and reused in future sessions.

```python
from ailang_parse import DocParse

# First time: device_auth() opens browser, user signs in, key saved to disk
client = DocParse()
client.device_auth(label="my-agent")

# Future sessions: key auto-loaded from ~/.config/ailang-parse/credentials.json
client = DocParse()
result = client.parse("report.docx")

# Or set env var: export DOCPARSE_API_KEY=dp_your_key
client = DocParse()
result = client.parse("report.docx")

# Check usage
usage = client.keys.usage(key_id="abc123", user_id="user123")
print(f"Requests today: {usage.usage.requests_today} / {usage.quota.requests_per_day}")

# Rotate (new key, old one revoked, same tier)
new_key = client.keys.rotate(key_id="abc123", user_id="user123")
print(new_key.key)  # New key

# Revoke
client.keys.revoke(key_id="abc123", user_id="user123")
```

## Migrating from Unstructured

One import change:

```python
# Before
from unstructured_client import UnstructuredClient
client = UnstructuredClient(server_url="https://api.unstructured.io")

# After
from ailang_parse import UnstructuredClient
client = UnstructuredClient(
    server_url="https://api.parse.sunholo.com"
)

# All existing code works unchanged
elements = client.general.partition(file="report.docx")
for el in elements:
    print(f"{el.type}: {el.text[:80]}")
    print(f"  metadata: {el.metadata.filename}")
```

## Error Handling

```python
from ailang_parse import DocParse, DocParseError, AuthError, QuotaError

client = DocParse(api_key="dp_invalid")

try:
    result = client.parse("file.docx")
except AuthError as e:
    print(f"Bad key: {e}")           # 401
except QuotaError as e:
    print(f"Quota exceeded: {e}")    # 429
except DocParseError as e:
    print(f"API error ({e.status_code}): {e}")
    print(f"  suggested fix: {e.suggested_fix}")
    print(f"  details: {e.details}")       # Structured error details dict
    print(f"  request_id: {e.request_id}") # For support/debugging
```

## Configuration

```python
client = DocParse(
    api_key="dp_your_key",
    base_url="https://your-deployment.run.app",  # Custom endpoint
    timeout=120,                                   # Request timeout (seconds)
)
```

## License

Apache 2.0 — see [LICENSE](../../LICENSE) for details.

## Links

- [AILANG Parse Website](https://www.sunholo.com/ailang-parse/)
- [API Documentation](https://www.sunholo.com/ailang-parse//api.html)
- [GitHub](https://github.com/sunholo-data/ailang-parse)
- [Swagger UI](https://api.parse.sunholo.com/api/_meta/docs)
