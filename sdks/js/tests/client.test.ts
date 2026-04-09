/**
 * Tests for @ailang/parse SDK — types, client, unwrap, error handling.
 * Uses Node built-in test runner and a local mock HTTP server.
 */
import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

import { DocParse } from "../src/client.ts";
import {
  DocParseError, AuthError, QuotaError,
  supportsFormat, isDeterministic,
  type FormatsResult,
} from "../src/types.ts";
import { UnstructuredClient } from "../src/compat.ts";

// ── Mock HTTP server ──

let server: http.Server;
let baseUrl: string;
let mockStatus = 200;
let mockBody: any = {};

function setMock(status: number, body: any) {
  mockStatus = status;
  mockBody = body;
}

before(async () => {
  server = http.createServer((req, res) => {
    // Drain request body
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      const responseBody = JSON.stringify(mockBody);
      res.writeHead(mockStatus, {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(responseBody).toString(),
      });
      res.end(responseBody);
    });
  });

  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const addr = server.address() as { port: number };
  baseUrl = `http://127.0.0.1:${addr.port}`;
});

after(() => {
  server?.close();
});

// ── Type tests ──

describe("types", () => {
  it("DocParseError has statusCode", () => {
    const e = new DocParseError("fail", 500);
    assert.equal(e.message, "fail");
    assert.equal(e.statusCode, 500);
    assert.ok(e instanceof Error);
  });

  it("AuthError defaults to 401", () => {
    const e = new AuthError();
    assert.equal(e.statusCode, 401);
    assert.ok(e instanceof DocParseError);
  });

  it("QuotaError has tier info", () => {
    const e = new QuotaError("over", "free", 100, 50);
    assert.equal(e.statusCode, 429);
    assert.equal(e.tier, "free");
    assert.equal(e.used, 100);
    assert.equal(e.limit, 50);
  });
});

// ── Client construction ──

describe("client construction", () => {
  it("accepts explicit API key", () => {
    const c = new DocParse({ apiKey: "dp_test123" });
    // We can verify by making a request later; just ensure no throw
    assert.ok(c);
  });

  it("strips trailing slash from baseUrl", () => {
    const c = new DocParse({ baseUrl: "http://localhost:8080/" });
    assert.ok(c);
  });

  it("reads DOCPARSE_API_KEY from env", () => {
    const prev = process.env.DOCPARSE_API_KEY;
    process.env.DOCPARSE_API_KEY = "dp_envkey";
    try {
      const c = new DocParse();
      assert.ok(c);
    } finally {
      if (prev === undefined) delete process.env.DOCPARSE_API_KEY;
      else process.env.DOCPARSE_API_KEY = prev;
    }
  });
});

// ── Unwrap logic (tested indirectly via API calls) ──

describe("health", () => {
  it("returns HealthResult on success", async () => {
    setMock(200, {
      result: JSON.stringify({
        status: "ok",
        version: "1.2.3",
        service: "docparse",
        formats_parse: 12,
        formats_generate: 9,
      }),
    });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const h = await c.health();
    assert.equal(h.status, "ok");
    assert.equal(h.version, "1.2.3");
    assert.equal(h.formats_parse, 12);
  });
});

describe("formats", () => {
  it("returns FormatsResult on success", async () => {
    setMock(200, {
      result: JSON.stringify({
        parse: ["docx", "pdf", "html"],
        generate: ["docx", "html"],
        ai_required: ["pdf"],
      }),
    });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const f = await c.formats();
    assert.ok(f.parse.includes("docx"));
    assert.deepEqual(f.ai_required, ["pdf"]);
  });
});

