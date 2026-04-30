import { test, expect } from "@playwright/test";
import { resolve } from "node:path";

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
  await page.waitForFunction(
    () => (window as unknown as { DocParseEngine?: { isReady: () => boolean } }).DocParseEngine?.isReady() === true,
    null,
    { timeout: 60_000 },
  );

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
