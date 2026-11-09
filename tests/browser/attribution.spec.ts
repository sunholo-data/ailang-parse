import { test, expect, type Page, type Request } from "@playwright/test";
import { readFileSync, existsSync, statSync } from "node:fs";
import { resolve, extname, normalize } from "node:path";

// Campaign attribution + visit counter (docs/js/components.js).
//
// The code runs only on the www.sunholo.com origin, so the page is loaded AT
// https://www.sunholo.com/ailang-parse/ with every request to that prefix
// fulfilled from the locally built _site/. Nothing reaches the real site or
// the docparse API: the visit beacon is intercepted and answered locally, and
// every other external request is aborted. Codes and campaigns are invented.

const SITE_ROOT = resolve(__dirname, "../../_site");
const ORIGIN = "https://www.sunholo.com";
const PREFIX = `${ORIGIN}/ailang-parse/`;
const VISIT_URL = "https://docparse.ailang.sunholo.com/api/v1/visit";

const TYPES: Record<string, string> = {
  ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
  ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json",
  ".wasm": "application/wasm",
};

async function serveSite(page: Page, beacons: Request[]) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = req.url();
    if (url.startsWith(VISIT_URL)) {
      beacons.push(req);
      return route.fulfill({ status: 204, body: "" });
    }
    if (!url.startsWith(PREFIX)) return route.abort();
    let rel = decodeURIComponent(new URL(url).pathname.slice("/ailang-parse/".length)) || "index.html";
    if (rel.endsWith("/")) rel += "index.html";
    const file = normalize(resolve(SITE_ROOT, rel));
    if (!file.startsWith(SITE_ROOT) || !existsSync(file) || statSync(file).isDirectory()) {
      return route.fulfill({ status: 404, body: "not found" });
    }
    return route.fulfill({
      status: 200,
      contentType: TYPES[extname(file)] || "application/octet-stream",
      body: readFileSync(file),
    });
  });
}

// Playwright's Chromium reports navigator.webdriver = true, which the counter
// (correctly) treats as a bot. Present as a normal browser for these tests.
async function asHumanBrowser(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, "webdriver", { get: () => false });
  });
}

test("landing link stores attribution, sets dp_attr, strips the URL and beacons once", async ({ page, context }) => {
  const beacons: Request[] = [];
  await asHumanBrowser(page);
  await serveSite(page, beacons);

  await page.goto(`${PREFIX}why.html?ref=demo-partner&utm_source=demo&utm_campaign=launch&tab=x#top`);
  await page.waitForFunction(() => typeof (window as any).docparseVisit === "function");

  // Address bar: campaign params gone, the rest kept.
  expect(page.url()).toBe(`${PREFIX}why.html?tab=x#top`);

  const stored = await page.evaluate(() => ({
    ref: localStorage.getItem("docparse_ref"),
    attr: localStorage.getItem("docparse_attr"),
  }));
  expect(stored.ref).toBe("demo-partner");
  const attr = JSON.parse(stored.attr!);
  expect(attr).toMatchObject({
    ref: "demo-partner", utm_source: "demo", utm_campaign: "launch",
    landing: "/ailang-parse/why.html",
  });
  expect(typeof attr.at).toBe("string");

  const cookie = (await context.cookies(ORIGIN)).find((c) => c.name === "dp_attr");
  expect(cookie).toBeTruthy();
  expect(cookie!.domain).toBe(".sunholo.com");
  expect(cookie!.path).toBe("/");
  expect(cookie!.secure).toBe(true);
  expect(cookie!.sameSite).toBe("Lax");
  const days = (cookie!.expires - Date.now() / 1000) / 86400;
  expect(days).toBeGreaterThan(89);
  expect(days).toBeLessThanOrEqual(90);
  expect(JSON.parse(decodeURIComponent(cookie!.value))).toEqual(attr);

  await expect.poll(() => beacons.length).toBe(1);
  expect(beacons[0].method()).toBe("POST");
  expect(JSON.parse(beacons[0].postData() || "{}")).toEqual({
    site: "ailang-parse", page: "/ailang-parse/why.html",
    ref: "demo-partner", utm_source: "demo", utm_campaign: "launch",
  });

  // Second page view: plain beacon, first touch untouched.
  await page.goto(`${PREFIX}docs.html?ref=other-partner`);
  await expect.poll(() => beacons.length).toBe(2);
  // dp_attr (Domain=.sunholo.com) exists by now, yet the counter must not carry
  // it: fetch with credentials:'omit', not sendBeacon, which always sends cookies.
  for (const b of beacons) expect((await b.allHeaders())["cookie"]).toBeUndefined();
  expect(JSON.parse(beacons[1].postData() || "{}")).toEqual({
    site: "ailang-parse", page: "/ailang-parse/docs.html", ref: "other-partner",
  });
  expect(await page.evaluate(() => localStorage.getItem("docparse_attr"))).toBe(stored.attr);
  expect(await page.evaluate(() => localStorage.getItem("docparse_ref"))).toBe("demo-partner");
});

test("no beacon under automation (navigator.webdriver) or Global Privacy Control", async ({ browser }) => {
  for (const mode of ["webdriver", "gpc"] as const) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const beacons: Request[] = [];
    if (mode === "gpc") {
      await asHumanBrowser(page);
      await page.addInitScript(() => {
        Object.defineProperty(Navigator.prototype, "globalPrivacyControl", { get: () => true });
      });
    }
    await serveSite(page, beacons);
    await page.goto(`${PREFIX}why.html?ref=demo-partner`);
    await page.waitForFunction(() => typeof (window as any).docparseVisit === "function");
    // Attribution itself is unaffected; only the counter stays silent.
    expect(await page.evaluate(() => localStorage.getItem("docparse_ref"))).toBe("demo-partner");
    expect(page.url()).toBe(`${PREFIX}why.html`);
    await page.waitForTimeout(500);
    expect(beacons.length, mode).toBe(0);
    await context.close();
  }
});
