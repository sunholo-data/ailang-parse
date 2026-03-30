/** AILANG Parse HTTP client — handles API communication and response unwrapping. */

import type { ParseResult, HealthResult, FormatsResult, DocParseOptions } from "./types.js";
import { DocParseError, AuthError, QuotaError } from "./types.js";
import { KeyManager } from "./keys.js";

const DEFAULT_BASE_URL = "https://api.parse.sunholo.com";

export class DocParse {
  private apiKey: string;
  private baseUrl: string;
  private timeout: number;

  /** Key management methods. */
  keys: KeyManager;

  constructor(opts: DocParseOptions) {
    this.apiKey = opts.apiKey;
    this.baseUrl = (opts.baseUrl || DEFAULT_BASE_URL).replace(/\/$/, "");
    this.timeout = opts.timeout || 60000;
    this.keys = new KeyManager(this);
  }

  /** Parse a document file. Returns structured blocks. */
  async parse(filepath: string, outputFormat = "blocks"): Promise<ParseResult> {
    return this._call("POST", "/api/v1/parse", [filepath, outputFormat]) as Promise<ParseResult>;
  }

  /** Check API health. */
  async health(): Promise<HealthResult> {
    return this._call("GET", "/api/v1/health") as Promise<HealthResult>;
  }

  /** List supported formats. */
  async formats(): Promise<FormatsResult> {
    return this._call("GET", "/api/v1/formats") as Promise<FormatsResult>;
  }

  /** Internal: make an API call and unwrap the serve-api response envelope. */
  async _call(method: string, path: string, args?: string[]): Promise<any> {
    const url = this.baseUrl + path;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.apiKey) {
      headers["x-api-key"] = this.apiKey;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const resp = await fetch(url, {
        method,
        headers,
        body: method !== "GET" ? JSON.stringify({ args: args || [] }) : undefined,
        signal: controller.signal,
      });

      if (resp.status === 401) throw new AuthError();
      if (resp.status === 429) throw new QuotaError("Quota exceeded");
      if (!resp.ok) throw new DocParseError(`API error: ${resp.status}`, resp.status);

      const outer = await resp.json();

      if (outer.error) throw new DocParseError(outer.error);

      const resultStr = outer.result || "";
      if (!resultStr) return outer;

      try {
        return JSON.parse(resultStr);
      } catch {
        return { raw: resultStr };
      }
    } finally {
      clearTimeout(timer);
    }
  }
}
