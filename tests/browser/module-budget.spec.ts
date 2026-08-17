import { test } from "@playwright/test";

// Times each vendored module's WASM type-check.
//
// The in-browser type-checker has a 2s PER-MODULE wall-clock budget, so
// whether the demo loads depends on the visitor's hardware — a module that
// takes 0.4s here can blow the budget on a slower machine. This prints the
// per-module cost so growth can be checked against the budget before it
// breaks someone's browser (it broke CI at v0.34.0).
test("per-module type-check timings", async ({ page }) => {
  test.setTimeout(300_000);
  await page.goto("/");
  await page.waitForFunction(
    () => (window as unknown as { docparseWasm?: unknown }).docparseWasm !== undefined,
    null,
    { timeout: 120_000 },
  );

  const timings = await page.evaluate(async () => {
    const w = window as any;
    const engine = await w.docparseWasm.ready();
    const base = w.docparseWasm.assetBase
      ? w.docparseWasm.assetBase() + "ailang/"
      : "/ailang/";
    const mods: { name: string; path: string }[] = w.docparseWasm.modules();
    const out: { name: string; ms: number; ok: boolean }[] = [];
    for (const mod of mods) {
      const m = mod.name;
      const path = base + mod.path + "?v=" + Date.now();
      const resp = await fetch(path);
      if (!resp.ok) { out.push({ name: m, ms: -1, ok: false }); continue; }
      const src = await resp.text();
      const t0 = performance.now();
      const r = engine.repl.loadModule(m, src);
      const t1 = performance.now();
      out.push({ name: m, ms: Math.round(t1 - t0), ok: !!r.success });
    }
    return out;
  });

  timings.sort((a, b) => b.ms - a.ms);
  console.log("PER-MODULE TYPE-CHECK (budget 2000ms each):");
  for (const t of timings) {
    const pct = Math.round((t.ms / 2000) * 100);
    console.log(`  ${String(t.ms).padStart(5)}ms  ${String(pct).padStart(3)}% of budget  ${t.ok ? "ok " : "ERR"}  ${t.name}`);
  }
});
