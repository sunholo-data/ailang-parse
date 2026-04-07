// Unit + golden tests for docs/js/docparse-blocks.js — the shared block
// transformation layer used by both the homepage WASM demo and the workbench.
//
// Run from repo root:
//
//   node --test docs/js/__tests__/
//
// No browser, no WASM, no headless runner — just Node's built-in test runner
// loading the IIFE into a vm context with a `window` shim. The point is to
// pin the *transformation* layer (section flattening, markdown emission,
// insights counts, merged-cell detection) so the next regression like
// "challenge_merged_cells.xlsx renders empty" gets caught before it ships.

import { test } from 'node:test';
// Non-strict assert: vm.runInContext gives the loaded module its own
// Array/Object prototypes, so deepStrictEqual would fail on values that are
// structurally identical but cross-realm. deepEqual ignores the prototype.
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '..', '..', '..');
const BLOCKS_PATH = resolve(REPO_ROOT, 'docs', 'js', 'docparse-blocks.js');
const FIXTURES_DIR = resolve(__dirname, 'fixtures');

// Load docparse-blocks.js into a sandboxed vm context with a window shim,
// then return the resulting `window.DocParseBlocks` object.
function loadDocParseBlocks() {
  const code = readFileSync(BLOCKS_PATH, 'utf8');
  const ctx = { window: {} };
  vm.createContext(ctx);
  vm.runInContext(code, ctx, { filename: 'docparse-blocks.js' });
  if (!ctx.window.DocParseBlocks) {
    throw new Error('docparse-blocks.js did not expose window.DocParseBlocks');
  }
  return ctx.window.DocParseBlocks;
}

function loadFixture(name) {
  return JSON.parse(readFileSync(resolve(FIXTURES_DIR, name), 'utf8'));
}

const DPB = loadDocParseBlocks();

// ── typeOf ──────────────────────────────────────────────────────────────

test('typeOf normalizes canonical types', () => {
  assert.equal(DPB.typeOf({ type: 'heading' }), 'heading');
  assert.equal(DPB.typeOf({ type: 'Table' }), 'table');
  assert.equal(DPB.typeOf({ type: 'section' }), 'section');
  assert.equal(DPB.typeOf({ type: 'image' }), 'image');
});

test('typeOf normalizes legacy aliases', () => {
  assert.equal(DPB.typeOf({ type: 'paragraph' }), 'text');
  assert.equal(DPB.typeOf({ type: 'para' }), 'text');
  assert.equal(DPB.typeOf({ type: 'trackchange' }), 'change');
  assert.equal(DPB.typeOf({ type: 'tracked' }), 'change');
});

test('typeOf returns "unknown" for nullish/garbage', () => {
  assert.equal(DPB.typeOf(null), 'unknown');
  assert.equal(DPB.typeOf(undefined), 'unknown');
  assert.equal(DPB.typeOf({}), 'unknown');
  assert.equal(DPB.typeOf('not an object'), 'unknown');
});

// ── cellText ────────────────────────────────────────────────────────────

test('cellText handles all the shapes parsers actually emit', () => {
  assert.equal(DPB.cellText('plain'), 'plain');           // CSV/XLSX path
  assert.equal(DPB.cellText({ text: 'rich' }), 'rich');   // DOCX path
  assert.equal(DPB.cellText({ text: 'm', colSpan: 2 }), 'm'); // merged
  assert.equal(DPB.cellText(null), '');
  assert.equal(DPB.cellText(undefined), '');
  assert.equal(DPB.cellText({}), '');
});

// ── flatten ─────────────────────────────────────────────────────────────

test('flatten unwraps container sections (sheet, slide, article, thread)', () => {
  const blocks = [
    { type: 'section', kind: 'sheet', blocks: [
      { type: 'heading', text: 'Sheet 1' },
      { type: 'table', rows: [['a', 'b']] },
    ]},
  ];
  const flat = DPB.flatten(blocks);
  assert.equal(flat.length, 2);
  assert.equal(flat[0].type, 'heading');
  assert.equal(flat[1].type, 'table');
  // Tagged with enclosing section kind so consumers can render context.
  assert.equal(flat[0]._sectionKind, 'sheet');
  assert.equal(flat[1]._sectionKind, 'sheet');
});

