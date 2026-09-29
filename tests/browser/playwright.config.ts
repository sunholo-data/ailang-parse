import { defineConfig, devices } from "@playwright/test";

// Browser smoke tests run against a locally-served `_site/` directory built
// the same way as in pages.yml (`cp -r docs/ _site/` + WASM downloaded into
// `_site/wasm/`). The webServer config below assumes _site exists at the
// repo root before tests start. CI builds _site explicitly; locally, run
// `cp -r docs _site && bash docs/wasm/download.sh` (mv ailang.wasm into
// `_site/wasm/`) before `npx playwright test`.

// Overridable because 8765 is also the local `ailang coordinator` port: with
// reuseExistingServer the suite would silently run against the coordinator
// (every page 404s) instead of _site/.
const PORT = Number(process.env.BROWSER_TEST_PORT || 8765);
const SITE_ROOT = "../../_site";

export default defineConfig({
  testDir: ".",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  timeout: 90_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: `python3 -m http.server ${PORT} --directory ${SITE_ROOT}`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
