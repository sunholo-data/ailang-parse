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
  var WASM_BINARY_URL = 'wasm/ailang.wasm?v=20260330';
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
  var parseTimerEl = document.getElementById('parse-timer');

  // ── Loading spinner (CSS-only) ──
  var spinnerCSS = document.createElement('style');
  spinnerCSS.textContent = '.dp-spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--dp-blue-border);border-top-color:var(--dp-blue);border-radius:50%;animation:dp-spin .6s linear infinite;vertical-align:-2px;margin-right:6px}@keyframes dp-spin{to{transform:rotate(360deg)}}';
  document.head.appendChild(spinnerCSS);

  // ── Parse timer ──
  var parseTimerStart = 0;
  var parseTimerInterval = null;

  function startParseTimer() {
    parseTimerStart = performance.now();
    if (parseTimerEl) {
      parseTimerEl.style.display = '';
      parseTimerEl.className = 'dp-parse-timer active';
      parseTimerEl.textContent = '0ms';
    }
    clearInterval(parseTimerInterval);
    parseTimerInterval = setInterval(function () {
      if (!parseTimerEl) return;
      var elapsed = performance.now() - parseTimerStart;
      parseTimerEl.textContent = formatElapsed(elapsed);
    }, 50);
  }

  function stopParseTimer() {
    clearInterval(parseTimerInterval);
    parseTimerInterval = null;
    if (parseTimerEl) {
      var elapsed = performance.now() - parseTimerStart;
      parseTimerEl.textContent = formatElapsed(elapsed);
      parseTimerEl.className = 'dp-parse-timer done';
    }
  }

  function formatElapsed(ms) {
    if (ms < 1000) return Math.round(ms) + 'ms';
    return (ms / 1000).toFixed(2) + 's';
  }

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
    var elapsed = parseTimerStart ? ' <span style="color:var(--text-muted);font-size:10px">' + formatElapsed(performance.now() - parseTimerStart) + '</span>' : '';
    line.innerHTML = '<span class="dp-pipeline-stage' + cls + '">' + escHtml(stage) + '</span> ' + escHtml(detail) + elapsed;
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
      // Enable UI
      setUIEnabled(true);
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

        // Only force JSON response when the prompt asks for JSON output
        var promptText = parsed.prompt || input;
        var wantsJson = promptText.indexOf('JSON') !== -1 && promptText.indexOf('ONLY the JSON') !== -1;
        var genConfig = { temperature: 0.2, maxOutputTokens: 32768 };
        if (wantsJson) genConfig.responseMimeType = 'application/json';

        var resp = await fetch(GEMINI_URL + '?key=' + apiKey, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contents: [{ parts: parts }],
            generationConfig: genConfig
          })
        });

        var data = await resp.json();

        // Surface API errors visibly
        if (!resp.ok || data.error) {
          var errMsg = data.error ? (data.error.message || JSON.stringify(data.error)) : ('HTTP ' + resp.status);
          console.error('Gemini API error:', errMsg);
          pipelineLog('error', 'Gemini: ' + errMsg, 'error');
          setStatus('AI error: ' + errMsg, true);
          return '[]';
        }

        var text = data.candidates?.[0]?.content?.parts?.[0]?.text;
        if (!text) {
          var reason = data.candidates?.[0]?.finishReason || 'no content returned';
          console.warn('Gemini returned no text:', reason, data);
          pipelineLog('error', 'Gemini returned no content: ' + reason, 'error');
          return '[]';
        }
        return text;
      } catch (e) {
        console.error('Gemini handler error:', e);
        pipelineLog('error', 'Gemini error: ' + e.message, 'error');
        setStatus('AI error: ' + e.message, true);
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

    // Start parse timer
    startParseTimer();

    // Determine format
    var zipFormats = ['docx', 'pptx', 'xlsx', 'odt', 'odp', 'ods', 'epub'];
    var aiFormats = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp',
                     'wav', 'mp3', 'aiff', 'aac', 'ogg', 'flac',
                     'mp4', 'mov', 'avi', 'webm', 'wmv', 'mpeg', 'mpg', 'flv', '3gpp'];

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

      // AI post-pass: describe embedded images if API key is present
      var apiKey = localStorage.getItem('gemini-api-key');
      if (apiKey && allBlocks.length > 0) {
        allBlocks = await describeEmbeddedImages(allBlocks, apiKey);
      }

      setDotState('ready');
      setStatus('Parsed ' + allBlocks.length + ' blocks');
      showOutput(allBlocks);
    } catch (err) {
      pipelineLog('error', err.message, 'error');
      showError('Parse error: ' + err.message);
      console.error(err);
    }
  }

  // ── AI image description for embedded images in Office docs ──
  async function describeEmbeddedImages(blocks, apiKey) {
    var imageBlocks = [];
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i].type === 'image' && blocks[i].data) {
        imageBlocks.push(i);
      }
    }
    if (imageBlocks.length === 0) return blocks;

    pipelineLog('ai', 'Describing ' + imageBlocks.length + ' embedded image(s) with AI...');
    setStatus('Describing ' + imageBlocks.length + ' image(s) with AI...', false, true);

    // Ensure AI handler is registered
    if (engine && typeof engine.repl.setAIHandler === 'function') {
      engine.repl.setAIHandler(createGeminiHandler(apiKey));
      if (typeof engine.repl.grantCapability === 'function') engine.repl.grantCapability('AI');
    }

    var described = 0;
    for (var j = 0; j < imageBlocks.length; j++) {
      var idx = imageBlocks[j];
      var block = blocks[idx];
      try {
        var mime = block.mime || 'image/png';
        var r = await engine.callAsync('describeImageBase64', block.data, mime);
        if (r.success && r.result && r.result.length > 0) {
          blocks[idx].description = r.result;
          described++;
          pipelineLog('ai', 'Image ' + (j + 1) + ': ' + r.result.substring(0, 80) + (r.result.length > 80 ? '...' : ''));
        }
      } catch (e) {
        pipelineLog('ai', 'Image ' + (j + 1) + ' description failed: ' + e.message);
      }
    }
    if (described > 0) {
      pipelineLog('done', described + ' image(s) described via AI', 'done');
    }
    return blocks;
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

    var mimeMap = {
      pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
      gif: 'image/gif', bmp: 'image/bmp', tiff: 'image/tiff', webp: 'image/webp',
      wav: 'audio/wav', mp3: 'audio/mp3', aiff: 'audio/aiff', aac: 'audio/aac',
      ogg: 'audio/ogg', flac: 'audio/flac',
      mp4: 'video/mp4', mov: 'video/quicktime', avi: 'video/x-msvideo', webm: 'video/webm',
      wmv: 'video/x-ms-wmv', mpeg: 'video/mpeg', mpg: 'video/mpeg', flv: 'video/x-flv', '3gpp': 'video/3gpp'
    };
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
  var lastOutput = { json: '', markdown: '', a2ui: '', a2uiNodes: [], blocks: [] };

  // ── Output rendering ──
  function showOutput(blocks, rawContent) {
    stopParseTimer();
    if (outputEmpty) outputEmpty.style.display = 'none';
    if (outputTabs) outputTabs.classList.add('visible');

    lastOutput.blocks = blocks;
    lastOutput.json = JSON.stringify(blocks, null, 2);
    lastOutput.markdown = blocksToMarkdown(blocks);

    // A2UI conversion via AILANG WASM
    var a2uiNodes = [];
    if (engine) {
      try {
        var a2uiResult = engine.call('convertBlocksToA2UI', lastOutput.json);
        if (a2uiResult && a2uiResult.success) {
          var parsed = JSON.parse(a2uiResult.result);
          if (Array.isArray(parsed) && parsed.length > 0) {
            a2uiNodes = parsed;
          }
        } else {
          console.warn('A2UI conversion failed:', a2uiResult ? a2uiResult.error : 'null');
        }
      } catch (e) {
        console.warn('A2UI WASM conversion error:', e);
      }
    }
    lastOutput.a2ui = JSON.stringify(a2uiNodes, null, 2);
    lastOutput.a2uiNodes = a2uiNodes;

    // Blocks view
    if (panelBlocks) panelBlocks.innerHTML = renderBlocks(blocks);

    // JSON view
    if (panelJson) panelJson.innerHTML = '<pre>' + escHtml(lastOutput.json) + '</pre>';

    // Markdown view
    if (panelMarkdown) panelMarkdown.innerHTML = '<pre>' + escHtml(lastOutput.markdown) + '</pre>';

    // A2UI view (DOM-based, streaming triggered on tab switch)
    if (panelA2UI) buildA2UIDemo(a2uiNodes, panelA2UI);

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
    } else if (['wav', 'mp3', 'aiff', 'aac', 'ogg', 'flac'].indexOf(ext) !== -1) {
      renderAudioPreview(buffer, ext);
    } else if (['mp4', 'mov', 'avi', 'webm', 'wmv', 'mpeg', 'mpg'].indexOf(ext) !== -1) {
      renderVideoPreview(buffer, ext);
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

  // ── Audio preview ──
  function renderAudioPreview(buffer, ext) {
    var mimeMap = { wav: 'audio/wav', mp3: 'audio/mpeg', aiff: 'audio/aiff', aac: 'audio/aac', ogg: 'audio/ogg', flac: 'audio/flac' };
    var blob = new Blob([buffer], { type: mimeMap[ext] || 'audio/mpeg' });
    var url = URL.createObjectURL(blob);
    panelPreview.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;gap:16px">' +
      '<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="var(--dp-blue)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>' +
      '<audio controls src="' + url + '" style="width:100%;max-width:400px">Your browser does not support audio playback.</audio>' +
      '<div style="font-size:12px;color:var(--text-muted)">.' + ext.toUpperCase() + ' audio file</div></div>';
  }

  // ── Video preview ──
  function renderVideoPreview(buffer, ext) {
    var mimeMap = { mp4: 'video/mp4', mov: 'video/quicktime', avi: 'video/x-msvideo', webm: 'video/webm', wmv: 'video/x-ms-wmv', mpeg: 'video/mpeg', mpg: 'video/mpeg' };
    var blob = new Blob([buffer], { type: mimeMap[ext] || 'video/mp4' });
    var url = URL.createObjectURL(blob);
    panelPreview.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;padding:20px;gap:12px">' +
      '<video controls src="' + url + '" style="width:100%;max-width:100%;max-height:400px;border-radius:8px;background:#000">Your browser does not support video playback.</video>' +
      '<div style="font-size:12px;color:var(--text-muted)">.' + ext.toUpperCase() + ' video file</div></div>';
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
        var iconCopy = document.getElementById('copy-icon');
        var iconDone = document.getElementById('copy-icon-done');
        var label = document.getElementById('copy-label');
        if (btn) {
          btn.classList.add('copied');
          if (iconCopy) iconCopy.style.display = 'none';
          if (iconDone) iconDone.style.display = '';
          if (label) label.textContent = 'Copied!';
          setTimeout(function () {
            btn.classList.remove('copied');
            if (iconCopy) iconCopy.style.display = '';
            if (iconDone) iconDone.style.display = 'none';
            if (label) label.textContent = 'Copy';
          }, 1500);
        }
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

    // Trigger A2UI streaming animation when tab becomes visible
    if (which === 'a2ui' && panelA2UI && panelA2UI._a2uiMeta) {
      triggerA2UIStream();
    }
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

  // ── A2UI visual renderer (streaming/progressive) ──
  // Note: blocksToA2UI conversion is now handled by AILANG via WASM
  // (docparse/services/a2ui_formatter.ail → convertBlocksJsonToA2UI)
  // The JS duplicate was removed to eliminate drift risk.

  function typeClass(t) { return 'a2ui-type-' + t.replace(/[^a-z]/g, ''); }

  // Walk the A2UI tree depth-first from root, collecting nodes with depth metadata
  function flattenTreeOrder(nodes) {
    var nodeMap = {};
    nodes.forEach(function (n) { nodeMap[n.id] = n; });
    var root = nodeMap['doc'] || nodes[0];
    if (!root) return { ordered: [], nodeMap: nodeMap };

    var ordered = [];
    function walk(node, depth) {
      if (!node || depth > 10) return;
      ordered.push({ node: node, depth: depth });
      if (node.children && node.children.length > 0) {
        node.children.forEach(function (childId) {
          var child = nodeMap[childId];
          if (child) walk(child, depth + 1);
        });
      }
    }
    walk(root, 0);
    return { ordered: ordered, nodeMap: nodeMap };
  }

  // Compute animation delays: depth-wave cascade
  function computeDelays(ordered) {
    var total = ordered.length;
    var interLevel = total > 80 ? 40 : 80;
    var intraLevel = total > 80 ? 15 : 30;

    // Group by depth, track index within each depth level
    var depthCounts = {};
    var delays = [];
    ordered.forEach(function (entry) {
      var d = entry.depth;
      if (!depthCounts[d]) depthCounts[d] = 0;
      var delay = (d * interLevel) + (depthCounts[d] * intraLevel);
      delays.push(delay);
      depthCounts[d]++;
    });

    // Cap at 3000ms
    var maxDelay = Math.max.apply(null, delays);
    if (maxDelay > 3000) {
      var scale = 3000 / maxDelay;
      delays = delays.map(function (d) { return Math.round(d * scale); });
    }
    return delays;
  }

  // Build a single A2UI node DOM element (no animation classes yet — added by container class)
  function buildNodeEl(node, nodeMap, depth, orderIndex, delay) {
    var el = document.createElement('div');
    el.className = 'a2ui-node a2ui-node--hidden';
    el.style.animationDelay = delay + 'ms';
    el.setAttribute('data-a2ui-idx', orderIndex);

    // Header
    var header = document.createElement('div');
    header.className = 'a2ui-node-header';
    var idSpan = document.createElement('span');
    idSpan.className = 'a2ui-node-id';
    idSpan.textContent = node.id;
    header.appendChild(idSpan);
    var typeSpan = document.createElement('span');
    typeSpan.className = 'a2ui-node-type ' + typeClass(node.type);
    typeSpan.textContent = node.type;
    header.appendChild(typeSpan);
    if (node.props && node.props.label) {
      var labelSpan = document.createElement('span');
      labelSpan.style.cssText = 'font-size:11px;color:var(--text-muted)';
      labelSpan.textContent = node.props.label;
      header.appendChild(labelSpan);
    }
    el.appendChild(header);

    // Content preview
    var content = null;
    if (node.type === 'heading' && node.props) {
      content = document.createElement('div');
      content.className = 'a2ui-node-content';
      var lvl = parseInt(node.props.level || '1');
      content.style.cssText = 'font-weight:700;font-size:' + (20 - lvl * 2) + 'px';
      content.textContent = node.props.text || '';
    } else if (node.type === 'text' && node.props) {
      content = document.createElement('div');
      content.className = 'a2ui-node-content';
      var txt = node.props.text || '';
      content.textContent = txt.length > 200 ? txt.substring(0, 200) + '...' : txt;
    } else if (node.type === 'table' && node.props) {
      content = document.createElement('div');
      content.className = 'a2ui-node-content';
      content.style.cssText = 'font-family:var(--font-mono);font-size:11px';
      try {
        var hdrs = JSON.parse(node.props.headers || '[]');
        var rows = JSON.parse(node.props.rows || '[]');
        content.textContent = hdrs.length + ' cols, ' + rows.length + ' rows';
      } catch(e) { content.textContent = '[table]'; }
    } else if (node.type === 'list' && node.props) {
      content = document.createElement('div');
      content.className = 'a2ui-node-content';
      content.style.cssText = 'font-family:var(--font-mono);font-size:11px';
      try {
        var items = JSON.parse(node.props.items || '[]');
        content.textContent = items.length + ' items (' + (node.props.ordered === 'true' ? 'ordered' : 'unordered') + ')';
      } catch(e) { content.textContent = '[list]'; }
    } else if (node.type === 'callout' && node.props) {
      content = document.createElement('div');
      var cls = node.props.variant === 'delete' ? 'dp-block-change--delete' : 'dp-block-change--insert';
      content.className = 'dp-block-change ' + cls;
      content.style.fontSize = '12px';
      content.innerHTML = '<strong>' + escHtml(node.props.variant || '') + '</strong> ' + escHtml(node.props.text || '');
    } else if (node.type === 'image' && node.props) {
      content = document.createElement('div');
      content.className = 'a2ui-node-content';
      content.style.color = 'var(--dp-blue)';
      content.textContent = '[Image: ' + (node.props.alt || node.props.mime || '') + ']';
    } else if (node.type === 'media' && node.props) {
      content = document.createElement('div');
      content.className = 'a2ui-node-content';
      content.textContent = '[' + (node.props.mediaType || 'media') + ': ' + (node.props.description || '') + ']';
    } else if (node.type === 'key-value' && node.props) {
      content = document.createElement('div');
      content.className = 'a2ui-node-content';
      content.innerHTML = '<strong>' + escHtml(node.props.label || '') + ':</strong> ' + escHtml(node.props.value || '');
    }
    if (content) el.appendChild(content);

    // Props (non-trivial)
    if (node.props && Object.keys(node.props).length > 0 && node.type !== 'container') {
      var propKeys = Object.keys(node.props).filter(function(k) { return k !== 'text' && k !== 'label'; });
      if (propKeys.length > 0) {
        var propsDiv = document.createElement('div');
        propsDiv.className = 'a2ui-node-props';
        propKeys.forEach(function(k) {
          var v = node.props[k];
          if (v.length > 40) v = v.substring(0, 40) + '...';
          var s = document.createElement('span');
          s.textContent = k + '=' + v;
          propsDiv.appendChild(s);
        });
        el.appendChild(propsDiv);
      }
    }

    return el;
  }

  // Build the full A2UI demo DOM structure with streaming support
  function buildA2UIDemo(nodes, container) {
    // Clear previous
    container.innerHTML = '';
    container._a2uiMeta = null;
    if (container._a2uiTimers) {
      container._a2uiTimers.forEach(clearTimeout);
      container._a2uiTimers = [];
    }

    if (!Array.isArray(nodes) || nodes.length === 0) {
      container.innerHTML = '<div class="dp-block-text">No A2UI nodes</div>';
      return;
    }

    var treeData = flattenTreeOrder(nodes);
    var ordered = treeData.ordered;
    var nodeMap = treeData.nodeMap;
    var delays = computeDelays(ordered);

    // Create the split-panel wrapper
    var demo = document.createElement('div');
    demo.className = 'a2ui-demo';

    // ── Left: JSON panel ──
    var jsonPanel = document.createElement('div');
    jsonPanel.className = 'a2ui-json';
    var jsonLabel = document.createElement('div');
    jsonLabel.className = 'a2ui-label';
    jsonLabel.textContent = 'A2UI JSON';
    jsonPanel.appendChild(jsonLabel);

    var pre = document.createElement('pre');
    var jsonSpans = [];

    // Build per-node JSON spans
    pre.appendChild(document.createTextNode('[\n'));
    ordered.forEach(function (entry, i) {
      var span = document.createElement('span');
      span.className = 'a2ui-json-node a2ui-node--hidden';
      span.style.animationDelay = delays[i] + 'ms';
      span.setAttribute('data-a2ui-idx', i);
      span.textContent = '  ' + JSON.stringify(entry.node, null, 2).split('\n').join('\n  ');
      if (i < ordered.length - 1) span.textContent += ',';
      span.textContent += '\n';
      pre.appendChild(span);
      jsonSpans.push(span);
    });
    pre.appendChild(document.createTextNode(']'));
    jsonPanel.appendChild(pre);
    demo.appendChild(jsonPanel);

    // ── Right: Component tree ──
    var preview = document.createElement('div');
    preview.className = 'a2ui-preview';

    // Header with replay controls
    var streamHeader = document.createElement('div');
    streamHeader.className = 'a2ui-stream-header';
    var treeLabel = document.createElement('div');
    treeLabel.className = 'a2ui-label';
    treeLabel.textContent = 'Component Tree';
    streamHeader.appendChild(treeLabel);

    var controls = document.createElement('div');
    controls.className = 'a2ui-stream-controls';
    var status = document.createElement('span');
    status.className = 'a2ui-stream-status';
    status.innerHTML = '<span class="a2ui-stream-counter">0/' + ordered.length + '</span> nodes';
    controls.appendChild(status);
    var replayBtn = document.createElement('button');
    replayBtn.className = 'a2ui-replay-btn';
    replayBtn.textContent = 'Replay';
    replayBtn.onclick = function () { window.triggerA2UIStream(); };
    controls.appendChild(replayBtn);
    streamHeader.appendChild(controls);
    preview.appendChild(streamHeader);

    // Build tree DOM recursively, assigning delays from the ordered list
    var orderLookup = {};
    ordered.forEach(function (entry, i) {
      orderLookup[entry.node.id] = { index: i, delay: delays[i], depth: entry.depth };
    });

    function buildTree(node, depth) {
      if (!node || depth > 10) return null;
      var info = orderLookup[node.id];
      if (!info) return null;

      var el = buildNodeEl(node, nodeMap, info.depth, info.index, info.delay);

      // Recursively build children
      if (node.children && node.children.length > 0) {
        var childrenDiv = document.createElement('div');
        childrenDiv.className = 'a2ui-container-children';
        var parentDelay = info.delay;
        childrenDiv.style.animationDelay = parentDelay + 'ms';
        node.children.forEach(function (childId) {
          var child = nodeMap[childId];
          if (child) {
            var childEl = buildTree(child, depth + 1);
            if (childEl) childrenDiv.appendChild(childEl);
          }
        });
        el.appendChild(childrenDiv);
      }
      return el;
    }

    var root = nodeMap['doc'] || nodes[0];
    if (root) {
      var rootEl = buildTree(root, 0);
      if (rootEl) preview.appendChild(rootEl);
    }
    demo.appendChild(preview);
    container.appendChild(demo);

    // Store metadata for streaming trigger
    container._a2uiMeta = {
      totalNodes: ordered.length,
      delays: delays,
      jsonSpans: jsonSpans,
      demo: demo
    };
  }

  // Trigger the streaming animation (called on tab switch + replay)
  function triggerA2UIStream() {
    if (!panelA2UI || !panelA2UI._a2uiMeta) return;
    var meta = panelA2UI._a2uiMeta;
    var demo = meta.demo;
    if (!demo) return;

    // Clear previous timers
    if (panelA2UI._a2uiTimers) {
      panelA2UI._a2uiTimers.forEach(clearTimeout);
    }
    panelA2UI._a2uiTimers = [];

    // Reset: remove streaming class, force reflow
    demo.classList.remove('a2ui-demo--streaming');
    // Also reset the status badge
    var statusEl = demo.querySelector('.a2ui-stream-status');
    if (statusEl) statusEl.classList.remove('done');
    var counter = demo.querySelector('.a2ui-stream-counter');
    if (counter) counter.textContent = '0/' + meta.totalNodes;

    void demo.offsetHeight; // force reflow to reset CSS animations

    // Start streaming
    demo.classList.add('a2ui-demo--streaming');

    // Schedule counter updates + JSON auto-scroll to match animation timing
    meta.delays.forEach(function (delay, i) {
      var t = setTimeout(function () {
        if (counter) counter.textContent = (i + 1) + '/' + meta.totalNodes;
        // Auto-scroll JSON panel to current node
        var jsonSpan = meta.jsonSpans[i];
        if (jsonSpan && jsonSpan.parentNode && jsonSpan.parentNode.parentNode) {
          var scrollContainer = jsonSpan.parentNode.parentNode;
          scrollContainer.scrollTop = jsonSpan.offsetTop - 40;
        }
        // Mark done on last node
        if (i === meta.totalNodes - 1 && statusEl) {
          statusEl.classList.add('done');
        }
      }, delay + 50);
      panelA2UI._a2uiTimers.push(t);
    });
  }
  window.triggerA2UIStream = triggerA2UIStream;

  // ── Helpers ──
  function showError(msg) {
    stopParseTimer();
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

  // ── Disable UI until WASM is ready ──
  function setUIEnabled(enabled) {
    if (dropzone) {
      dropzone.style.pointerEvents = enabled ? '' : 'none';
      dropzone.style.opacity = enabled ? '' : '0.5';
    }
    if (fileInput) fileInput.disabled = !enabled;
    document.querySelectorAll('.dp-demo-btn').forEach(function (b) { b.disabled = !enabled; });
  }
  setUIEnabled(false);

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
