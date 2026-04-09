/**
 * AILANG Parse HTTP client — handles API communication, response unwrapping,
 * and persistent credential storage.
 */

import type { ParseResult, HealthResult, FormatsResult, DocParseOptions, ResponseMeta } from "./types.js";
import { DocParseError, AuthError, QuotaError } from "./types.js";
import { KeyManager } from "./keys.js";

// @ts-ignore — plain JS sibling module, no .d.ts
import { DEFAULT_BASE_URL, loadSavedKey, saveKey } from "./credentials.js";
export { DEFAULT_BASE_URL };

export class DocParse {
  private apiKey: string;
  private baseUrl: string;
  private timeout: number;
  /**
   * Stored key id, populated from saved credentials or a successful
   * `deviceAuth()` flow. Used by {@link keyInfo} when no explicit id is
   * passed.
   */
  private keyId: string;

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
    let keyId = "";
    if (!key) {
      try { key = process.env.DOCPARSE_API_KEY || ""; } catch { /* browser */ }
    }
    if (!key) {
      const saved = loadSavedKey(this.baseUrl);
      if (saved) {
        key = saved.api_key;
        keyId = saved.key_id || "";
      }
    }

    this.apiKey = key;
    this.keyId = keyId;
    this.keys = new KeyManager(this);
  }

  /** Extract response metadata from API response headers. */
  private static _extractMeta(headers: Headers): ResponseMeta {
    return {
      requestId: headers.get("X-Request-Id") || "",
      tier: headers.get("X-DocParse-Tier") || "",
      quotaRemainingDay: parseInt(headers.get("X-DocParse-Quota-Remaining-Day") || "-1", 10),
      quotaRemainingMonth: parseInt(headers.get("X-DocParse-Quota-Remaining-Month") || "-1", 10),
      quotaRemainingAi: parseInt(headers.get("X-DocParse-Quota-Remaining-Ai") || "-1", 10),
      format: headers.get("X-AilangParse-Format") || "",
      replayable: (headers.get("X-AilangParse-Replayable") || "").toLowerCase() === "true",
    };
  }

  /** Parse a document by sample ID or server-side filepath. Returns structured blocks.
   *  For uploading local files, use {@link parseFile} instead. */
  async parse(filepath: string, outputFormat = "blocks", opts?: { sourceUrl?: string }): Promise<ParseResult> {
    const url = this.baseUrl + "/api/v1/parse";
    const body: Record<string, string> = { filepath, outputFormat };
    if (this.apiKey) body.apiKey = this.apiKey;
    if (opts?.sourceUrl) body.sourceUrl = opts.sourceUrl;

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
      const meta = DocParse._extractMeta(resp.headers);
      const result = DocParse._buildParseResult(this._unwrap(await resp.json()), outputFormat);
      result.responseMeta = meta;
      return result;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Parse a document from a URL. Convenience wrapper around {@link parse}. */
  async parseUrl(url: string, outputFormat = "blocks"): Promise<ParseResult> {
    return this.parse("", outputFormat, { sourceUrl: url });
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

      const meta = DocParse._extractMeta(resp.headers);
      const result = DocParse._buildParseResult(this._unwrap(await resp.json()), outputFormat);
      result.responseMeta = meta;
      return result;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Build a ParseResult from a possibly-raw API response. For
   * `outputFormat: "markdown"` / `"html"` the API returns a raw rendered
   * string; `_unwrap` surfaces it as `{raw: "<str>"}`. We promote that to
   * `ParseResult.text` so callers receive the rendered output instead of
   * a silently-empty result.
   */
  private static _buildParseResult(data: any, outputFormat: string): ParseResult {
    if (data && typeof data === "object" && typeof data.raw === "string") {
      return {
        status: "ok",
        filename: "",
        format: outputFormat,
        blocks: [],
        metadata: {} as any,
        summary: {} as any,
        text: data.raw,
        markdown: "",
        sections: [],
      };
    }
    const status = data?.status || (data?.format ? "ok" : "");
    return {
      status,
      filename: data?.filename || "",
      format: data?.format || "",
      blocks: data?.blocks || [],
      metadata: data?.metadata || ({} as any),
      summary: data?.summary || ({} as any),
      text: data?.text || "",
      markdown: data?.markdown || "",
      sections: data?.sections || [],
    };
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
   * Return live usage + quota info for the *currently configured* key.
   *
   * Resolution order for the key id:
   * 1. The id stored on the client (saved credentials or {@link deviceAuth}).
   * 2. Otherwise call `keys.list("")` and find the entry whose `key`
   *    matches `apiKey`. The resolved id is cached for future calls.
   *
   * Throws if neither path can resolve a key id — the AILANG API has no
   * `/auth/whoami` endpoint, so the SDK needs either a saved credential or
   * a list-able admin key.
   */
  async keyInfo(): Promise<any> {
    if (!this.apiKey) {
      throw new DocParseError("client.keyInfo() requires an API key on the client");
    }
    if (!this.keyId) {
      let listing: any;
      try {
        listing = await this.keys.list("");
      } catch (e) {
        throw new DocParseError(
          "client.keyInfo() requires a saved credential or deviceAuth flow — " +
          "pass keyId explicitly to client.keys.usage(): " + (e as Error).message,
        );
      }
      const keys = Array.isArray(listing?.keys) ? listing.keys : [];
      for (const k of keys) {
        if (k && (k.key === this.apiKey || k.api_key === this.apiKey)) {
          this.keyId = k.key_id || k.keyId || "";
          if (this.keyId) break;
        }
      }
      if (!this.keyId) {
        throw new DocParseError(
          "client.keyInfo() could not resolve key_id — pass it explicitly to client.keys.usage()",
        );
      }
    }
    return this.keys.usage(this.keyId);
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
  }): Promise<{
    api_key: string;
    key_id: string;
    tier: string;
    label: string;
    verification_url: string;
    poll_url: string;
  }> {
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
        this.keyId = pollData.key_id || "";
        const result = {
          api_key: pollData.api_key,
          key_id: pollData.key_id || "",
          tier: pollData.tier || "free",
          label: pollData.label || label,
          verification_url: url,
          poll_url: this.baseUrl + "/api/v1/auth/device/poll",
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
  private static _raiseEnvelopeError(
    msg: string, suggestedFix = "",
    details: Record<string, unknown> = {}, requestId = "",
  ): never {
    if (DocParse._isAuthErrorMessage(msg)) throw new AuthError(msg);
    throw new DocParseError(msg, 0, suggestedFix, details, requestId);
  }

  /** Unwrap serve-api response envelope. */
  private _unwrap(outer: any): any {
    if (outer.error) {
      if (typeof outer.error === "string") {
        const suggested = outer.suggested_fix || "";
        const msg = outer.message || outer.error;
        DocParse._raiseEnvelopeError(msg, suggested);
      }
      if (typeof outer.error === "object") {
        const err = outer.error;
        const msg = err.message || JSON.stringify(err);
        const suggested = err.suggested_fix || "";
        const details = err.details || {};
        const requestId = outer.request_id || "";
        DocParse._raiseEnvelopeError(msg, suggested, details, requestId);
      }
      // Unknown error shape — return for caller handling
      return outer;
    }
    const resultStr = outer.result || "";
    if (!resultStr) return outer;
    try {
      const inner = JSON.parse(resultStr);
      // Check for error in inner result (API wraps errors in envelope too)
      if (inner?.error) {
        const err = inner.error;
        if (typeof err === "object") {
          const msg = err.message || JSON.stringify(err);
          const suggested = err.suggested_fix || "";
          const details = err.details || {};
          const requestId = inner.request_id || "";
          DocParse._raiseEnvelopeError(msg, suggested, details, requestId);
        }
        DocParse._raiseEnvelopeError(String(err));
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