describe("FormatsResult helpers (#6)", () => {
  const f: FormatsResult = {
    parse: ["docx", "pdf", "html"],
    generate: ["docx", "html"],
    ai_required: ["pdf"],
    status: "ok",
  };
  it("supportsFormat is case-insensitive", () => {
    assert.equal(supportsFormat(f, "docx"), true);
    assert.equal(supportsFormat(f, "DOCX"), true);
    assert.equal(supportsFormat(f, ".docx"), true);
    assert.equal(supportsFormat(f, "xlsx"), false);
  });
  it("supportsFormat operation defaults to parse", () => {
    assert.equal(supportsFormat(f, "pdf"), true);
    assert.equal(supportsFormat(f, "pdf", "generate"), false);
  });
  it("isDeterministic excludes ai_required", () => {
    assert.equal(isDeterministic(f, "docx"), true);
    assert.equal(isDeterministic(f, "html"), true);
    assert.equal(isDeterministic(f, "pdf"), false);
    assert.equal(isDeterministic(f, "xlsx"), false);
  });
});

describe("parse markdown raw-string (#2)", () => {
  it("parse() returns ParseResult.text for raw markdown response", async () => {
    setMock(200, { result: "# Title\n\nBody paragraph\n" });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const r = await c.parse("doc.md", "markdown");
    assert.equal(r.status, "ok");
    assert.equal(r.text, "# Title\n\nBody paragraph\n");
    assert.equal(r.format, "markdown");
    assert.deepEqual(r.blocks, []);
  });

  it("parseFile() returns ParseResult.text for raw html response", async () => {
    setMock(200, { result: "<h1>Title</h1>" });
    const { mkdtempSync, writeFileSync } = await import("fs");
    const { join } = await import("path");
    const { tmpdir } = await import("os");
    const dir = mkdtempSync(join(tmpdir(), "ailang-md-test-"));
    const local = join(dir, "doc.html");
    writeFileSync(local, Buffer.from("<h1>x</h1>"));
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const r = await c.parseFile(local, "html");
    assert.equal(r.text, "<h1>Title</h1>");
    assert.equal(r.format, "html");
  });
});

describe("parse", () => {
  it("returns ParseResult with blocks", async () => {
    setMock(200, {
      result: JSON.stringify({
        status: "ok",
        filename: "sample.docx",
        format: "docx",
        blocks: [
          { type: "heading", text: "Title", level: 1 },
          { type: "text", text: "Body paragraph" },
        ],
        metadata: { title: "Sample", author: "Test" },
        summary: { totalBlocks: 2, headings: 1 },
      }),
    });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const r = await c.parse("sample.docx");
    assert.equal(r.status, "ok");
    assert.equal(r.blocks.length, 2);
    assert.equal(r.blocks[0].type, "heading");
    assert.equal(r.metadata.title, "Sample");
    assert.equal(r.summary.totalBlocks, 2);
  });
});

// ── Error handling ──

describe("error handling", () => {
  it("throws AuthError on 401", async () => {
    setMock(401, { error: "unauthorized" });
    const c = new DocParse({ apiKey: "dp_bad", baseUrl });
    await assert.rejects(() => c.health(), AuthError);
  });

  it("throws QuotaError on 429", async () => {
    setMock(429, { error: "quota exceeded" });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    await assert.rejects(() => c.health(), QuotaError);
  });

  it("throws DocParseError on envelope error", async () => {
    setMock(200, { error: "parse failed" });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    await assert.rejects(() => c.parse("bad.docx"), DocParseError);
  });

  it("throws DocParseError on 500", async () => {
    setMock(500, { error: "internal" });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    await assert.rejects(() => c.health(), DocParseError);
  });

  it("routes envelope 'Invalid or expired API key' to AuthError", async () => {
    setMock(200, { error: "Invalid or expired API key" });
    const c = new DocParse({ apiKey: "dp_bad", baseUrl });
    await assert.rejects(() => c.parse("sample.docx"), AuthError);
  });

  it("routes inner-result auth error to AuthError", async () => {
    setMock(200, {
      result: JSON.stringify({ error: { message: "Invalid or expired API key" } }),
    });
    const c = new DocParse({ apiKey: "dp_bad", baseUrl });
    await assert.rejects(() => c.parse("sample.docx"), AuthError);
  });

  it("routes 'Unauthorized' envelope error to AuthError", async () => {
    setMock(200, { error: "Unauthorized" });
    const c = new DocParse({ apiKey: "dp_bad", baseUrl });
    await assert.rejects(() => c.parse("sample.docx"), AuthError);
  });

  it("non-auth envelope error stays as plain DocParseError (not AuthError)", async () => {
    setMock(200, { error: "malformed document" });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    await assert.rejects(
      () => c.parse("bad.docx"),
      (e: unknown) => e instanceof DocParseError && !(e instanceof AuthError),
    );
  });
});

