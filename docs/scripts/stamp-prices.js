#!/usr/bin/env node
/**
 * stamp-prices.js — Build-time injection of DP_DATA values into HTML files.
 *
 * Single source of truth: site-data.js defines all pricing/format/site data.
 * This script reads site-data.js, then for every HTML file in docs/, finds
 * elements with data-dp="dotted.path" attributes and replaces their text
 * content with the resolved, formatted value from DP_DATA.
 *
 * Usage:
 *   node docs/scripts/stamp-prices.js          # stamp all HTML files in docs/
 *   node docs/scripts/stamp-prices.js --check  # dry-run: report stale values, exit 1 if any
 *
 * Run before deployment to ensure static HTML matches site-data.js.
 */

const fs = require('fs');
const path = require('path');

const DOCS_DIR = path.resolve(__dirname, '..');
const SITE_DATA_PATH = path.join(DOCS_DIR, 'js', 'site-data.js');

// ── Load DP_DATA from site-data.js ──
const siteDataSrc = fs.readFileSync(SITE_DATA_PATH, 'utf8');
const sandbox = {};
const wrappedSrc = siteDataSrc
  .replace(/\bvar\s+(\w+)\s*=/g, 'sandbox.$1 =')
  .replace(/\bfunction\s+(\w+)\s*\(/g, 'sandbox.$1 = function(');

try {
  new Function('sandbox', `
    var window = undefined;
    var location = { search: '' };
    var document = { querySelectorAll: function() { return []; } };
    ${wrappedSrc}
  `)(sandbox);
} catch (e) {
  console.error('Failed to parse site-data.js:', e.message);
  process.exit(1);
}

const DP_DATA = sandbox.DP_DATA;
if (!DP_DATA) {
  console.error('DP_DATA not found in site-data.js');
  process.exit(1);
}

// ── Resolve a dotted path against DP_DATA ──
function dpResolve(dotPath) {
  const parts = dotPath.split('.');
  let val = DP_DATA;
  for (const part of parts) {
    if (val == null) return undefined;
    val = val[part];
  }
  return val;
}

// ── Format a value for display (mirrors dpFormat in site-data.js) ──
function dpFormat(val) {
  if (val === -1 || val >= 1000000) return 'Unlimited';
  if (typeof val === 'number' && val >= 1000) return val.toLocaleString('en-US');
  return String(val);
}

// ── Process a single HTML file ──
// Regex: data-dp="path">old text<  →  data-dp="path">new text<
// Captures: (1) dp path, (2) current text content, (3) the closing <
const RE = /data-dp="([^"]+)">([^<]*?)(<)/g;

function processFile(filePath, checkOnly) {
  let html = fs.readFileSync(filePath, 'utf8');
  const relPath = path.relative(DOCS_DIR, filePath);
  let changes = 0;
  let stale = 0;

  const stamped = html.replace(RE, (match, dpPath, currentText, closingBracket) => {
    const val = dpResolve(dpPath);
    if (val === undefined) {
      console.warn(`  WARN: ${relPath}: data-dp="${dpPath}" — path not found in DP_DATA`);
      return match;
    }

    const formatted = dpFormat(val);

    if (currentText !== formatted) {
      stale++;
      if (checkOnly) {
        console.log(`  STALE: ${relPath}: data-dp="${dpPath}" — "${currentText.trim()}" → "${formatted}"`);
      } else {
        changes++;
        return `data-dp="${dpPath}">${formatted}${closingBracket}`;
      }
    }
    return match;
  });

  if (!checkOnly && changes > 0) {
    fs.writeFileSync(filePath, stamped, 'utf8');
  }

  return { changes, stale };
}

// ── Main ──
const checkOnly = process.argv.includes('--check');
const htmlFiles = fs.readdirSync(DOCS_DIR)
  .filter(f => f.endsWith('.html'))
  .map(f => path.join(DOCS_DIR, f));

console.log(`${checkOnly ? 'Checking' : 'Stamping'} ${htmlFiles.length} HTML files from site-data.js...`);

let totalChanges = 0;
let totalStale = 0;

for (const file of htmlFiles) {
  const { changes, stale } = processFile(file, checkOnly);
  totalChanges += changes;
  totalStale += stale;
}

if (checkOnly) {
  if (totalStale > 0) {
    console.log(`\n${totalStale} stale value(s) found. Run without --check to fix.`);
    process.exit(1);
  } else {
    console.log('\nAll data-dp values are up to date.');
  }
} else {
  console.log(`\nStamped ${totalChanges} value(s) across ${htmlFiles.length} files.`);
}