test('flatten keeps atomic sections intact (comment, header, footer, attachment)', () => {
  const blocks = [
    { type: 'section', kind: 'comment', blocks: [{ type: 'text', text: 'hi' }] },
    { type: 'section', kind: 'header',  blocks: [{ type: 'text', text: 'top' }] },
    { type: 'section', kind: 'footer',  blocks: [{ type: 'text', text: 'bot' }] },
  ];
  const flat = DPB.flatten(blocks);
  assert.equal(flat.length, 3);
  flat.forEach(b => assert.equal(b.type, 'section'));
  assert.deepEqual(flat.map(b => b.kind), ['comment', 'header', 'footer']);
});

test('flatten does not mutate input blocks', () => {
  const original = [{ type: 'section', kind: 'sheet', blocks: [{ type: 'text', text: 'x' }] }];
  const snapshot = JSON.stringify(original);
  DPB.flatten(original);
  assert.equal(JSON.stringify(original), snapshot);
});

test('flatten tolerates non-array input', () => {
  assert.deepEqual(DPB.flatten(null), []);
  assert.deepEqual(DPB.flatten(undefined), []);
  assert.deepEqual(DPB.flatten('nope'), []);
});

test('flatten recurses through nested container sections', () => {
  const blocks = [
    { type: 'section', kind: 'article', blocks: [
      { type: 'section', kind: 'sheet', blocks: [
        { type: 'heading', text: 'deep' },
      ]},
    ]},
  ];
  const flat = DPB.flatten(blocks);
  assert.equal(flat.length, 1);
  assert.equal(flat[0].type, 'heading');
});

// ── merged cell detection ───────────────────────────────────────────────

test('isMergedCell detects colSpan/rowSpan/merged flags', () => {
  assert.equal(DPB.isMergedCell({ text: 'x', colSpan: 2 }), true);
  assert.equal(DPB.isMergedCell({ text: 'x', rowSpan: 3 }), true);
  assert.equal(DPB.isMergedCell({ text: 'x', merged: true }), true);
  assert.equal(DPB.isMergedCell({ text: 'x', colSpan: 1, rowSpan: 1 }), false);
  assert.equal(DPB.isMergedCell('plain'), false);
  assert.equal(DPB.isMergedCell(null), false);
});

test('isMergedTable / countMergedCells walk row arrays', () => {
  const table = { type: 'table', rows: [
    ['a', 'b', 'c'],
    [{ text: 'span', colSpan: 2 }, 'c'],
    ['d', { text: 'r', rowSpan: 2 }, 'e'],
  ]};
  assert.equal(DPB.isMergedTable(table), true);
  assert.equal(DPB.countMergedCells(table), 2);
});

test('isMergedTable returns false for plain string-array tables (current XLSX shape)', () => {
  // This is the shape both CLI and WASM emit today since xlsx_parser uses
  // simpleCell() unconditionally. When merge-range parsing lands, these
  // fixtures will need refreshing.
  const table = { type: 'table', rows: [['Region', 'Revenue'], ['EU', '100']] };
  assert.equal(DPB.isMergedTable(table), false);
  assert.equal(DPB.countMergedCells(table), 0);
});

// ── computeInsights ─────────────────────────────────────────────────────

test('computeInsights walks flattened blocks and tallies features', () => {
  const blocks = [
    { type: 'heading', text: 'H' },
    { type: 'change', changeType: 'insertion', author: 'a', text: 't' },
    { type: 'section', kind: 'comment', blocks: [{ type: 'text', text: 'c' }] },
    { type: 'section', kind: 'header',  blocks: [{ type: 'text', text: 'h' }] },
    { type: 'section', kind: 'sheet',   blocks: [
      { type: 'table', rows: [[{ text: 'm', colSpan: 2 }, 'x']] },
    ]},
  ];
  const i = DPB.computeInsights(blocks);
  assert.equal(i.headings, 1);
  assert.equal(i.changes, 1);
  assert.equal(i.comments, 1);
  assert.equal(i.headfoot, 1);
  assert.equal(i.tables, 1);
  assert.equal(i.merged, 1);
});

// ── toMarkdown ──────────────────────────────────────────────────────────

