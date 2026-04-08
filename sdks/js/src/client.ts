/**
 * AILANG Parse HTTP client — handles API communication, response unwrapping,
 * and persistent credential storage.
 */

import type { ParseResult, HealthResult, FormatsResult, DocParseOptions } from "./types.js";
import { DocParseError, AuthError, QuotaError } from "./types.js";
import { KeyManager } from "./keys.js";

// @ts-ignore — plain JS sibling module, no .d.ts
import { DEFAULT_BASE_URL, loadSavedKey, saveKey } from "./credentials.js";
export { DEFAULT_BASE_URL };

export class DocParse {
  private apiKey: string;
  private baseUrl: string;
  private timeout: number;

  /** Key management methods. */
  keys: KeyManager;

  /**
   * Create a new AILANG Parse client.
   *
   * API key resolution order:
   * 1. Explicit ``apiKey`` in options
   * 2. ``DOCPARSE_API_KEY`` environment variable (Node.js)
   * 3. Saved credentials in ``~/.config/ailang-parse/credentials.json``
   */
  constructor(opts?: DocParseOptions) {
    this.baseUrl = ((opts?.baseUrl || DEFAULT_BASE_URL) as string).replace(/\/$/, "");
    this.timeout = opts?.timeout || 60000;

    // Resolve API key: explicit > env var > saved credentials
    let key = opts?.apiKey || "";
    if (!key) {
      try { key = process.env.DOCPARSE_API_KEY || ""; } catch { /* browser */ }
    }
    if (!key) {
      const saved = loadSavedKey(this.baseUrl);
      if (saved) key = saved.api_key;
    }

    this.apiKey = key;
    this.keys = new KeyManager(this);
  }

