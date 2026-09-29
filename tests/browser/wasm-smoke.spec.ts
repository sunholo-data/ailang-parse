import { test, expect } from "@playwright/test";
import { basename, resolve } from "node:path";
import { readFileSync } from "node:fs";

// Smoke test for the homepage AILANG WASM demo.
//
// Goal: prove that the deployed bundle (vendored modules + pinned ailang.wasm
// + pkg/sunholo/* registry copies) actually loads in a browser and parses a
// document. Static checks (check-wasm-bindings.py) cover version and import
// drift, but cannot catch runtime regressions inside ailang.wasm itself.
//
// Fixture: data/test_files/sample.docx — 4.5 KB, used by other CI jobs.
// Expected output (verified via `./bin/docparse data/test_files/sample.docx`):
//   Title: "DocParse Test Document"
//   First H1: "Introduction"
//   First H2: "Features"

const SAMPLE_DOCX = resolve(__dirname, "../../data/test_files/sample.docx");

test("homepage loads WASM and parses sample.docx", async ({ page }) => {
  // Surface console errors so a regression in WASM init is visible in the
  // failure report rather than appearing as an opaque assertion timeout.
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`console.error: ${msg.text()}`);
  });

  await page.goto("/");

  // wasm-demo.js exposes window.DocParseEngine.isReady() once the WASM
  // runtime has booted and all parser modules have loaded. Boot can take
  // 10–30s on a cold Chromium in CI, so the timeout is generous.
  //
  // The console errors collected above are reported HERE, not only at the end
  // of the test. A boot failure makes isReady() stay false forever, so the
  // wait is what fails — and reporting errors after it meant a hard module
  // error surfaced as a bare "Timeout 60000ms exceeded" with the actual cause
  // (a WASM type-checker budget overrun naming the module) visible only inside
  // the trace artifact. Failing with the real message costs nothing and is the
  // difference between a one-line diagnosis and an archaeology session.
  try {
    await page.waitForFunction(
      () => (window as unknown as { DocParseEngine?: { isReady: () => boolean } }).DocParseEngine?.isReady() === true,
      null,
      { timeout: 60_000 },
    );
  } catch (e) {
    const detail = consoleErrors.length
      ? `\n\nConsole errors during WASM boot:\n  - ${consoleErrors.join("\n  - ")}`
      : "\n\nNo console errors were captured — the page is likely just slow to boot.";
    throw new Error(`${(e as Error).message}${detail}`);
  }

  // Upload the fixture via the existing file input on the homepage demo.
  await page.locator("#file-input").setInputFiles(SAMPLE_DOCX);

  // The "Parsed" tab (#panel-blocks) is what the homepage renders blocks
  // into. Wait for the known first heading from sample.docx to appear.
  // We click the tab to make it visible — the layout swaps tabs by
  // toggling display:none, so visible-text assertions need it active.
  await page.locator('[data-tab="blocks"]').click();
  await expect(page.locator("#panel-blocks")).toContainText("Introduction", {
    timeout: 30_000,
  });
  await expect(page.locator("#panel-blocks")).toContainText("Features");

  if (consoleErrors.length > 0) {
    throw new Error(
      `WASM smoke test produced console errors:\n  - ${consoleErrors.join("\n  - ")}`,
    );
  }
});

test("footer displays pinned AILANG version", async ({ page }) => {
  await page.goto("/");
  // Footer is rendered by components.js after page load; the AILANG
  // version pulls from DP_DATA.ailangVersion (stamped by pages.yml in CI,
  // or the locally-checked-in default).
  const footer = page.locator("footer.footer");
  await expect(footer).toBeVisible();
  await expect(footer).toContainText(/AILANG v\d+\.\d+\.\d+/);
});

// The workbench's own entry point (window.DocParseEngine.parseFile), fed the
// files a partner reported failing in September 2026. Two separate bugs:
//   - comments.docx / track_changes_move.docx: the engine failed to boot on a
//     slower machine because markdown_parser blew the wall-clock type-check
//     limit (see module-budget.spec.ts), so every parse failed;
//   - sample_rtf.rtf: .rtf was accepted as a text format but parseFile had no
//     dispatch branch for it, so it failed on every machine with
//     "Parse failed: no result from engine.call".
// The markdown case drives all four markdown modules (inline runs, table, and
// the comment / track-change blockquotes markdown_writer emits).
const WORKBENCH_CASES: { file: string; expect: string[] }[] = [
  { file: "../../data/test_files/comments.docx", expect: ['"type":"comment"', "I left a comment."] },
  { file: "../../data/test_files/track_changes_move.docx", expect: ['"changeType":"move-to"', "Here is the text to be moved."] },
  { file: "../../docs/assets/sample_rtf.rtf", expect: ["Sample RTF Document"] },
];

const MARKDOWN_ROUNDTRIP = [
  "# Title",
  "",
  "Some **bold** and `code`.",
  "",
  "| A | B |",
  "| :-- | --: |",
  "| 1 | 2 |",
  "",
  "> **Comment (Alice, 2026-01-01T00:00:00Z):** looks right",
  "",
  "> [insert by Bob on 2026-01-02] added words",
  "",
].join("\n");

test("workbench parses the partner-reported files via DocParseEngine", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`console.error: ${msg.text()}`);
  });

  await page.goto("/workbench.html");
  const booted = await page.evaluate(async () => {
    const eng = (window as any).DocParseEngine;
    try { await eng.init(); return "ok"; } catch (e) { return String((e as Error).message); }
  });
  expect(booted, `engine failed to boot; console:\n  ${consoleErrors.join("\n  ")}`).toBe("ok");

  const cases = WORKBENCH_CASES.map((c) => ({
    name: basename(c.file),
    b64: readFileSync(resolve(__dirname, c.file)).toString("base64"),
    expect: c.expect,
  }));
  cases.push({
    name: "roundtrip.md",
    b64: Buffer.from(MARKDOWN_ROUNDTRIP, "utf8").toString("base64"),
    expect: ['"bold":true', '"code":true', '"type":"table"', '"type":"comment"', "looks right", '"changeType":"insert"'],
  });

  const results = await page.evaluate(async (cs) => {
    const out: { name: string; json: string; error: string }[] = [];
    for (const c of cs) {
      const bytes = Uint8Array.from(atob(c.b64), (ch) => ch.charCodeAt(0));
      try {
        const r = await (window as any).DocParseEngine.parseFile(new File([bytes], c.name));
        out.push({ name: c.name, json: JSON.stringify(r.blocks), error: "" });
      } catch (e) {
        out.push({ name: c.name, json: "", error: String((e as Error).message) });
      }
    }
    return out;
  }, cases);

  for (const c of cases) {
    const r = results.find((x) => x.name === c.name)!;
    expect(r.error, `${c.name} failed to parse`).toBe("");
    for (const needle of c.expect) expect(r.json, `${c.name} output`).toContain(needle);
  }
});
