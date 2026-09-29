import { test, expect } from "@playwright/test";

// Per-module WASM type-check cost, gated on the DETERMINISTIC step count.
//
// The in-browser type-checker's limit is wall-clock and per module, so whether
// the site boots depends on the visitor's hardware. In September 2026 a
// partner's machine hit the then-8s limit 68,608 steps into markdown_parser
// (105k steps; 2.6s on an M4 Max), and every DOCX they dropped on the
// workbench failed. Wall-clock on a CI runner cannot see that — this used to
// print timings and assert nothing — so the gate is typeCheckSteps, which is
// identical for identical source on every machine. Wall-clock is printed for
// context only.
//
// STEP_CEILING: no module may exceed it. At the slowest rate seen in the field
// (8s / 68,608 steps) a module at the ceiling type-checks in ~12s, which the
// 30s limit wasm-demo.js now sets absorbs with room to spare. markdown_parser
// at 105k would have failed here. When a module crosses it, split it or move
// work behind typed helper functions (see CHANGELOG "Workbench DOCX parsing
// works again") — do not raise the number.
const STEP_CEILING = 100_000;

// Known debt, capped at today's cost so it can shrink but not grow.
// docx_generator is only loaded by docs/lab/docx-generation.html.
const OVER_CEILING_CAPS: Record<string, number> = {
  "docparse/services/docx_generator": 155_000,
};

// Modules outside the default boot set that pages load on demand
// (docs/lab/docx-generation.html), in dependency order.
const EXTRA_MODULES = [
  "docparse/services/docx_template",
  "docparse/services/docx_layout",
  "docparse/services/docx_generator",
  "docparse/services/docparse_generate",
];

type Stat = { name: string; ok: boolean; ms: number | null; steps: number | null; budgetMs: number | null };

test("per-module type-check cost stays under the step ceiling", async ({ page }) => {
  test.setTimeout(300_000);
  await page.goto("/");
  await page.waitForFunction(
    () => (window as unknown as { docparseWasm?: unknown }).docparseWasm !== undefined,
    null,
    { timeout: 120_000 },
  );

  // loadStats() is what the page itself recorded while booting — the real
  // loads, in the real order — plus the extras loaded here.
  const stats: Stat[] = await page.evaluate(async (extras) => {
    const w = window as any;
    await w.docparseWasm.ready();
    for (const name of extras) await w.docparseWasm.loadExtraModule(name, name + ".ail");
    return w.docparseWasm.loadStats();
  }, EXTRA_MODULES);

  const bootSet: string[] = await page.evaluate(() =>
    (window as any).docparseWasm.modules().map((m: { name: string }) => m.name),
  );

  const capFor = (name: string) => OVER_CEILING_CAPS[name] ?? STEP_CEILING;
  const budget = stats.find((s) => s.budgetMs)?.budgetMs ?? 0;
  const sorted = [...stats].sort((a, b) => (b.steps ?? 0) - (a.steps ?? 0));
  console.log(`PER-MODULE TYPE-CHECK (step ceiling ${STEP_CEILING}; wall-clock limit ${budget}ms)`);
  for (const t of sorted) {
    const pct = t.steps == null ? "  ?" : String(Math.round((t.steps / capFor(t.name)) * 100)).padStart(3);
    console.log(
      `  ${String(t.steps ?? "?").padStart(7)} steps  ${pct}% of cap  ${String(t.ms ?? "?").padStart(5)}ms  ${t.ok ? "ok " : "ERR"}  ${t.name}`,
    );
  }

  // Every module in the bundle must have been measured — one missing from the
  // stats is one this gate has silently stopped covering.
  const measured = stats.map((s) => s.name);
  for (const name of [...bootSet, ...EXTRA_MODULES]) {
    expect(measured, `no load stats for ${name}`).toContain(name);
  }
  for (const t of stats) {
    expect(t.ok, `${t.name} failed to load`).toBe(true);
    expect(t.steps, `${t.name}: runtime did not report typeCheckSteps`).not.toBeNull();
  }
  const over = stats.filter((t) => (t.steps ?? 0) > capFor(t.name));
  expect(
    over.map((t) => `${t.name}: ${t.steps} steps (cap ${capFor(t.name)})`),
    "modules over their type-check step cap",
  ).toEqual([]);
});
