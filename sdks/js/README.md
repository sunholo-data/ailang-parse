# @ailang/parse

JavaScript/TypeScript client for the [AILANG Parse](https://www.sunholo.com/docparse) document parsing API. Parse 13 formats, generate 8 — zero dependencies, native fetch.

## Install

```bash
npm install @ailang/parse
```

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

// Access structured data
console.log(result.status);           // "success"
console.log(result.blocks);           // Block[]
console.log(result.metadata.title);   // Document title
console.log(result.summary.tables);   // Number of tables
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

Key generation uses the device auth flow (v0.10.0+). Direct generation is no longer available.

```typescript
// Get a key via device auth flow:
//   1. POST /api/v1/auth/device       → {device_code, user_code, verification_url}
//   2. User opens verification_url, signs in, clicks Approve
//   3. POST /api/v1/auth/device/poll  → {api_key, tier}

// Usage
const usage = await client.keys.usage('keyId123', 'user123');
console.log(`${usage.usage.requestsToday} / ${usage.quota.requestsPerDay} requests`);

// Rotate / Revoke
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
  else if (e instanceof DocParseError) console.log(`API error: ${e.statusCode}`);
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

## Links

- [AILANG Parse Website](https://www.sunholo.com/docparse)
- [API Documentation](https://www.sunholo.com/docparse/api.html)
- [GitHub](https://github.com/sunholo-data/docparse)
