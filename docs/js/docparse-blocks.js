// Shared block helpers used by both the homepage WASM demo (wasm-demo.js)
// and the workbench (workbench.html). Anything that touches Block ADT shape
// — section unwrapping, markdown conversion, insights, merged-cell detection —
// lives here so we never again fix the same bug in two places. (See the
// "challenge_merged_cells.xlsx renders empty in workbench" regression for
// the cautionary tale.)
//
// Visual rendering (HTML) deliberately stays per-page since the homepage and
// workbench have different aesthetics. This module is the *transformation*
// layer they share, not the presentation layer.
//
// Loaded as a classic script before any consumer:
//   <script src="js/docparse-blocks.js"></script>
//
// Exposes the global `window.DocParseBlocks`.

(function () {
  'use strict';

  // ── Block type normalization ────────────────────────────────────────
  // The AILANG output_formatter emits canonical lowercase types
  // (heading, text, table, list, image, audio, video, section, change),
  // but historic output and tests sometimes used variants. Normalize here.
  function typeOf(b) {
    if (!b || typeof b !== 'object') return 'unknown';
    var t = (b.type || '').toLowerCase();
    if (t === 'heading') return 'heading';
    if (t === 'table') return 'table';
    if (t === 'change' || t === 'trackchange' || t === 'tracked') return 'change';
    if (t === 'comment') return 'comment';
    if (t === 'image') return 'image';
    if (t === 'list') return 'list';
    if (t === 'section') return 'section';
    if (t === 'text' || t === 'paragraph' || t === 'para') return 'text';
    return t || 'unknown';
  }

  // ── Cell text extraction ────────────────────────────────────────────
  // Cells can be plain strings, {text: ...} objects, or merged cells with
  // additional colSpan/rowSpan attributes.
  function cellText(c) {
    if (c == null) return '';
    if (typeof c === 'string') return c;
    if (typeof c === 'object') return c.text || '';
    return String(c);
  }

  // ── Section flattening ──────────────────────────────────────────────
  // Walks SectionBlocks recursively, returning a flat list of leaves while
  // tagging each with its enclosing section kind. Container sections (sheet,
  // article, slide, thread) get unwrapped; comment/header/footer sections
  // stay atomic because consumers usually have dedicated rendering for them.
  //
  // Returned blocks are shallow clones with a `_sectionKind` property added
  // when they originated from inside a container section. Original input is
  // never mutated.
  var ATOMIC_SECTION_KINDS = { comment: 1, header: 1, footer: 1, attachment: 1 };

  function flatten(blocks, sectionContext) {
    var out = [];
    if (!Array.isArray(blocks)) return out;
    blocks.forEach(function (b) {
      if (!b || typeof b !== 'object') return;
      if (typeOf(b) === 'section' && Array.isArray(b.blocks)) {
        if (ATOMIC_SECTION_KINDS[b.kind]) {
          out.push(sectionContext ? assignTag(b, sectionContext) : b);
          return;
        }
        flatten(b.blocks, b.kind || sectionContext).forEach(function (sub) { out.push(sub); });
        return;
      }
      out.push(sectionContext && !b._sectionKind ? assignTag(b, sectionContext) : b);
    });
    return out;
  }

  function assignTag(block, kind) {
    // Shallow clone to avoid mutating parser output.
    var copy = {};
    for (var k in block) if (Object.prototype.hasOwnProperty.call(block, k)) copy[k] = block[k];
    copy._sectionKind = kind;
    return copy;
  }

  // ── Merged cell detection ───────────────────────────────────────────
  function isMergedCell(c) {
    return !!(c && typeof c === 'object' && (c.colSpan > 1 || c.rowSpan > 1 || c.merged));
  }
  function isMergedTable(b) {
    if (typeOf(b) !== 'table' || !Array.isArray(b.rows)) return false;
    for (var i = 0; i < b.rows.length; i++) {
      var row = b.rows[i];
      if (!Array.isArray(row)) continue;
      for (var j = 0; j < row.length; j++) {
        if (isMergedCell(row[j])) return true;
      }
    }
    return false;
  }
  function countMergedCells(b) {
    if (typeOf(b) !== 'table' || !Array.isArray(b.rows)) return 0;
    var n = 0;
    b.rows.forEach(function (row) {
      if (!Array.isArray(row)) return;
      row.forEach(function (c) { if (isMergedCell(c)) n++; });
    });
    return n;
  }

  // ── Insights ────────────────────────────────────────────────────────
  // Counts the structural features that the homepage banner and the
  // workbench inspector both surface. Walks flattened blocks so XLSX sheet
  // sections, DOCX section wrappers, etc. all contribute correctly.
  function computeInsights(blocks) {
    var changes = 0, comments = 0, headfoot = 0, merged = 0, tables = 0, headings = 0;
    flatten(blocks).forEach(function (b) {
      var t = typeOf(b);
      if (t === 'change') changes++;
      if (t === 'comment' || b.kind === 'comment') comments++;
      if (b.kind === 'header' || b.kind === 'footer') headfoot++;
      if (t === 'table') {
        tables++;
        merged += countMergedCells(b);
      }
      if (t === 'heading') headings++;
    });
    return {
      changes: changes,
      comments: comments,
      headfoot: headfoot,
      merged: merged,
      tables: tables,
      headings: headings
    };
  }

  // ── Markdown conversion ─────────────────────────────────────────────
  // Format-agnostic — DOCX, PPTX, XLSX, HTML, MD, CSV, EML all flow through
  // the same code path because flatten() normalizes the section nesting.
  function toMarkdown(blocks) {
    return flatten(blocks).map(blockToMarkdown).filter(Boolean).join('\n\n');
  }

  function blockToMarkdown(b) {
    var t = typeOf(b);
    if (t === 'heading') {
      return repeat('#', Math.max(1, Math.min(6, b.level || 1))) + ' ' + (b.text || '');
    }
    if (t === 'table') {
      var headers = (b.headers || []).map(cellText);
      if (headers.length === 0 && Array.isArray(b.rows) && b.rows[0]) {
        headers = (Array.isArray(b.rows[0]) ? b.rows[0] : []).map(cellText);
      }
      var sep = headers.map(function () { return '---'; });
      var dataRows = (b.rows || []).map(function (r) {
        return '| ' + (Array.isArray(r) ? r : []).map(cellText).join(' | ') + ' |';
      });
      return '| ' + headers.join(' | ') + ' |\n| ' + sep.join(' | ') + ' |\n' + dataRows.join('\n');
    }
    if (t === 'list' && Array.isArray(b.items)) {
      return b.items.map(function (i, idx) {
        return (b.ordered ? (idx + 1) + '. ' : '- ') + cellText(i);
      }).join('\n');
    }
    if (t === 'change') {
      return '> **' + (b.changeType || 'change') + '** by ' + (b.author || 'unknown') + ': ' + (b.text || '');
    }
    if (t === 'comment' || b.kind === 'comment') {
      var body = b.text || extractCommentText(b);
      // Quote the annotated span so the comment and its target read as one
      // unit; an unanchored comment is labelled rather than left to imply one.
      if (b.anchored && b.anchorText) {
        return '> ' + b.anchorText + '\n>\n> **Comment (' + (b.author || 'unknown') + '):** ' + body;
      }
      if (b.anchored === false) {
        return '> **Comment (' + (b.author || 'unknown') + ', unanchored):** ' + body;
      }
      return '> **[' + (b.author || 'comment') + ']** ' + body;
    }
    if (t === 'image') {
      return '![' + (b.description || b.alt || 'image') + ']()';
    }
    return b.text || '';
  }

  function extractCommentText(b) {
    if (!Array.isArray(b.blocks)) return '';
    return b.blocks.map(function (sub) { return sub.text || ''; }).filter(Boolean).join(' ');
  }

  function repeat(str, n) {
    var out = '';
    for (var i = 0; i < n; i++) out += str;
    return out;
  }

  // ── Public API ──────────────────────────────────────────────────────
  window.DocParseBlocks = {
    typeOf: typeOf,
    cellText: cellText,
    flatten: flatten,
    isMergedCell: isMergedCell,
    isMergedTable: isMergedTable,
    countMergedCells: countMergedCells,
    computeInsights: computeInsights,
    toMarkdown: toMarkdown,
    // Exposed for consumers that want to render a single block in their own style
    blockToMarkdown: blockToMarkdown
  };
})();
