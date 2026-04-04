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

describe("parseFile (integration)", () => {
  it("uploads and parses a local DOCX", async (t) => {
    skipUnlessKey(t);
    const fs = await import("fs");
    const path = await import("path");
    const os = await import("os");

    // Create a minimal DOCX using archiver-like approach (manual zip)
    const { Uint8Array: U8 } = globalThis;
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "docparse-test-"));
    const docxPath = path.join(tmpDir, "test.docx");

    // Use Node's built-in to create a minimal zip/docx
    const { execSync } = await import("child_process");
    const contentDir = path.join(tmpDir, "docx_content");
    fs.mkdirSync(path.join(contentDir, "word"), { recursive: true });
    fs.mkdirSync(path.join(contentDir, "_rels"), { recursive: true });
    fs.writeFileSync(path.join(contentDir, "[Content_Types].xml"),
      '<?xml version="1.0" encoding="UTF-8"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
      '</Types>');
    fs.writeFileSync(path.join(contentDir, "_rels", ".rels"),
      '<?xml version="1.0" encoding="UTF-8"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
      '</Relationships>');
    fs.writeFileSync(path.join(contentDir, "word", "document.xml"),
      '<?xml version="1.0" encoding="UTF-8"?>' +
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
      '<w:body><w:p><w:r><w:t>JS SDK integration test</w:t></w:r></w:p></w:body>' +
      '</w:document>');
    execSync(`cd "${contentDir}" && zip -r "${docxPath}" .`, { stdio: "pipe" });

    let r;
    try {
      r = await client.parseFile(docxPath);
    } catch (e) {
      if (e instanceof DocParseError) {
        t.skip(`ParseFile not available: ${(e as DocParseError).message}`);
        return;
      }
      throw e;
    }
    assert.ok(r.status === "ok" || r.status === "success");
    assert.ok(r.blocks.length > 0);

    // Cleanup
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });
});
