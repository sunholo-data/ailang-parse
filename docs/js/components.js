/**
 * AILANG Parse — API base URL
 * Override via ?api=https://your-endpoint.run.app in the URL.
 * Or change DP_DATA.site.api_url in site-data.js to update all pages at once.
 */
var _dpParams = (typeof window !== 'undefined') ? new URLSearchParams(window.location.search) : null;
var _dpApiUrl = (typeof DP_DATA !== 'undefined' && DP_DATA.site && DP_DATA.site.api_url) || null;
var API_BASE = (_dpParams && _dpParams.get('api')) || _dpApiUrl || 'https://ailang-dev-docparse-api-ejjw6zt3bq-ew.a.run.app';

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
        '<span class="header-sep"></span>' +
        '<span class="header-subtitle">Universal Document Parsing</span>' +

        // Primary navigation — page links
        '<nav class="header-nav dp-site-nav">' +
          navLink('index.html', 'Home', 'index') +
          navLink('docs.html', 'Docs', 'docs') +
          navLink('api.html', 'API', 'api') +
          navLink('selfhost.html', 'Run Locally', 'selfhost') +
          navLink('benchmarks.html', 'Benchmarks', 'benchmarks') +
        '</nav>' +

        // Right-side links + auth
        '<div class="header-right">' +
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

  // ── Inject Footer ──
  var footerMount = document.getElementById('footer-mount');
  if (footerMount) {
    footerMount.outerHTML =
      '<footer class="footer">' +
        '<div class="footer-brand">' +
          '<img src="img/docparse-logo.svg" alt="AILANG Parse" width="22" height="22" style="border-radius:3px">' +
          '<span>AILANG <span style="color:var(--dp-blue)">Parse</span></span>' +
        '</div>' +
        '<div class="footer-line">' +
          'Powered by <a href="https://github.com/sunholo-data/ailang">AILANG</a>' +
          '<span class="footer-sep"></span>' +
          '<a href="https://www.sunholo.com/">sunholo.com</a>' +
          '<span class="footer-sep"></span>' +
          '<a href="https://sunholo.com/ailang-demos/">Demos</a>' +
        '</div>' +
        '<div class="footer-line" style="margin-top:4px">' +
          '&copy; 2026 Holosun ApS' +
        '</div>' +
      '</footer>';
  }

  // ── Scroll Reveal ──
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
        }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

    document.querySelectorAll('.reveal').forEach(function (el) {
      observer.observe(el);
    });
  }

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
  var DEFAULT_API = 'https://ailang-dev-docparse-api-ejjw6zt3bq-ew.a.run.app';
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
