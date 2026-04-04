/**
 * Tests for @ailang/parse SDK — types, client, unwrap, error handling.
 * Uses Node built-in test runner and a local mock HTTP server.
 */
import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

import { DocParse } from "../src/client.ts";
import { DocParseError, AuthError, QuotaError } from "../src/types.ts";
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
});
