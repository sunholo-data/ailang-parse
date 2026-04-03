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

  /**
   * Start Stripe checkout for a tier ('pro' or 'business').
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
