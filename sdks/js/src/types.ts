/** AILANG Parse types — Block ADT, ParseResult, metadata, errors. */

// ── Errors ──

export interface DocParseErrorOpts {
  statusCode?: number;
  suggestedFix?: string;
  details?: Record<string, unknown> | null;
  requestId?: string;
  replayable?: boolean;
}

export class DocParseError extends Error {
  statusCode: number;
  suggestedFix: string;
  details: Record<string, unknown> | null;
  requestId: string;
  replayable: boolean;
  /**
   * Backwards-compatible: `new DocParseError("msg")`,
   * `new DocParseError("msg", 500)`, or
   * `new DocParseError("msg", { statusCode: 500, requestId: "r" })`.
   */
  constructor(message: string, statusOrOpts: number | DocParseErrorOpts = 0,
              suggestedFix: string = "",
              details: Record<string, unknown> | null = null,
              requestId: string = "") {
    super(message);
    this.name = "DocParseError";
    if (typeof statusOrOpts === "object" && statusOrOpts !== null) {
      this.statusCode = statusOrOpts.statusCode ?? 0;
      this.suggestedFix = statusOrOpts.suggestedFix ?? "";
      this.details = statusOrOpts.details ?? null;
      this.requestId = statusOrOpts.requestId ?? "";
      this.replayable = statusOrOpts.replayable ?? false;
    } else {
      this.statusCode = statusOrOpts;
      this.suggestedFix = suggestedFix;
      this.details = details;
      this.requestId = requestId;
      this.replayable = false;
    }
  }
}

export class AuthError extends DocParseError {
  constructor(message: string = "Invalid or missing API key",
              opts: DocParseErrorOpts = {}) {
    super(message, { statusCode: 401, ...opts });
    this.name = "AuthError";
  }
}

export interface QuotaErrorOpts extends DocParseErrorOpts {
  tier?: string;
  used?: number;
  limit?: number;
}

export class QuotaError extends DocParseError {
  tier: string;
  used: number;
  limit: number;
  /**
   * Backwards-compatible: legacy positional form
   * `new QuotaError("msg", "free", 100, 50)` and the new opts-bag form
   * `new QuotaError("msg", { tier: "free", requestId: "r" })` both work.
   */
  constructor(message: string = "Quota exceeded",
              tierOrOpts: string | QuotaErrorOpts = {},
              used: number = 0, limit: number = 0) {
    let opts: QuotaErrorOpts;
    if (typeof tierOrOpts === "string") {
      opts = { tier: tierOrOpts, used, limit };
    } else {
      opts = tierOrOpts;
    }
    super(message, { statusCode: 429, ...opts });
    this.name = "QuotaError";
    this.tier = opts.tier ?? "";
    this.used = opts.used ?? 0;
    this.limit = opts.limit ?? 0;
  }
}

// ── Cell ──

export interface Cell {
  text: string;
  colSpan: number;
  merged: boolean;
}

// ── Block (discriminated union via type field) ──

export interface Block {
  type: "text" | "heading" | "table" | "list" | "image" | "audio" | "video" | "section" | "change";
  text: string;
  level: number;
  style: string;
  // ChangeBlock
  changeType?: string;
  author?: string;
  date?: string;
  // TableBlock
  headers?: Cell[];
  rows?: Cell[][];
  // ListBlock
  items?: string[];
  ordered?: boolean;
  // ImageBlock / AudioBlock / VideoBlock
  description?: string;
  transcription?: string;
  mime?: string;
  dataLength?: number;
  // SectionBlock
  kind?: string;
  blocks?: Block[];
}

// ── Metadata ──

export interface DocMetadata {
  title: string;
  author: string;
  created: string;
  modified: string;
  pageCount: number;
}

export interface Summary {
  totalBlocks: number;
  headings: number;
  tables: number;
  images: number;
  changes: number;
}

// ── Results ──

/** A heading-delimited section of a document (markdown+metadata output). */
export interface Section {
  heading: string;
  level: number;
  markdown: string;
}

/** Metadata extracted from API response HTTP headers. */
export interface ResponseMeta {
  requestId: string;
  tier: string;
  quotaRemainingDay: number;
  quotaRemainingMonth: number;
  quotaRemainingAi: number;
  format: string;
  replayable: boolean;
}

