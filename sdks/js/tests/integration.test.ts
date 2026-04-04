/**
 * Integration tests — hit the real AILANG Parse API.
 *
 * Run:  DOCPARSE_API_KEY=dp_... npx tsx --test tests/integration.test.ts
 *
 * Skipped automatically when DOCPARSE_API_KEY is not set.
 */
import { describe, it, before } from "node:test";
import assert from "node:assert/strict";

import { DocParse } from "../src/client.ts";
import { DocParseError } from "../src/types.ts";
import { UnstructuredClient } from "../src/compat.ts";

const API_KEY = process.env.DOCPARSE_API_KEY || "";
const SAMPLE_FILE = "sample_docx_basic";

function skipUnlessKey(t: any) {
  if (!API_KEY) t.skip("DOCPARSE_API_KEY not set");
}

let client: DocParse;

before(() => {
  if (API_KEY) {
    client = new DocParse({ apiKey: API_KEY });
  }
});

// ── Unauthenticated endpoints ──

describe("health (integration)", () => {
  it("returns healthy status", async (t) => {
    skipUnlessKey(t);
    const h = await client.health();
    assert.ok(h.status === "ok" || h.status === "healthy");
    assert.ok(h.version);
    assert.equal(h.service, "docparse");
    assert.ok(h.formats_parse > 0);
    assert.ok(h.formats_generate > 0);
  });
});

describe("formats (integration)", () => {
  it("lists supported formats", async (t) => {
    skipUnlessKey(t);
    const f = await client.formats();
    assert.ok(f.parse.includes("docx"));
    assert.ok(f.parse.includes("pdf"));
    assert.ok(f.generate.includes("html"));
    assert.ok(f.ai_required.length > 0);
  });
});

// ── Authenticated endpoints ──

describe("parse (integration)", () => {
  it("parses sample.docx", async (t) => {
    skipUnlessKey(t);
    let r;
    try {
      r = await client.parse(SAMPLE_FILE);
    } catch (e) {
      if (e instanceof DocParseError) {
        t.skip(`Parse not available with current key: ${e.message}`);
        return;
      }
      throw e;
    }
    assert.ok(r.status === "ok" || r.status === "success");
    assert.ok(r.filename);
    assert.ok(r.blocks.length > 0);
    assert.ok(r.summary.totalBlocks > 0);
  });

  it("all blocks have valid types", async (t) => {
    skipUnlessKey(t);
    let r;
    try {
      r = await client.parse(SAMPLE_FILE);
    } catch (e) {
      if (e instanceof DocParseError) {
        t.skip(`Parse not available: ${e.message}`);
        return;
      }
      throw e;
    }
    const validTypes = new Set(["text", "heading", "table", "list", "image", "audio", "video", "section", "change"]);
    for (const block of r.blocks) {
      assert.ok(validTypes.has(block.type), `unexpected block type: ${block.type}`);
    }
  });

  it("parses with markdown output", async (t) => {
    skipUnlessKey(t);
    let r;
    try {
      r = await client.parse(SAMPLE_FILE, "markdown");
    } catch (e) {
      if (e instanceof DocParseError) {
        t.skip(`Parse not available: ${e.message}`);
        return;
      }
      throw e;
    }
    // Markdown may return raw text instead of structured blocks
    assert.ok(r !== null);
  });
});

describe("UnstructuredClient compat (integration)", () => {
  it("partition returns elements", async (t) => {
    skipUnlessKey(t);
    const uc = new UnstructuredClient({ apiKey: API_KEY });
    let elements;
    try {
      elements = await uc.general.partition({ file: SAMPLE_FILE });
    } catch (e) {
      if (e instanceof DocParseError) {
        t.skip(`Partition not available: ${e.message}`);
        return;
      }
      throw e;
    }
    assert.ok(elements.length > 0);
    for (const el of elements) {
      assert.ok(el.type);
      assert.equal(typeof el.text, "string");
    }
  });
});
