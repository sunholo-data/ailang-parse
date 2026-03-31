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
        return {
          api_key: pollData.api_key,
          key_id: pollData.key_id || "",
          tier: pollData.tier || "free",
          label: pollData.label || label,
        };
      }

      const err = pollData.error || "";
      if (err && err !== "AUTHORIZATION_PENDING") {
        throw new DocParseError(pollData.message || err);
      }
    }
    throw new DocParseError("Device authorization timed out");
  }

  /** Unwrap serve-api response envelope. */
  private _unwrap(outer: any): any {
    if (outer.error) throw new DocParseError(outer.error);
    const resultStr = outer.result || "";
    if (!resultStr) return outer;
    try {
      return JSON.parse(resultStr);
    } catch {
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