test('toMarkdown emits headings with correct level', () => {
  const md = DPB.toMarkdown([
    { type: 'heading', level: 1, text: 'H1' },
    { type: 'heading', level: 3, text: 'H3' },
  ]);
  assert.match(md, /^# H1/m);
  assert.match(md, /^### H3/m);
});

test('toMarkdown clamps heading level to [1,6]', () => {
  const md = DPB.toMarkdown([
    { type: 'heading', level: 0, text: 'low' },
    { type: 'heading', level: 99, text: 'high' },
  ]);
  assert.match(md, /^# low/m);
  assert.match(md, /^###### high/m);
});

test('toMarkdown emits tables with header + separator + rows', () => {
  const md = DPB.toMarkdown([{
    type: 'table',
    headers: ['A', 'B'],
    rows: [['1', '2'], ['3', '4']],
  }]);
  assert.match(md, /\| A \| B \|/);
  assert.match(md, /\| --- \| --- \|/);
  assert.match(md, /\| 1 \| 2 \|/);
  assert.match(md, /\| 3 \| 4 \|/);
});

test('toMarkdown derives table headers from first row when headers missing', () => {
  const md = DPB.toMarkdown([{
    type: 'table',
    rows: [['Col1', 'Col2'], ['v1', 'v2']],
  }]);
  assert.match(md, /\| Col1 \| Col2 \|/);
});

test('toMarkdown emits ordered/unordered lists', () => {
  const ul = DPB.toMarkdown([{ type: 'list', items: ['a', 'b'] }]);
  assert.equal(ul, '- a\n- b');
  const ol = DPB.toMarkdown([{ type: 'list', ordered: true, items: ['a', 'b'] }]);
  assert.equal(ol, '1. a\n2. b');
});

test('toMarkdown emits change blocks as quoted lines with author', () => {
  const md = DPB.toMarkdown([{
    type: 'change', changeType: 'insertion', author: 'Mark', text: 'new line',
  }]);
  assert.match(md, /^> \*\*insertion\*\* by Mark: new line$/);
});

test('toMarkdown unwraps sheet sections so XLSX content is not lost', () => {
  // The exact bug that triggered this whole module: XLSX SectionBlock
  // children were dropped because the renderer didn't recurse into sections.
  const md = DPB.toMarkdown([{
    type: 'section', kind: 'sheet', blocks: [
      { type: 'heading', level: 2, text: 'Sheet1' },
      { type: 'table', rows: [['A', 'B']] },
    ],
  }]);
  assert.match(md, /## Sheet1/);
  assert.match(md, /\| A \| B \|/);
});

// ── Golden fixture tests ────────────────────────────────────────────────
// These pin real parser output. If a parser change shifts output shape, the
// fixture has to be regenerated *intentionally*. That's the point.

test('golden: challenge_merged_cells.xlsx — flatten unwraps both sheets', () => {
  const blocks = loadFixture('challenge_merged_cells_xlsx.json');
  // Two sheets at the top level.
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].type, 'section');
  assert.equal(blocks[0].kind, 'sheet');

  const flat = DPB.flatten(blocks);
  // Each sheet has heading + table → 4 leaves total.
  assert.equal(flat.length, 4);
  const types = flat.map(b => b.type);
  assert.deepEqual(types, ['heading', 'table', 'heading', 'table']);
  // All leaves are tagged with their sheet origin.
  flat.forEach(b => assert.equal(b._sectionKind, 'sheet'));
});

test('golden: challenge_merged_cells.xlsx — markdown contains both tables', () => {
  const blocks = loadFixture('challenge_merged_cells_xlsx.json');
  const md = DPB.toMarkdown(blocks);
  assert.match(md, /Region/);
  assert.match(md, /Revenue/);
  assert.match(md, /Merged 2 rows/);
});

test('golden: challenge_merged_cells.xlsx — insights count both tables', () => {
  const blocks = loadFixture('challenge_merged_cells_xlsx.json');
  const i = DPB.computeInsights(blocks);
  assert.equal(i.tables, 2);
  // Current parser shape: simpleCell() for every cell, so no merged metadata.
  // When xlsx_parser learns merge-range detection, this assertion flips to >0
  // and the fixture has to be regenerated.
  assert.equal(i.merged, 0);
});

test('golden: comments.docx — insights detect comments as atomic sections', () => {
  const blocks = loadFixture('comments_docx.json');
  const i = DPB.computeInsights(blocks);
  assert.ok(i.comments >= 1, 'expected at least one comment');
});

test('golden: track_changes_move.docx — insights detect change blocks', () => {
  const blocks = loadFixture('track_changes_move_docx.json');
  const i = DPB.computeInsights(blocks);
  assert.ok(i.changes >= 1, 'expected at least one change block');
});

test('golden: ailang_formats.csv — single table renders as markdown', () => {
  const blocks = loadFixture('ailang_formats_csv.json');
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].type, 'table');
  const md = DPB.toMarkdown(blocks);
  assert.match(md, /\|/); // pipes present → table emitted
  assert.match(md, /---/); // separator row present
});