// ── Unstructured compat ──

describe("UnstructuredClient compat", () => {
  it("partition returns elements", async () => {
    setMock(200, {
      result: JSON.stringify([
        { type: "NarrativeText", element_id: "abc", text: "Hello", metadata: { filename: "test.docx" } },
        { type: "Title", element_id: "def", text: "Heading", metadata: {} },
      ]),
    });
    const uc = new UnstructuredClient({ serverUrl: baseUrl, apiKey: "dp_test" });
    const elements = await uc.general.partition({ file: "sample.docx" });
    assert.equal(elements.length, 2);
    assert.equal(elements[0].type, "NarrativeText");
    assert.equal(elements[0].text, "Hello");
  });

  it("partition throws on error", async () => {
    setMock(200, { error: "parse failed" });
    const uc = new UnstructuredClient({ serverUrl: baseUrl });
    await assert.rejects(() => uc.general.partition({ file: "bad.docx" }), DocParseError);
  });

  it("partition routes envelope auth error to AuthError", async () => {
    setMock(200, { error: "Invalid or expired API key" });
    const uc = new UnstructuredClient({ serverUrl: baseUrl, apiKey: "dp_bad" });
    await assert.rejects(() => uc.general.partition({ file: "sample.docx" }), AuthError);
  });

  it("partition routes inner-result auth error to AuthError", async () => {
    setMock(200, {
      result: JSON.stringify({ error: { message: "Invalid or expired API key" } }),
    });
    const uc = new UnstructuredClient({ serverUrl: baseUrl, apiKey: "dp_bad" });
    await assert.rejects(() => uc.general.partition({ file: "sample.docx" }), AuthError);
  });

  it("partition routes 401 status to AuthError", async () => {
    setMock(401, { error: "unauthorized" });
    const uc = new UnstructuredClient({ serverUrl: baseUrl, apiKey: "dp_bad" });
    await assert.rejects(() => uc.general.partition({ file: "sample.docx" }), AuthError);
  });

  it("partition routes 429 status to QuotaError", async () => {
    setMock(429, { error: "quota" });
    const uc = new UnstructuredClient({ serverUrl: baseUrl, apiKey: "dp_test" });
    await assert.rejects(() => uc.general.partition({ file: "sample.docx" }), QuotaError);
  });
});

// ── KeyManager ──

describe("KeyManager", () => {
  it("list returns key list", async () => {
    setMock(200, {
      result: JSON.stringify({ status: "ok", keys: [{ key_id: "k1" }] }),
    });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const out: any = await c.keys.list("u1");
    assert.equal(out.status, "ok");
    assert.equal(out.keys[0].key_id, "k1");
  });

  it("revoke returns success", async () => {
    setMock(200, { result: JSON.stringify({ status: "revoked" }) });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const out: any = await c.keys.revoke("k1", "u1");
    assert.equal(out.status, "revoked");
  });

  it("rotate returns new key info", async () => {
    setMock(200, {
      result: JSON.stringify({
        status: "active", key: "dp_newkey", keyId: "k2",
        label: "rotated", tier: "free", created: "2026-04-08",
        quota: { requestsPerDay: 50 },
      }),
    });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const info: any = await c.keys.rotate("k1");
    assert.equal(info.key, "dp_newkey");
  });

  it("usage returns usage info", async () => {
    setMock(200, {
      result: JSON.stringify({
        status: "ok", keyId: "k1", tier: "free",
        usage: { requestsToday: 3, requestsThisMonth: 10, totalRequests: 100 },
        quota: { requestsPerDay: 50 },
      }),
    });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const u: any = await c.keys.usage("k1");
    assert.equal(u.usage.requestsToday, 3);
  });

  it("propagates auth error from envelope", async () => {
    setMock(200, { error: "Invalid or expired API key" });
    const c = new DocParse({ apiKey: "dp_bad", baseUrl });
    await assert.rejects(() => c.keys.list("u1"), AuthError);
  });
});

