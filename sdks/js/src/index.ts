/**
 * @ailang/parse — JavaScript/TypeScript client for AILANG Parse.
 *
 * @example
 * ```typescript
 * import { DocParse } from '@ailang/parse';
 *
 * const client = new DocParse({ apiKey: 'dp_a1b2c3d4...' });
 * const result = await client.parse('report.docx');
 * console.log(result.blocks);
 * ```
 *
 * @example Unstructured migration
 * ```typescript
 * import { UnstructuredClient } from '@ailang/parse';
 *
 * const client = new UnstructuredClient({
 *   serverUrl: 'https://api.parse.sunholo.com'
 * });
 * const elements = await client.general.partition({ file: 'report.docx' });
 * ```
 */

export { DocParse } from "./client.js";
export { UnstructuredClient } from "./compat.js";
export { KeyManager } from "./keys.js";
export type {
  Block, Cell,
  ParseResult, DocMetadata, Summary,
  HealthResult, FormatsResult,
  KeyInfo, Quota, Usage, UsageInfo,
  Element, ElementMetadata,
  DocParseOptions,
} from "./types.js";
export { DocParseError, AuthError, QuotaError } from "./types.js";
