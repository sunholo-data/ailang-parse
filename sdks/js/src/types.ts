/** AILANG Parse types — Block ADT, ParseResult, metadata, errors. */

// ── Errors ──

export class DocParseError extends Error {
  statusCode: number;
  constructor(message: string, statusCode: number = 0) {
    super(message);
    this.name = "DocParseError";
    this.statusCode = statusCode;
  }
}

export class AuthError extends DocParseError {
  constructor(message: string = "Invalid or missing API key") {
    super(message, 401);
    this.name = "AuthError";
  }
}

export class QuotaError extends DocParseError {
  tier: string;
  used: number;
  limit: number;
  constructor(message: string, tier = "", used = 0, limit = 0) {
    super(message, 429);
    this.name = "QuotaError";
    this.tier = tier;
    this.used = used;
    this.limit = limit;
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

export interface DocParseOptions {
  apiKey?: string;
  baseUrl?: string;
  timeout?: number;
}