describe("keyInfo (#8)", () => {
  it("falls back to keys.list to resolve key_id, then caches", async () => {
    // First mock = keys.list response. Replace before second call.
    setMock(200, {
      result: JSON.stringify({
        status: "ok",
        keys: [
          { key_id: "k_other", key: "dp_other" },
          { key_id: "k_match", key: "dp_test" },
        ],
      }),
    });
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    // Stub usage() to avoid juggling two mock responses on the shared server.
    const calls: string[] = [];
    (c as any).keys.usage = async (kid: string) => {
      calls.push(kid);
      return { status: "ok", keyId: kid };
    };
    const info: any = await c.keyInfo();
    assert.equal(info.keyId, "k_match");
    assert.deepEqual(calls, ["k_match"]);
    // Second call should be cached — no extra list lookup needed.
    setMock(500, { error: "would fail if list re-queried" });
    await c.keyInfo();
    assert.deepEqual(calls, ["k_match", "k_match"]);
  });

  it("throws when no api key configured", async () => {
    const prev = process.env.DOCPARSE_API_KEY;
    delete process.env.DOCPARSE_API_KEY;
    try {
      const c = new DocParse({ baseUrl: "http://nokey.test" });
      await assert.rejects(() => c.keyInfo(), DocParseError);
    } finally {
      if (prev !== undefined) process.env.DOCPARSE_API_KEY = prev;
    }
  });
});

// ── parseFile multipart upload ──

describe("parseFile", () => {
  it("uploads local file via multipart", async () => {
    setMock(200, {
      result: JSON.stringify({
        status: "ok",
        filename: "upload.docx",
        format: "docx",
        blocks: [{ type: "text", text: "hello" }],
        metadata: {},
        summary: { totalBlocks: 1 },
      }),
    });
    // Write a real temp file so the readFileSync path works
    const { mkdtempSync, writeFileSync } = await import("fs");
    const { join } = await import("path");
    const { tmpdir } = await import("os");
    const dir = mkdtempSync(join(tmpdir(), "ailang-parse-test-"));
    const local = join(dir, "upload.docx");
    writeFileSync(local, Buffer.from("PK\x03\x04 fake docx"));
    const c = new DocParse({ apiKey: "dp_test", baseUrl });
    const r = await c.parseFile(local);
    assert.equal(r.status, "ok");
    assert.equal(r.blocks[0].text, "hello");
  });

  it("parseFile routes 401 to AuthError", async () => {
    setMock(401, { error: "unauthorized" });
    const { mkdtempSync, writeFileSync } = await import("fs");
    const { join } = await import("path");
    const { tmpdir } = await import("os");
    const dir = mkdtempSync(join(tmpdir(), "ailang-parse-test-"));
    const local = join(dir, "upload.docx");
    writeFileSync(local, Buffer.from("PK\x03\x04 fake"));
    const c = new DocParse({ apiKey: "dp_bad", baseUrl });
    await assert.rejects(() => c.parseFile(local), AuthError);
  });

  it("parseFile routes envelope auth error to AuthError", async () => {
    setMock(200, { error: "Invalid or expired API key" });
    const { mkdtempSync, writeFileSync } = await import("fs");
    const { join } = await import("path");
    const { tmpdir } = await import("os");
    const dir = mkdtempSync(join(tmpdir(), "ailang-parse-test-"));
    const local = join(dir, "upload.docx");
    writeFileSync(local, Buffer.from("PK\x03\x04 fake"));
    const c = new DocParse({ apiKey: "dp_bad", baseUrl });
    await assert.rejects(() => c.parseFile(local), AuthError);
  });
});
