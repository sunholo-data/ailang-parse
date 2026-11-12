/**
 * AILANG Parse — API base URL
 * Override via ?api=https://your-endpoint.run.app in the URL.
 * Or change DP_DATA.site.api_url in site-data.js to update all pages at once.
 */
var _dpParams = (typeof window !== 'undefined') ? new URLSearchParams(window.location.search) : null;
var _dpApiUrl = (typeof DP_DATA !== 'undefined' && DP_DATA.site && DP_DATA.site.api_url) || null;
var API_BASE = (_dpParams && _dpParams.get('api')) || _dpApiUrl || 'https://docparse.ailang.sunholo.com';

/**
 * AILANG Parse — Shared Components
 * Injects header navigation, footer, scroll-reveal, output tab logic,
 * head normalisation, data-dp value injection, and data-src code loading
 * across all pages. No build step required.
 *
 * Requires: site-data.js loaded first (defines DP_DATA, dpResolve, dpFormat).
 */
(function () {
  'use strict';

  // ── Campaign attribution + visit counter ──
  // Shared contract with the docparse API (/api/v1/referral/claim, /api/v1/visit)
  // and docparse/docs/js/firebase-app.js. Partner and campaign links land here
  // as www.sunholo.com/ailang-parse/<page>?ref=<code>&utm_source=...
  //
  // First touch wins. localStorage.docparse_ref keeps the bare partner code
  // exactly as before; localStorage.docparse_attr holds the whole first-touch
  // object {ref?, utm_*?, landing, at}, mirrored into the dp_attr cookie on
  // .sunholo.com so the MCP sign-in page on docparse.ailang.sunholo.com can
  // read it. Neither is overwritten while either exists. firebase-app.js hands
  // them to the server at sign-in and clears them once it confirms.
  //
  // The visit counter sends one request per page load: path plus the
  // campaign fields of the CURRENT URL, no cookies set or sent, no
  // identifiers. It stays silent under automation, Do Not Track and Global
  // Privacy Control. It uses fetch with keepalive and credentials:'omit'
  // rather than sendBeacon, because sendBeacon always attaches cookies and
  // would carry dp_attr (Domain=.sunholo.com) to the API.
  //
  // Everything runs only on the www.sunholo.com origin and is wrapped in
  // try/catch: attribution must never break the page.
  var DPA = (function () {
    var SITE_HOST = 'www.sunholo.com';
    var REF_RE = /^[a-z0-9-]{2,32}$/;
    var UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];
    var STRIP_KEYS = ['ref'].concat(UTM_KEYS);
    var COOKIE_NAME = 'dp_attr';
    var COOKIE_SCOPE = '; Domain=.sunholo.com; Path=/';
    var COOKIE_MAX_AGE = 7776000; // 90 days
    // Same docparse API hosts as firebase-app.js ENV_CONFIG, so ?env=dev|test
    // sends the beacon where that page's sign-in goes. ?api= wins over both.
    var ENV_API = {
      dev: 'https://ailang-dev-docparse-api-ejjw6zt3bq-ew.a.run.app',
      test: 'https://ailang-test-docparse-api-rrmdhcxo4a-ew.a.run.app'
    };

    function validRef(v) {
      return (typeof v === 'string' && REF_RE.test(v)) ? v : null;
    }
    function validUtm(v) {
      return (typeof v === 'string' && v.length > 0 && v.length <= 100 && !/[<>"]/.test(v)) ? v : null;
    }

    // {ref?, utm_*?} from a query string. Invalid values are dropped, not cleaned.
    function campaign(search) {
      var params = new URLSearchParams(search || '');
      var out = {};
      var ref = validRef(params.get('ref'));
      if (ref) out.ref = ref;
      UTM_KEYS.forEach(function (k) {
        var v = validUtm(params.get(k));
        if (v) out[k] = v;
      });
      return out;
    }

    function hasCampaign(c) {
      if (c.ref) return true;
      for (var i = 0; i < UTM_KEYS.length; i++) if (c[UTM_KEYS[i]]) return true;
      return false;
    }

    // The first-touch object, or null when the URL carries no valid campaign.
    function buildAttr(search, pathname, nowIso) {
      var attr = campaign(search);
      if (!hasCampaign(attr)) return null;
      attr.landing = String(pathname || '').slice(0, 200);
      attr.at = nowIso;
      return attr;
    }

    function cookieString(attr) {
      return COOKIE_NAME + '=' + encodeURIComponent(JSON.stringify(attr)) + COOKIE_SCOPE +
        '; Max-Age=' + COOKIE_MAX_AGE + '; SameSite=Lax; Secure';
    }

    function hasAttrCookie(cookieHeader) {
      return String(cookieHeader || '').split(/;\s*/).some(function (c) {
        return c.indexOf(COOKIE_NAME + '=') === 0 && c.length > COOKIE_NAME.length + 1;
      });
    }

    // First touch: nothing stored yet in either place.
    function isFirstTouch(storedAttr, cookieHeader) {
      return (storedAttr === null || storedAttr === undefined || storedAttr === '') &&
        !hasAttrCookie(cookieHeader);
    }

    // Address bar without ref/utm_*, other params and the hash kept. null when
    // there is nothing to strip.
    function strippedUrl(search, pathname, hash) {
      var params = new URLSearchParams(search || '');
      var found = STRIP_KEYS.filter(function (k) { return params.has(k); });
      if (!found.length) return null;
      found.forEach(function (k) { params.delete(k); });
      var qs = params.toString();
      return pathname + (qs ? '?' + qs : '') + (hash || '');
    }

    function visitBody(search, pathname) {
      var body = { site: 'ailang-parse', page: String(pathname || '').slice(0, 200) };
      var c = campaign(search);
      Object.keys(c).forEach(function (k) { body[k] = c[k]; });
      return body;
    }

    // Why the beacon must not be sent, or null to send it.
    function visitSkipReason(hostname, nav, win) {
      if (hostname !== SITE_HOST) return 'host';
      if (!nav) return 'no-navigator';
      if (nav.webdriver === true) return 'webdriver';
      if (nav.doNotTrack === '1' || (win && win.doNotTrack === '1')) return 'dnt';
      if (nav.globalPrivacyControl) return 'gpc';
      if (!win || typeof win.fetch !== 'function') return 'no-fetch';
      return null;
    }

    function visitBase(search, apiBase) {
      var params = new URLSearchParams(search || '');
      if (params.get('api')) return apiBase;
      return ENV_API[params.get('env')] || apiBase;
    }

    return {
      SITE_HOST: SITE_HOST,
      validRef: validRef,
      validUtm: validUtm,
      campaign: campaign,
      buildAttr: buildAttr,
      cookieString: cookieString,
      isFirstTouch: isFirstTouch,
      strippedUrl: strippedUrl,
      visitBody: visitBody,
      visitSkipReason: visitSkipReason,
      visitBase: visitBase
    };
  })();
  window.DocParseAttribution = DPA;

  // One beacon per page load. Returns true when the browser queued it.
  var dpVisitSent = false;
  window.docparseVisit = function () {
    if (dpVisitSent) return false;
    try {
      if (DPA.visitSkipReason(window.location.hostname, window.navigator, window)) return false;
      dpVisitSent = true;
      var body = DPA.visitBody(window.location.search, window.location.pathname);
      var url = DPA.visitBase(window.location.search, API_BASE) + '/api/v1/visit';
      // text/plain + no-cors: a simple request, no preflight; credentials
      // omitted so no cookie travels with it; keepalive survives navigation.
      window.fetch(url, {
        method: 'POST', body: JSON.stringify(body), keepalive: true,
        credentials: 'omit', mode: 'no-cors', referrerPolicy: 'no-referrer',
        headers: { 'Content-Type': 'text/plain' }
      }).catch(function () { /* fire and forget */ });
      return true;
    } catch (e) { return false; }
  };

  (function captureAttribution() {
    if (window.location.hostname !== DPA.SITE_HOST) return;
    var search = window.location.search;

    // Legacy key, unchanged: bare partner code, first touch wins.
    var refCode = DPA.validRef(new URLSearchParams(search).get('ref'));
    if (refCode) {
      try {
        var existing = window.localStorage.getItem('docparse_ref');
        if (existing === null || existing === '') {
          window.localStorage.setItem('docparse_ref', refCode);
        }
      } catch (e) { /* storage unavailable — skip capture */ }
    }

    // Full first-touch object: localStorage + cookie, set together, never overwritten.
    try {
      var attr = DPA.buildAttr(search, window.location.pathname, new Date().toISOString());
      if (attr) {
        var stored = null;
        var storageOk = true;
        try { stored = window.localStorage.getItem('docparse_attr'); } catch (e) { storageOk = false; }
        if (DPA.isFirstTouch(stored, document.cookie)) {
          if (storageOk) {
            try { window.localStorage.setItem('docparse_attr', JSON.stringify(attr)); } catch (e) { /* ignore */ }
          }
          try { document.cookie = DPA.cookieString(attr); } catch (e) { /* ignore */ }
        }
      }
    } catch (e) { /* never break the page */ }

    // Count the visit while the campaign fields are still in the URL.
    window.docparseVisit();

    // Clean the address bar: strip ref and utm_*, keep any other params and the hash.
    try {
      var clean = DPA.strippedUrl(search, window.location.pathname, window.location.hash);
      if (clean !== null) window.history.replaceState(null, '', clean);
    } catch (e) { /* replaceState unavailable — leave the URL as it is */ }
  })();

  // ── Ensure <head> has OG tags and all CSS files ──
  (function ensureHead() {
    var head = document.head;
    var title = document.title || '';
    var desc = (document.querySelector('meta[name="description"]') || {}).content || '';

    function ensureMeta(prop, content) {
      if (!content) return;
      if (head.querySelector('meta[property="' + prop + '"]')) return;
      var m = document.createElement('meta');
      m.setAttribute('property', prop);
      m.setAttribute('content', content);
      head.appendChild(m);
    }

    var site = (typeof DP_DATA !== 'undefined' && DP_DATA.site) || {};
    var page = location.pathname.split('/').pop() || 'index.html';
    ensureMeta('og:title', title);
    ensureMeta('og:description', desc);
    ensureMeta('og:type', 'website');
    ensureMeta('og:url', (site.base_url || '') + '/' + page);
    if (site.og_image) ensureMeta('og:image', site.og_image);

    // Ensure all CSS files are linked
    var cssFiles = ['design-system.css', 'docparse.css', 'prism.css', 'docs-layout.css', 'components.css'];
    cssFiles.forEach(function (file) {
      if (!head.querySelector('link[href$="' + file + '"]')) {
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'css/' + file;
        head.appendChild(link);
      }
    });
  })();

  // ── Inject data-dp values from DP_DATA ──
  if (typeof DP_DATA !== 'undefined' && typeof dpResolve === 'function') {
    document.querySelectorAll('[data-dp]').forEach(function (el) {
      var val = dpResolve(el.getAttribute('data-dp'));
      if (val !== undefined) {
        el.textContent = (typeof dpFormat === 'function') ? dpFormat(val) : String(val);
      }
    });
  }

  // ── Detect current page for active nav highlighting ──
  var path = window.location.pathname;
  function isActive(page) {
    if (page === 'index' || page === 'home') {
      return path.endsWith('/') || path.endsWith('/index.html') || path.endsWith('/docparse/');
    }
    return path.indexOf(page + '.html') !== -1;
  }

  function navLink(href, label, page) {
    var cls = isActive(page) ? ' class="dp-nav-active"' : '';
    return '<a href="' + href + '"' + cls + '>' + label + '</a>';
  }

  // ── GitHub SVG icon ──
  var ghIcon = '<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" style="vertical-align:-2px;margin-right:3px"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>';

  // ── Inject Header ──
  var headerMount = document.getElementById('header-mount');
  if (headerMount) {
    headerMount.outerHTML =
      '<header class="header">' +
        '<a href="index.html" class="nav-home" title="AILANG Parse">' +
          '<img src="img/docparse-logo.svg" alt="AILANG Parse" class="header-logo">' +
        '</a>' +
        '<span class="header-title">AILANG <span class="dp-accent">Parse</span></span>' +
        '<span class="dp-beta-badge">Beta</span>' +
        '<span class="header-sep"></span>' +
        '<span class="header-subtitle">Universal Document Parsing</span>' +

        // Primary navigation — page links
        '<nav class="header-nav dp-site-nav">' +
          navLink('index.html', 'Home', 'index') +
          navLink('workbench.html', 'Workbench', 'workbench') +
          navLink('docs.html', 'Docs', 'docs') +
          navLink('connect.html', 'Connect AI', 'connect') +
          navLink('api.html', 'API', 'api') +
          navLink('selfhost.html', 'Run Locally', 'selfhost') +
          navLink('pricing.html', 'Pricing', 'pricing') +
          navLink('benchmarks.html', 'Benchmarks', 'benchmarks') +
        '</nav>' +

        // Right-side links + auth
        '<div class="header-right">' +
          '<a href="https://ailang.sunholo.com/" target="_blank" rel="noopener">' +
            '<img src="img/ailang-logo.svg" alt="" width="14" height="14" style="vertical-align:-2px;margin-right:3px">AILANG' +
          '</a>' +
          '<a href="https://www.sunholo.com/" target="_blank" rel="noopener">' +
            '<img src="img/sunholo-logo.svg" alt="" width="14" height="14" style="vertical-align:-2px;margin-right:3px">sunholo.com' +
          '</a>' +
          '<div id="header-auth" class="dp-header-auth" style="display:none">' +
            '<button class="dp-header-auth-btn" onclick="document.getElementById(\'header-auth\').classList.toggle(\'open\')">' +
              '<img id="header-avatar" class="dp-header-avatar" src="" alt="">' +
              '<span id="header-user-name" class="dp-header-user-name"></span>' +
              '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><polyline points="2,4 5,7 8,4"/></svg>' +
            '</button>' +
            '<div class="dp-header-auth-menu">' +
              '<div id="header-user-email" class="dp-header-auth-email"></div>' +
              '<a href="/docparse/dashboard.html" class="dp-header-auth-item">Dashboard</a>' +
              '<button class="dp-header-auth-item" onclick="dpSignOut()">Sign out</button>' +
            '</div>' +
          '</div>' +
        '</div>' +

        // Mobile hamburger
        '<button class="dp-nav-toggle" aria-label="Toggle navigation" onclick="document.querySelector(\'.dp-site-nav\').classList.toggle(\'dp-nav-open\')">' +
          '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="5" x2="17" y2="5"/><line x1="3" y1="10" x2="17" y2="10"/><line x1="3" y1="15" x2="17" y2="15"/></svg>' +
        '</button>' +
      '</header>';
  }

  // ── Inject Pre-Footer CTA Band (feature pages only) ──
  var footerMount = document.getElementById('footer-mount');
  if (footerMount) {
    var page = location.pathname.split('/').pop() || 'index.html';
    var noCta = ['index.html', 'api.html', 'pricing.html', 'privacy.html', 'terms.html', 'docs.html'];
    var showCta = noCta.indexOf(page) === -1 && !document.querySelector('[data-no-cta]');
    if (showCta) {
      var ctaBand = document.createElement('div');
      ctaBand.style.cssText = 'max-width:700px;margin:40px auto 0;padding:20px 24px;border-radius:var(--radius);background:var(--dp-blue-faded,rgba(37,99,235,0.04));border:1px solid var(--dp-blue-border,rgba(37,99,235,0.15));text-align:center';
      ctaBand.innerHTML =
        '<div style="font-family:var(--font-display);font-size:14px;font-weight:700;color:var(--text-primary);margin-bottom:6px">Ready to parse at scale?</div>' +
        '<div style="font-size:12px;color:var(--text-secondary);line-height:1.6;margin-bottom:12px">Free tier: <span data-dp="pricing.tiers.free.requests_per_month">1,000</span> documents/month. Pro from &euro;<span data-dp="pricing.tiers.pro.price_eur">29</span>/mo.</div>' +
        '<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">' +
          '<a href="pricing.html" class="dp-btn dp-btn--primary" style="font-size:12px;padding:6px 16px;text-decoration:none">See Pricing</a>' +
          '<a href="api.html#getting-started" class="dp-btn dp-btn--secondary" style="font-size:12px;padding:6px 16px;text-decoration:none">Get API Key</a>' +
          '<a href="workbench.html" class="dp-btn dp-btn--ghost" style="font-size:12px;padding:6px 16px;text-decoration:none">Try Workbench</a>' +
        '</div>';
      footerMount.parentNode.insertBefore(ctaBand, footerMount);
    }

    // Link columns. The list is written by docs/scripts/stamp-site-nav.py from
    // docs/data/site-map.json; do not edit it here.
/* nav:footer */
  var FOOTER_COLS = [{"title": "Convert", "links": [["docx-to-markdown.html", "Word (DOCX) to Markdown"], ["pdf-to-word.html", "PDF to Word"], ["pdf-to-powerpoint.html", "PDF to PowerPoint"], ["document-generation.html", "Markdown to Word, PowerPoint and Excel"], ["templates.html", "Word proposal templates"]]}, {"title": "Compare", "links": [["docx-to-markdown.html", "Word (DOCX) to Markdown"], ["benchmarks.html", "Benchmarks"], ["migrate-from-unstructured.html", "Unstructured vs AILANG Parse"], ["vs-pdf-conversion.html", "Direct parsing vs PDF conversion"], ["why.html", "Why AILANG Parse"]]}, {"title": "Extract", "links": [["track-changes.html", "Track changes"], ["comments.html", "Comments"], ["tables.html", "Tables and merged cells"], ["chunking.html", "Chunking for RAG"], ["sec-filings.html", "SEC filings"]]}, {"title": "Formats", "links": [["docx-parsing.html", "DOCX"], ["xlsx-parsing.html", "XLSX"], ["pptx-parsing.html", "PPTX"], ["pdf-parsing.html", "PDF"], ["html-parsing.html", "HTML"], ["email-parsing.html", "Email"], ["odt-parsing.html", "ODT"], ["ods-parsing.html", "ODS"], ["odp-parsing.html", "ODP"], ["epub-parsing.html", "EPUB"], ["latex-parsing.html", "LaTeX"], ["rtf-parsing.html", "RTF"]]}, {"title": "Connect", "links": [["connect.html", "ChatGPT, Claude and Codex"], ["mcp.html", "MCP server"], ["claude-code.html", "Claude Code plugin"], ["api.html", "API and SDKs"], ["integrations.html", "Integrations"], ["superdoc.html", "SuperDoc for legal review"]]}, {"title": "Try, run and buy", "links": [["workbench.html", "Workbench"], ["selfhost.html", "Run locally"], ["performance.html", "Performance guide"], ["pricing.html", "Pricing"]]}];
/* /nav:footer */
    var footerCols = FOOTER_COLS.map(function (col) {
      return '<div class="footer-col' + (col.title === 'Formats' ? ' footer-col--formats' : '') + '"><h3>' + col.title + '</h3>' +
        col.links.map(function (l) { return '<a href="' + l[0] + '">' + l[1] + '</a>'; }).join('') + '</div>';
    }).join('');

    footerMount.outerHTML =
      '<footer class="footer">' +
        (footerCols ? '<nav class="footer-cols" aria-label="Site">' + footerCols + '</nav>' : '') +
        '<div class="footer-brand">' +
          '<img src="img/docparse-logo.svg" alt="AILANG Parse" width="22" height="22" style="border-radius:3px">' +
          '<span>AILANG <span style="color:var(--dp-blue)">Parse</span></span>' +
        '</div>' +
        '<div class="footer-line">' +
          'Powered by <a href="https://ailang.sunholo.com/"><img src="img/ailang-logo.svg" alt="" width="14" height="14" style="vertical-align:-2px;margin-right:3px">AILANG</a>' +
          '<span class="footer-sep"></span>' +
          '<a href="https://www.sunholo.com/">sunholo.com</a>' +
          '<span class="footer-sep"></span>' +
          '<a href="workbench.html">Workbench</a>' +
          '<span class="footer-sep"></span>' +
          '<a href="https://sunholo.com/ailang-demos/">Demos</a>' +
        '</div>' +
        '<div class="footer-line" style="margin-top:4px">' +
          '&copy; 2026 Holosun ApS' +
          '<span class="footer-sep"></span>' +
          '<span class="footer-version">v' + (window.DP_DATA && window.DP_DATA.version || '?') + '</span>' +
          (window.DP_DATA && window.DP_DATA.ailangVersion
            ? '<span class="footer-sep"></span>' +
              '<span class="footer-version" title="Pinned AILANG WASM runtime">' +
                'AILANG <a href="https://github.com/sunholo-data/ailang/releases/tag/' +
                window.DP_DATA.ailangVersion + '">' + window.DP_DATA.ailangVersion +
              '</a></span>'
            : '') +
          '<span class="footer-sep"></span>' +
          '<a href="privacy.html">Privacy</a>' +
          '<span class="footer-sep"></span>' +
          '<a href="terms.html">Terms</a>' +
        '</div>' +
      '</footer>';
  }

  // ── Section links: a "#" beside each heading with an id, to share that section ──
  document.querySelectorAll('.dp-docs-content h2[id], .dp-docs-content h3[id]').forEach(function (h) {
    if (h.id === 'related' || h.querySelector('.dp-anchor')) return;
    var a = document.createElement('a');
    a.className = 'dp-anchor';
    a.href = '#' + h.id;
    a.textContent = '#';
    a.setAttribute('aria-label', 'Link to this section');
    h.appendChild(a);
  });

  // ── Scroll Reveal (with staggered cascade) ──
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          // Auto-stagger siblings for cascade effect
          var siblings = entry.target.parentElement.querySelectorAll('.reveal');
          var index = Array.prototype.indexOf.call(siblings, entry.target);
          if (!entry.target.style.transitionDelay && !entry.target.className.match(/reveal-delay/)) {
            entry.target.style.transitionDelay = (index * 0.04) + 's';
          }
          entry.target.classList.add('visible');
        }
      });
    }, { threshold: 0.05, rootMargin: '0px 0px -10px 0px' });

    document.querySelectorAll('.reveal').forEach(function (el) {
      observer.observe(el);
    });
  }

  // ── Sidebar scroll-spy (shared across all sidebar pages) ──
  (function () {
    var sidebarLinks = document.querySelectorAll('.dp-docs-sidebar a[href^="#"]');
    if (!sidebarLinks.length) return;
    var sections = [];
    sidebarLinks.forEach(function (a) {
      var id = a.getAttribute('href').slice(1);
      var el = document.getElementById(id);
      if (el) sections.push({ el: el, link: a });
    });
    function updateSpy() {
      var active = sections[0];
      sections.forEach(function (s) {
        if (s.el.getBoundingClientRect().top <= 120) active = s;
      });
      sidebarLinks.forEach(function (a) { a.classList.remove('active'); });
      if (active) active.link.classList.add('active');
    }
    window.addEventListener('scroll', updateSpy, { passive: true });
    updateSpy();
  })();

  // ── Output example tabs (reusable across pages) ──
  document.querySelectorAll('.dp-output-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      var tabId = this.getAttribute('data-tab');
      var container = this.closest('.dp-output-container') || document;
      container.querySelectorAll('.dp-output-tab').forEach(function (t) { t.classList.remove('active'); });
      container.querySelectorAll('.dp-output-panel').forEach(function (p) { p.classList.remove('active'); });
      this.classList.add('active');
      var panel = container.querySelector('#panel-' + tabId) || document.getElementById('panel-' + tabId);
      if (panel) panel.classList.add('active');
    });
  });

  // ── Active nav highlight on scroll (for index.html anchor sections) ──
  var sectionNavLinks = document.querySelectorAll('.dp-section-nav a');
  if (sectionNavLinks.length > 0) {
    var sections = [];
    sectionNavLinks.forEach(function (link) {
      var id = link.getAttribute('href').replace('#', '');
      var sec = document.getElementById(id);
      if (sec) sections.push({ el: sec, link: link });
    });

    function updateActiveSection() {
      var scrollY = window.scrollY + 120;
      var current = null;
      sections.forEach(function (s) {
        if (s.el.offsetTop <= scrollY) current = s;
      });
      sectionNavLinks.forEach(function (l) {
        l.classList.remove('dp-nav-active');
      });
      if (current) {
        current.link.classList.add('dp-nav-active');
      }
    }

    window.addEventListener('scroll', updateActiveSection, { passive: true });
    updateActiveSection();
  }

  // ── Rewrite API URLs in code blocks when ?api= override is active ──
  var DEFAULT_API = 'https://docparse.ailang.sunholo.com';
  if (API_BASE !== DEFAULT_API) {
    document.querySelectorAll('pre code').forEach(function (el) {
      if (el.innerHTML.indexOf(DEFAULT_API) !== -1) {
        el.innerHTML = el.innerHTML.split(DEFAULT_API).join(API_BASE);
      }
    });
    document.querySelectorAll('a[href*="' + DEFAULT_API + '"]').forEach(function (el) {
      el.href = el.href.replace(DEFAULT_API, API_BASE);
    });
  }

  // ── Load external code examples via data-src ──
  document.querySelectorAll('code[data-src]').forEach(function (el) {
    var src = el.getAttribute('data-src');
    fetch(src)
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.text();
      })
      .then(function (text) {
        el.textContent = text;
        if (window.Prism) Prism.highlightElement(el);
      })
      .catch(function () {
        // Keep inline fallback content — do nothing
      });
  });

  // ── Inject data-dp values from static DP_DATA immediately ──
  function injectDataDp() {
    document.querySelectorAll('[data-dp]').forEach(function (el) {
      var val = dpResolve(el.getAttribute('data-dp'));
      if (val !== undefined && typeof val !== 'object') {
        el.textContent = dpFormat(val);
      }
    });
  }
  if (typeof DP_DATA !== 'undefined') injectDataDp();

  // ── Fetch live pricing to overlay DP_DATA (best-effort) ──
  if (typeof DP_DATA !== 'undefined' && DP_DATA.pricing) {
    fetch(API_BASE + '/api/v1/pricing', { signal: AbortSignal.timeout(5000) })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.tiers) return;
        // Merge live API values into DP_DATA (static fallbacks remain for missing fields)
        // Map legacy "enterprise" → "business"
        for (var name in data.tiers) {
          var target = (name === 'enterprise') ? 'business' : name;
          if (!DP_DATA.pricing.tiers[target]) DP_DATA.pricing.tiers[target] = {};
          for (var key in data.tiers[name]) {
            DP_DATA.pricing.tiers[target][key] = data.tiers[name][key];
          }
        }
        delete DP_DATA.pricing.tiers['enterprise'];
        // Re-inject data-dp values with merged data
        injectDataDp();
      })
      .catch(function () { /* API unavailable — static values stand */ });
  }
})();
