/**
 * AILANG Parse — Shared Stripe Checkout Module
 * Provides dpCheckout.init() and dpCheckout.start(tier) for any page
 * with Firebase Auth loaded.
 *
 * Requires: firebase-app.js loaded first (provides firebase.auth()).
 */
(function () {
  'use strict';

  var BILLING_URLS = {
    dev:  'https://ailang-dev-billing-api-ejjw6zt3bq-ew.a.run.app',
    test: 'https://ailang-test-billing-api-rrmdhcxo4a-ew.a.run.app',
    prod: 'https://ailang-billing-api-ao6kuhcibq-ew.a.run.app'
  };

  var envParam = new URLSearchParams(window.location.search).get('env');
  var env = envParam || ((window.location.hostname === 'www.sunholo.com' || window.location.hostname === 'sunholo.com') ? 'prod' : 'dev');
  var BILLING_BASE = BILLING_URLS[env] || BILLING_URLS.dev;

  var config = { prices: {} };
  var configReady = false;

  // Unwrap AILANG serve-api Result responses
  function unwrap(data) {
    var r = data.result;
    if (typeof r === 'string') {
      try { return JSON.parse(r); } catch (e) { return { error: r }; }
    }
    if (r && r.__tag === 'Ok' && r.fields && r.fields[0]) {
      var inner = r.fields[0];
      if (typeof inner === 'string') {
        try { return JSON.parse(inner); } catch (e) { return { value: inner }; }
      }
      return inner;
    }
    if (r && r.__tag === 'Err' && r.fields && r.fields[0]) {
      return { error: r.fields[0] };
    }
    return r || data;
  }

  function init() {
    return fetch(BILLING_BASE + '/billing/config')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var cfg = unwrap(data);
        if (cfg && cfg.prices) {
          config = cfg;
          configReady = true;
        }
      })
      .catch(function () { /* config fetch failed — checkout will show error */ });
  }

  // ── ToS confirmation modal ──
  var modalEl = null;

  function showConfirm(tier, onAccept) {
    if (modalEl) modalEl.remove();

    var tierLabel = tier.charAt(0).toUpperCase() + tier.slice(1);
    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;padding:20px';
    overlay.innerHTML =
      '<div style="background:var(--bg-card,#fff);border-radius:12px;padding:28px 24px;max-width:400px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.2);font-family:var(--font-body,system-ui,sans-serif)">' +
        '<div style="font-family:var(--font-display,system-ui,sans-serif);font-size:16px;font-weight:700;color:var(--text-primary,#111);margin-bottom:12px">Subscribe to ' + tierLabel + '</div>' +
        '<label style="display:flex;align-items:flex-start;gap:8px;font-size:13px;color:var(--text-secondary,#555);cursor:pointer;line-height:1.5">' +
          '<input type="checkbox" id="dp-tos-agree" style="margin-top:3px;accent-color:var(--dp-blue,#2563eb)">' +
          '<span>I agree to the <a href="/docparse/terms.html" target="_blank" style="color:var(--dp-blue,#2563eb)">Terms of Service</a> and <a href="/docparse/privacy.html" target="_blank" style="color:var(--dp-blue,#2563eb)">Privacy Policy</a></span>' +
        '</label>' +
        '<div style="display:flex;gap:10px;margin-top:18px;justify-content:flex-end">' +
          '<button id="dp-tos-cancel" class="dp-btn dp-btn--ghost" style="font-size:13px;padding:6px 16px;cursor:pointer">Cancel</button>' +
          '<button id="dp-tos-continue" class="dp-btn dp-btn--primary" style="font-size:13px;padding:6px 16px;opacity:0.5;pointer-events:none;cursor:pointer">Continue to Checkout</button>' +
        '</div>' +
      '</div>';

    document.body.appendChild(overlay);
    modalEl = overlay;

    var checkbox = overlay.querySelector('#dp-tos-agree');
    var continueBtn = overlay.querySelector('#dp-tos-continue');
    var cancelBtn = overlay.querySelector('#dp-tos-cancel');

    checkbox.addEventListener('change', function () {
      continueBtn.style.opacity = this.checked ? '1' : '0.5';
      continueBtn.style.pointerEvents = this.checked ? '' : 'none';
    });

    cancelBtn.addEventListener('click', function () { overlay.remove(); modalEl = null; });
    overlay.addEventListener('click', function (e) { if (e.target === overlay) { overlay.remove(); modalEl = null; } });

    continueBtn.addEventListener('click', function () {
      overlay.remove();
      modalEl = null;
      onAccept();
    });
  }

  /**
   * Start Stripe checkout for a tier ('pro' or 'business').
   * Shows a ToS confirmation modal before redirecting to Stripe.
   * @param {string} tier - 'pro' or 'business'
   * @param {HTMLElement} [btn] - optional button to update text during redirect
   */
  function start(tier, btn) {
    var user = typeof firebase !== 'undefined' && firebase.auth && firebase.auth().currentUser;
    if (!user) {
      if (typeof dpSignIn === 'function') dpSignIn();
      else window.location.href = '/docparse/dashboard.html';
      return;
    }

    var priceKey = tier + '_monthly';
    var priceId = config.prices && config.prices[priceKey];
    if (!priceId) {
      alert('Billing not configured — please try again in a moment');
      return;
    }

    showConfirm(tier, function () {
      var origText = btn ? btn.textContent : '';
      if (btn) { btn.textContent = 'Redirecting\u2026'; btn.style.pointerEvents = 'none'; }

      user.getIdToken().then(function (token) {
        var body = JSON.stringify({
          priceId: priceId,
          successUrl: window.location.origin + window.location.pathname + '?upgraded=1',
          cancelUrl: window.location.origin + window.location.pathname + '?cancelled=1'
        });
        return fetch(BILLING_BASE + '/billing/checkout-session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
          body: JSON.stringify({ args: [user.uid, user.email, body] })
        });
      }).then(function (r) { return r.json(); })
        .then(function (data) {
          var result = unwrap(data);
          if (result.url) {
            window.location.href = result.url;
          } else {
            alert('Checkout error: ' + (result.error || JSON.stringify(result)));
            if (btn) { btn.textContent = origText; btn.style.pointerEvents = ''; }
          }
        }).catch(function (err) {
          alert('Checkout failed: ' + err.message);
          if (btn) { btn.textContent = origText; btn.style.pointerEvents = ''; }
        });
    });
  }

  function isReady() { return configReady; }
  function getConfig() { return config; }
  function getBillingBase() { return BILLING_BASE; }

  window.dpCheckout = {
    init: init,
    start: start,
    isReady: isReady,
    getConfig: getConfig,
    getBillingBase: getBillingBase
  };
})();
