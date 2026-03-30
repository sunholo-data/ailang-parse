/**
 * AILANG Parse WASM Demo — Full in-browser document parsing
 *
 * Architecture:
 * - WASM runtime (ailang.wasm) loaded from local docs/wasm/
 * - AILANG modules (docparse/*.ail) loaded from local docs/ailang/ directory
 * - JSZip handles ZIP extraction in JS
 * - Mammoth.js handles DOCX preview rendering
 * - AILANG handles XML → Block ADT → JSON conversion
 * - AI calls (PDF/image) use Gemini via user's own API key in localStorage
 *
 * Sensible limits:
 * - Max file size: 20MB
 * - Max ZIP entries processed: 100
 * - Max XML size per entry: 5MB
 * - Max slides/sheets: 50
 * - Timeout per parse: 30 seconds
 */

(function () {
  'use strict';

  // ── Configuration ──
  var WASM_BINARY_URL = 'wasm/ailang.wasm';
  var MODULE_BASE = 'ailang/';
  var MAX_FILE_SIZE = 20 * 1024 * 1024;
  var MAX_XML_SIZE = 5 * 1024 * 1024;
  var MAX_SLIDES = 50;
  var MAX_SHEETS = 50;

  var DOCPARSE_MODULE = 'docparse/services/docparse_browser';

  var MODULES_TO_LOAD = [
    { name: 'docparse/types/document',           path: 'docparse/types/document.ail' },
    { name: 'docparse/services/format_router',    path: 'docparse/services/format_router.ail' },
    { name: 'docparse/services/zip_extract',      path: 'docparse/services/zip_extract.ail' },
    { name: 'docparse/services/docx_parser',      path: 'docparse/services/docx_parser.ail' },
    { name: 'docparse/services/pptx_parser',      path: 'docparse/services/pptx_parser.ail' },
    { name: 'docparse/services/xlsx_parser',      path: 'docparse/services/xlsx_parser.ail' },
    { name: 'docparse/services/output_formatter', path: 'docparse/services/output_formatter.ail' },
    // A2UI: vendored package + formatter (dependencies before dependents)
    { name: 'pkg/sunholo/a2ui/components',        path: 'pkg/sunholo/a2ui/components.ail' },
    { name: 'docparse/services/a2ui_formatter',   path: 'docparse/services/a2ui_formatter.ail' },
    { name: 'docparse/services/docparse_browser', path: 'docparse/services/docparse_browser.ail' },
  ];

  var EXTRA_STDLIBS = ['std/xml', 'std/list', 'std/io'];

  // ── State ──
  var engine = null;
  var wasmReady = false;
  var wasmLoading = false;
  var wasmError = null;
  var lastFileBuffer = null;
  var lastFileExt = null;
  var lastFileContent = null; // for text files

  // ── DOM refs ──
  var statusEl = document.getElementById('wasm-status');
  var dotEl = document.getElementById('status-dot');
  var fileInfoEl = document.getElementById('file-info');
  var dropzone = document.getElementById('dropzone');
  var fileInput = document.getElementById('file-input');
  var infoBar = document.getElementById('info-bar');
  var outputTabs = document.getElementById('output-tabs');
  var outputEmpty = document.getElementById('output-empty');
  var panelBlocks = document.getElementById('panel-blocks');
  var panelPreview = document.getElementById('panel-preview');
  var panelJson = document.getElementById('panel-json');
  var panelMarkdown = document.getElementById('panel-markdown');
  var panelA2UI = document.getElementById('panel-a2ui');
  var aiUpsell = document.getElementById('ai-upsell');

  // ── Loading spinner (CSS-only) ──
  var spinnerCSS = document.createElement('style');
  spinnerCSS.textContent = '.dp-spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--dp-blue-border);border-top-color:var(--dp-blue);border-radius:50%;animation:dp-spin .6s linear infinite;vertical-align:-2px;margin-right:6px}@keyframes dp-spin{to{transform:rotate(360deg)}}';
  document.head.appendChild(spinnerCSS);

  // ── Status dot ──
  function setDotState(state) {
    if (!dotEl) return;
    dotEl.className = 'dp-status-dot';
    if (state) dotEl.classList.add(state);
  }

  // ── Status display ──
  function setStatus(msg, isError, loading) {
    if (statusEl) {
      if (loading) {
        statusEl.innerHTML = '<span class="dp-spinner"></span>' + msg;
      } else {
        statusEl.textContent = msg;
      }
      statusEl.style.color = isError ? '#ef4444' : 'var(--text-secondary)';
    }
    if (isError) {
      setDotState('error');
    } else if (loading) {
      setDotState('processing');
    }
  }

  // ── Pipeline log ──
  function clearPipeline() {
    var log = document.getElementById('pipeline-log');
    if (log) log.innerHTML = '';
  }

  function pipelineLog(stage, detail, stageClass) {
    var panel = document.getElementById('pipeline-panel');
    if (panel) panel.style.display = 'block';
    var log = document.getElementById('pipeline-log');
    if (!log) return;
    var line = document.createElement('div');
    line.className = 'dp-pipeline-line';
    var cls = stageClass ? ' ' + stageClass : '';
    line.innerHTML = '<span class="dp-pipeline-stage' + cls + '">' + escHtml(stage) + '</span> ' + escHtml(detail);
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  // ── WASM initialization ──
  async function initWasm() {
    if (wasmReady || wasmLoading) return;
    wasmLoading = true;
    setDotState('loading');
    setStatus('Loading WASM runtime...', false, true);

    try {
      if (!('WebAssembly' in window)) {
        throw new Error('WebAssembly not supported in this browser');
      }

      await loadScript('wasm/wasm_exec.js');
      await loadScript('wasm/ailang-repl.js');

      if (typeof AilangREPL === 'undefined') {
        throw new Error('AilangREPL not found after loading scripts');
      }

      setStatus('Initializing AILANG...', false, true);
      var repl = new AilangREPL();
      setStatus('Loading WASM binary...', false, true);
      await repl.init(WASM_BINARY_URL);

      // Import stdlib
      var stdlibs = ['std/json', 'std/option', 'std/result', 'std/string', 'std/math', 'std/ai'];
      for (var i = 0; i < stdlibs.length; i++) {
        repl.importModule(stdlibs[i]);
      }
      for (var j = 0; j < EXTRA_STDLIBS.length; j++) {
        repl.importModule(EXTRA_STDLIBS[j]);
      }

      // Load AILANG Parse modules
      for (var k = 0; k < MODULES_TO_LOAD.length; k++) {
        var mod = MODULES_TO_LOAD[k];
        setStatus('Loading ' + mod.name.split('/').pop() + '... (' + (k + 1) + '/' + MODULES_TO_LOAD.length + ')');

        var resp = await fetch(MODULE_BASE + mod.path + '?v=' + Date.now());
        if (!resp.ok) throw new Error('Failed to fetch ' + mod.path);
        var code = await resp.text();

        var result = repl.loadModule(mod.name, code);
        if (!result.success) throw new Error('Module ' + mod.name + ' failed: ' + result.error);
      }

      // Set up AI handler if user has API key
      var apiKey = localStorage.getItem('gemini-api-key');
      if (apiKey && typeof repl.setAIHandler === 'function') {
        repl.setAIHandler(createGeminiHandler(apiKey));
        if (typeof repl.grantCapability === 'function') repl.grantCapability('AI');
      }

      engine = {
        repl: repl,
        call: function (func) {
          var args = Array.prototype.slice.call(arguments, 1);
          var r = repl.call(DOCPARSE_MODULE, func, ...args);
          if (!r.success) return { success: false, error: r.error };
          return { success: true, result: parseWasmResult(r.result) };
        },
        callAsync: async function (func) {
          var args = Array.prototype.slice.call(arguments, 1);
          var r;
          if (typeof repl.callAsync === 'function') {
            r = await repl.callAsync(DOCPARSE_MODULE, func, ...args);
          } else {
            r = repl.call(DOCPARSE_MODULE, func, ...args);
          }
          if (!r.success) return { success: false, error: r.error };
          return { success: true, result: parseWasmResult(r.result) };
        }
      };

      wasmReady = true;
      wasmLoading = false;
      setDotState('ready');
      setStatus('Ready \u2014 drop a file to parse');
      // Enable file input
      if (fileInput) fileInput.disabled = false;
    } catch (err) {
      wasmError = err.message;
      wasmLoading = false;
      setStatus('WASM load failed: ' + err.message, true);
      console.error('WASM init error:', err);
    }
  }

  // ── Gemini AI handler ──
  function createGeminiHandler(apiKey) {
    var GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent';
    return async function (input) {
      try {
        var parsed = JSON.parse(input);
        var parts = [];

        if (parsed.mode === 'multimodal' && parsed.data) {
          parts.push({ inlineData: { mimeType: parsed.mimeType, data: parsed.data } });
          parts.push({ text: parsed.prompt });
        } else {
          parts.push({ text: input });
        }

        var resp = await fetch(GEMINI_URL + '?key=' + apiKey, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contents: [{ parts: parts }],
            generationConfig: { temperature: 0.2, maxOutputTokens: 32768, responseMimeType: 'application/json' }
          })
        });

        var data = await resp.json();
        return data.candidates?.[0]?.content?.parts?.[0]?.text || '[]';
      } catch (e) {
        console.error('Gemini handler error:', e);
        return '[]';
      }
    };
  }

  // ── Parse WASM result string ──
  function parseWasmResult(s) {
    if (!s) return s;
    var m = s.match(/^(.+) :: \w+$/s);
    if (m) s = m[1];
    if (s.startsWith('"') && s.endsWith('"')) {
      try { s = JSON.parse(s); } catch (e) { s = s.slice(1, -1); }
    }
    return s;
  }

  // ── Load external script ──
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      script.src = src;
      script.onload = resolve;
      script.onerror = function () { reject(new Error('Failed to load ' + src)); };
      document.head.appendChild(script);
    });
  }

  // ── File handling ──
  window.handleDocParseFile = async function (file) {
    // Validate size
    if (file.size > MAX_FILE_SIZE) {
      showError('File too large for browser parsing (' + (file.size / 1024 / 1024).toFixed(1) + 'MB). Use the <a href="api.html" style="color:var(--dp-blue)">API</a> for files up to 200MB.');
      return;
    }

    // Reset state
    clearPipeline();
    lastFileBuffer = null;
    lastFileExt = null;
    lastFileContent = null;
    setDotState('processing');

    var ext = file.name.split('.').pop().toLowerCase();
    var sizeKB = (file.size / 1024).toFixed(1);
    lastFileExt = ext;

    // Capture buffer upfront so preview works for all file types
    var textFormats = ['html', 'htm', 'md', 'csv', 'tsv'];
    if (textFormats.indexOf(ext) !== -1) {
      lastFileContent = await file.text();
    } else {
      lastFileBuffer = await file.arrayBuffer();
    }

    // Show info
    showInfoBar(ext, sizeKB);
    if (fileInfoEl) fileInfoEl.textContent = file.name + ' \u00B7 ' + sizeKB + ' KB';

    pipelineLog('detect', ext.toUpperCase() + ' file, ' + sizeKB + ' KB');

    // Show preview immediately (the "before" view) while parsing runs
    if (outputEmpty) outputEmpty.style.display = 'none';
    if (outputTabs) outputTabs.classList.add('visible');
    var actionsEl = document.getElementById('output-actions');
    if (actionsEl) actionsEl.style.display = 'flex';
    await renderPreview();
    // Switch to Preview tab so user sees the original document first
    var previewTab = document.querySelector('#output-tabs .dp-output-tab[data-tab="preview"]');
    if (previewTab) window.switchOutputTab(previewTab);

    // Init WASM if needed
    if (!wasmReady && !wasmError) {
      await initWasm();
    }

    // Determine format
    var zipFormats = ['docx', 'pptx', 'xlsx', 'odt', 'odp', 'ods', 'epub'];
    var aiFormats = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'];

    if (textFormats.indexOf(ext) !== -1) {
      pipelineLog('route', 'Text format \u2014 client-side parsing');
      await parseTextFile(file, ext);
    } else if (zipFormats.indexOf(ext) !== -1) {
      pipelineLog('route', 'ZIP-based Office format \u2014 WASM parsing');
      if (!wasmReady) {
        showError('WASM not loaded. ' + (wasmError || 'Try refreshing.'));
        return;
      }
      await parseZipFile(file, ext);
    } else if (aiFormats.indexOf(ext) !== -1) {
      pipelineLog('route', 'Binary format \u2014 AI extraction');
      await parseAIFile(file, ext);
    } else {
      showError('Unsupported format: .' + ext);
    }
  };

  // ── Parse text-based formats ──
  async function parseTextFile(file, ext) {
    var content = lastFileContent;

    pipelineLog('parse', 'Reading ' + content.length + ' characters');

    var blocks = textToBlocks(content, ext);
    pipelineLog('done', blocks.length + ' blocks extracted', 'done');
    setDotState('ready');
    setStatus('Parsed ' + blocks.length + ' blocks');
    showOutput(blocks, content);
  }

  // ── Parse ZIP-based Office formats via WASM ──
  async function parseZipFile(file, ext) {
    setStatus('Extracting ZIP...', false, true);
    pipelineLog('zip', 'Extracting ZIP archive...');

    try {
      var buffer = lastFileBuffer;
      var zip = await JSZip.loadAsync(buffer);
      var allBlocks = [];

      pipelineLog('zip', Object.keys(zip.files).length + ' entries found');

      if (ext === 'docx') {
        allBlocks = await parseDocxZip(zip);
      } else if (ext === 'pptx') {
        allBlocks = await parsePptxZip(zip);
      } else if (ext === 'xlsx') {
        allBlocks = await parseXlsxZip(zip);
      } else if (ext === 'odt' || ext === 'odp' || ext === 'ods') {
        pipelineLog('info', 'ODF formats use the API for full parsing');
        showFallback(ext, 'ODF formats use the API for full parsing.');
        setDotState('ready');
        return;
      } else if (ext === 'epub') {
        pipelineLog('info', 'EPUB uses the API for full parsing');
        showFallback(ext, 'EPUB uses the API for full parsing.');
        setDotState('ready');
        return;
      }

      pipelineLog('done', allBlocks.length + ' blocks extracted', 'done');
      setDotState('ready');
      setStatus('Parsed ' + allBlocks.length + ' blocks');
      showOutput(allBlocks);
    } catch (err) {
      pipelineLog('error', err.message, 'error');
      showError('Parse error: ' + err.message);
      console.error(err);
    }
  }

  // ── DOCX parsing ──
  async function parseDocxZip(zip) {
    var allBlocks = [];

    // Body
    var bodyEntry = zip.file('word/document.xml');
    if (bodyEntry) {
      var bodyXml = await bodyEntry.async('string');
      if (bodyXml.length <= MAX_XML_SIZE) {
        pipelineLog('xml', 'Parsing document body...');
        setStatus('Parsing document body...', false, true);
        var r = engine.call('parseDocxBody', bodyXml);
        if (r.success) {
          var blocks = safeJsonParse(r.result, []);
          allBlocks = allBlocks.concat(blocks);
          updateInfoBar('blocks', allBlocks.length);
          pipelineLog('xml', blocks.length + ' body blocks');
        }
      }
    }

    // Headers
    var headerEntries = Object.keys(zip.files).filter(function (n) { return n.match(/^word\/header\d+\.xml$/); });
    if (headerEntries.length > 0) {
      pipelineLog('xml', 'Parsing ' + headerEntries.length + ' header(s)...');
    }
    for (var i = 0; i < Math.min(headerEntries.length, 5); i++) {
      var xml = await zip.file(headerEntries[i]).async('string');
      if (xml.length <= MAX_XML_SIZE) {
        var hr = engine.call('parseDocxSection', xml, 'header');
        if (hr.success) allBlocks = allBlocks.concat(safeJsonParse(hr.result, []));
      }
    }

    // Footers
    var footerEntries = Object.keys(zip.files).filter(function (n) { return n.match(/^word\/footer\d+\.xml$/); });
    if (footerEntries.length > 0) {
      pipelineLog('xml', 'Parsing ' + footerEntries.length + ' footer(s)...');
    }
    for (var j = 0; j < Math.min(footerEntries.length, 5); j++) {
      var fxml = await zip.file(footerEntries[j]).async('string');
      if (fxml.length <= MAX_XML_SIZE) {
        var fr = engine.call('parseDocxSection', fxml, 'footer');
        if (fr.success) allBlocks = allBlocks.concat(safeJsonParse(fr.result, []));
      }
    }

    // Comments
    var commentsEntry = zip.file('word/comments.xml');
    if (commentsEntry) {
      pipelineLog('xml', 'Parsing comments...');
      var cxml = await commentsEntry.async('string');
      if (cxml.length <= MAX_XML_SIZE) {
        var cr = engine.call('parseDocxComments', cxml);
        if (cr.success) allBlocks = allBlocks.concat(safeJsonParse(cr.result, []));
      }
    }

    // Metadata
    var coreEntry = zip.file('docProps/core.xml');
    if (coreEntry) {
      pipelineLog('meta', 'Extracting metadata...');
      var mxml = await coreEntry.async('string');
      var mr = engine.call('parseMetadataXml', mxml);
      if (mr.success) {
        var meta = safeJsonParse(mr.result, {});
        if (meta.title) updateInfoBar('title', meta.title);
      }
    }

    return allBlocks;
  }

  // ── PPTX parsing ──
  async function parsePptxZip(zip) {
    var allBlocks = [];
    var slideEntries = Object.keys(zip.files)
      .filter(function (n) { return n.match(/^ppt\/slides\/slide\d+\.xml$/); })
      .sort();

    pipelineLog('xml', 'Found ' + slideEntries.length + ' slide(s)');

    for (var i = 0; i < Math.min(slideEntries.length, MAX_SLIDES); i++) {
      pipelineLog('slide', 'Parsing slide ' + (i + 1) + '/' + slideEntries.length);
      setStatus('Parsing slide ' + (i + 1) + '/' + slideEntries.length + '...');
      var xml = await zip.file(slideEntries[i]).async('string');
      if (xml.length <= MAX_XML_SIZE) {
        var r = engine.call('parsePptxSlide', xml);
        if (r.success) allBlocks = allBlocks.concat(safeJsonParse(r.result, []));
      }
    }
    return allBlocks;
  }

  // ── XLSX parsing ──
  async function parseXlsxZip(zip) {
    var allBlocks = [];

    // Load shared strings
    var ssEntry = zip.file('xl/sharedStrings.xml');
    var ssXml = ssEntry ? await ssEntry.async('string') : '';
    if (ssEntry) pipelineLog('xml', 'Loaded shared strings');

    // Find sheets
    var sheetEntries = Object.keys(zip.files)
      .filter(function (n) { return n.match(/^xl\/worksheets\/sheet\d+\.xml$/); })
      .sort();

    pipelineLog('xml', 'Found ' + sheetEntries.length + ' sheet(s)');

    for (var i = 0; i < Math.min(sheetEntries.length, MAX_SHEETS); i++) {
      pipelineLog('sheet', 'Parsing sheet ' + (i + 1) + '/' + sheetEntries.length);
      setStatus('Parsing sheet ' + (i + 1) + '/' + sheetEntries.length + '...');
      var xml = await zip.file(sheetEntries[i]).async('string');
      var sheetName = 'Sheet' + (i + 1);
      if (xml.length <= MAX_XML_SIZE) {
        var r = engine.call('parseXlsxSheet', xml, ssXml, sheetName);
        if (r.success) allBlocks = allBlocks.concat(safeJsonParse(r.result, []));
      }
    }
    return allBlocks;
  }

  // ── AI-based parsing (PDF/image) ──
  async function parseAIFile(file, ext) {
    var apiKey = localStorage.getItem('gemini-api-key');
    if (!apiKey) {
      if (aiUpsell) aiUpsell.classList.add('visible');
      pipelineLog('error', 'No API key \u2014 AI parsing requires a Gemini key', 'error');
      showError('PDF/image parsing requires an AI model. Add your Google API key in Settings.');
      setDotState('ready');
      return;
    }
    if (aiUpsell) aiUpsell.classList.remove('visible');

    if (!wasmReady) {
      await initWasm();
      if (!wasmReady) {
        showError('WASM not loaded \u2014 cannot parse with AI. ' + (wasmError || ''));
        return;
      }
    }

    // Always (re-)register AI handler with current key
    if (typeof engine.repl.setAIHandler === 'function') {
      engine.repl.setAIHandler(createGeminiHandler(apiKey));
      if (typeof engine.repl.grantCapability === 'function') engine.repl.grantCapability('AI');
    }

    pipelineLog('read', 'Preparing file for AI...');
    setStatus('Preparing file...', false, true);
    var buffer = lastFileBuffer;
    var bytes = new Uint8Array(buffer);
    var base64 = '';
    var chunkSize = 8192;
    for (var ci = 0; ci < bytes.length; ci += chunkSize) {
      var chunk = bytes.subarray(ci, Math.min(ci + chunkSize, bytes.length));
      base64 += String.fromCharCode.apply(null, chunk);
    }
    base64 = btoa(base64);

    var mimeMap = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', bmp: 'image/bmp', tiff: 'image/tiff', webp: 'image/webp' };
    var mime = mimeMap[ext] || 'application/octet-stream';

    pipelineLog('ai', 'Sending to Gemini (' + mime + ')...');
    setStatus('Parsing with AI (this may take a moment)...', false, true);
    try {
      var r = await engine.callAsync('parseFileFromBase64', base64, mime, file.name);
      if (r.success) {
        var blocks = safeJsonParse(r.result, []);
        pipelineLog('done', blocks.length + ' blocks extracted via AI', 'done');
        setDotState('ready');
        setStatus('Parsed ' + blocks.length + ' blocks via AI');
        showOutput(blocks);
      } else {
        pipelineLog('error', r.error, 'error');
        showError('AI parse failed: ' + r.error);
      }
    } catch (err) {
      pipelineLog('error', err.message, 'error');
      showError('AI parse error: ' + err.message);
    }
  }

  // ── Text to blocks (client-side) ──
  function textToBlocks(content, ext) {
    var blocks = [];
    var lines = content.split('\n');

    if (ext === 'md') {
      lines.forEach(function (line) {
        if (line.match(/^### /)) blocks.push({ type: 'heading', text: line.replace(/^### /, ''), level: 3 });
        else if (line.match(/^## /)) blocks.push({ type: 'heading', text: line.replace(/^## /, ''), level: 2 });
        else if (line.match(/^# /)) blocks.push({ type: 'heading', text: line.replace(/^# /, ''), level: 1 });
        else if (line.trim()) blocks.push({ type: 'text', text: line, style: 'normal' });
      });
    } else if (ext === 'csv' || ext === 'tsv') {
      var delim = ext === 'tsv' ? '\t' : ',';
      var rows = lines.filter(function (l) { return l.trim(); }).slice(0, 200);
      if (rows.length > 0) {
        var headers = rows[0].split(delim);
        var dataRows = rows.slice(1).map(function (r) { return r.split(delim); });
        blocks.push({ type: 'table', headers: headers, rows: dataRows });
      }
    } else {
      blocks.push({ type: 'text', text: content.substring(0, 10000), style: 'normal' });
    }
    return blocks;
  }

  // ── Output data (for copy/download) ──
  var lastOutput = { json: '', markdown: '', a2ui: '', blocks: [] };

  // ── Output rendering ──
  function showOutput(blocks, rawContent) {
    if (outputEmpty) outputEmpty.style.display = 'none';
    if (outputTabs) outputTabs.classList.add('visible');

    lastOutput.blocks = blocks;
    lastOutput.json = JSON.stringify(blocks, null, 2);
    lastOutput.markdown = blocksToMarkdown(blocks);

    // A2UI conversion via AILANG WASM (same code path as the server)
    var a2uiNodes = [];
    if (engine) {
      try {
        var a2uiResult = engine.call(DOCPARSE_MODULE, 'convertBlocksToA2UI', lastOutput.json);
        if (a2uiResult && a2uiResult.success) {
          a2uiNodes = JSON.parse(a2uiResult.result);
        }
      } catch (e) {
        console.warn('A2UI WASM conversion failed, falling back to empty:', e);
      }
    }
    lastOutput.a2ui = JSON.stringify(a2uiNodes, null, 2);

    // Blocks view
    if (panelBlocks) panelBlocks.innerHTML = renderBlocks(blocks);

    // JSON view
    if (panelJson) panelJson.innerHTML = '<pre>' + escHtml(lastOutput.json) + '</pre>';

    // Markdown view
    if (panelMarkdown) panelMarkdown.innerHTML = '<pre>' + escHtml(lastOutput.markdown) + '</pre>';

    // A2UI view
    if (panelA2UI) panelA2UI.innerHTML = renderA2UIDemo(a2uiNodes);

    // Re-render preview (WASM is now ready, so XLSX/PPTX previews will work)
    renderPreview();

    // Show action buttons
    var actionsEl = document.getElementById('output-actions');
    if (actionsEl) actionsEl.style.display = 'flex';

    // Switch to Blocks tab (the "after" parsed view)
    var blocksTab = document.querySelector('#output-tabs .dp-output-tab[data-tab="blocks"]');
    if (blocksTab) window.switchOutputTab(blocksTab);
  }

  // ── Preview rendering ──
  async function renderPreview() {
    if (!panelPreview) return;
    var ext = lastFileExt;

    if (!ext) {
      panelPreview.innerHTML = '<div class="office-preview-fallback">No file loaded</div>';
      return;
    }

    // Text preview
    if (lastFileContent != null) {
      if (ext === 'html' || ext === 'htm') {
        panelPreview.innerHTML = '<div class="office-preview-page">' + lastFileContent + '</div>';
      } else {
        panelPreview.innerHTML = '<div class="office-preview-text"><pre>' + escHtml(lastFileContent) + '</pre></div>';
      }
      return;
    }

    if (!lastFileBuffer) {
      panelPreview.innerHTML = '<div class="office-preview-fallback">No preview available</div>';
      return;
    }

    var buffer = lastFileBuffer;

    if (ext === 'docx') {
      panelPreview.innerHTML = '<div class="office-preview-fallback">Rendering preview...</div>';
      try {
        await renderDocxPreview(buffer);
      } catch (err) {
        panelPreview.innerHTML = '<div class="office-preview-fallback">DOCX preview failed: ' + escHtml(err.message) + '</div>';
      }
    } else if (ext === 'pptx') {
      await renderPptxPreview(buffer);
    } else if (ext === 'xlsx') {
      await renderXlsxPreview(buffer);
    } else if (ext === 'pdf') {
      renderPdfPreview(buffer);
    } else if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff'].indexOf(ext) !== -1) {
      renderImagePreview(buffer, ext);
    } else {
      panelPreview.innerHTML = '<div class="office-preview-fallback">No preview available for .' + ext + ' files</div>';
    }
  }

  // ── DOCX preview via Mammoth.js ──
  async function renderDocxPreview(buffer) {
    if (typeof mammoth === 'undefined') {
      panelPreview.innerHTML = '<div class="office-preview-fallback">Preview library not loaded</div>';
      return;
    }
    var result = await mammoth.convertToHtml({ arrayBuffer: buffer });
    var warnings = result.messages.filter(function (m) { return m.type === 'warning'; }).length;
    var html = '<div class="office-preview-page">' + result.value + '</div>';
    if (warnings > 0) {
      html += '<div class="office-preview-note">' + warnings + ' conversion warning' + (warnings > 1 ? 's' : '') + ' (minor formatting differences)</div>';
    }
    panelPreview.innerHTML = html;
  }

  // ── XLSX preview with sheet tabs ──
  async function renderXlsxPreview(buffer) {
    if (!engine) {
      panelPreview.innerHTML = '<div class="office-preview-fallback">Loading WASM for preview...</div>';
      return;
    }
    try {
      var zip = await JSZip.loadAsync(buffer);
      var ssEntry = zip.file('xl/sharedStrings.xml');
      var ssXml = ssEntry ? await ssEntry.async('string') : '';
      var sheetEntries = Object.keys(zip.files)
        .filter(function (e) { return e.match(/^xl\/worksheets\/sheet\d+\.xml$/); })
        .sort();

      if (sheetEntries.length === 0) {
        panelPreview.innerHTML = '<div class="office-preview-fallback">No sheets found</div>';
        return;
      }

      var sheets = [];
      for (var i = 0; i < Math.min(sheetEntries.length, MAX_SHEETS); i++) {
        var xml = await zip.file(sheetEntries[i]).async('string');
        if (xml && engine) {
          var sheetName = 'Sheet' + (i + 1);
          var r = engine.call('parseXlsxSheet', xml, ssXml, sheetName);
          if (r.success) {
            sheets.push({ name: sheetName, blocks: safeJsonParse(r.result, []) });
          }
        }
      }

      panelPreview.innerHTML = buildSheetTabsHtml(sheets);
      wireSheetTabs();
    } catch (err) {
      panelPreview.innerHTML = '<div class="office-preview-fallback">XLSX preview failed: ' + escHtml(err.message) + '</div>';
    }
  }

  function buildSheetTabsHtml(sheets) {
    var html = '<div class="office-preview office-preview-xlsx">';
    if (sheets.length > 1) {
      html += '<div class="xlsx-sheet-tabs">';
      sheets.forEach(function (s, i) {
        html += '<button class="xlsx-sheet-tab' + (i === 0 ? ' active' : '') + '" data-sheet="' + i + '">' + escHtml(s.name) + '</button>';
      });
      html += '</div>';
    }
    sheets.forEach(function (sheet, i) {
      html += '<div class="xlsx-sheet-content' + (i === 0 ? ' active' : '') + '" data-sheet="' + i + '">';
      (sheet.blocks || []).forEach(function (block) {
        if (block.type === 'table') {
          html += buildPreviewTableHtml(block);
        } else if (block.type === 'section' && block.blocks) {
          block.blocks.forEach(function (b) {
            if (b.type === 'table') html += buildPreviewTableHtml(b);
            else if (b.type === 'heading') html += '<div class="xlsx-sheet-name">' + escHtml(b.text) + '</div>';
          });
        }
      });
      html += '</div>';
    });
    html += '</div>';
    return html;
  }

  function wireSheetTabs() {
    var tabs = panelPreview.querySelectorAll('.xlsx-sheet-tab');
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var idx = this.getAttribute('data-sheet');
        panelPreview.querySelectorAll('.xlsx-sheet-tab').forEach(function (t) { t.classList.remove('active'); });
        panelPreview.querySelectorAll('.xlsx-sheet-content').forEach(function (c) { c.classList.remove('active'); });
        this.classList.add('active');
        var content = panelPreview.querySelector('.xlsx-sheet-content[data-sheet="' + idx + '"]');
        if (content) content.classList.add('active');
      });
    });
  }

  // ── PPTX preview with slide cards ──
  async function renderPptxPreview(buffer) {
    if (!engine) {
      panelPreview.innerHTML = '<div class="office-preview-fallback">Loading WASM for preview...</div>';
      return;
    }
    try {
      var zip = await JSZip.loadAsync(buffer);
      var slideEntries = Object.keys(zip.files)
        .filter(function (e) { return e.match(/^ppt\/slides\/slide\d+\.xml$/) && e.indexOf('_rels') === -1; })
        .sort();

      var slides = [];
      for (var i = 0; i < Math.min(slideEntries.length, MAX_SLIDES); i++) {
        var xml = await zip.file(slideEntries[i]).async('string');
        if (xml && engine) {
          var r = engine.call('parsePptxSlide', xml);
          if (r.success) slides.push(safeJsonParse(r.result, []));
        }
      }

      var html = '<div class="pptx-slides">';
      slides.forEach(function (slideBlocks, i) {
        html += '<div class="pptx-slide">';
        html += '<div class="pptx-slide-number">Slide ' + (i + 1) + '</div>';
        html += '<div class="pptx-slide-content">';
        var blocks = Array.isArray(slideBlocks) ? slideBlocks : [slideBlocks];
        blocks.forEach(function (block) {
          var innerBlocks = (block.type === 'section' && block.blocks) ? block.blocks : [block];
          innerBlocks.forEach(function (b) {
            if (b.type === 'heading') {
              var level = Math.min(b.level || 2, 4);
              html += '<h' + level + '>' + escHtml(b.text || '') + '</h' + level + '>';
            } else if (b.type === 'text' && (b.text || '').trim()) {
              html += '<p>' + escHtml(b.text) + '</p>';
            } else if (b.type === 'list') {
              var tag = b.ordered ? 'ol' : 'ul';
              html += '<' + tag + '>';
              (b.items || []).forEach(function (it) { html += '<li>' + escHtml(it) + '</li>'; });
              html += '</' + tag + '>';
            } else if (b.type === 'table') {
              html += buildPreviewTableHtml(b);
            }
          });
        });
        html += '</div></div>';
      });
      html += '</div>';
      panelPreview.innerHTML = html;
    } catch (err) {
      panelPreview.innerHTML = '<div class="office-preview-fallback">PPTX preview failed: ' + escHtml(err.message) + '</div>';
    }
  }

  // ── PDF preview ──
  function renderPdfPreview(buffer) {
    var blob = new Blob([buffer], { type: 'application/pdf' });
    var url = URL.createObjectURL(blob);
    panelPreview.innerHTML = '<div class="office-preview-pdf"><object data="' + url + '" type="application/pdf" width="100%" height="600"><div class="office-preview-fallback">PDF preview not available in this browser</div></object></div>';
  }

  // ── Image preview ──
  function renderImagePreview(buffer, ext) {
    var mimeMap = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', bmp: 'image/bmp', webp: 'image/webp', tiff: 'image/tiff' };
    var blob = new Blob([buffer], { type: mimeMap[ext] || 'image/png' });
    var url = URL.createObjectURL(blob);
    panelPreview.innerHTML = '<div class="office-preview-image"><img src="' + url + '" alt="Image preview"></div>';
  }

  // ── Shared preview table builder ──
  function buildPreviewTableHtml(block) {
    var headers = block.headers || [];
    var rows = block.rows || [];
    var html = '<div class="xlsx-table-wrap"><table class="xlsx-table">';
    if (headers.length > 0) {
      html += '<thead><tr>';
      headers.forEach(function (cell) {
        var text = typeof cell === 'string' ? cell : (cell.text || '');
        var colspan = (typeof cell === 'object' && cell.colSpan > 1) ? ' colspan="' + cell.colSpan + '"' : '';
        html += '<th' + colspan + '>' + escHtml(text) + '</th>';
      });
      html += '</tr></thead>';
    }
    if (rows.length > 0) {
      html += '<tbody>';
      rows.forEach(function (row) {
        var cells = Array.isArray(row) ? row : [];
        html += '<tr>';
        cells.forEach(function (cell) {
          var text = typeof cell === 'string' ? cell : (cell.text || '');
          var colspan = (typeof cell === 'object' && cell.colSpan > 1) ? ' colspan="' + cell.colSpan + '"' : '';
          html += '<td' + colspan + '>' + escHtml(text) + '</td>';
        });
        html += '</tr>';
      });
      html += '</tbody>';
    }
    html += '</table></div>';
    return html;
  }

  // ── Copy to clipboard ──
  window.dpCopyOutput = function () {
    var activeTab = document.querySelector('#output-tabs .dp-output-tab.active');
    var which = activeTab ? activeTab.getAttribute('data-tab') : 'json';
    var text = which === 'json' ? lastOutput.json : which === 'markdown' ? lastOutput.markdown : which === 'a2ui' ? lastOutput.a2ui : lastOutput.json;

    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function () {
        var btn = document.getElementById('copy-output-btn');
        if (btn) { var orig = btn.textContent; btn.textContent = 'Copied!'; setTimeout(function () { btn.textContent = orig; }, 1500); }
      });
    }
  };

  // ── Download output ──
  window.dpDownloadOutput = function () {
    var activeTab = document.querySelector('#output-tabs .dp-output-tab.active');
    var which = activeTab ? activeTab.getAttribute('data-tab') : 'json';

    var text, filename, mime;
    if (which === 'json') {
      text = lastOutput.json;
      filename = 'docparse-output.json';
      mime = 'application/json';
    } else if (which === 'markdown') {
      text = lastOutput.markdown;
      filename = 'docparse-output.md';
      mime = 'text/markdown';
    } else if (which === 'a2ui') {
      text = lastOutput.a2ui;
      filename = 'docparse-output.a2ui.json';
      mime = 'application/json';
    } else {
      text = lastOutput.json;
      filename = 'docparse-output.json';
      mime = 'application/json';
    }

    var blob = new Blob([text], { type: mime });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── Switch output tabs (used by onclick handlers in HTML) ──
  window.switchOutputTab = function (tab) {
    if (!tab) return;
    document.querySelectorAll('#output-tabs .dp-output-tab').forEach(function (t) { t.classList.remove('active'); });
    tab.classList.add('active');
    var which = tab.getAttribute('data-tab');
    var panels = ['blocks', 'preview', 'json', 'markdown', 'a2ui'];
    panels.forEach(function (p) {
      var el = document.getElementById('panel-' + p);
      if (el) el.style.display = which === p ? 'block' : 'none';
    });
  };

  function renderBlocks(blocks) {
    if (!Array.isArray(blocks)) return '<div class="dp-block"><div class="dp-block-text">No blocks</div></div>';

    return blocks.map(function (b) {
      if (!b || !b.type) return '';

      switch (b.type) {
        case 'heading':
          var lvl = b.level || 1;
          return '<div class="dp-block"><div class="dp-block-heading" data-level="' + lvl + '">' + escHtml(b.text || '') + '</div></div>';

        case 'text':
          return '<div class="dp-block"><div class="dp-block-text">' + escHtml(b.text || '') + '</div></div>';

        case 'table':
          var html = '<table class="dp-block-table"><thead><tr>';
          (b.headers || []).forEach(function (h) {
            var text = typeof h === 'string' ? h : (h.text || '');
            html += '<th>' + escHtml(text) + '</th>';
          });
          html += '</tr></thead><tbody>';
          (b.rows || []).forEach(function (row) {
            html += '<tr>';
            (Array.isArray(row) ? row : []).forEach(function (c) {
              var text = typeof c === 'string' ? c : (c.text || '');
              html += '<td>' + escHtml(text) + '</td>';
            });
            html += '</tr>';
          });
          html += '</tbody></table>';
          return '<div class="dp-block">' + html + '</div>';

        case 'list':
          var tag = b.ordered ? 'ol' : 'ul';
          var items = (b.items || []).map(function (i) { return '<li>' + escHtml(i) + '</li>'; }).join('');
          return '<div class="dp-block"><' + tag + '>' + items + '</' + tag + '></div>';

        case 'change':
          var cls = (b.changeType === 'delete') ? 'dp-block-change--delete' : 'dp-block-change--insert';
          return '<div class="dp-block"><div class="dp-block-change ' + cls + '">' +
            '<strong>' + escHtml(b.changeType || '') + '</strong> by ' + escHtml(b.author || '') + ': ' + escHtml(b.text || '') +
            '</div></div>';

        case 'section':
          return '<div class="dp-block dp-block-section"><div class="dp-block-section-label">' + escHtml(b.kind || 'section') + '</div>' +
            renderBlocks(b.blocks || b.children || []) + '</div>';

        case 'image':
          return '<div class="dp-block"><div class="dp-block-text" style="color:var(--dp-blue)">[Image: ' + escHtml(b.description || b.mime || 'embedded') + ']</div></div>';

        default:
          return '<div class="dp-block"><div class="dp-block-text">' + escHtml(b.text || JSON.stringify(b)) + '</div></div>';
      }
    }).join('');
  }

  function blocksToMarkdown(blocks) {
    if (!Array.isArray(blocks)) return '';
    return blocks.map(function (b) {
      if (!b) return '';
      switch (b.type) {
        case 'heading': return '#'.repeat(b.level || 1) + ' ' + (b.text || '');
        case 'text': return b.text || '';
        case 'table':
          var hdr = (b.headers || []).map(function (h) { return typeof h === 'string' ? h : h.text || ''; });
          var sep = hdr.map(function () { return '---'; });
          var rows = (b.rows || []).map(function (r) {
            return '| ' + (Array.isArray(r) ? r : []).map(function (c) { return typeof c === 'string' ? c : c.text || ''; }).join(' | ') + ' |';
          });
          return '| ' + hdr.join(' | ') + ' |\n| ' + sep.join(' | ') + ' |\n' + rows.join('\n');
        case 'list': return (b.items || []).map(function (i, idx) { return (b.ordered ? (idx + 1) + '. ' : '- ') + i; }).join('\n');
        case 'change': return '> **' + (b.changeType || '') + '** by ' + (b.author || '') + ': ' + (b.text || '');
        case 'section': return '### ' + (b.kind || 'section') + '\n' + blocksToMarkdown(b.blocks || b.children || []);
        case 'image': return '![' + (b.description || 'image') + ']()';
        default: return b.text || '';
      }
    }).join('\n\n');
  }

  // ── A2UI visual renderer ──
  // Note: blocksToA2UI conversion is now handled by AILANG via WASM
  // (docparse/services/a2ui_formatter.ail → convertBlocksJsonToA2UI)
  // The JS duplicate was removed to eliminate drift risk.
  function renderA2UIDemo(nodes) {
    if (!Array.isArray(nodes) || nodes.length === 0) return '<div class="dp-block-text">No A2UI nodes</div>';

    // Build lookup map
    var nodeMap = {};
    nodes.forEach(function (n) { nodeMap[n.id] = n; });

    function typeClass(t) { return 'a2ui-type-' + t.replace(/[^a-z]/g, ''); }

    function renderNode(node, depth) {
      if (!node || depth > 10) return '';
      var html = '<div class="a2ui-node">';
      html += '<div class="a2ui-node-header">';
      html += '<span class="a2ui-node-id">' + escHtml(node.id) + '</span>';
      html += '<span class="a2ui-node-type ' + typeClass(node.type) + '">' + escHtml(node.type) + '</span>';

      // Show label for containers
      if (node.props && node.props.label) {
        html += '<span style="font-size:11px;color:var(--text-muted)">' + escHtml(node.props.label) + '</span>';
      }
      html += '</div>';

      // Render content preview based on type
      if (node.type === 'heading' && node.props) {
        var lvl = node.props.level || '1';
        html += '<div class="a2ui-node-content" style="font-weight:700;font-size:' + (20 - parseInt(lvl) * 2) + 'px">' + escHtml(node.props.text || '') + '</div>';
      } else if (node.type === 'text' && node.props) {
        var txt = node.props.text || '';
        html += '<div class="a2ui-node-content">' + escHtml(txt.length > 200 ? txt.substring(0, 200) + '...' : txt) + '</div>';
      } else if (node.type === 'table' && node.props) {
        try {
          var hdrs = JSON.parse(node.props.headers || '[]');
          var rows = JSON.parse(node.props.rows || '[]');
          html += '<div class="a2ui-node-content" style="font-family:var(--font-mono);font-size:11px">' +
            hdrs.length + ' cols, ' + rows.length + ' rows</div>';
        } catch(e) { html += '<div class="a2ui-node-content">[table]</div>'; }
      } else if (node.type === 'list' && node.props) {
        try {
          var items = JSON.parse(node.props.items || '[]');
          html += '<div class="a2ui-node-content" style="font-family:var(--font-mono);font-size:11px">' +
            items.length + ' items (' + (node.props.ordered === 'true' ? 'ordered' : 'unordered') + ')</div>';
        } catch(e) { html += '<div class="a2ui-node-content">[list]</div>'; }
      } else if (node.type === 'callout' && node.props) {
        var cls = node.props.variant === 'delete' ? 'dp-block-change--delete' : 'dp-block-change--insert';
        html += '<div class="dp-block-change ' + cls + '" style="font-size:12px">' +
          '<strong>' + escHtml(node.props.variant || '') + '</strong> ' + escHtml(node.props.text || '') + '</div>';
      } else if (node.type === 'image' && node.props) {
        html += '<div class="a2ui-node-content" style="color:var(--dp-blue)">[Image: ' + escHtml(node.props.alt || node.props.mime || '') + ']</div>';
      } else if (node.type === 'media' && node.props) {
        html += '<div class="a2ui-node-content">[' + escHtml(node.props.mediaType || 'media') + ': ' + escHtml(node.props.description || '') + ']</div>';
      } else if (node.type === 'key-value' && node.props) {
        html += '<div class="a2ui-node-content"><strong>' + escHtml(node.props.label || '') + ':</strong> ' + escHtml(node.props.value || '') + '</div>';
      }

      // Show non-trivial props
      if (node.props && Object.keys(node.props).length > 0 && node.type !== 'container') {
        var propKeys = Object.keys(node.props).filter(function(k) { return k !== 'text' && k !== 'label'; });
        if (propKeys.length > 0) {
          html += '<div class="a2ui-node-props">';
          propKeys.forEach(function(k) {
            var v = node.props[k];
            if (v.length > 40) v = v.substring(0, 40) + '...';
            html += '<span>' + escHtml(k) + '=' + escHtml(v) + '</span>';
          });
          html += '</div>';
        }
      }

      // Render children for containers
      if (node.children && node.children.length > 0) {
        html += '<div class="a2ui-container-children">';
        node.children.forEach(function (childId) {
          var child = nodeMap[childId];
          if (child) html += renderNode(child, depth + 1);
        });
        html += '</div>';
      }
      html += '</div>';
      return html;
    }

    // Build split view
    var jsonStr = JSON.stringify(nodes, null, 2);
    var html = '<div class="a2ui-demo">';
    html += '<div class="a2ui-json"><div class="a2ui-label">A2UI JSON</div><pre>' + escHtml(jsonStr) + '</pre></div>';
    html += '<div class="a2ui-preview"><div class="a2ui-label">Component Tree</div>';
    // Render from root
    var root = nodeMap['doc'] || nodes[0];
    if (root) html += renderNode(root, 0);
    html += '</div></div>';
    return html;
  }

  // ── Helpers ──
  function showError(msg) {
    setDotState('error');
    if (panelBlocks) panelBlocks.innerHTML = '<div class="dp-block"><div class="dp-block-text" style="color:#ef4444">' + msg + '</div></div>';
    if (outputEmpty) outputEmpty.style.display = 'none';
    if (outputTabs) outputTabs.classList.add('visible');
    window.switchOutputTab(document.querySelector('#output-tabs .dp-output-tab.active'));
  }

  function showFallback(ext, msg) {
    showError(escHtml(msg) + ' <a href="api.html" style="color:var(--dp-blue)">Use the API</a> for full parsing.');
  }

  function showInfoBar(ext, sizeKB) {
    if (!infoBar) return;
    infoBar.innerHTML = '<span class="dp-info-chip">' + ext.toUpperCase() + '</span>' +
      '<span class="dp-info-chip">' + sizeKB + ' KB</span>';
    infoBar.classList.add('visible');
  }

  function updateInfoBar(key, value) {
    if (!infoBar) return;
    infoBar.innerHTML += '<span class="dp-info-chip">' + escHtml(String(value)) + (key === 'blocks' ? ' blocks' : '') + '</span>';
  }

  function safeJsonParse(s, fallback) {
    try { return JSON.parse(s); } catch (e) { return fallback; }
  }

  function escHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Wire up file handling ──
  if (dropzone) {
    ['dragenter', 'dragover'].forEach(function (evt) {
      dropzone.addEventListener(evt, function (e) { e.preventDefault(); dropzone.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
      dropzone.addEventListener(evt, function (e) { e.preventDefault(); dropzone.classList.remove('dragover'); });
    });
    dropzone.addEventListener('drop', function (e) {
      if (e.dataTransfer.files.length > 0) window.handleDocParseFile(e.dataTransfer.files[0]);
    });
  }
  if (fileInput) {
    fileInput.addEventListener('change', function () {
      if (this.files.length > 0) window.handleDocParseFile(this.files[0]);
    });
  }

  // ── Demo file buttons ──
  document.querySelectorAll('.dp-demo-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var path = this.getAttribute('data-file');
      if (!path) return;
      // Disable all demo buttons during loading
      document.querySelectorAll('.dp-demo-btn').forEach(function (b) { b.disabled = true; });
      setStatus('Loading demo file...', false, true);
      setDotState('processing');
      fetch(path)
        .then(function (resp) {
          if (!resp.ok) throw new Error('Failed to fetch demo file');
          return resp.blob();
        })
        .then(function (blob) {
          var name = path.split('/').pop();
          var file = new File([blob], name);
          return window.handleDocParseFile(file);
        })
        .catch(function (err) {
          showError('Failed to load demo: ' + escHtml(err.message));
        })
        .finally(function () {
          document.querySelectorAll('.dp-demo-btn').forEach(function (b) { b.disabled = false; });
        });
    });
  });

  // ── Start WASM loading (desktop auto-loads, mobile defers) ──
  if (window.innerWidth >= 768) {
    initWasm();
  } else {
    // Mobile: show a load button instead of auto-downloading 35MB
    if (statusEl) statusEl.textContent = 'Tap to load parser (35 MB)';
    setDotState('');
    var mobileLoadBtn = document.createElement('button');
    mobileLoadBtn.className = 'dp-dropzone-btn';
    mobileLoadBtn.textContent = 'Load Parser (35 MB)';
    mobileLoadBtn.style.cssText = 'display:block;margin:12px auto;font-size:13px;padding:10px 24px';
    mobileLoadBtn.onclick = function () {
      mobileLoadBtn.remove();
      initWasm();
    };
    if (dropzone) dropzone.parentNode.insertBefore(mobileLoadBtn, dropzone);
  }
})();
