/**
 * @ailang/parse — JavaScript/TypeScript client for AILANG Parse.
 *
 * @example Upload and parse a local file
 * ```typescript
 * import { DocParse } from '@ailang/parse';
 *
 * const client = new DocParse({ apiKey: 'dp_a1b2c3d4...' });
 * const result = await client.parseFile('report.docx');
 * console.log(result.blocks);
 * ```
 *
 * @example Parse a sample or server-side file
 * ```typescript
 * const result = await client.parse('sample_docx_basic');
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
  DocParseErrorOpts, QuotaErrorOpts,
} from "./types.js";
export { DocParseError, AuthError, QuotaError } from "./types.js";
