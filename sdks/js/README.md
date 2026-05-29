# @ailang/parse

JavaScript/TypeScript client and MCP server for the [AILANG Parse](https://www.sunholo.com/docparse/) document parsing API. Parse 19 formats (including LaTeX/arXiv and RTF), generate 9 — zero dependencies, native fetch.

## Install

```bash
npm install @ailang/parse
```

## MCP Server (Claude Desktop, Cursor, VS Code)

Run as a stdio MCP server that bridges to the hosted AILANG Parse API. Requires Node.js >= 18.

```json
{
  "mcpServers": {
    "ailang-parse": {
      "command": "npx",
      "args": ["-y", "@ailang/parse", "mcp"]
    }
  }
}
```

Add to `claude_desktop_config.json` (Claude Desktop), `.cursor/mcp.json` (Cursor), or `.vscode/settings.json` (VS Code). Provides 7 tools: parse, convert, formats, estimate, auth, auth-poll, and account.

## Quick Start

```typescript
import { DocParse } from '@ailang/parse'

const client = new DocParse({ apiKey: 'dp_your_key_here' });

// Parse a document
const result = await client.parse('report.docx');
console.log(`${result.blocks.length} blocks, format: ${result.format}`);

for (const block of result.blocks) {
  switch (block.type) {
    case 'heading':
      console.log(`  H${block.level}: ${block.text}`);
      break;
    case 'table':
      console.log(`  Table: ${block.headers?.length} cols, ${block.rows?.length} rows`);
      break;
    case 'change':
      console.log(`  ${block.changeType} by ${block.author}: ${block.text}`);
      break;
    default:
      console.log(`  ${block.type}: ${block.text?.slice(0, 80)}`);
  }
}
```

## Parse Documents

```typescript
// Parse with different output formats
const blocks = await client.parse('report.docx');                    // Block ADT (default)
const markdown = await client.parse('report.docx', 'markdown');      // Markdown
const html = await client.parse('report.docx', 'html');              // HTML
const mdMeta = await client.parse('report.docx', 'markdown+metadata'); // Markdown with sections

// Upload a local file (multipart)
const result = await client.parseFile('local/report.docx');

// Parse from a signed URL (GCS, S3, Azure Blob — no local file needed)
const result = await client.parseUrl(
  'https://storage.googleapis.com/bucket/doc.docx?X-Goog-Signature=...',
  'markdown+metadata',
);

// Access structured data
console.log(result.status);           // "success"
console.log(result.blocks);           // Block[]
console.log(result.metadata.title);   // Document title
console.log(result.summary.tables);   // Number of tables

// markdown+metadata format includes sections
console.log(result.markdown);
for (const s of result.sections) {
  console.log(`  ${s.heading}: ${s.markdown.slice(0, 60)}...`);
}
```

## Response Metadata

Every parse result includes quota and request metadata from response headers:

```typescript
const result = await client.parse('report.docx');
const meta = result.responseMeta;

console.log(meta.requestId);           // "req_abc123"
console.log(meta.tier);                // "free", "pro", or "business"
console.log(meta.quotaRemainingDay);   // Requests left today
console.log(meta.quotaRemainingMonth); // Requests left this month
console.log(meta.quotaRemainingAi);    // AI requests remaining
console.log(meta.format);             // Detected input format ("docx", etc.)
console.log(meta.replayable);         // Whether this request can be replayed
```

## Block Types

All 9 block types are fully typed:

```typescript
import type { Block, Cell, ParseResult } from '@ailang/parse'

// Type narrowing via block.type
for (const block of result.blocks) {
  if (block.type === 'section') {
    console.log(`Section: ${block.kind}`);  // "slide", "header", etc.
    for (const child of block.blocks ?? []) {
      console.log(`  ${child.type}: ${child.text}`);
    }
  }
}
```

## API Key Management

API key resolution (checked in order):
1. Explicit `apiKey` in constructor options
2. `DOCPARSE_API_KEY` environment variable (Node.js)
3. Saved credentials in `~/.config/ailang-parse/credentials.json`

Use the device auth flow to get an API key. The user signs in once — the key is saved automatically and reused in future sessions.

```typescript
import { DocParse } from '@ailang/parse';

// First time: deviceAuth() opens browser, user signs in, key saved to disk
const client = new DocParse();
await client.deviceAuth({ label: 'my-agent' });

// Future sessions: key auto-loaded from ~/.config/ailang-parse/credentials.json
const client = new DocParse();
const result = await client.parse('report.docx');

// Usage / Rotate / Revoke
const usage = await client.keys.usage('keyId123', 'user123');
const newKey = await client.keys.rotate('keyId123', 'user123');
await client.keys.revoke('keyId123', 'user123');
```

## Migrating from Unstructured

```typescript
// Before
import { UnstructuredClient } from 'unstructured-client';
const client = new UnstructuredClient({ serverUrl: 'https://api.unstructured.io' });

// After — one import change
import { UnstructuredClient } from '@ailang/parse'
const client = new UnstructuredClient({
  serverUrl: 'https://api.parse.sunholo.com'
});

// All existing code works unchanged
const elements = await client.general.partition({ file: 'report.docx' });
```

## Error Handling

```typescript
import { DocParse, DocParseError, AuthError, QuotaError } from '@ailang/parse'

try {
  const result = await client.parse('file.docx');
} catch (e) {
  if (e instanceof AuthError) console.log('Bad API key');
  else if (e instanceof QuotaError) console.log('Quota exceeded');
  else if (e instanceof DocParseError) {
    console.log(`API error: ${e.statusCode}`);
    console.log(`  suggested fix: ${e.suggestedFix}`);
    console.log(`  details: ${JSON.stringify(e.details)}`);  // Structured error details
    console.log(`  request ID: ${e.requestId}`);             // For support/debugging
  }
}
```

## Configuration

```typescript
const client = new DocParse({
  apiKey: 'dp_your_key',
  baseUrl: 'https://your-deployment.run.app',  // Custom endpoint
  timeout: 120000,                              // Request timeout (ms)
});
```

### Retry on transient failures

`parse` / `parseFile` can retry transient AI-provider failures (the server
returns `502`/`503`/`504`, and marks safe-to-retry `5xx` with
`X-AilangParse-Replayable`). Retry is **off by default** — opt in with `retry`:

```typescript
const client = new DocParse({
  apiKey: 'dp_your_key',
  retry: {
    maxRetries: 3,            // default 0 (no retry)
    retryableStatuses: [502, 503, 504],
    respectReplayable: true,  // also retry replayable 5xx
    backoffBaseMs: 1000,      // delay N = min(base * 2**N, max)
    backoffMaxMs: 30000,
  },
});
```

## Browser Usage

Works in browsers with native `fetch`:

```html
<script type="module">
  import { DocParse } from './node_modules/@ailang/parse/src/index.js';

  const client = new DocParse({ apiKey: 'dp_your_key' });
  const health = await client.health();
  console.log(health.status); // "healthy"
</script>
```

## License

Apache 2.0 — see [LICENSE](../../LICENSE) for details.

## Links

- [AILANG Parse Website](https://www.sunholo.com/ailang-parse/)
- [API Documentation](https://www.sunholo.com/ailang-parse//api.html)
- [GitHub](https://github.com/sunholo-data/ailang-parse)
