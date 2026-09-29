import { test, expect } from "@playwright/test";
import { basename, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

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

// Slide order in the browser path. JS extracts the ZIP and used to .sort() the
// slide part names, so slide10.xml came before slide2.xml — and file names are
// not the deck order anyway. The fixture's presentation.xml orders 13 slides
// differently from their file numbers (built by
// benchmarks/create_pptx_order_fixture.py); titles must come out in deck order.
const ORDER_PPTX = resolve(__dirname, "../../data/test_files/pptx_slide_order_notes.pptx");
const DECK_TITLES = ["Kickoff", "Agenda", "Market", "Pricing", "Roadmap", "Team",
  "Risks", "Budget", "Metrics", "Timeline", "Asks", "Close"];

test("browser parses PPTX slides in presentation order", async ({ page }) => {
  test.setTimeout(180_000);
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`console.error: ${msg.text()}`);
  });
  await page.goto("/");
  try {
    await page.waitForFunction(
      () => (window as unknown as { DocParseEngine?: { isReady: () => boolean } }).DocParseEngine?.isReady() === true,
      null,
      { timeout: 120_000 },
    );
  } catch (e) {
    throw new Error(`${(e as Error).message}\n\nConsole errors:\n  - ${consoleErrors.join("\n  - ")}`);
  }
  await page.locator("#file-input").setInputFiles(ORDER_PPTX);
  await page.locator('[data-tab="blocks"]').click();
  const panel = page.locator("#panel-blocks");
  await expect(panel).toContainText("Close", { timeout: 30_000 });
  const text = (await panel.textContent()) ?? "";
  const positions = DECK_TITLES.map((t) => text.indexOf(t));
  expect(positions.every((p) => p >= 0)).toBe(true);
  expect(positions).toEqual([...positions].sort((a, b) => a - b));
  expect(consoleErrors).toEqual([]);
});

// ── Workbench parity with the server on the v0.47.0 fixtures ────────────────
//
// The workbench reads the ZIP in JavaScript and hands parts to AILANG, so
// anything the server resolves through a part's relationships has to be
// resolved again on this path. Expectations come from the same Python scripts
// that check the server (--expect-json), so the two cannot drift apart.

const REPO_ROOT = resolve(__dirname, "../..");
function expectationsFrom(script: string): any {
  return JSON.parse(execFileSync("python3", [script, "--expect-json"], { cwd: REPO_ROOT, encoding: "utf8" }));
}

async function parseOnWorkbench(page: import("@playwright/test").Page, file: string): Promise<any[]> {
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`console.error: ${msg.text()}`);
  });
  await page.goto("/workbench.html");
  const booted = await page.evaluate(async () => {
    try { await (window as any).DocParseEngine.init(); return "ok"; } catch (e) { return String((e as Error).message); }
  });
  expect(booted, `engine failed to boot; console:\n  ${consoleErrors.join("\n  ")}`).toBe("ok");
  const b64 = readFileSync(resolve(REPO_ROOT, file)).toString("base64");
  const out = await page.evaluate(async ({ name, b64 }) => {
    const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
    try {
      const r = await (window as any).DocParseEngine.parseFile(new File([bytes], name));
      return { blocks: r.blocks, error: "" };
    } catch (e) {
      return { blocks: [], error: String((e as Error).message) };
    }
  }, { name: basename(file), b64 });
  expect(out.error, `${file} failed to parse`).toBe("");
  expect(consoleErrors).toEqual([]);
  return out.blocks;
}

const cellText = (c: any) => (typeof c === "string" ? c : (c?.text ?? ""));

// G2b. The workbench sorted worksheet parts as strings (sheet10 before sheet2)
// and named them Sheet1..N. This fixture has 11 sheets stored in lexicographic
// zip order, with a tab order that is not the part numbering. Its Leads sheet
// also has blank cells mid-row, which must not shift later values left.
test("workbench XLSX: sheets in tab order with real names, cells in their columns", async ({ page }) => {
  test.setTimeout(180_000);
  const want = expectationsFrom("benchmarks/check_xlsx_positions.py");
  const blocks = await parseOnWorkbench(page, "data/test_files/challenge/challenge_sparse_rows.xlsx");

  const sheets = blocks.filter((b) => b.type === "section" && b.kind === "sheet");
  expect(sheets.map((s) => s.name)).toEqual(want.sheets);

  const byName = Object.fromEntries(sheets.map((s) => [s.name, s]));
  const tableOf = (name: string) => (byName[name]?.blocks ?? []).find((b: any) => b.type === "table");
  for (const [name, first] of Object.entries(want.firstHeader)) {
    expect(cellText(tableOf(name)?.headers?.[0]), `sheet ${name} paired with the wrong part`).toBe(first);
  }
  const rows = (tableOf("Leads")?.rows ?? []).map((r: any[]) => r.map(cellText));
  expect(rows).toEqual(want.leads);
});

// G2. The workbench returned no speaker notes. The server emits each slide's
// notes as {kind:"notes", name:"Slide N"} right after the slide, resolving the
// notes part through the slide's rels. In this fixture notesSlideK is never
// slide K's notes, one slide has none, and one empty slide has notes.
test("workbench PPTX: speaker notes follow their slide, resolved through its rels", async ({ page }) => {
  test.setTimeout(180_000);
  const want: [string, string, string][] = expectationsFrom("benchmarks/create_pptx_order_fixture.py");
  const blocks = await parseOnWorkbench(page, "data/test_files/pptx_slide_order_notes.pptx");
  const got = blocks
    .filter((b) => b.type === "section")
    .map((b) => [b.kind ?? "", b.name ?? "", (b.blocks ?? []).map((c: any) => c.text ?? "").join("|")]);
  expect(got).toEqual(want);
});
