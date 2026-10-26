/**
 * sec-filings.html — read, search and question Anthropic's S-1 from its parse.
 *
 * Data (built by docs/scripts/build-sec-demo-data.py from one docparse run):
 *   data/sec-s1-demo.json   summary: stats, outline (H1-H3), risk factors, tokens
 *   data/sec-s1/blocks.json the whole document as compact blocks:
 *     ["g", page] ["h", level, text] ["p", text] ["l", ordered, items]
 *     ["t", headers, rows]  (cell: string | [text, colSpan, merged]) ["i", src]
 *   data/sec-s1/img/<src>   web copies of the filing's images
 *
 * AI: the visitor's own Gemini key (localStorage 'gemini-api-key', the slot the
 * homepage and Workbench share), or Claude where the page runs as a Claude
 * artifact (window.claude.use('sample')). Only the selected sections are sent.
 */
(function () {
  'use strict';

  var EDGAR = 'https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/';
  var IMG = 'data/sec-s1/img/';
  var GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent';
  // Running as the Claude artifact copy of this page (window.claude is set by the viewer).
  var IN_CLAUDE = !!(window.claude && typeof window.claude.use === 'function');
  var KEY_SLOT = 'gemini-api-key';

  var D, B;            // summary, blocks
  var pages = [];      // printed page of each block
  var ends = [];       // for a heading block: index where its section ends
  var outline = [];    // summary outline entries (+ parent, end, path)
  var selected = [];   // outline indices, in selection order
  var current = -1;    // outline index shown in the reader
  var expanded = {};   // H1 outline index -> its sub-headings are listed

  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return Number(n).toLocaleString('en-US'); };
  var esc = function (s) {
    return String(s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; });
  };
  var words = function (s) { s = String(s).trim(); return s ? s.split(/\s+/).length : 0; };

  Promise.all([
    fetch('data/sec-s1-demo.json').then(function (r) { return r.json(); }),
    fetch('data/sec-s1/blocks.json').then(function (r) { return r.json(); })
  ]).then(function (res) {
    D = res[0]; B = res[1];
    index();
    renderStats();
    renderTree();
    renderTables();
    renderImages();
    renderRisks();
    renderBars();
    initAsk();
    var rf = outline.findIndex(function (o) { return o.l === 1 && o.t === 'Risk Factors'; });
    if (rf >= 0) expanded[rf] = true;
    show(rf >= 0 ? rf : 0, null, false);
  }).catch(function () {
    $('sec-reader-head').innerHTML = '<p class="crumb">The parsed filing could not be loaded. Reload the page to try again.</p>';
  });

  // ---- Indexing --------------------------------------------------------------
  function index() {
    var page = '';
    B.forEach(function (b, i) { if (b[0] === 'g') page = b[1]; pages[i] = page; });
    // Section end of every heading: the next heading at the same or a higher level.
    var open = [];
    B.forEach(function (b, i) {
      if (b[0] !== 'h') return;
      while (open.length && B[open[open.length - 1]][1] >= b[1]) ends[open.pop()] = i;
      open.push(i);
    });
    open.forEach(function (i) { ends[i] = B.length; });

    var stack = [];
    outline = D.outline.map(function (o, k) {
      while (stack.length && D.outline[stack[stack.length - 1]].l >= o.l) stack.pop();
      var e = { t: o.t, l: o.l, p: o.p, i: o.i, w: o.w, sub: o.sub, tables: o.tables,
                parent: stack.length ? stack[stack.length - 1] : -1, end: ends[o.i] || B.length };
      stack.push(k);
      return e;
    });
    outline.forEach(function (o) {
      var path = [], p = o.parent;
      while (p >= 0) { path.unshift(outline[p].t); p = outline[p].parent; }
      o.path = path;
      o.top = o.l === 1 ? -1 : topOf(o);
    });
  }
  function topOf(o) { var p = o.parent, last = -1; while (p >= 0) { last = p; p = outline[p].parent; } return last; }

  // Deepest outline entry containing block i.
  function entryFor(i) {
    var best = -1;
    outline.forEach(function (o, k) { if (o.i <= i && i < o.end && (best < 0 || o.l >= outline[best].l)) best = k; });
    if (best < 0) outline.forEach(function (o, k) { if (o.i <= i) best = k; });
    return best < 0 ? 0 : best;
  }
  function headingBefore(i) {
    for (var j = i; j >= 0; j--) if (B[j][0] === 'h') return B[j][2];
    return '';
  }

  // ---- Rendering blocks --------------------------------------------------------
  function cell(c) { return typeof c === 'string' ? { t: c, s: 1, m: 0 } : { t: c[0], s: c[1] || 1, m: c[2] || 0 }; }
  function tableHtml(b) {
    var head = b[1].map(cell).filter(function (c) { return !c.m; });
    var hasHead = head.some(function (c) { return c.t; });
    var h = hasHead ? '<thead><tr>' + head.map(function (c) {
      return '<th' + (c.s > 1 ? ' colspan="' + c.s + '"' : '') + '>' + esc(c.t) + '</th>';
    }).join('') + '</tr></thead>' : '';
    var body = b[2].map(function (r) {
      return '<tr>' + r.map(cell).filter(function (c) { return !c.m; }).map(function (c) {
        return '<td' + (c.s > 1 ? ' colspan="' + c.s + '"' : '') + '>' + esc(c.t).replace(/\n/g, '<br>') + '</td>';
      }).join('') + '</tr>';
    }).join('');
    return '<div class="sec-table-wrap"><table class="sec-fin">' + h + '<tbody>' + body + '</tbody></table></div>';
  }
  function blockHtml(b, i) {
    var id = ' id="b' + i + '"';
    switch (b[0]) {
      case 'g': return '<div class="pg"' + id + '>' + (b[1] ? 'page ' + esc(b[1]) : 'unnumbered page') + '</div>';
      case 'h': return '<div class="h h' + Math.min(b[1], 5) + '"' + id + '>' + esc(b[2]) + '</div>';
      case 'l': return '<' + (b[1] ? 'ol' : 'ul') + id + '>' + b[2].map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</' + (b[1] ? 'ol' : 'ul') + '>';
      case 't': return '<div' + id + '>' + tableHtml(b) + '</div>';
      case 'i': return '<figure' + id + '><img loading="lazy" src="' + IMG + esc(b[1]) + '" alt="Image from the filing: ' + esc(b[1]) + '" data-img="' + i + '"><figcaption>' + esc(b[1]) + '</figcaption></figure>';
      default: return '<p' + id + '>' + esc(b[1]) + '</p>';
    }
  }
  function rangeHtml(a, z, skipFirstHeading) {
    var out = [];
    for (var i = a; i < z; i++) { if (i === a && skipFirstHeading && B[i][0] === 'h') continue; out.push(blockHtml(B[i], i)); }
    return '<div class="sec-doc">' + out.join('') + '</div>';
  }
  function pageChip(p, asButton) {
    if (!p) return '<span class="sec-chip">unnumbered page</span>';
    return asButton ? '<button type="button" class="sec-chip sec-chip--page" data-page="' + esc(p) + '">p.&nbsp;' + esc(p) + '</button>'
                    : '<span class="sec-chip sec-chip--page">p.&nbsp;' + esc(p) + '</span>';
  }

  // ---- Stats -----------------------------------------------------------------
  function renderStats() {
    var k = D.parse.kinds;
    $('sec-stats').innerHTML = [
      [(D.source.bytes / 1e6).toFixed(1) + '&nbsp;MB', 'of filing HTML, parsed in seconds'],
      [fmt(D.parse.blocks), 'typed blocks in reading order'],
      [fmt(k.heading || 0), 'headings &middot; ' + fmt(k.table || 0) + ' tables &middot; ' + fmt(k.image || 0) + ' images'],
      [fmt(D.parse.pages), 'pages, so every passage cites its page']
    ].map(function (s) { return '<div class="sec-stat"><b>' + s[0] + '</b><span>' + s[1] + '</span></div>'; }).join('');
  }

  // ---- Outline + reader --------------------------------------------------------
  function renderTree() {
    var q = $('sec-filter').value.trim().toLowerCase();
    var html = '';
    outline.forEach(function (o, k) {
      var vis = q ? o.t.toLowerCase().indexOf(q) >= 0 : (o.l === 1 || expanded[o.top]);
      if (!vis) return;
      var kids = o.l === 1 && o.sub > 0 && !q;
      html += '<li class="l' + o.l + '">' +
        '<input type="checkbox" data-sel="' + k + '" aria-label="Select ' + esc(o.t) + '"' + (selected.indexOf(k) >= 0 ? ' checked' : '') + '>' +
        '<button type="button" data-i="' + k + '"' + (current === k ? ' aria-current="true"' : '') + (kids ? ' aria-expanded="' + !!expanded[k] + '"' : '') + '>' +
        (o.l === 1 ? '<span class="toggle">' + (kids ? (expanded[k] ? '▾' : '▸') : '') + '</span>' : '') +
        '<span class="t">' + esc(o.t) + '</span><span class="pg">' + (o.p ? 'p.' + esc(o.p) : '') + '</span></button></li>';
    });
    $('sec-tree').innerHTML = html || '<li style="padding:10px 14px;font-size:13px;color:var(--text-muted)">No heading matches.</li>';
  }
  $('sec-tree').addEventListener('click', function (e) {
    var cb = e.target.closest('input[data-sel]');
    if (cb) { toggleSelect(+cb.getAttribute('data-sel'), cb.checked); return; }
    var b = e.target.closest('button[data-i]');
    if (!b) return;
    var k = +b.getAttribute('data-i');
    if (outline[k].l === 1 && outline[k].sub > 0 && !$('sec-filter').value.trim()) expanded[k] = !expanded[k];
    show(k, null, false);
  });
  $('sec-filter').addEventListener('input', renderTree);

  function show(k, focusBlock, scrollPage) {
    current = k;
    var o = outline[k];
    if (o.top >= 0) expanded[o.top] = true;
    var tokens = Math.round(o.w * 1.3);
    var isSel = selected.indexOf(k) >= 0;
    $('sec-reader-head').innerHTML =
      (o.path.length ? '<div class="crumb">' + o.path.map(esc).join(' › ') + '</div>' : '') +
      '<h3>' + esc(o.t) + '</h3><div class="sec-meta">' + pageChip(o.p) +
      '<span class="sec-chip">' + fmt(o.w) + ' words</span>' +
      (o.tables ? '<span class="sec-chip">' + fmt(o.tables) + ' table' + (o.tables > 1 ? 's' : '') + '</span>' : '') +
      '<span class="sec-chip">~' + fmt(tokens) + ' tokens</span>' +
      '<button type="button" class="sec-btn" id="reader-sel" aria-pressed="' + isSel + '">' + (isSel ? 'Selected' : 'Select for AI') + '</button></div>';
    var body = $('sec-body');
    body.innerHTML = rangeHtml(o.i, o.end, true);
    renderTree();
    if (focusBlock != null) {
      var el = $('b' + focusBlock);
      if (el) { body.scrollTop = el.offsetTop - body.offsetTop - 8; el.classList.add('flash'); }
    } else body.scrollTop = 0;
    if (scrollPage) $('read').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  $('sec-reader-head').addEventListener('click', function (e) {
    if (e.target.id === 'reader-sel') toggleSelect(current, selected.indexOf(current) < 0);
  });
  $('sec-body').addEventListener('click', function (e) {
    var img = e.target.closest('img[data-img]');
    if (img) openImage(+img.getAttribute('data-img'));
  });

  function openBlock(i) { show(entryFor(i), i, true); }
  function openPage(p) {
    for (var i = 0; i < B.length; i++) if (B[i][0] === 'g' && B[i][1] === p) return openBlock(i);
  }
  // Page chips anywhere on the page jump to that page in the reader.
  document.addEventListener('click', function (e) {
    var c = e.target.closest('[data-page]');
    if (c) { e.preventDefault(); if ($('sec-lightbox').open) $('sec-lightbox').close(); openPage(c.getAttribute('data-page')); }
  });

  // ---- Selection ------------------------------------------------------------------
  function toggleSelect(k, on) {
    var at = selected.indexOf(k);
    if (on && at < 0) selected.push(k);
    if (!on && at >= 0) selected.splice(at, 1);
    renderSelection();
    renderTree();
    if (k === current) show(current, null, false);
  }
  function renderSelection() {
    $('sec-sel').innerHTML = selected.length ? selected.map(function (k) {
      var o = outline[k];
      return '<span class="chip">' + esc(o.t) + (o.p ? ' <span style="color:var(--text-muted)">p.' + esc(o.p) + '</span>' : '') +
        '<button type="button" data-unsel="' + k + '" aria-label="Remove ' + esc(o.t) + '">×</button></span>';
    }).join('') : '<span class="note">Nothing selected yet. Tick sections in the outline or pick an example.</span>';
    var w = selected.reduce(function (s, k) { return s + outline[k].w; }, 0);
    $('sec-cost').textContent = selected.length ? 'About ' + fmt(Math.round(w * 1.3)) + ' tokens of the filing will be sent.' : '';
  }
  $('sec-sel').addEventListener('click', function (e) {
    var b = e.target.closest('[data-unsel]');
    if (b) toggleSelect(+b.getAttribute('data-unsel'), false);
  });

  // ---- Tables -----------------------------------------------------------------------
  var tables = [];
  function renderTables() {
    B.forEach(function (b, i) {
      if (b[0] !== 't') return;
      var all = [b[1]].concat(b[2]);
      var text = all.map(function (r) { return r.map(function (c) { return cell(c).t; }).join(' '); }).join(' ');
      var first = b[2].map(function (r) { return cell(r[0] || '').t; }).filter(Boolean).slice(0, 3).join(' · ');
      var cols = Math.max.apply(null, all.map(function (r) { return r.reduce(function (s, c) { return s + (cell(c).m ? 0 : cell(c).s); }, 0); }));
      var hasHead = b[1].some(function (c) { return cell(c).t; });
      tables.push({ i: i, h: headingBefore(i), p: pages[i], rows: b[2].length + (hasHead ? 1 : 0), cols: cols, first: first, hay: (headingBefore(i) + ' ' + text).toLowerCase() });
    });
    drawTables();
  }
  function drawTables() {
    var q = $('tbl-filter').value.trim().toLowerCase();
    var list = tables.filter(function (t) { return !q || t.hay.indexOf(q) >= 0; });
    $('tbl-count').textContent = fmt(list.length) + ' of ' + fmt(tables.length) + ' tables';
    $('tbl-list').innerHTML = list.map(function (t) {
      var open = !q && t.h === 'Consolidated Statements of Operations Data' && t === tables.find(function (x) { return x.h === t.h; });
      return '<details data-t="' + t.i + '"' + (open ? ' open' : '') + '><summary><span class="t">' + esc(t.h || 'Untitled') +
        '<small>' + esc(t.first) + '</small></span><span class="sec-chip">' + t.rows + ' × ' + t.cols + '</span>' + pageChip(t.p) + '</summary>' +
        '<div class="inner">' + (open ? tableInner(t.i) : '') + '</div></details>';
    }).join('') || '<p style="padding:12px 14px;font-size:13px">No table matches.</p>';
  }
  function tableInner(i) {
    return '<div class="acts"><button type="button" class="sec-btn" data-goto="' + i + '">Show in reader</button>' +
      '<button type="button" class="sec-btn" data-csv="' + i + '">Copy as CSV</button></div>' + tableHtml(B[i]);
  }
  $('tbl-filter').addEventListener('input', drawTables);
  $('tbl-list').addEventListener('toggle', function (e) {
    var d = e.target;
    if (d.open && !d.querySelector('.sec-table-wrap')) d.querySelector('.inner').innerHTML = tableInner(+d.getAttribute('data-t'));
  }, true);
  $('tbl-list').addEventListener('click', function (e) {
    var g = e.target.closest('[data-goto]');
    if (g) return openBlock(+g.getAttribute('data-goto'));
    var c = e.target.closest('[data-csv]');
    if (c) copyCsv(+c.getAttribute('data-csv'), c);
  });
  function copyCsv(i, btn) {
    var b = B[i];
    var rows = [b[1]].concat(b[2]).map(function (r) {
      return r.map(cell).filter(function (c) { return !c.m; }).map(function (c) {
        var t = c.t.replace(/\n/g, ' ');
        return /[",]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
      }).join(',');
    }).join('\n');
    var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = 'Copy as CSV'; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(rows).then(done, function () { showCsv(btn, rows); });
    } else showCsv(btn, rows);
  }
  function showCsv(btn, rows) {
    var ta = document.createElement('textarea');
    ta.value = rows; ta.rows = 6; ta.style.cssText = 'width:100%;font-family:var(--font-mono);font-size:12px;margin-bottom:10px';
    btn.closest('.inner').insertBefore(ta, btn.closest('.acts').nextSibling);
    ta.select();
  }

  // ---- Images -----------------------------------------------------------------------
  function imgKind(src) {
    if (/x25pg\d/.test(src)) return 'Founders’ letter';
    if (/case ?stud/i.test(src)) return 'Case study';
    return '';
  }
  function renderImages() {
    var html = '';
    B.forEach(function (b, i) {
      if (b[0] !== 'i') return;
      var o = outline[entryFor(i)];
      var kind = imgKind(b[1]);
      html += '<figure><button type="button" class="thumb" data-img="' + i + '" aria-label="Open ' + esc(b[1]) + '">' +
        '<img loading="lazy" src="' + IMG + esc(b[1]) + '" alt=""></button><figcaption>' +
        (kind ? '<b>' + kind + '</b>' : '') + '<span>' + esc(o ? o.t : '') + '</span>' + pageChip(pages[i]) + '</figcaption></figure>';
    });
    $('img-grid').innerHTML = html;
  }
  $('img-grid').addEventListener('click', function (e) {
    var b = e.target.closest('[data-img]');
    if (b) openImage(+b.getAttribute('data-img'));
  });

  var lbIndex = -1;
  function openImage(i) {
    lbIndex = i;
    var src = B[i][1], o = outline[entryFor(i)];
    $('lb-img').src = IMG + src;
    $('lb-img').alt = 'Image from the filing: ' + src;
    $('lb-title').textContent = imgKind(src) || (o ? o.t : src);
    $('lb-meta').innerHTML = pageChip(pages[i]) + '<span class="sec-chip">' + esc(src) + '</span>';
    $('lb-orig').href = EDGAR + encodeURIComponent(src);
    $('lb-answer').hidden = true; $('lb-answer').innerHTML = '';
    $('lb-transcribe').disabled = !provider();
    $('lb-transcribe').title = provider() ? '' : 'Add a Gemini API key in Compare & Ask AI first';
    var dlg = $('sec-lightbox');
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
  }
  $('lb-close').addEventListener('click', function () { $('sec-lightbox').close(); });
  $('sec-lightbox').addEventListener('click', function (e) { if (e.target === this) this.close(); });
  $('lb-goto').addEventListener('click', function () { $('sec-lightbox').close(); openBlock(lbIndex); });
  $('lb-transcribe').addEventListener('click', function () {
    var src = B[lbIndex][1];
    var out = $('lb-answer');
    out.hidden = false;
    fetch(IMG + src).then(function (r) { return r.blob(); }).then(function (blob) {
      runAI(TRANSCRIBE_PROMPT, out, blob);
    }).catch(function () { out.innerHTML = '<p class="err">The image could not be loaded.</p>'; });
  });
  var TRANSCRIBE_PROMPT =
    'This is one page image from Anthropic, PBC\'s Form S-1 registration statement. Transcribe all of its text in reading order. ' +
    'If the page has two columns, give the whole left column before the right one. Use Markdown: "#" for headings, plain paragraphs, ' +
    'footnotes at the end. Describe any photo or chart in one line in square brackets. Output only the transcription.';

  // ---- Risk factors, token bars -----------------------------------------------------------
  function renderRisks() {
    $('sec-risk').innerHTML =
      '<p style="font-size:13px;color:var(--text-muted);margin:0 0 10px"><strong>' + fmt(D.parse.riskFactors) + '</strong> risk factors in ' + D.riskGroups.length + ' categories.</p>' +
      D.riskGroups.map(function (g) {
        return '<details><summary><span class="t">' + esc(g.t) + '</span><span class="sec-chip">' + g.items.length + '</span>' + pageChip(g.p, true) + '</summary><ol>' +
          g.items.map(function (r) { return '<li>' + esc(r.t) + pageChip(r.p, true) + '</li>'; }).join('') + '</ol></details>';
      }).join('');
  }
  function renderBars() {
    var t = D.tokens;
    $('sec-bars').innerHTML = [['Whole filing', t.full], ['Risk Factors section', t.riskFactors], ['Outline with page numbers', t.outline]].map(function (r) {
      return '<div class="sec-bar"><span class="lbl">' + r[0] + '</span><span class="track"><span class="fill" style="width:' +
        Math.max(0.4, 100 * r[1] / t.full).toFixed(2) + '%"></span></span><span class="n">~' + fmt(r[1]) + '</span></div>';
    }).join('');
  }

  // ---- Compare & Ask --------------------------------------------------------------------
  var PRESETS = [
    { label: 'Summarise the main risks', titles: ['Risk Factors Summary'],
      q: 'Summarise the main risks in six bullets. Cite the page for each.' },
    { label: 'Compare two reporting periods',
      titles: ['Comparison of the Six Months Ended June 30, 2025 and 2026', 'Comparison of the Years Ended December 31, 2024 and 2025'],
      q: 'Compare revenue growth and the main drivers of operating expenses in these two periods. Give a short table, then two or three sentences. Cite pages.' },
    { label: 'Explain the governance structure', titles: ['Long-Term Benefit Trust', 'Founder Voting Structure'],
      q: 'Explain in plain language how the Long-Term Benefit Trust and the founder voting structure work together, and what they mean for a holder of Class A common stock. Cite pages.' }
  ];
  var ai = { claude: null, ctl: null };

  function getKey() { try { return (localStorage.getItem(KEY_SLOT) || '').trim(); } catch (e) { return ''; } }
  function provider() { return ai.claude ? 'claude' : (getKey() ? 'gemini' : null); }

  function initAsk() {
    $('sec-presets').innerHTML = PRESETS.map(function (p, n) {
      var ok = p.titles.every(function (t) { return outline.some(function (o) { return o.t === t; }); });
      return ok ? '<button type="button" class="sec-btn" data-preset="' + n + '">' + esc(p.label) + '</button>' : '';
    }).join('');
    $('sec-presets').addEventListener('click', function (e) {
      var b = e.target.closest('[data-preset]');
      if (!b) return;
      var p = PRESETS[+b.getAttribute('data-preset')];
      // A title can appear in the summary and again in full; take the fuller section.
      selected = p.titles.map(function (t) {
        var best = -1;
        outline.forEach(function (o, k) { if (o.t === t && (best < 0 || o.w > outline[best].w)) best = k; });
        return best;
      });
      $('sec-q').value = p.q;
      renderSelection(); renderTree(); renderCompare();
    });
    try { $('sec-key').value = getKey(); } catch (e) { /* storage unavailable */ }
    $('sec-key-save').addEventListener('click', function () {
      try { localStorage.setItem(KEY_SLOT, $('sec-key').value.trim()); } catch (e) { /* storage unavailable */ }
      aiStatus();
    });
    $('sec-key-clear').addEventListener('click', function () {
      try { localStorage.removeItem(KEY_SLOT); } catch (e) { /* storage unavailable */ }
      $('sec-key').value = ''; aiStatus();
    });
    $('sec-compare-btn').addEventListener('click', renderCompare);
    $('sec-ask-btn').addEventListener('click', ask);
    $('sec-stop-btn').addEventListener('click', function () { if (ai.ctl) ai.ctl.abort(); });
    renderSelection();
    aiStatus();
    // Inside a Claude artifact viewer the page can ask Claude instead.
    if (IN_CLAUDE) {
      window.claude.use('sample').then(function (s) { if (s) { ai.claude = s; aiStatus(); } }).catch(function () {});
    }
  }

  function aiStatus() {
    var p = provider();
    $('sec-key-box').querySelector('.keyrow').hidden = p === 'claude';
    $('sec-claude-link').hidden = IN_CLAUDE;
    $('sec-ai-status').textContent =
      p === 'claude' ? 'Answers come from Claude in this preview. Only the selected sections are sent.'
      : p === 'gemini' ? 'Using your Gemini key, saved in this browser and shared with the Workbench. Only the selected sections are sent to Google.'
      : 'Add a Gemini API key to ask questions. It is saved in this browser only, and the Workbench uses the same key.';
    $('sec-ask-btn').disabled = !p;
  }

  function renderCompare() {
    $('sec-compare').innerHTML = selected.map(function (k) {
      var o = outline[k];
      var z = Math.min(o.end, o.i + 400);
      return '<div class="col"><h4>' + esc(o.t) + '<small>' + (o.path.length ? esc(o.path.join(' › ')) + ' · ' : '') +
        (o.p ? 'p. ' + esc(o.p) + ' · ' : '') + fmt(o.w) + ' words</small></h4>' + rangeHtml(o.i, z, true) + '</div>';
    }).join('');
    if (selected.length) $('sec-compare').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Selected sections as plain text with page markers the model can cite.
  function sectionText(o, budget) {
    var lines = ['## ' + (o.path.length ? o.path.join(' > ') + ' > ' : '') + o.t];
    var size = 0, cut = false;
    for (var i = o.i + 1; i < o.end; i++) {
      var b = B[i], s;
      if (b[0] === 'g') s = '[page ' + (b[1] || 'unnumbered') + ']';
      else if (b[0] === 'h') s = '#'.repeat(Math.min(b[1], 5) + 1) + ' ' + b[2];
      else if (b[0] === 'l') s = b[2].map(function (x) { return '- ' + x; }).join('\n');
      else if (b[0] === 't') s = [b[1]].concat(b[2]).map(function (r) { return r.map(cell).filter(function (c) { return !c.m; }).map(function (c) { return c.t.replace(/\n/g, ' '); }).join(' | '); }).join('\n');
      else if (b[0] === 'i') s = '[image: ' + b[1] + ']';
      else s = b[1];
      if (size + s.length > budget) { cut = true; break; }
      lines.push(s); size += s.length + 1;
    }
    if (cut) lines.push('[… the rest of this section was left out to fit]');
    return '[page ' + (o.p || 'unnumbered') + ']\n' + lines.join('\n');
  }

  function ask() {
    var q = $('sec-q').value.trim();
    var out = $('sec-answer');
    out.hidden = false;
    if (!selected.length) { out.innerHTML = '<p class="err">Select at least one section first: tick it in the outline or pick an example.</p>'; return; }
    if (!q) { out.innerHTML = '<p class="err">Type a question first.</p>'; $('sec-q').focus(); return; }
    // Claude takes up to 256 KiB per call; Gemini 2.5 Flash reads far more.
    var total = provider() === 'claude' ? 200000 : 1500000;
    var per = Math.floor(total / selected.length);
    var prompt =
      'You are reading excerpts from the Form S-1 registration statement that Anthropic, PBC filed with the SEC on October 26, 2026. ' +
      'Answer the question using only these excerpts. Lines like [page 27] mark where each printed page starts; cite the page for each claim as (p. 27). ' +
      'If the excerpts do not answer the question, say so. Use short paragraphs, bullets or a small Markdown table.\n\n' +
      'Question: ' + q + '\n\nExcerpts:\n\n' + selected.map(function (k) { return sectionText(outline[k], per); }).join('\n\n');
    runAI(prompt, out, null);
  }

  function runAI(prompt, out, imageBlob) {
    var p = provider();
    if (!p) { out.innerHTML = '<p class="err">Add a Gemini API key in Compare &amp; Ask AI first.</p>'; return; }
    if (ai.ctl) ai.ctl.abort();
    var ctl = ai.ctl = new AbortController();
    out.innerHTML = '<p>Thinking…</p>';
    $('sec-stop-btn').hidden = false;
    var finish = function () { if (ai.ctl === ctl) { ai.ctl = null; $('sec-stop-btn').hidden = true; } };

    if (p === 'claude') {
      var opts = { signal: ctl.signal, onText: function (u) { out.innerHTML = md(u.text); } };
      if (imageBlob) opts.images = [imageBlob];
      ai.claude(prompt, opts).then(function (r) {
        out.innerHTML = md(r.text) + (r.truncated ? '<p class="note">The answer was cut short. Ask about fewer sections at a time.</p>' : '');
      }).catch(function (e) {
        if (e && e.code === 'cancelled') { out.innerHTML = e.text ? md(e.text) : ''; return; }
        var msg = {
          not_granted: 'Claude was not allowed for this page.',
          sampling_disabled: 'Claude is not available for this account.',
          rate_limited: 'Too many requests just now. Try again in a little while.',
          prompt_too_large: 'That is too much text for one question. Select fewer or smaller sections.',
          images_unavailable: 'This view cannot send images to Claude.'
        }[e && e.code] || 'Claude could not answer. Try again.';
        out.innerHTML = (e && e.text ? md(e.text) : '') + '<p class="err">' + msg + '</p>';
      }).then(finish);
      return;
    }

    var parts = [{ text: prompt }];
    var go = function () {
      return fetch(GEMINI_URL + '?key=' + encodeURIComponent(getKey()), {
        method: 'POST', signal: ctl.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contents: [{ parts: parts }], generationConfig: { temperature: 0.2, maxOutputTokens: 8192 } })
      }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).then(function (res) {
        if (!res.ok || res.j.error) throw new Error(res.j.error ? res.j.error.message : 'Gemini returned an error.');
        var c = res.j.candidates && res.j.candidates[0];
        var text = c && c.content && c.content.parts ? c.content.parts.map(function (x) { return x.text || ''; }).join('') : '';
        if (!text) throw new Error('Gemini returned no answer' + (c && c.finishReason ? ' (' + c.finishReason + ')' : '') + '.');
        out.innerHTML = md(text);
      });
    };
    var run = imageBlob ? blobToBase64(imageBlob).then(function (b64) {
      parts = [{ inlineData: { mimeType: imageBlob.type || 'image/jpeg', data: b64 } }, { text: prompt }];
      return go();
    }) : go();
    run.catch(function (err) {
      if (err && err.name === 'AbortError') { out.innerHTML = ''; return; }
      out.innerHTML = '<p class="err">' + esc(err && err.message ? err.message : 'The request failed.') + ' Check the key and try again.</p>';
    }).then(finish);
  }

  function blobToBase64(blob) {
    return new Promise(function (res, rej) {
      var r = new FileReader();
      r.onload = function () { res(String(r.result).split(',')[1]); };
      r.onerror = rej;
      r.readAsDataURL(blob);
    });
  }

  // ---- Minimal Markdown for answers (escaped first; page citations become links) -------------
  function inline(s) {
    return s
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
      .replace(/\b(pp?\.|[Pp]ages?)\s?((?:F-|II-)?\d{1,3}|[ivx]{1,5})\b/g, function (m, pre, n) {
        var known = pages.indexOf(n) >= 0;
        return known ? '<button type="button" class="sec-chip sec-chip--page" data-page="' + n + '">' + pre + ' ' + n + '</button>' : m;
      });
  }
  function md(text) {
    var lines = esc(text).split('\n'), html = '', list = null, table = [];
    var flushList = function () { if (list) { html += '</' + list + '>'; list = null; } };
    var flushTable = function () {
      if (!table.length) return;
      var rows = table.filter(function (r) { return !/^\s*\|?\s*:?-{2,}/.test(r); }).map(function (r) {
        return r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(function (c) { return inline(c.trim()); });
      });
      html += '<div class="sec-table-wrap"><table class="sec-fin"><thead><tr>' + rows[0].map(function (c) { return '<th>' + c + '</th>'; }).join('') +
        '</tr></thead><tbody>' + rows.slice(1).map(function (r) { return '<tr>' + r.map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
      table = [];
    };
    lines.forEach(function (l) {
      if (/^\s*\|.*\|\s*$/.test(l)) { flushList(); table.push(l); return; }
      flushTable();
      var m;
      if ((m = l.match(/^\s*#{1,6}\s+(.*)/))) { flushList(); html += '<h4>' + inline(m[1]) + '</h4>'; }
      else if ((m = l.match(/^\s*[-*•]\s+(.*)/))) { if (list !== 'ul') { flushList(); html += '<ul>'; list = 'ul'; } html += '<li>' + inline(m[1]) + '</li>'; }
      else if ((m = l.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== 'ol') { flushList(); html += '<ol>'; list = 'ol'; } html += '<li>' + inline(m[1]) + '</li>'; }
      else if (!l.trim()) { flushList(); }
      else { flushList(); html += '<p>' + inline(l) + '</p>'; }
    });
    flushList(); flushTable();
    return html;
  }

  // ---- Tabs (catalogue, run-it-yourself) --------------------------------------------------------
  ['cat-tabs', 'sec-tabs'].forEach(function (id) {
    var tabs = document.querySelectorAll('#' + id + ' [role=tab]');
    tabs.forEach(function (t) {
      t.addEventListener('click', function () {
        tabs.forEach(function (o) {
          var on = o === t;
          o.setAttribute('aria-selected', on);
          $(o.getAttribute('aria-controls')).hidden = !on;
        });
      });
    });
  });
})();