  /** Parse a document by sample ID or server-side filepath. Returns structured blocks.
   *  For uploading local files, use {@link parseFile} instead. */
  async parse(filepath: string, outputFormat = "blocks"): Promise<ParseResult> {
    const url = this.baseUrl + "/api/v1/parse";
    const body: Record<string, string> = { filepath, outputFormat };
    if (this.apiKey) body.apiKey = this.apiKey;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (this.apiKey) headers["x-api-key"] = this.apiKey;
      const resp = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (resp.status === 401) throw new AuthError();
      if (resp.status === 429) throw new QuotaError("Quota exceeded");
      if (!resp.ok) throw new DocParseError(`API error: ${resp.status}`, resp.status);
      return this._unwrap(await resp.json()) as ParseResult;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Upload a local file and parse it. Returns structured blocks.
   *
   * Uses multipart/form-data to upload the file directly to the API.
   * Works on all tiers (Free: 10 MB, Pro: 25 MB, Business: 50 MB).
   *
   * @example
   * ```ts
   * const result = await client.parseFile("report.docx");
   * console.log(result.blocks);
   * ```
   */
  async parseFile(filepath: string, outputFormat = "blocks"): Promise<ParseResult> {
    const url = this.baseUrl + "/api/v1/parse";
    let form: any;

    // Detect Node.js vs browser
    const isNode = typeof process !== "undefined" && process.versions?.node;

    if (isNode) {
      // Node.js: read file from disk using native FormData/Blob (Node 18+)
      const { readFileSync } = await import("fs");
      const { basename } = await import("path");

      const fileData = readFileSync(filepath);
      const blob = new Blob([fileData]);
      form = new FormData();
      form.append("filepath", blob, basename(filepath));
      form.append("outputFormat", outputFormat);
      if (this.apiKey) form.append("apiKey", this.apiKey);
    } else {
      // Browser: expect a File object or use native FormData
      form = new FormData();
      form.append("filepath", filepath as any);
      form.append("outputFormat", outputFormat);
      if (this.apiKey) form.append("apiKey", this.apiKey);
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const headers: Record<string, string> = {};
      if (this.apiKey) headers["x-api-key"] = this.apiKey;

      const resp = await fetch(url, {
        method: "POST",
        headers,
        body: form,
        signal: controller.signal,
      });

      if (resp.status === 401) throw new AuthError();
      if (resp.status === 429) throw new QuotaError("Quota exceeded");
      if (!resp.ok) throw new DocParseError(`API error: ${resp.status}`, resp.status);

      return this._unwrap(await resp.json()) as ParseResult;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Check API health. */
  async health(): Promise<HealthResult> {
    return this._call("GET", "/api/v1/health") as Promise<HealthResult>;
  }

  /** List supported formats. */
  async formats(): Promise<FormatsResult> {
    return this._call("GET", "/api/v1/formats") as Promise<FormatsResult>;
  }

  /**
   * Run the device authorization flow (RFC 8628) to obtain an API key.
   *
   * Requests a device code, prints the verification URL, then polls until
   * the user approves. On success the key is stored on this client instance.
   *
   * @param label - Key label (default: "default")
   * @param scope - Access scope (default: "parse")
   * @param pollInterval - Override poll interval in ms (default: from server)
   * @param timeout - Max time to wait in ms (default: 900000 = 15 min)
   * @returns Object with api_key, key_id, tier, label
   */
  async deviceAuth(opts?: {
    label?: string;
    scope?: string;
    pollInterval?: number;
    timeout?: number;
  }): Promise<{ api_key: string; key_id: string; tier: string; label: string }> {
    const label = opts?.label || "default";
    const scope = opts?.scope || "parse";
    const timeout = opts?.timeout || 900_000;

    // 1. Request device code (unauthenticated)
    const resp = await fetch(this.baseUrl + "/api/v1/auth/device", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label, scope }),
    });
    if (!resp.ok) throw new DocParseError(`Device auth request failed: ${resp.status}`, resp.status);
    const data = this._unwrap(await resp.json());

    const deviceCode = data.device_code;
    const userCode = data.user_code;
    const url = data.verification_url || "";
    const interval = opts?.pollInterval || (data.interval || 5) * 1000;

    // 2. Print instructions
    console.log(`\n  Authorize this device:`);
    console.log(`  ${url}`);
    console.log(`  Code: ${userCode}\n`);

    // 3. Poll until approved or timeout
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, interval));
      const pollResp = await fetch(this.baseUrl + "/api/v1/auth/device/poll", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deviceCode }),
      });
      const pollData = this._unwrap(await pollResp.json());

      if (pollData.status === "approved" && pollData.api_key) {
        this.apiKey = pollData.api_key;
        const result = {
          api_key: pollData.api_key,
          key_id: pollData.key_id || "",
          tier: pollData.tier || "free",
          label: pollData.label || label,
        };
        saveKey(result.api_key, this.baseUrl, result.key_id, result.tier, result.label);
        return result;
      }

      const err = pollData.error || "";
      if (err && err !== "AUTHORIZATION_PENDING") {
        throw new DocParseError(pollData.message || err);
      }
    }
    throw new DocParseError("Device authorization timed out");
  }

  /** Detect auth-related error messages from server-side envelope errors. */
  private static _isAuthErrorMessage(msg: string): boolean {
    if (!msg) return false;
    const m = msg.toLowerCase();
    return (
      m.includes("invalid or expired api key") ||
      m.includes("invalid api key") ||
      m.includes("missing api key") ||
      m.includes("unauthorized") ||
      m.includes("api key required")
    );
  }

  /** Throw AuthError for auth-like messages, otherwise DocParseError. */
  private static _raiseEnvelopeError(msg: string): never {
    if (DocParse._isAuthErrorMessage(msg)) throw new AuthError(msg);
    throw new DocParseError(msg);
  }

  /** Unwrap serve-api response envelope. */
  private _unwrap(outer: any): any {
    if (outer.error) {
      if (typeof outer.error === "string") {
        DocParse._raiseEnvelopeError(outer.error);
      }
      // Dict errors (e.g. device-auth poll) — return for caller handling
      return outer;
    }
    const resultStr = outer.result || "";
    if (!resultStr) return outer;
    try {
      const inner = JSON.parse(resultStr);
      // Check for error in inner result (API wraps errors in envelope too)
      if (inner?.error) {
        const err = inner.error;
        const msg = typeof err === "object" ? err.message || JSON.stringify(err) : String(err);
        DocParse._raiseEnvelopeError(msg);
      }
      return inner;
    } catch (e) {
      if (e instanceof DocParseError) throw e;
      return { raw: resultStr };
    }
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

      return this._unwrap(outer);
    } finally {
      clearTimeout(timer);
    }
  }
}
