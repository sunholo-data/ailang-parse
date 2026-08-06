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
  // Cache-bust query is auto-stamped by .github/workflows/pages.yml from
  // docs/wasm/.ailang-version. The checked-in value reflects whatever pin was
  // current at the last commit; CI rewrites it to match the deployed pin so a
  // stale browser cache can never serve a mismatched ailang.wasm.
  var WASM_BINARY_URL = 'wasm/ailang.wasm?v=v0.30.0';
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
    // omml before docx_parser/pptx_parser — both import renderOmml from it
    { name: 'docparse/services/omml',             path: 'docparse/services/omml.ail' },
    { name: 'docparse/services/docx_parser',      path: 'docparse/services/docx_parser.ail' },
    { name: 'docparse/services/pptx_parser',      path: 'docparse/services/pptx_parser.ail' },
    { name: 'docparse/services/xlsx_parser',      path: 'docparse/services/xlsx_parser.ail' },
    // Text format parsers (html_parser before eml_parser — dependency)
    { name: 'docparse/services/html_parser',      path: 'docparse/services/html_parser.ail' },
    { name: 'docparse/services/csv_parser',       path: 'docparse/services/csv_parser.ail' },
    { name: 'docparse/services/markdown_parser',   path: 'docparse/services/markdown_parser.ail' },
    { name: 'docparse/services/rtf_parser',       path: 'docparse/services/rtf_parser.ail' },
    { name: 'docparse/services/eml_parser',       path: 'docparse/services/eml_parser.ail' },
    { name: 'docparse/services/tex_parser',       path: 'docparse/services/tex_parser.ail' },
    // ODF + EPUB structural parsers (run pure XML→Blocks via AILANG WASM;
    // JS only does ZIP extraction with JSZip).
    { name: 'docparse/services/odt_parser',       path: 'docparse/services/odt_parser.ail' },
    { name: 'docparse/services/odp_parser',       path: 'docparse/services/odp_parser.ail' },
    { name: 'docparse/services/ods_parser',       path: 'docparse/services/ods_parser.ail' },
    { name: 'docparse/services/epub_parser',      path: 'docparse/services/epub_parser.ail' },
    { name: 'docparse/services/output_formatter', path: 'docparse/services/output_formatter.ail' },
    // A2UI: vendored package + formatter (dependencies before dependents)
    { name: 'pkg/sunholo/a2ui/components',        path: 'pkg/sunholo/a2ui/components.ail' },
    { name: 'docparse/services/a2ui_formatter',   path: 'docparse/services/a2ui_formatter.ail' },
    { name: 'docparse/services/docparse_browser', path: 'docparse/services/docparse_browser.ail' },
  ];

  var EXTRA_STDLIBS = ['std/xml', 'std/list', 'std/io', 'std/bytes'];

  // ── State ──
  var engine = null;
  var wasmReady = false;
  var wasmLoading = false;
  var wasmError = null;
  // In-flight init promise so concurrent callers (e.g. workbench dropping
  // files before WASM is ready) all await the same load instead of seeing
  // wasmLoading=true and falling through to "not ready".
  var initPromise = null;
  // Progress listeners — receive {phase, label, percent} events as the
  // engine boots. Used by the workbench to drive a real progress bar.
  var progressListeners = [];
  function emitProgress(phase, label, percent) {
    var ev = { phase: phase, label: label, percent: Math.max(0, Math.min(100, percent)) };
    for (var i = 0; i < progressListeners.length; i++) {
      try { progressListeners[i](ev); } catch (_) {}
    }
  }
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
  // Idempotent + concurrent-safe: every caller awaits the same `initPromise`
  // so a file dropped on the workbench before WASM is ready will queue
  // cleanly behind the boot sequence instead of throwing.
  function initWasm() {
    if (wasmReady) return Promise.resolve();
    if (initPromise) return initPromise;
    initPromise = (async function () {
      wasmLoading = true;
      setDotState('loading');
      setStatus('Loading WASM runtime...', false, true);
      emitProgress('script', 'Fetching AILANG runtime…', 2);

      try {
        if (!('WebAssembly' in window)) {
          throw new Error('WebAssembly not supported in this browser');
        }

        await loadScript('wasm/wasm_exec.js');
        emitProgress('script', 'Runtime scripts loaded', 8);
        await loadScript('wasm/ailang-repl.js');
        emitProgress('script', 'Runtime scripts loaded', 12);

        if (typeof AilangREPL === 'undefined') {
          throw new Error('AilangREPL not found after loading scripts');
        }

        setStatus('Initializing AILANG...', false, true);
        emitProgress('wasm', 'Initializing AILANG…', 15);
        var repl = new AilangREPL();
        setStatus('Loading WASM binary...', false, true);
        emitProgress('wasm', 'Downloading WASM binary (~35 MB, one-time)…', 18);
        await repl.init(WASM_BINARY_URL);
        emitProgress('wasm', 'WASM binary ready', 55);

        // Import stdlib
        var stdlibs = ['std/json', 'std/option', 'std/result', 'std/string', 'std/math', 'std/ai'];
        var allStdlibs = stdlibs.concat(EXTRA_STDLIBS);
        for (var i = 0; i < allStdlibs.length; i++) {
          repl.importModule(allStdlibs[i]);
          emitProgress('stdlib', 'Loading ' + allStdlibs[i] + '…',
            55 + Math.round(((i + 1) / allStdlibs.length) * 15));
        }

        // Load AILANG Parse modules
        for (var k = 0; k < MODULES_TO_LOAD.length; k++) {
          var mod = MODULES_TO_LOAD[k];
          var label = 'Loading ' + mod.name.split('/').pop() + ' (' + (k + 1) + '/' + MODULES_TO_LOAD.length + ')';
          setStatus(label);
          emitProgress('modules', label, 70 + Math.round(((k + 1) / MODULES_TO_LOAD.length) * 28));

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
        emitProgress('ready', 'Ready', 100);
        // Enable UI
        setUIEnabled(true);
      } catch (err) {
        wasmError = err.message;
        wasmLoading = false;
        setStatus('WASM load failed: ' + err.message, true);
        emitProgress('error', err.message, 100);
        console.error('WASM init error:', err);
        // Reset so callers can retry after the user fixes whatever broke
        // (e.g. flaky network on the WASM download).
        initPromise = null;
        throw err;
      }
    })();
    return initPromise;
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
      showError('File too large for browser parsing (' + (file.size / 1024 / 1024).toFixed(1) + 'MB). Use the <a href="api.html" style="color:var(--dp-blue)">API</a> for files up to 50MB.');
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
    var textFormats = ['html', 'htm', 'md', 'csv', 'tsv', 'eml', 'mbox', 'tex', 'latex', 'ltx', 'rtf'];
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
      pipelineLog('route', 'Text format \u2014 WASM parsing');
      if (!wasmReady) {
        showError('WASM not loaded. ' + (wasmError || 'Try refreshing.'));
        return;
      }
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

  // ── Parse text-based formats via AILANG WASM ──
  async function parseTextFile(file, ext) {
    var content = lastFileContent;

    pipelineLog('parse', 'Parsing ' + content.length + ' characters via WASM');

    // Route to the correct AILANG parser
    var r;
    if (ext === 'eml') {
      r = engine.call('parseEmlContent', content);
    } else if (ext === 'mbox') {
      r = engine.call('parseMboxThreadedContent', content);
    } else if (ext === 'html' || ext === 'htm') {
      r = engine.call('parseHtmlContent', content);
    } else if (ext === 'csv') {
      r = engine.call('parseCsvContent', content, ',');
    } else if (ext === 'tsv') {
      r = engine.call('parseCsvContent', content, '\t');
    } else if (ext === 'md') {
      r = engine.call('parseMarkdownContent', content);
    } else if (ext === 'tex' || ext === 'latex' || ext === 'ltx') {
      r = engine.call('parseTexContent', content);
    } else if (ext === 'rtf') {
      r = engine.call('parseRtfContent', content);
    } else {
      // Fallback for unknown text formats
      var blocks = [{ type: 'text', text: content.substring(0, 10000), style: 'normal' }];
      pipelineLog('done', blocks.length + ' blocks extracted', 'done');
      setDotState('ready');
      setStatus('Parsed ' + blocks.length + ' blocks');
      showOutput(blocks, content);
      return;
    }

    if (r && r.success) {
      var blocks = safeJsonParse(r.result, []);
      pipelineLog('done', blocks.length + ' blocks extracted', 'done');
      setDotState('ready');
      setStatus('Parsed ' + blocks.length + ' blocks');
      showOutput(blocks, content);
    } else {
      var errMsg = r ? r.error : 'WASM call returned null';
      pipelineLog('error', errMsg, 'error');
      showError('Parse error: ' + errMsg);
    }
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
      } else if (ext === 'odt') {
        allBlocks = await parseOdtZip(zip);
      } else if (ext === 'odp') {
        allBlocks = await parseOdpZip(zip);
      } else if (ext === 'ods') {
        allBlocks = await parseOdsZip(zip);
      } else if (ext === 'epub') {
        allBlocks = await parseEpubZip(zip);
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

    // Body (with comments anchored to the text they annotate and spliced in
    // at their anchor point — comments.xml holds only the comment bodies, the
    // ranges they point at live in document.xml, so the two parse together)
    var bodyEntry = zip.file('word/document.xml');
    if (bodyEntry) {
      var bodyXml = await bodyEntry.async('string');
      var commentsEntry = zip.file('word/comments.xml');
      var commentsXml = commentsEntry ? await commentsEntry.async('string') : '';
      var extEntry = zip.file('word/commentsExtended.xml');
      var extXml = extEntry ? await extEntry.async('string') : '';
      if (commentsXml.length > MAX_XML_SIZE) commentsXml = '';
      if (extXml.length > MAX_XML_SIZE) extXml = '';
      if (bodyXml.length <= MAX_XML_SIZE) {
        pipelineLog('xml', 'Parsing document body...');
        setStatus('Parsing document body...', false, true);
        var r = engine.call('parseDocxBodyWithComments', bodyXml, commentsXml, extXml);
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

    // Comments — anchored to the body text they annotate, so they are parsed
    // alongside document.xml rather than on their own. Handled above in the
    // body step; nothing to append here.

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

  // ── ODF parsing (ODT / ODP / ODS) ──
  // JS extracts content.xml / meta.xml / styles.xml from the ODF zip via
  // JSZip; the parsing itself runs entirely in AILANG WASM. Same pattern
  // as parseDocxZip — we never reimplement parser logic here.
  async function parseOdtZip(zip) {
    var allBlocks = [];

    var contentEntry = zip.file('content.xml');
    if (contentEntry) {
      var xml = await contentEntry.async('string');
      if (xml.length <= MAX_XML_SIZE) {
        pipelineLog('xml', 'Parsing ODT content...');
        var r = engine.call('parseOdtContent', xml);
        if (r && r.success) {
          allBlocks = allBlocks.concat(safeJsonParse(r.result, []));
          pipelineLog('xml', allBlocks.length + ' body blocks');
        } else if (r) {
          pipelineLog('error', 'parseOdtContent failed: ' + r.error, 'error');
        }
      }
    }

    var stylesEntry = zip.file('styles.xml');
    if (stylesEntry) {
      var sxml = await stylesEntry.async('string');
      if (sxml.length <= MAX_XML_SIZE) {
        var sr = engine.call('parseOdtStylesXml', sxml);
        if (sr && sr.success) {
          allBlocks = allBlocks.concat(safeJsonParse(sr.result, []));
        }
      }
    }

    var metaEntry = zip.file('meta.xml');
    if (metaEntry) {
      var mxml = await metaEntry.async('string');
      var mr = engine.call('parseOdtMetadataXml', mxml);
      if (mr && mr.success) {
        var meta = safeJsonParse(mr.result, {});
        if (meta.title) updateInfoBar('title', meta.title);
      }
    }

    return allBlocks;
  }

  async function parseOdpZip(zip) {
    var allBlocks = [];

    var contentEntry = zip.file('content.xml');
    if (contentEntry) {
      var xml = await contentEntry.async('string');
      if (xml.length <= MAX_XML_SIZE) {
        pipelineLog('xml', 'Parsing ODP slides...');
        var r = engine.call('parseOdpContent', xml);
        if (r && r.success) {
          allBlocks = allBlocks.concat(safeJsonParse(r.result, []));
          pipelineLog('xml', allBlocks.length + ' slide block(s)');
        } else if (r) {
          pipelineLog('error', 'parseOdpContent failed: ' + r.error, 'error');
        }
      }
    }

    var metaEntry = zip.file('meta.xml');
    if (metaEntry) {
      var mxml = await metaEntry.async('string');
      var mr = engine.call('parseOdpMetadataXml', mxml);
      if (mr && mr.success) {
        var meta = safeJsonParse(mr.result, {});
        if (meta.title) updateInfoBar('title', meta.title);
      }
    }

    return allBlocks;
  }

  async function parseOdsZip(zip) {
    var allBlocks = [];

    var contentEntry = zip.file('content.xml');
    if (contentEntry) {
      var xml = await contentEntry.async('string');
      if (xml.length <= MAX_XML_SIZE) {
        pipelineLog('xml', 'Parsing ODS sheets...');
        var r = engine.call('parseOdsContent', xml);
        if (r && r.success) {
          allBlocks = allBlocks.concat(safeJsonParse(r.result, []));
          pipelineLog('xml', allBlocks.length + ' sheet block(s)');
        } else if (r) {
          pipelineLog('error', 'parseOdsContent failed: ' + r.error, 'error');
        }
      }
    }

    var metaEntry = zip.file('meta.xml');
    if (metaEntry) {
      var mxml = await metaEntry.async('string');
      var mr = engine.call('parseOdsMetadataXml', mxml);
      if (mr && mr.success) {
        var meta = safeJsonParse(mr.result, {});
        if (meta.title) updateInfoBar('title', meta.title);
      }
    }

    return allBlocks;
  }

  // ── EPUB parsing ──
  // JS walks the OPF in two stages — both stages call AILANG bridge
  // functions. Per-chapter HTML parsing goes through parseHtmlContent
  // (already exposed). No parser logic lives in this function.
  async function parseEpubZip(zip) {
    var allBlocks = [];

    // Step 1: container.xml -> OPF rootfile path (via AILANG)
    var containerEntry = zip.file('META-INF/container.xml');
    var opfPath = '';
    if (containerEntry) {
      var containerXml = await containerEntry.async('string');
      var cr = engine.call('parseEpubContainer', containerXml);
      if (cr && cr.success) opfPath = cr.result || '';
    }

    // Fallback: scan zip entries for any *.opf
    if (!opfPath) {
      var opfNames = Object.keys(zip.files).filter(function (n) { return n.match(/\.opf$/i); });
      if (opfNames.length > 0) opfPath = opfNames[0];
    }

    if (!opfPath) {
      pipelineLog('error', 'EPUB: no OPF file found', 'error');
      return allBlocks;
    }

    // Step 2: read OPF, extract spine + metadata (via AILANG)
    var opfEntry = zip.file(opfPath);
    if (!opfEntry) {
      pipelineLog('error', 'EPUB: OPF entry missing: ' + opfPath, 'error');
      return allBlocks;
    }
    var opfXml = await opfEntry.async('string');

    // opfDir = directory portion of opfPath, e.g. "OEBPS/" or ""
    var lastSlash = opfPath.lastIndexOf('/');
    var opfDir = lastSlash >= 0 ? opfPath.substring(0, lastSlash + 1) : '';

    // Metadata
    var mr = engine.call('parseEpubMetadataXml', opfXml);
    if (mr && mr.success) {
      var meta = safeJsonParse(mr.result, {});
      if (meta.title) updateInfoBar('title', meta.title);
    }

    // Spine (ordered list of chapter file paths)
    var sr = engine.call('parseEpubSpine', opfXml, opfDir);
    var spine = [];
    if (sr && sr.success) spine = safeJsonParse(sr.result, []);

    pipelineLog('xml', 'EPUB: found ' + spine.length + ' chapter(s)');

    // Step 3: parse each chapter via parseHtmlContent (AILANG)
    var maxChapters = Math.min(spine.length, 50);
    for (var i = 0; i < maxChapters; i++) {
      var entryPath = spine[i];
      var chapterEntry = zip.file(entryPath);
      if (!chapterEntry) continue;
      var chapterHtml = await chapterEntry.async('string');
      if (chapterHtml.length > MAX_XML_SIZE) continue;
      var hr = engine.call('parseHtmlContent', chapterHtml);
      if (hr && hr.success) {
        var blocks = safeJsonParse(hr.result, []);
        if (blocks.length > 0) {
          // Wrap in a SectionBlock so the inspector can show chapter boundaries.
          var basename = entryPath.substring(entryPath.lastIndexOf('/') + 1);
          allBlocks.push({
            type: 'section',
            kind: 'chapter:' + basename,
            blocks: blocks
          });
        }
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
    if (panelBlocks) {
      panelBlocks.innerHTML = renderBlocks(blocks);
      // If any equation/bibitem/cite content is present, typeset with MathJax.
      if (panelBlocks.querySelector('.dp-block-equation, .dp-block-bibitem, .dp-cite')) {
        typesetMath(panelBlocks);
      }
    }

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

    // Switch to A2UI tab (streaming rendered document)
    var a2uiTab = document.querySelector('#output-tabs .dp-output-tab[data-tab="a2ui"]');
    if (a2uiTab) window.switchOutputTab(a2uiTab);
  }

  // ── Preview rendering ──
  // Public version takes an explicit container; the homepage wrapper passes
  // its own panelPreview. The workbench passes its own preview pane. All
  // helpers below were refactored to take `container` instead of using a
  // closure-scoped DOM ref so we never duplicate this logic again.
  async function renderPreview() {
    return renderPreviewIntoImpl(
      { ext: lastFileExt, content: lastFileContent, buffer: lastFileBuffer },
      panelPreview
    );
  }

  async function renderPreviewIntoImpl(src, container) {
    if (!container) return;
    var ext = src.ext;

    if (!ext) {
      container.innerHTML = '<div class="office-preview-fallback">No file loaded</div>';
      return;
    }

    // Text preview
    if (src.content != null) {
      if (ext === 'html' || ext === 'htm') {
        container.innerHTML = '<div class="office-preview-page">' + src.content + '</div>';
      } else {
        container.innerHTML = '<div class="office-preview-text"><pre>' + escHtml(src.content) + '</pre></div>';
      }
      return;
    }

    if (!src.buffer) {
      container.innerHTML = '<div class="office-preview-fallback">No preview available</div>';
      return;
    }

    var buffer = src.buffer;

    if (ext === 'docx') {
      container.innerHTML = '<div class="office-preview-fallback">Rendering preview...</div>';
      try {
        await renderDocxPreview(buffer, container);
      } catch (err) {
        container.innerHTML = '<div class="office-preview-fallback">DOCX preview failed: ' + escHtml(err.message) + '</div>';
      }
    } else if (ext === 'pptx') {
      await renderPptxPreview(buffer, container);
    } else if (ext === 'xlsx') {
      await renderXlsxPreview(buffer, container);
    } else if (ext === 'pdf') {
      renderPdfPreview(buffer, container);
    } else if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff'].indexOf(ext) !== -1) {
      renderImagePreview(buffer, ext, container);
    } else if (['wav', 'mp3', 'aiff', 'aac', 'ogg', 'flac'].indexOf(ext) !== -1) {
      renderAudioPreview(buffer, ext, container);
    } else if (['mp4', 'mov', 'avi', 'webm', 'wmv', 'mpeg', 'mpg'].indexOf(ext) !== -1) {
      renderVideoPreview(buffer, ext, container);
    } else {
      container.innerHTML = '<div class="office-preview-fallback">No preview available for .' + ext + ' files</div>';
    }
  }

  // ── DOCX preview via Mammoth.js ──
  async function renderDocxPreview(buffer, container) {
    if (typeof mammoth === 'undefined') {
      container.innerHTML = '<div class="office-preview-fallback">Preview library not loaded</div>';
      return;
    }
    var result = await mammoth.convertToHtml({ arrayBuffer: buffer });
    var warnings = result.messages.filter(function (m) { return m.type === 'warning'; }).length;
    var html = '<div class="office-preview-page">' + result.value + '</div>';
    if (warnings > 0) {
      html += '<div class="office-preview-note">' + warnings + ' conversion warning' + (warnings > 1 ? 's' : '') + ' (minor formatting differences)</div>';
    }
    container.innerHTML = html;
  }

  // ── XLSX preview with sheet tabs ──
  async function renderXlsxPreview(buffer, container) {
    if (!engine) {
      container.innerHTML = '<div class="office-preview-fallback">Loading WASM for preview...</div>';
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
        container.innerHTML = '<div class="office-preview-fallback">No sheets found</div>';
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

      container.innerHTML = buildSheetTabsHtml(sheets);
      wireSheetTabs(container);
    } catch (err) {
      container.innerHTML = '<div class="office-preview-fallback">XLSX preview failed: ' + escHtml(err.message) + '</div>';
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

  function wireSheetTabs(container) {
    var tabs = container.querySelectorAll('.xlsx-sheet-tab');
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var idx = this.getAttribute('data-sheet');
        container.querySelectorAll('.xlsx-sheet-tab').forEach(function (t) { t.classList.remove('active'); });
        container.querySelectorAll('.xlsx-sheet-content').forEach(function (c) { c.classList.remove('active'); });
        this.classList.add('active');
        var content = container.querySelector('.xlsx-sheet-content[data-sheet="' + idx + '"]');
        if (content) content.classList.add('active');
      });
    });
  }

  // ── PPTX preview with slide cards ──
  async function renderPptxPreview(buffer, container) {
    if (!engine) {
      container.innerHTML = '<div class="office-preview-fallback">Loading WASM for preview...</div>';
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
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = '<div class="office-preview-fallback">PPTX preview failed: ' + escHtml(err.message) + '</div>';
    }
  }

  // ── PDF preview ──
  function renderPdfPreview(buffer, container) {
    var blob = new Blob([buffer], { type: 'application/pdf' });
    var url = URL.createObjectURL(blob);
    container.innerHTML = '<div class="office-preview-pdf"><object data="' + url + '" type="application/pdf" width="100%" height="600"><div class="office-preview-fallback">PDF preview not available in this browser</div></object></div>';
  }

  // ── Image preview ──
  function renderImagePreview(buffer, ext, container) {
    var mimeMap = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', bmp: 'image/bmp', webp: 'image/webp', tiff: 'image/tiff' };
    var blob = new Blob([buffer], { type: mimeMap[ext] || 'image/png' });
    var url = URL.createObjectURL(blob);
    container.innerHTML = '<div class="office-preview-image"><img src="' + url + '" alt="Image preview"></div>';
  }

  // ── Audio preview ──
  function renderAudioPreview(buffer, ext, container) {
    var mimeMap = { wav: 'audio/wav', mp3: 'audio/mpeg', aiff: 'audio/aiff', aac: 'audio/aac', ogg: 'audio/ogg', flac: 'audio/flac' };
    var blob = new Blob([buffer], { type: mimeMap[ext] || 'audio/mpeg' });
    var url = URL.createObjectURL(blob);
    container.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;gap:16px">' +
      '<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="var(--dp-blue)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>' +
      '<audio controls src="' + url + '" style="width:100%;max-width:400px">Your browser does not support audio playback.</audio>' +
      '<div style="font-size:12px;color:var(--text-muted)">.' + ext.toUpperCase() + ' audio file</div></div>';
  }

  // ── Video preview ──
  function renderVideoPreview(buffer, ext, container) {
    var mimeMap = { mp4: 'video/mp4', mov: 'video/quicktime', avi: 'video/x-msvideo', webm: 'video/webm', wmv: 'video/x-ms-wmv', mpeg: 'video/mpeg', mpg: 'video/mpeg' };
    var blob = new Blob([buffer], { type: mimeMap[ext] || 'video/mp4' });
    var url = URL.createObjectURL(blob);
    container.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;padding:20px;gap:12px">' +
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

  // ── MathJax lazy loader ──
  // Only load MathJax once, and only when we actually see LaTeX content.
  // Keeps the initial homepage payload small for the common (non-LaTeX) case.
  var mathjaxState = { loaded: false, loading: false, queue: [] };
  function ensureMathJax(cb) {
    if (mathjaxState.loaded) { cb(); return; }
    mathjaxState.queue.push(cb);
    if (mathjaxState.loading) return;
    mathjaxState.loading = true;
    window.MathJax = {
      tex: { inlineMath: [['$', '$'], ['\\(', '\\)']], displayMath: [['$$', '$$'], ['\\[', '\\]']] },
      options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] },
      startup: {
        ready: function () {
          window.MathJax.startup.defaultReady();
          mathjaxState.loaded = true;
          mathjaxState.queue.forEach(function (fn) { try { fn(); } catch (e) { console.warn(e); } });
          mathjaxState.queue = [];
        }
      }
    };
    var s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js';
    s.async = true;
    document.head.appendChild(s);
  }

  function typesetMath(root) {
    if (!root) return;
    ensureMathJax(function () {
      if (window.MathJax && window.MathJax.typesetPromise) {
        // texReset clears the AMS label registry so switching tabs or
        // re-rendering the same doc doesn't emit "Label 'x' multiply defined".
        if (typeof window.MathJax.texReset === 'function') {
          try { window.MathJax.texReset(); } catch (_) {}
        }
        window.MathJax.typesetPromise([root]).catch(function (e) { console.warn('MathJax typeset failed:', e); });
      }
    });
  }

  // Strip \label{...} directives from math source before MathJax sees it.
  // Labels are useful for cross-references in a compiled TeX run but have
  // no visual effect on display — and MathJax's global label store throws
  // "multiply defined" if the same label is typeset twice.
  function stripTexLabels(src) {
    return (src || '').replace(/\\label\{[^}]*\}/g, '');
  }

  // Inline LaTeX-ish markers inside paragraph text:
  //   [cite:key]  → citation pill
  //   [ref:label] → cross-reference pill
  //   $...$ kept as-is so MathJax can typeset it
  function renderInlineTex(text) {
    var out = escHtml(text || '');
    out = out.replace(/\[cite:([^\]]+)\]/g, function (_, k) {
      return '<span class="dp-cite" title="' + escHtml(k) + '">[' + escHtml(k) + ']</span>';
    });
    out = out.replace(/\[ref:([^\]]+)\]/g, function (_, k) {
      return '<span class="dp-xref" title="' + escHtml(k) + '">' + escHtml(k) + '</span>';
    });
    return out;
  }

  function renderBlocks(blocks) {
    if (!Array.isArray(blocks)) return '<div class="dp-block"><div class="dp-block-text">No blocks</div></div>';

    return blocks.map(function (b) {
      if (!b || !b.type) return '';

      switch (b.type) {
        case 'heading':
          var lvl = b.level || 1;
          return '<div class="dp-block"><div class="dp-block-heading" data-level="' + lvl + '">' + escHtml(b.text || '') + '</div></div>';

        case 'text':
          // Equation blocks: preserve the raw LaTeX source and let MathJax typeset it.
          if (b.style === 'equation-display' || b.style === 'equation') {
            var isDisplay = b.style === 'equation-display';
            var raw = stripTexLabels(b.text || '');
            // MathJax handles \begin{equation}/\begin{align} natively — pass through.
            // For bare inline equations, wrap in \(...\) if not already delimited.
            var body = raw;
            var hasEnv = /\\begin\{[a-zA-Z*]+\}/.test(raw);
            var hasDelim = /^\s*(\$\$|\\\[|\\\()/.test(raw);
            if (!hasEnv && !hasDelim) {
              body = isDisplay ? ('\\[' + raw + '\\]') : ('\\(' + raw + '\\)');
            }
            var cls = isDisplay ? 'dp-block-equation dp-block-equation--display' : 'dp-block-equation';
            return '<div class="dp-block"><div class="' + cls + '">' + escHtml(body) + '</div></div>';
          }
          // Bibliography entries: compact, hanging-indent style.
          if (b.style === 'bibitem') {
            return '<div class="dp-block"><div class="dp-block-bibitem">' + renderInlineTex(b.text) + '</div></div>';
          }
          // Abstract: italic callout, inline math still typeset.
          if (b.style === 'abstract') {
            return '<div class="dp-block"><div class="dp-block-abstract">' + renderInlineTex(b.text) + '</div></div>';
          }
          return '<div class="dp-block"><div class="dp-block-text">' + renderInlineTex(b.text) + '</div></div>';

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

        case 'comment':
          // Quote the annotated span above the comment. An unanchored comment
          // says so — it must never look like it has a target when it doesn't.
          var anchorHtml = (b.anchored && b.anchorText)
            ? '<div class="dp-block-comment-anchor">' + escHtml(b.anchorText) + '</div>'
            : '<div class="dp-block-comment-anchor dp-block-comment-anchor--none">unanchored</div>';
          return '<div class="dp-block"><div class="dp-block-comment">' + anchorHtml +
            '<div class="dp-block-comment-body"><strong>' + escHtml(b.author || '') + '</strong>: ' +
            escHtml(b.text || '') + '</div></div></div>';

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

  // Markdown conversion lives in the shared docparse-blocks.js so the
  // workbench and homepage demo cannot drift. Same logic, one source.
  function blocksToMarkdown(blocks) {
    if (!window.DocParseBlocks) {
      console.error('[wasm-demo] docparse-blocks.js must load before wasm-demo.js');
      return '';
    }
    return window.DocParseBlocks.toMarkdown(blocks);
  }

  // ── A2UI visual renderer (streaming rich document) ──
  // Renders A2UI nodes as an actual document (headings, paragraphs, tables, lists)
  // with progressive streaming animation. The document builds itself when the tab
  // is selected, with a collapsible JSON panel showing the underlying data.

  function typeClass(t) { return 'a2ui-type-' + t.replace(/[^a-z]/g, ''); }

  // Walk the A2UI tree depth-first from root, collecting leaf content nodes
  // (skip containers — they're structural, not visual)
  function flattenContentNodes(nodes) {
    var nodeMap = {};
    nodes.forEach(function (n) { nodeMap[n.id] = n; });
    var root = nodeMap['doc'] || nodes[0];
    if (!root) return { ordered: [], nodeMap: nodeMap };

    var ordered = [];
    function walk(node, depth) {
      if (!node || depth > 10) return;
      // Include all non-container nodes (the visible content)
      if (node.type !== 'container') {
        ordered.push({ node: node, depth: depth });
      }
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

  // Compute sequential streaming delays (simple stagger — content appears top to bottom)
  function computeStreamDelays(total) {
    var gap = total > 80 ? 15 : total > 30 ? 30 : 50;
    var delays = [];
    for (var i = 0; i < total; i++) {
      delays.push(i * gap);
    }
    // Cap at 3000ms
    if (delays.length > 0 && delays[delays.length - 1] > 3000) {
      var scale = 3000 / delays[delays.length - 1];
      delays = delays.map(function (d) { return Math.round(d * scale); });
    }
    return delays;
  }

  // Render a single A2UI node as a rich document element
  function renderRichNode(node) {
    var p = node.props || {};

    if (node.type === 'heading') {
      var lvl = Math.min(parseInt(p.level || '1'), 6);
      var h = document.createElement('h' + lvl);
      h.className = 'a2ui-rich-heading';
      h.textContent = p.text || '';
      return h;
    }

    if (node.type === 'text') {
      var div = document.createElement('div');
      div.className = 'a2ui-rich-text';
      if (p.style && p.style !== 'normal' && p.style !== '') {
        div.setAttribute('data-style', p.style);
      }
      // Equation styles: strip \label{} and wrap in \[...\]/\(...\) so
      // MathJax typesets the formula (must call typesetMath on the panel
      // after buildA2UIDemo completes).
      if (p.style === 'equation-display' || p.style === 'equation') {
        var isDisp = p.style === 'equation-display';
        var rawEq = stripTexLabels(p.text || '');
        var bodyEq = rawEq;
        var hasEnv2 = /\\begin\{[a-zA-Z*]+\}/.test(rawEq);
        var hasDelim2 = /^\s*(\$\$|\\\[|\\\()/.test(rawEq);
        if (!hasEnv2 && !hasDelim2) {
          bodyEq = isDisp ? ('\\[' + rawEq + '\\]') : ('\\(' + rawEq + '\\)');
        }
        div.textContent = bodyEq;
      } else {
        // Paragraph text: strip stray \label{} and render inline cite/xref pills.
        div.innerHTML = renderInlineTex(stripTexLabels(p.text || ''));
      }
      return div;
    }

    if (node.type === 'table') {
      var wrapper = document.createElement('div');
      wrapper.className = 'a2ui-rich-table-wrap';
      var table = document.createElement('table');
      table.className = 'a2ui-rich-table';
      try {
        var hdrs = JSON.parse(p.headers || '[]');
        var rows = JSON.parse(p.rows || '[]');
        if (hdrs.length > 0) {
          var thead = document.createElement('thead');
          var tr = document.createElement('tr');
          hdrs.forEach(function (h) {
            var th = document.createElement('th');
            th.textContent = typeof h === 'string' ? h : (h.text || '');
            if (h.colSpan && h.colSpan > 1) th.colSpan = h.colSpan;
            tr.appendChild(th);
          });
          thead.appendChild(tr);
          table.appendChild(thead);
        }
        if (rows.length > 0) {
          var tbody = document.createElement('tbody');
          rows.forEach(function (row) {
            var tr = document.createElement('tr');
            (Array.isArray(row) ? row : []).forEach(function (cell) {
              var td = document.createElement('td');
              td.textContent = typeof cell === 'string' ? cell : (cell.text || '');
              if (cell.colSpan && cell.colSpan > 1) td.colSpan = cell.colSpan;
              tr.appendChild(td);
            });
            tbody.appendChild(tr);
          });
          table.appendChild(tbody);
        }
      } catch (e) {
        table.innerHTML = '<tr><td>[table data]</td></tr>';
      }
      wrapper.appendChild(table);
      return wrapper;
    }

    if (node.type === 'list') {
      try {
        var items = JSON.parse(p.items || '[]');
        var list = document.createElement(p.ordered === 'true' ? 'ol' : 'ul');
        list.className = 'a2ui-rich-list';
        items.forEach(function (item) {
          var li = document.createElement('li');
          li.textContent = item;
          list.appendChild(li);
        });
        return list;
      } catch (e) {
        var fb = document.createElement('div');
        fb.className = 'a2ui-rich-text';
        fb.textContent = '[list]';
        return fb;
      }
    }

    if (node.type === 'callout') {
      var callout = document.createElement('div');
      var isDelete = p.variant === 'delete';
      callout.className = 'a2ui-rich-callout ' + (isDelete ? 'a2ui-rich-callout--delete' : 'a2ui-rich-callout--insert');
      var badge = document.createElement('span');
      badge.className = 'a2ui-rich-callout-badge';
      badge.textContent = p.variant || 'change';
      callout.appendChild(badge);
      if (p.text) {
        var txt = document.createElement('span');
        txt.textContent = p.text;
        if (isDelete) txt.style.textDecoration = 'line-through';
        callout.appendChild(txt);
      }
      var meta = [];
      if (p.author) meta.push(p.author);
      if (p.date) meta.push(p.date);
      if (meta.length > 0) {
        var metaSpan = document.createElement('span');
        metaSpan.className = 'a2ui-rich-callout-meta';
        metaSpan.textContent = meta.join(' \u00B7 ');
        callout.appendChild(metaSpan);
      }
      return callout;
    }

    if (node.type === 'image') {
      var imgDiv = document.createElement('div');
      imgDiv.className = 'a2ui-rich-image';
      imgDiv.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';
      var desc = document.createElement('span');
      desc.textContent = p.alt || p.description || p.mime || 'Image';
      imgDiv.appendChild(desc);
      return imgDiv;
    }

    if (node.type === 'media') {
      var mediaDiv = document.createElement('div');
      mediaDiv.className = 'a2ui-rich-media';
      var icon = p.mediaType === 'audio' ? '\u266B' : '\u25B6';
      mediaDiv.innerHTML = '<span class="a2ui-rich-media-icon">' + icon + '</span>';
      var label = document.createElement('span');
      label.textContent = (p.mediaType || 'media') + ': ' + (p.description || p.transcription || '');
      mediaDiv.appendChild(label);
      return mediaDiv;
    }

    if (node.type === 'key-value') {
      var kvDiv = document.createElement('div');
      kvDiv.className = 'a2ui-rich-kv';
      kvDiv.innerHTML = '<span class="a2ui-rich-kv-label">' + escHtml(p.label || '') + '</span> ' + escHtml(p.value || '');
      return kvDiv;
    }

    if (node.type === 'divider') {
      return document.createElement('hr');
    }

    // Fallback
    var fallback = document.createElement('div');
    fallback.className = 'a2ui-rich-text';
    fallback.textContent = p.text || '[' + node.type + ']';
    return fallback;
  }

  // Build the full A2UI demo: rich document (streaming) + collapsible JSON
  function buildA2UIDemo(nodes, container) {
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

    var treeData = flattenContentNodes(nodes);
    var ordered = treeData.ordered;
    var delays = computeStreamDelays(ordered.length);

    // Wrapper
    var demo = document.createElement('div');
    demo.className = 'a2ui-demo';

    // ── Rich document panel (primary, top/left) ──
    var docPanel = document.createElement('div');
    docPanel.className = 'a2ui-rich-doc';

    // Header with controls
    var streamHeader = document.createElement('div');
    streamHeader.className = 'a2ui-stream-header';
    var docLabel = document.createElement('div');
    docLabel.className = 'a2ui-label';
    docLabel.textContent = 'Rendered Document';
    streamHeader.appendChild(docLabel);

    var controls = document.createElement('div');
    controls.className = 'a2ui-stream-controls';
    var status = document.createElement('span');
    status.className = 'a2ui-stream-status';
    status.innerHTML = '<span class="a2ui-stream-counter">0/' + ordered.length + '</span> elements';
    controls.appendChild(status);
    var replayBtn = document.createElement('button');
    replayBtn.className = 'a2ui-replay-btn';
    replayBtn.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> Replay';
    replayBtn.onclick = function () { window.triggerA2UIStream(container); };
    controls.appendChild(replayBtn);
    streamHeader.appendChild(controls);
    docPanel.appendChild(streamHeader);

    // Render each content node as rich document element
    var richEls = [];
    ordered.forEach(function (entry, i) {
      var el = renderRichNode(entry.node);
      el.classList.add('a2ui-node--hidden');
      el.style.animationDelay = delays[i] + 'ms';
      el.setAttribute('data-a2ui-idx', i);
      docPanel.appendChild(el);
      richEls.push(el);
    });

    demo.appendChild(docPanel);

    // ── JSON panel (secondary, collapsible) ──
    var jsonPanel = document.createElement('div');
    jsonPanel.className = 'a2ui-json';

    var jsonToggle = document.createElement('button');
    jsonToggle.className = 'a2ui-json-toggle';
    jsonToggle.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg> A2UI JSON <span class="a2ui-json-badge">' + nodes.length + ' nodes</span>';
    jsonToggle.onclick = function () {
      var content = jsonPanel.querySelector('.a2ui-json-content');
      if (content) {
        var isOpen = content.style.display !== 'none';
        content.style.display = isOpen ? 'none' : 'block';
        jsonToggle.classList.toggle('open', !isOpen);
      }
    };
    jsonPanel.appendChild(jsonToggle);

    var jsonContent = document.createElement('div');
    jsonContent.className = 'a2ui-json-content';
    jsonContent.style.display = 'none';
    var pre = document.createElement('pre');
    pre.textContent = JSON.stringify(nodes, null, 2);
    jsonContent.appendChild(pre);
    jsonPanel.appendChild(jsonContent);

    demo.appendChild(jsonPanel);
    container.appendChild(demo);

    // Store metadata
    container._a2uiMeta = {
      totalNodes: ordered.length,
      delays: delays,
      richEls: richEls,
      demo: demo,
      docPanel: docPanel
    };

    // Typeset any inline / display math emitted by equation-styled text nodes.
    // Safe to call unconditionally — ensureMathJax skips if no math is present
    // (the script isn't loaded until something actually needs it).
    if (/\\begin\{|\\\[|\\\(|\$[^$]/.test(docPanel.textContent || '')) {
      typesetMath(docPanel);
    }
  }

  // Trigger the streaming animation. `container` defaults to the homepage's
  // panelA2UI for the existing onclick handlers; the workbench passes its own
  // pane. The `_a2uiMeta` and `_a2uiTimers` state lives on the container, so
  // multiple A2UI panes can stream independently without interfering.
  function triggerA2UIStream(container) {
    var pane = container || panelA2UI;
    if (!pane || !pane._a2uiMeta) return;
    var meta = pane._a2uiMeta;
    var demo = meta.demo;
    if (!demo) return;

    // Clear previous timers
    if (pane._a2uiTimers) {
      pane._a2uiTimers.forEach(clearTimeout);
    }
    pane._a2uiTimers = [];

    // Reset
    demo.classList.remove('a2ui-demo--streaming');
    var statusEl = demo.querySelector('.a2ui-stream-status');
    if (statusEl) statusEl.classList.remove('done');
    var counter = demo.querySelector('.a2ui-stream-counter');
    if (counter) counter.textContent = '0/' + meta.totalNodes;

    void demo.offsetHeight; // force reflow

    // Start streaming
    demo.classList.add('a2ui-demo--streaming');

    // Counter updates + auto-scroll the rich doc panel
    meta.delays.forEach(function (delay, i) {
      var t = setTimeout(function () {
        if (counter) counter.textContent = (i + 1) + '/' + meta.totalNodes;
        // Auto-scroll to keep current element visible (scroll the parent panel)
        var el = meta.richEls[i];
        if (el) {
          var panelRect = pane.getBoundingClientRect();
          var elRect = el.getBoundingClientRect();
          if (elRect.bottom > panelRect.bottom - 20) {
            pane.scrollTop += elRect.bottom - panelRect.bottom + 40;
          }
        }
        if (i === meta.totalNodes - 1 && statusEl) {
          statusEl.classList.add('done');
        }
      }, delay + 50);
      pane._a2uiTimers.push(t);
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

  // ──────────────────────────────────────────────────────────────
  // ── Pure AI parse helper for the public API ───────────────────
  // Mirrors what parseAIFile() does internally for the homepage demo, but
  // returns a clean { name, ext, sizeKB, ms, blocks } shape instead of
  // poking the homepage DOM. The workbench calls this transparently when
  // the user has a Gemini key in localStorage.
  async function parseAIFileViaWasm(file, ext, sizeKB, apiKey) {
    // Always (re-)register the AI handler so a freshly added key takes
    // effect without a page reload.
    if (engine && engine.repl && typeof engine.repl.setAIHandler === 'function') {
      engine.repl.setAIHandler(createGeminiHandler(apiKey));
      if (typeof engine.repl.grantCapability === 'function') engine.repl.grantCapability('AI');
    }

    var t0 = performance.now();
    var buffer = await file.arrayBuffer();
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
      wmv: 'video/x-ms-wmv', mpeg: 'video/mpeg', mpg: 'video/mpeg'
    };
    var mime = mimeMap[ext] || 'application/octet-stream';

    var r = await engine.callAsync('parseFileFromBase64', base64, mime, file.name);
    if (!r || !r.success) {
      var err = new Error('AI parse failed: ' + (r ? r.error : 'no result'));
      err.code = 'AI_PARSE_FAILED';
      console.error('[DocParseEngine] AI parse failed for .' + ext, { file: file.name, error: r && r.error });
      throw err;
    }
    var blocks = safeJsonParse(r.result, []);
    var ms = Math.round(performance.now() - t0);
    return { name: file.name, ext: ext, sizeKB: sizeKB, ms: ms, blocks: blocks };
  }

  // Public API — for workbench.html and any future consumer.
  // Pure parse: no homepage DOM dependency. Returns plain JS objects
  // or throws Error. The homepage UI keeps using its closure-private
  // helpers (handleDocParseFile / parseTextFile / parseZipFile) and
  // is not affected by anything below.
  // ──────────────────────────────────────────────────────────────
  window.DocParseEngine = {
    MAX_FILE_SIZE: MAX_FILE_SIZE,
    isReady:   function () { return wasmReady; },
    isLoading: function () { return wasmLoading; },
    getError:  function () { return wasmError; },
    init:      function () { return initWasm(); },

    /**
     * Subscribe to engine boot progress events. The callback receives
     * `{phase, label, percent}` objects as the engine downloads the WASM
     * binary, imports stdlibs, and loads parser modules. Returns an
     * unsubscribe function. If the engine is already ready, the callback
     * is invoked once synchronously with `{phase: 'ready', percent: 100}`.
     */
    onProgress: function (cb) {
      if (typeof cb !== 'function') return function () {};
      progressListeners.push(cb);
      if (wasmReady) {
        try { cb({ phase: 'ready', label: 'Ready', percent: 100 }); } catch (_) {}
      }
      return function () {
        var idx = progressListeners.indexOf(cb);
        if (idx >= 0) progressListeners.splice(idx, 1);
      };
    },

    /**
     * Get/set the Gemini API key in localStorage. The key unlocks PDF, image,
     * audio, and video parsing in the browser via WASM → Gemini. Returns null
     * if no key is set. Both the homepage demo and the workbench read/write
     * the same `gemini-api-key` slot, so a key set on one page is immediately
     * usable on the other.
     */
    getApiKey: function () {
      var k = localStorage.getItem('gemini-api-key') || '';
      return k.trim() ? k : null;
    },
    setApiKey: function (key) {
      var trimmed = (key || '').trim();
      if (trimmed) {
        localStorage.setItem('gemini-api-key', trimmed);
        // Re-register the AI handler if WASM is already up so the new key
        // takes effect without a reload.
        if (engine && engine.repl && typeof engine.repl.setAIHandler === 'function') {
          engine.repl.setAIHandler(createGeminiHandler(trimmed));
          if (typeof engine.repl.grantCapability === 'function') engine.repl.grantCapability('AI');
        }
      } else {
        localStorage.removeItem('gemini-api-key');
      }
    },

    /**
     * Parse a File via the in-browser AILANG WASM engine.
     * Returns: { name, ext, sizeKB, ms, blocks }
     * Throws:  Error (with .code === 'NEEDS_API' for formats that require the hosted API)
     */
    parseFile: async function (file) {
      if (file.size > MAX_FILE_SIZE) {
        var sizeMB = (file.size / 1024 / 1024).toFixed(1);
        var tooBig = new Error('File too large for browser parsing (' + sizeMB + ' MB). Use the API for files up to 50 MB.');
        tooBig.code = 'TOO_LARGE';
        throw tooBig;
      }

      var ext = file.name.split('.').pop().toLowerCase();
      var sizeKB = parseFloat((file.size / 1024).toFixed(1));

      var textFormats = ['html', 'htm', 'md', 'txt', 'csv', 'tsv', 'eml', 'mbox', 'tex', 'latex', 'ltx', 'rtf'];
      var zipFormats  = ['docx', 'pptx', 'xlsx', 'odt', 'odp', 'ods', 'epub'];
      // Formats that need an AI vision/multimodal model. WASM still drives
      // the parse — it just delegates the visual extraction step to whichever
      // model the user's API key points at (Gemini today).
      var aiFormats   = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp',
                         'wav', 'mp3', 'aiff', 'aac', 'ogg', 'flac',
                         'mp4', 'mov', 'avi', 'webm', 'wmv', 'mpeg', 'mpg'];
      // Nothing is API-only any more — every structural format has a WASM path.
      var apiOnly     = [];

      if (aiFormats.indexOf(ext) !== -1) {
        // Try AI parsing in-browser if the user has a Gemini key in
        // localStorage. Otherwise fall back to NEEDS_API so the workbench
        // can show its "needs API" UI with a link to add a key.
        var apiKey = localStorage.getItem('gemini-api-key');
        if (!apiKey) {
          var needsKey = new Error(ext.toUpperCase() + ' parsing needs an AI model — add a Google API key to enable it.');
          needsKey.code = 'NEEDS_API_KEY';
          throw needsKey;
        }
        if (!wasmReady) await initWasm();
        if (!wasmReady) throw new Error(wasmError || 'WASM failed to initialize');
        return await parseAIFileViaWasm(file, ext, sizeKB, apiKey);
      }
      if (apiOnly.indexOf(ext) !== -1) {
        var needsApi = new Error(ext.toUpperCase() + ' parsing requires the hosted API engine.');
        needsApi.code = 'NEEDS_API';
        throw needsApi;
      }
      if (textFormats.indexOf(ext) === -1 && zipFormats.indexOf(ext) === -1) {
        var unsup = new Error('Unsupported format: .' + ext);
        unsup.code = 'UNSUPPORTED';
        throw unsup;
      }

      if (!wasmReady) await initWasm();
      if (!wasmReady) throw new Error(wasmError || 'WASM failed to initialize');

      var t0 = performance.now();
      var blocks = [];

      if (textFormats.indexOf(ext) !== -1) {
        var content = await file.text();
        var r;
        if (ext === 'eml')                          r = engine.call('parseEmlContent', content);
        else if (ext === 'mbox')                    r = engine.call('parseMboxThreadedContent', content);
        else if (ext === 'html' || ext === 'htm')   r = engine.call('parseHtmlContent', content);
        else if (ext === 'csv')                     r = engine.call('parseCsvContent', content, ',');
        else if (ext === 'tsv')                     r = engine.call('parseCsvContent', content, '\t');
        else if (ext === 'md')                      r = engine.call('parseMarkdownContent', content);
        else if (ext === 'txt')                     r = engine.call('parseMarkdownContent', content);
        else if (ext === 'tex' || ext === 'latex' || ext === 'ltx') r = engine.call('parseTexContent', content);
        if (!r || !r.success) {
          // Surface the full WASM result so callers can inspect it in DevTools.
          var rawErr = r ? r.error : 'no result from engine.call';
          console.error('[DocParseEngine] WASM call failed for .' + ext, {
            file: file.name,
            sizeKB: sizeKB,
            entry: ext === 'eml' ? 'parseEmlContent'
                 : ext === 'mbox' ? 'parseMboxThreadedContent'
                 : ext === 'html' || ext === 'htm' ? 'parseHtmlContent'
                 : ext === 'csv' ? 'parseCsvContent'
                 : ext === 'tsv' ? 'parseCsvContent'
                 : ext === 'md' || ext === 'txt' ? 'parseMarkdownContent'
                 : ext === 'tex' || ext === 'latex' || ext === 'ltx' ? 'parseTexContent' : 'unknown',
            wasmResult: r,
            error: rawErr
          });
          throw new Error('Parse failed: ' + rawErr);
        }
        blocks = safeJsonParse(r.result, []);
      } else {
        if (typeof JSZip === 'undefined') throw new Error('JSZip not loaded — include vendor/jszip.min.js before wasm-demo.js');
        var buffer = await file.arrayBuffer();
        var zip = await JSZip.loadAsync(buffer);
        if      (ext === 'docx') blocks = await parseDocxZip(zip);
        else if (ext === 'pptx') blocks = await parsePptxZip(zip);
        else if (ext === 'xlsx') blocks = await parseXlsxZip(zip);
        else if (ext === 'odt')  blocks = await parseOdtZip(zip);
        else if (ext === 'odp')  blocks = await parseOdpZip(zip);
        else if (ext === 'ods')  blocks = await parseOdsZip(zip);
        else if (ext === 'epub') blocks = await parseEpubZip(zip);
      }

      var ms = Math.round(performance.now() - t0);
      return { name: file.name, ext: ext, sizeKB: sizeKB, ms: ms, blocks: blocks };
    },

    /**
     * Convert parsed blocks to A2UI nodes via the AILANG WASM formatter.
     * Returns an array of A2UI nodes (possibly empty). Never throws — logs
     * to console on failure and returns []. Both the homepage and the
     * workbench call this; logic must stay shared.
     */
    convertToA2UI: function (blocks) {
      if (!engine) return [];
      try {
        var json = typeof blocks === 'string' ? blocks : JSON.stringify(blocks);
        var r = engine.call('convertBlocksToA2UI', json);
        if (r && r.success) {
          var parsed = JSON.parse(r.result);
          if (Array.isArray(parsed)) return parsed;
        } else {
          console.warn('[DocParseEngine] convertToA2UI failed:', r ? r.error : 'null');
        }
      } catch (e) {
        console.warn('[DocParseEngine] convertToA2UI error:', e);
      }
      return [];
    },

    /**
     * Render the streaming A2UI demo into an arbitrary container.
     * The streaming animation is triggered separately via streamA2UI() so
     * callers can defer it until the pane becomes visible.
     */
    renderA2UIInto: function (nodes, container) {
      buildA2UIDemo(nodes || [], container);
    },

    /**
     * Trigger (or replay) the A2UI streaming animation in a given container.
     * Container must have been initialized via renderA2UIInto first.
     */
    streamA2UI: function (container) {
      triggerA2UIStream(container);
    },

    /**
     * Render a file preview (DOCX/PPTX/XLSX/PDF/image/audio/video/text) into
     * an arbitrary container. The workbench calls this with its own preview
     * pane; the homepage continues to use its own renderPreview() wrapper.
     * Reads the File freshly so callers don't need to manage buffers.
     */
    renderPreviewInto: async function (file, container) {
      if (!container) return;
      if (!file) {
        container.innerHTML = '<div class="office-preview-fallback">No file loaded</div>';
        return;
      }
      var ext = file.name.split('.').pop().toLowerCase();
      var textFormats = ['html', 'htm', 'md', 'csv', 'tsv', 'eml', 'mbox', 'txt'];
      var src = { ext: ext, content: null, buffer: null };
      try {
        if (textFormats.indexOf(ext) !== -1) {
          src.content = await file.text();
        } else {
          src.buffer = await file.arrayBuffer();
        }
      } catch (e) {
        container.innerHTML = '<div class="office-preview-fallback">Could not read file: ' + escHtml(e.message) + '</div>';
        return;
      }
      // XLSX/PPTX previews need WASM for sheet/slide parsing.
      if ((ext === 'xlsx' || ext === 'pptx') && !wasmReady) {
        try { await initWasm(); } catch (_) { /* fall through; helper will show fallback */ }
      }
      return renderPreviewIntoImpl(src, container);
    }
  };
})();