export interface ParseResult {
  status: string;
  filename: string;
  format: string;
  blocks: Block[];
  metadata: DocMetadata;
  summary: Summary;
  /**
   * Raw rendered output for `outputFormat: "markdown"` / `"html"`.
   * Empty string for the default `"blocks"` output, which populates
   * `blocks` instead.
   */
  text: string;
  /** Full rendered markdown body for `outputFormat: "markdown+metadata"`. */
  markdown: string;
  /** Heading-sliced sections for `outputFormat: "markdown+metadata"`. */
  sections: Section[];
  /** A2UI adjacency-list nodes for `outputFormat: "a2ui"`. */
  nodes?: any[];
  /** HTTP response metadata (request ID, tier, quota remaining). */
  responseMeta?: ResponseMeta;
}

export interface HealthResult {
  status: string;
  version: string;
  service: string;
  formats_parse: number;
  formats_generate: number;
}

export interface FormatsResult {
  parse: string[];
  generate: string[];
  ai_required: string[];
  status: string;
}

/**
 * Free-function helpers for FormatsResult — case-insensitive and tolerant
 * of a leading dot. Exported as standalone functions (rather than methods)
 * so the FormatsResult interface stays a plain destructurable object.
 */
function _normalizeFormat(fmt: string): string {
  return fmt.toLowerCase().replace(/^\./, "");
}

export function supportsFormat(
  formats: FormatsResult,
  fmt: string,
  operation: "parse" | "generate" = "parse",
): boolean {
  const target = _normalizeFormat(fmt);
  const haystack = operation === "generate" ? formats.generate : formats.parse;
  return haystack.some((x) => _normalizeFormat(x) === target);
}

export function isDeterministic(
  formats: FormatsResult,
  fmt: string,
): boolean {
  if (!supportsFormat(formats, fmt, "parse")) return false;
  const target = _normalizeFormat(fmt);
  return !formats.ai_required.some((x) => _normalizeFormat(x) === target);
}

// ── Key management ──

export interface Quota {
  requestsPerDay: number;
  requestsPerMonth: number;
  aiLimitPerRequest: number;
  fsLimitPerRequest: number;
}

export interface KeyInfo {
  status: string;
  key: string;
  keyId: string;
  label: string;
  tier: string;
  created: string;
  quota: Quota;
  message?: string;
}

export interface Usage {
  requestsToday: number;
  requestsThisMonth: number;
  totalRequests: number;
}

export interface UsageInfo {
  status: string;
  keyId: string;
  tier: string;
  usage: Usage;
  quota: Quota;
}

// ── Unstructured compatibility ──

export interface ElementMetadata {
  filename?: string;
  filetype?: string;
  category_depth?: number;
  image_mime_type?: string;
  text_as_html?: string;
}

export interface Element {
  type: string;
  element_id: string;
  text: string;
  metadata: ElementMetadata;
}

// ── Client options ──

/**
 * Retry configuration for transient parse failures. Mirrors the Python SDK's
 * RetryPolicy. The server returns 502/503/504 for transient AI-provider
 * failures and marks safe-to-retry 5xx with `X-AilangParse-Replayable`.
 *
 * The default (no `retry` option) does NOT retry — opt in with `maxRetries`:
 *
 * ```ts
 * new DocParse({ retry: { maxRetries: 3 } });
 * ```
 *
 * Delay before retry N is `min(backoffBaseMs * 2 ** N, backoffMaxMs)`.
 */
export interface RetryPolicy {
  /** Maximum number of retries (0 = no retry). */
  maxRetries?: number;
  /** HTTP statuses that always trigger a retry. Default `[502, 503, 504]`. */
  retryableStatuses?: number[];
  /** Also retry any 5xx carrying `X-AilangParse-Replayable: true`. Default `true`. */
  respectReplayable?: boolean;
  /** Exponential backoff base, milliseconds. Default `1000`. */
  backoffBaseMs?: number;
  /** Upper bound on per-retry delay, milliseconds. Default `30000`. */
  backoffMaxMs?: number;
}

export interface DocParseOptions {
  apiKey?: string;
  baseUrl?: string;
  timeout?: number;
  /** Retry policy for transient parse failures. Default: no retry. */
  retry?: RetryPolicy;
}
