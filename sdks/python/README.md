# AILANG Parse Python SDK

Python client and MCP server for the [AILANG Parse](https://www.sunholo.com/ailang-parse/) document parsing API. Parse 13 formats, generate 8 — zero dependencies for Office, pluggable AI for PDFs.

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

# Access structured data
print(result.status)          # "success"
print(result.filename)        # "report.docx"
print(result.format)          # "zip-office"
print(result.blocks)          # List[Block]
print(result.metadata.title)  # Document title
print(result.metadata.author) # Document author
print(result.summary.tables)  # Number of tables found
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
