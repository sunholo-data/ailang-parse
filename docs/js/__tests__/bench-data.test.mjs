import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../bench-data.js', import.meta.url), 'utf8');
function element(path, extra = {}) {
  const attrs = { 'data-bench': path, ...extra };
  return { textContent: 'OLD SCORE', style: {}, getAttribute: (k) => attrs[k] || null,
    setAttribute: (k, v) => { attrs[k] = v; }, attrs };
}
async function inject(elements, summary, offline = false) {
  vm.runInNewContext(source, { window: {}, document: { querySelectorAll: () => elements },
    fetch: async () => { if (offline) throw new Error('offline'); return { ok: true, json: async () => summary }; } });
  await new Promise(setImmediate);
}

test('benchmark values retain one decimal and file counts stay counts', async () => {
  const score = element('ailang_parse.composite');
  const count = element('ailang_parse.files_ok');
  await inject([score, count], { adapters: [{ id: 'ailang_parse', composite: .956, files_ok: 1 }] });
  assert.equal(score.textContent, '95.6%');
  assert.equal(count.textContent, '1');
});
test('a successful refresh clears obsolete provider scores and bar widths', async () => {
  const score = element('old_provider.composite');
  const bar = element('old_provider.adjusted', { 'data-bench-attr': 'data-width', 'data-width': '90' });
  const absent = element('ailang_parse.structural_fidelity');
  await inject([score, bar, absent], { adapters: [{ id: 'ailang_parse', structural_fidelity: null }] });
  assert.equal(score.textContent, '—');
  assert.equal(absent.textContent, '—');
  assert.equal(bar.attrs['data-width'], '0');
});
test('offline pages retain their dated checked-in fallback', async () => {
  const score = element('ailang_parse.composite');
  await inject([score], {}, true);
  assert.equal(score.textContent, 'OLD SCORE');
});
