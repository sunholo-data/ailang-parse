/** Unstructured API compatibility — drop-in replacement for unstructured-client. */

import type { Element } from "./types.js";
import { DocParseError } from "./types.js";

const DEFAULT_BASE_URL = "https://api.parse.sunholo.com";

class GeneralApi {
  private baseUrl: string;
  private apiKey: string;
  private timeout: number;

  constructor(baseUrl: string, apiKey: string, timeout: number) {
    this.baseUrl = baseUrl;
    this.apiKey = apiKey;
    this.timeout = timeout;
  }

  /**
   * Partition a document — returns Unstructured-format elements.
   *
   * Note: `file` must be a sample ID or server-side path, not a local file path.
   * The `/general/v0/general` endpoint does not yet support multipart file upload.
   * To upload local files, use {@link DocParse.parseFile} instead:
   * ```ts
   * const result = await new DocParse({ apiKey: "dp_..." }).parseFile("report.docx");
   * ```
   */
  async partition(opts: { file: string; strategy?: string }): Promise<Element[]> {
    const url = `${this.baseUrl}/general/v0/general`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.apiKey) {
      headers["unstructured-api-key"] = this.apiKey;
    }

    const resp = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ args: [opts.file, opts.strategy || "auto"] }),
    });

    if (!resp.ok) throw new DocParseError(`API error: ${resp.status}`, resp.status);

    const outer = await resp.json();
    if (outer.error) throw new DocParseError(outer.error);

    const resultStr = outer.result || "[]";
    try {
      const elements = JSON.parse(resultStr);
      return Array.isArray(elements) ? elements : [];
    } catch {
      return [];
    }
  }
}

/**
 * Drop-in replacement for `unstructured-client`'s UnstructuredClient.
 *
 * Migration:
 * ```typescript
 * // Before
 * import { UnstructuredClient } from 'unstructured-client';
 * const client = new UnstructuredClient({ serverUrl: 'https://api.unstructured.io' });
 *
 * // After — one import change
 * import { UnstructuredClient } from '@ailang/parse/compat';
 * const client = new UnstructuredClient({
 *   serverUrl: 'https://api.parse.sunholo.com'
 * });
 * ```
 */
export class UnstructuredClient {
  general: GeneralApi;

  constructor(opts: { serverUrl?: string; apiKey?: string; timeout?: number }) {
    const baseUrl = (opts.serverUrl || DEFAULT_BASE_URL).replace(/\/$/, "");
    this.general = new GeneralApi(baseUrl, opts.apiKey || "", opts.timeout || 60000);
  }
}
