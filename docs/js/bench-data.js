/**
 * AILANG Parse — Benchmark Data Injector
 *
 * Single source of truth for OfficeDocBench numbers shown across the docs site.
 * Loads docs/data/officedocbench-summary.json (mirrored from
 * benchmarks/officedocbench/results/summary.json by eval_officedocbench.py --all)
 * and injects values into elements with `data-bench` attributes.
 *
 * Usage in HTML:
 *   <span data-bench="ailang_parse.composite">93.9%</span>
 *   <span data-bench="ailang_parse.adjusted">93.9%</span>
 *   <span data-bench="kreuzberg.composite">71.1%</span>
 *   <span data-bench="kreuzberg.adjusted">68.0%</span>
 *   <span data-bench="ailang_parse.coverage">100%</span>
 *   <span data-bench="total_files">69</span>
 *   <span data-bench="run_date">2026-04-07</span>
 *   <span data-bench="ailang_parse.per_format.docx.composite">90.9%</span>
 *
 * The inline text in the element is a fallback shown if the fetch fails.
 *
 * Path resolution rules:
 *   - Top-level keys (`total_files`, `run_date`, `schema_version`) → summary[key]
 *   - Anything else → adapter id is the first segment, then dotted path into the adapter object
 *   - Numeric values in [0, 1] are auto-formatted as percentages (one decimal)
 *   - Values >= 1 are displayed as integers
 */
(function () {
  var SUMMARY_URL = 'data/officedocbench-summary.json';

  function format(value, key) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'number') {
      // Coverage / score / composite — anything ratio-shaped → percentage
      if (value >= 0 && value <= 1 && /composite|coverage|adjusted|score|recall|quality|fidelity|jaccard|count|metadata|detection|fields|fmt/i.test(key)) {
        return (value * 100).toFixed(1) + '%';
      }
      return String(value);
    }
    return String(value);
  }

  function resolve(summary, path) {
    var parts = path.split('.');
    var top = parts[0];
    if (top in summary && top !== 'adapters') {
      // Top-level field like total_files / run_date
      return summary[top];
    }
    // First segment is an adapter id, rest is a path into the adapter object
    var adapter = (summary.adapters || []).find(function (a) { return a.id === top; });
    if (!adapter) return undefined;
    var node = adapter;
    for (var i = 1; i < parts.length; i++) {
      if (node == null) return undefined;
      node = node[parts[i]];
    }
    return node;
  }

  function inject(summary) {
    document.querySelectorAll('[data-bench]').forEach(function (el) {
      var path = el.getAttribute('data-bench');
      var value = resolve(summary, path);
      if (value === undefined || typeof value === 'object') return;

      // data-bench-attr → write raw numeric value (0-100 for ratios) to that attribute.
      // data-bench-style → write percentage string to that CSS style property (e.g. "width").
      // Default → replace textContent with formatted value.
      var attrTarget = el.getAttribute('data-bench-attr');
      var styleTarget = el.getAttribute('data-bench-style');
      var pct = (typeof value === 'number' && value >= 0 && value <= 1)
        ? (value * 100).toFixed(1)
        : null;

      if (attrTarget) {
        el.setAttribute(attrTarget, pct !== null ? pct : String(value));
      } else if (styleTarget) {
        el.style[styleTarget] = pct !== null ? pct + '%' : String(value);
      } else {
        el.textContent = format(value, path);
      }
    });
  }

  // Expose for callers that load data after DOM ready (e.g. dynamic tables)
  window.BENCH_INJECT = inject;

  fetch(SUMMARY_URL, { cache: 'no-cache' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data) return;
      window.BENCH_DATA = data;
      inject(data);
    })
    .catch(function () { /* keep inline fallback values */ });
})();
