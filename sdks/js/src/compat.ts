/** Unstructured API compatibility — drop-in replacement for unstructured-client. */

import type { Element } from "./types.js";
import { DocParseError } from "./types.js";

const DEFAULT_BASE_URL = "https://docparse.ailang.sunholo.com";

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
   * Accepts a local file path (uploaded via multipart, Node.js only) or a
   * sample ID (sent as JSON). Usage is identical to unstructured-client.
   */
  async partition(opts: { file: string; strategy?: string }): Promise<Element[]> {
    const url = `${this.baseUrl}/general/v0/general`;
    const headers: Record<string, string> = {};
    if (this.apiKey) {
      headers["unstructured-api-key"] = this.apiKey;
    }

    let resp: Response;
    // Node.js: check if file exists on disk → multipart upload
    let isLocalFile = false;
    try {
      const fs = require("fs");
      isLocalFile = fs.existsSync(opts.file) && fs.statSync(opts.file).isFile();
    } catch { /* browser */ }

    if (isLocalFile) {
      const fs = require("fs");
      const path = require("path");
      const { FormData: NodeFormData } = require("undici");
      const { Blob } = require("buffer");
      const fileData = fs.readFileSync(opts.file);
      const form = new NodeFormData();
      form.append("files", new Blob([fileData]), path.basename(opts.file));
      if (opts.strategy) form.append("strategy", opts.strategy);
      resp = await fetch(url, { method: "POST", headers, body: form });
    } else {
      headers["Content-Type"] = "application/json";
      resp = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify({ filepath: opts.file, strategy: opts.strategy || "auto" }),
      });
    }

    if (!resp.ok) throw new DocParseError(`API error: ${resp.status}`, resp.status);

    const outer = await resp.json();
    if (outer.error) throw new DocParseError(outer.error);

    const resultStr = outer.result || "[]";
    try {
      const parsed = JSON.parse(resultStr);
      // Check for error in inner result
      if (parsed?.error) {
        const err = parsed.error;
        const msg = typeof err === "object" ? err.message || JSON.stringify(err) : String(err);
        throw new DocParseError(msg);
      }
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      if (e instanceof DocParseError) throw e;
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
    // Resolve key: explicit > env var
    let key = opts.apiKey || "";
    if (!key) {
      try { key = process.env.DOCPARSE_API_KEY || ""; } catch { /* browser */ }
    }
    this.general = new GeneralApi(baseUrl, key, opts.timeout || 60000);
  }
}
