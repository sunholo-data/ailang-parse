// Unit tests for campaign attribution + the visit counter:
//   docs/js/components.js   first-touch capture, cookie, URL strip, visit beacon
//   docs/js/firebase-app.js claim body and clear-on-success
//
// Run from repo root:  node --test docs/js/__tests__/*.test.mjs
//
// Both files are browser IIFEs. Each test loads the real file into a fresh vm
// context whose `window` is the context itself (as in a browser) with small
// stubs for location, history, localStorage, document.cookie and navigator.
// All codes and campaign values are invented.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const COMPONENTS = readFileSync(new URL('../components.js', import.meta.url), 'utf8');
const FIREBASE_APP = readFileSync(new URL('../firebase-app.js', import.meta.url), 'utf8');

// Cross-realm values → plain values of this realm.
const plain = (v) => JSON.parse(JSON.stringify(v));

function makeStorage(initial = {}, { broken = false } = {}) {
  const data = new Map(Object.entries(initial));
  const guard = () => { if (broken) throw new Error('SecurityError: storage disabled'); };
  return {
    data,
    getItem: (k) => { guard(); return data.has(k) ? data.get(k) : null; },
    setItem: (k, v) => { guard(); data.set(k, String(v)); },
    removeItem: (k) => { guard(); data.delete(k); },
  };
}

// A minimal cookie jar: remembers every raw write, honours Max-Age=0.
function makeCookieJar(initial = {}) {
  const jar = new Map(Object.entries(initial));
  const writes = [];
  return {
    jar,
    writes,
    get cookie() { return [...jar].map(([k, v]) => `${k}=${v}`).join('; '); },
    set cookie(raw) {
      writes.push(raw);
      const [pair, ...attrs] = raw.split(/;\s*/);
      const eq = pair.indexOf('=');
      const name = pair.slice(0, eq);
      const value = pair.slice(eq + 1);
      if (attrs.some((a) => /^max-age=0$/i.test(a))) jar.delete(name);
      else jar.set(name, value);
    },
  };
}

function baseContext(href, { storage, cookies, navigator } = {}) {
  const url = new URL(href);
  const replaced = [];
  const ctx = {
    console: { log() {}, warn() {}, error() {} },
    URLSearchParams,
    Blob,
    location: {
      hostname: url.hostname,
      pathname: url.pathname,
      search: url.search,
      hash: url.hash,
    },
    history: { replaceState: (_s, _t, u) => replaced.push(u) },
    localStorage: storage || makeStorage(),
    navigator: navigator || {},
  };
  return { ctx, replaced, cookies: cookies || makeCookieJar() };
}

function beaconNavigator(extra = {}) {
  const beacons = [];
  return {
    beacons,
    nav: {
      webdriver: false,
      sendBeacon: (u, blob) => { beacons.push({ url: u, blob }); return true; },
      ...extra,
    },
  };
}

// Load components.js as a browser would on `href`.
function loadComponents(href, opts = {}) {
  const { ctx, replaced, cookies } = baseContext(href, opts);
  const jar = cookies;
  ctx.document = {
    get cookie() { return jar.cookie; },
    set cookie(v) { jar.cookie = v; },
    title: '',
    head: { querySelector: () => null, appendChild() {} },
    createElement: () => ({ setAttribute() {} }),
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
  };
  vm.createContext(ctx);
  ctx.window = ctx;
  vm.runInContext(COMPONENTS, ctx, { filename: 'components.js' });
  return { ctx, replaced, cookies: jar, storage: ctx.localStorage };
}

const SITE = 'https://www.sunholo.com/ailang-parse/';

// ── first-touch rule ────────────────────────────────────────────────────

test('first touch stores docparse_ref, docparse_attr and the dp_attr cookie', () => {
  const { nav } = beaconNavigator();
  const { storage, cookies } = loadComponents(
    `${SITE}pricing.html?ref=demo-partner&utm_source=demo&utm_medium=email`, { navigator: nav });
  assert.equal(storage.getItem('docparse_ref'), 'demo-partner');
  const attr = JSON.parse(storage.getItem('docparse_attr'));
  assert.equal(attr.ref, 'demo-partner');
  assert.equal(attr.utm_source, 'demo');
  assert.equal(attr.utm_medium, 'email');
  assert.equal(attr.landing, '/ailang-parse/pricing.html');
  assert.match(attr.at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  assert.deepEqual(JSON.parse(decodeURIComponent(cookies.jar.get('dp_attr'))), attr);
});

test('a later touch never overwrites the stored attribution', () => {
  const first = JSON.stringify({ ref: 'first-partner', utm_source: 'one', landing: '/ailang-parse/', at: '2026-01-01T00:00:00.000Z' });
  const storage = makeStorage({ docparse_ref: 'first-partner', docparse_attr: first });
  const { cookies } = loadComponents(`${SITE}?ref=second-partner&utm_source=two`, { storage });
  assert.equal(storage.getItem('docparse_ref'), 'first-partner');
  assert.equal(storage.getItem('docparse_attr'), first);
  assert.equal(cookies.writes.length, 0, 'cookie must not be rewritten');
});

test('an existing dp_attr cookie also blocks a new first touch', () => {
  const cookies = makeCookieJar({ dp_attr: encodeURIComponent('{"ref":"first-partner"}') });
  const { storage } = loadComponents(`${SITE}?utm_source=two`, { cookies });
  assert.equal(storage.getItem('docparse_attr'), null);
  assert.equal(cookies.writes.length, 0);
});

test('a utm-only touch stores docparse_attr but not docparse_ref', () => {
  const { storage } = loadComponents(`${SITE}?utm_source=newsletter&utm_campaign=launch`);
  assert.equal(storage.getItem('docparse_ref'), null);
  assert.deepEqual(
    Object.keys(JSON.parse(storage.getItem('docparse_attr'))).sort(),
    ['at', 'landing', 'utm_campaign', 'utm_source']);
});

test('docparse_ref keeps first-touch-wins independently of docparse_attr', () => {
  // Arrived first via a utm-only link, later via a partner link: the partner
  // code still lands in docparse_ref exactly as before, the attr stays put.
  const first = JSON.stringify({ utm_source: 'one', landing: '/ailang-parse/', at: '2026-01-01T00:00:00.000Z' });
  const storage = makeStorage({ docparse_attr: first });
  loadComponents(`${SITE}?ref=demo-partner`, { storage });
  assert.equal(storage.getItem('docparse_ref'), 'demo-partner');
  assert.equal(storage.getItem('docparse_attr'), first);
});

test('no campaign in the URL stores nothing and sets no cookie', () => {
  const { storage, cookies, replaced } = loadComponents(`${SITE}docs.html?page=2#install`);
  assert.equal(storage.data.size, 0);
  assert.equal(cookies.writes.length, 0);
  assert.deepEqual(replaced, [], 'nothing to strip, URL untouched');
});

test('other origins capture nothing and keep the URL', () => {
  const { nav, beacons } = beaconNavigator();
  const { storage, cookies, replaced } = loadComponents(
    'http://127.0.0.1:8971/index.html?ref=demo-partner&utm_source=demo', { navigator: nav });
  assert.equal(storage.data.size, 0);
  assert.equal(cookies.writes.length, 0);
  assert.deepEqual(replaced, []);
  assert.equal(beacons.length, 0);
});

test('broken localStorage still sets the cookie and never throws', () => {
  const storage = makeStorage({}, { broken: true });
  const { cookies, replaced } = loadComponents(`${SITE}?ref=demo-partner`, { storage });
  assert.ok(cookies.jar.has('dp_attr'));
  assert.deepEqual(replaced, ['/ailang-parse/']);
});

// ── validation ──────────────────────────────────────────────────────────

test('a malformed ref is dropped', () => {
  for (const bad of ['A', 'Demo-Partner', 'x', 'a'.repeat(33), 'demo_partner', 'demo partner', '<b>']) {
    const { storage } = loadComponents(`${SITE}?ref=${encodeURIComponent(bad)}`);
    assert.equal(storage.getItem('docparse_ref'), null, bad);
    assert.equal(storage.getItem('docparse_attr'), null, bad);
  }
});

test('oversized or markup-bearing utm values are dropped, valid ones kept', () => {
  const qs = new URLSearchParams({
    utm_source: 'demo',
    utm_medium: 'm'.repeat(101),
    utm_campaign: '<script>alert(1)</script>',
    utm_content: 'say "hi"',
    utm_term: 'x'.repeat(100),
  });
  const { storage } = loadComponents(`${SITE}?${qs}`);
  const attr = JSON.parse(storage.getItem('docparse_attr'));
  assert.equal(attr.utm_source, 'demo');
  assert.equal(attr.utm_term, 'x'.repeat(100));
  assert.equal('utm_medium' in attr, false);
  assert.equal('utm_campaign' in attr, false);
  assert.equal('utm_content' in attr, false);
});

test('landing is capped at 200 characters', () => {
  const DPA = loadComponents(`${SITE}`).ctx.DocParseAttribution;
  const attr = DPA.buildAttr('?utm_source=demo', '/' + 'p'.repeat(300), '2026-01-01T00:00:00.000Z');
  assert.equal(attr.landing.length, 200);
});

// ── URL stripping ───────────────────────────────────────────────────────

test('ref and every utm_* are stripped, other params and the hash kept', () => {
  const { replaced } = loadComponents(
    `${SITE}api.html?env=dev&ref=demo-partner&utm_source=demo&utm_medium=email&utm_campaign=c&utm_content=x&utm_term=t&tab=keys#getting-started`);
  assert.deepEqual(replaced, ['/ailang-parse/api.html?env=dev&tab=keys#getting-started']);
});

test('invalid campaign params are stripped too', () => {
  const { replaced, storage } = loadComponents(`${SITE}?ref=NOT_VALID&utm_source=${'z'.repeat(150)}`);
  assert.deepEqual(replaced, ['/ailang-parse/']);
  assert.equal(storage.data.size, 0);
});

// ── cookie string ───────────────────────────────────────────────────────

test('dp_attr cookie string has the contract attributes', () => {
  const DPA = loadComponents(`${SITE}`).ctx.DocParseAttribution;
  const attr = { ref: 'demo-partner', utm_source: 'demo', landing: '/ailang-parse/', at: '2026-01-01T00:00:00.000Z' };
  assert.equal(
    DPA.cookieString(attr),
    'dp_attr=' + encodeURIComponent(JSON.stringify(attr)) +
      '; Domain=.sunholo.com; Path=/; Max-Age=7776000; SameSite=Lax; Secure');
});

// ── visit beacon ────────────────────────────────────────────────────────

async function beaconBody(b) { return JSON.parse(await b.blob.text()); }

test('landing visit beacons path and campaign from the current URL', async () => {
  const { nav, beacons } = beaconNavigator();
  loadComponents(`${SITE}pricing.html?ref=demo-partner&utm_source=demo&utm_medium=${'m'.repeat(101)}`, { navigator: nav });
  assert.equal(beacons.length, 1);
  assert.equal(beacons[0].url, 'https://docparse.ailang.sunholo.com/api/v1/visit');
  assert.equal(beacons[0].blob.type, 'text/plain');
  assert.deepEqual(await beaconBody(beacons[0]),
    { site: 'ailang-parse', page: '/ailang-parse/pricing.html', ref: 'demo-partner', utm_source: 'demo' });
});

test('a later page view carries no campaign even with attribution stored', async () => {
  const { nav, beacons } = beaconNavigator();
  const storage = makeStorage({ docparse_ref: 'demo-partner', docparse_attr: '{"ref":"demo-partner"}' });
  loadComponents(`${SITE}docs.html`, { navigator: nav, storage });
  assert.deepEqual(await beaconBody(beacons[0]), { site: 'ailang-parse', page: '/ailang-parse/docs.html' });
});

test('the beacon carries no cookie and no identifier fields', async () => {
  const { nav, beacons } = beaconNavigator();
  const cookies = makeCookieJar({ dp_attr: 'x', other: 'y' });
  loadComponents(`${SITE}?utm_source=demo`, { navigator: nav, cookies });
  const body = await beaconBody(beacons[0]);
  assert.deepEqual(Object.keys(body).sort(), ['page', 'site', 'utm_source']);
});

test('the beacon follows ?env= and ?api= like the rest of the site', () => {
  for (const [qs, base] of [
    ['?env=dev', 'https://ailang-dev-docparse-api-ejjw6zt3bq-ew.a.run.app'],
    ['?env=test', 'https://ailang-test-docparse-api-rrmdhcxo4a-ew.a.run.app'],
    ['?env=prod', 'https://docparse.ailang.sunholo.com'],
    ['?env=dev&api=https://example.invalid', 'https://example.invalid'],
  ]) {
    const { nav, beacons } = beaconNavigator();
    loadComponents(`${SITE}${qs}`, { navigator: nav });
    assert.equal(beacons[0].url, `${base}/api/v1/visit`, qs);
  }
});

test('beacon is skipped under automation, DNT, GPC, or without sendBeacon', () => {
  const cases = [
    ['webdriver', { webdriver: true }],
    ['dnt', { doNotTrack: '1' }],
    ['gpc', { globalPrivacyControl: true }],
  ];
  for (const [why, extra] of cases) {
    const { nav, beacons } = beaconNavigator(extra);
    loadComponents(`${SITE}?ref=demo-partner`, { navigator: nav });
    assert.equal(beacons.length, 0, why);
  }
  // No sendBeacon: no throw, attribution still captured.
  const { storage } = loadComponents(`${SITE}?ref=demo-partner`, { navigator: { webdriver: false } });
  assert.equal(storage.getItem('docparse_ref'), 'demo-partner');
});

test('visitSkipReason names each skip condition', () => {
  const DPA = loadComponents(`${SITE}`).ctx.DocParseAttribution;
  const send = () => true;
  const host = 'www.sunholo.com';
  assert.equal(DPA.visitSkipReason(host, { sendBeacon: send }, {}), null);
  assert.equal(DPA.visitSkipReason('localhost', { sendBeacon: send }, {}), 'host');
  assert.equal(DPA.visitSkipReason(host, { webdriver: true, sendBeacon: send }, {}), 'webdriver');
  assert.equal(DPA.visitSkipReason(host, { doNotTrack: '1', sendBeacon: send }, {}), 'dnt');
  assert.equal(DPA.visitSkipReason(host, { sendBeacon: send }, { doNotTrack: '1' }), 'dnt');
  assert.equal(DPA.visitSkipReason(host, { doNotTrack: '0', sendBeacon: send }, {}), null);
  assert.equal(DPA.visitSkipReason(host, { globalPrivacyControl: true, sendBeacon: send }, {}), 'gpc');
  assert.equal(DPA.visitSkipReason(host, {}, {}), 'no-beacon');
});

test('docparseVisit sends at most once per page load', () => {
  const { nav, beacons } = beaconNavigator();
  const { ctx } = loadComponents(`${SITE}`, { navigator: nav });
  assert.equal(ctx.docparseVisit(), false);
  assert.equal(beacons.length, 1);
});

test('a throwing sendBeacon never breaks the page', () => {
  const nav = { webdriver: false, sendBeacon: () => { throw new Error('boom'); } };
  const { replaced } = loadComponents(`${SITE}?ref=demo-partner`, { navigator: nav });
  assert.deepEqual(replaced, ['/ailang-parse/']);
});

// ── claim body + clear (firebase-app.js) ────────────────────────────────

function loadFirebaseApp({ storage, cookies, fetchResult } = {}) {
  const { ctx } = baseContext('https://www.sunholo.com/ailang-parse/api.html', { storage });
  const jar = cookies || makeCookieJar();
  let authCallback = null;
  const fetches = [];
  ctx.document = {
    readyState: 'complete',
    get cookie() { return jar.cookie; },
    set cookie(v) { jar.cookie = v; },
    addEventListener() {},
    getElementById: () => null,
    querySelectorAll: () => [],
  };
  ctx.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  ctx.dispatchEvent = () => true;
  ctx.firebase = {
    initializeApp: () => ({}),
    auth: Object.assign(() => ({
      onAuthStateChanged: (cb) => { authCallback = cb; },
      isSignInWithEmailLink: () => false,
    }), { GoogleAuthProvider: {}, GithubAuthProvider: {}, EmailAuthProvider: {} }),
  };
  ctx.fetch = async (url, init) => {
    fetches.push({ url, init });
    return { json: async () => fetchResult || { ok: true } };
  };
  vm.createContext(ctx);
  ctx.window = ctx;
  vm.runInContext(FIREBASE_APP, ctx, { filename: 'firebase-app.js' });
  const signIn = async () => {
    authCallback({ email: 'someone@example.com', getIdToken: async () => 'id-token' });
    for (let i = 0; i < 5; i++) await new Promise(setImmediate);
  };
  return { ctx, fetches, signIn, jar, storage: ctx.localStorage };
}

test('claim body comes from docparse_attr, without `at`', () => {
  const { ctx } = loadFirebaseApp();
  const attr = JSON.stringify({ ref: 'demo-partner', utm_source: 'demo', utm_campaign: 'launch', landing: '/ailang-parse/pricing.html', at: '2026-01-01T00:00:00.000Z' });
  assert.deepEqual(plain(ctx.dpBuildClaimBody(attr, 'other-partner', '')),
    { ref: 'demo-partner', utm_source: 'demo', utm_campaign: 'launch', landing: '/ailang-parse/pricing.html' });
});

test('claim body falls back to docparse_ref, then the cookie', () => {
  const { ctx } = loadFirebaseApp();
  const cookie = 'other=1; dp_attr=' + encodeURIComponent(JSON.stringify({ ref: 'cookie-partner', utm_source: 'cookie-src', landing: '/ailang-parse/' }));
  // Old visitors: only the bare code.
  assert.deepEqual(plain(ctx.dpBuildClaimBody(null, 'demo-partner', '')), { ref: 'demo-partner' });
  // attr without a ref: ref from docparse_ref, utm from attr (not the cookie).
  assert.deepEqual(plain(ctx.dpBuildClaimBody('{"utm_source":"demo"}', 'demo-partner', cookie)),
    { ref: 'demo-partner', utm_source: 'demo' });
  // docparse_ref beats the cookie's ref.
  assert.deepEqual(plain(ctx.dpBuildClaimBody(null, 'demo-partner', cookie)),
    { ref: 'demo-partner', utm_source: 'cookie-src', landing: '/ailang-parse/' });
  // Nothing in localStorage at all: the cookie alone.
  assert.deepEqual(plain(ctx.dpBuildClaimBody(null, null, cookie)),
    { ref: 'cookie-partner', utm_source: 'cookie-src', landing: '/ailang-parse/' });
});

test('claim body re-validates and returns null when nothing is claimable', () => {
  const { ctx } = loadFirebaseApp();
  assert.equal(ctx.dpBuildClaimBody(null, null, ''), null);
  assert.equal(ctx.dpBuildClaimBody('not json', 'BAD REF', 'dp_attr=%E0%A4%A'), null);
  assert.equal(ctx.dpBuildClaimBody('{"ref":"X!","utm_source":"<x>"}', null, ''), null);
  assert.deepEqual(plain(ctx.dpBuildClaimBody(JSON.stringify({ utm_source: 'demo', utm_medium: 'm'.repeat(101) }), null, '')),
    { utm_source: 'demo' });
});

test('sign-in posts the claim and clears all three stores on success', async () => {
  const storage = makeStorage({
    docparse_ref: 'demo-partner',
    docparse_attr: JSON.stringify({ ref: 'demo-partner', utm_source: 'demo', landing: '/ailang-parse/', at: '2026-01-01T00:00:00.000Z' }),
  });
  const cookies = makeCookieJar({ dp_attr: 'x' });
  const { fetches, signIn } = loadFirebaseApp({ storage, cookies, fetchResult: { ok: true } });
  await signIn();
  assert.equal(fetches.length, 1);
  assert.equal(fetches[0].url, 'https://ailang-docparse-api-ao6kuhcibq-ew.a.run.app/api/v1/referral/claim');
  assert.equal(fetches[0].init.headers.Authorization, 'Bearer id-token');
  assert.deepEqual(JSON.parse(fetches[0].init.body), { ref: 'demo-partner', utm_source: 'demo', landing: '/ailang-parse/' });
  assert.equal(storage.getItem('docparse_ref'), null);
  assert.equal(storage.getItem('docparse_attr'), null);
  assert.ok(cookies.writes.includes('dp_attr=; Domain=.sunholo.com; Path=/; Max-Age=0; SameSite=Lax; Secure'));
  assert.equal(cookies.jar.has('dp_attr'), false);
});

test('a refused claim keeps everything for the next sign-in', async () => {
  const storage = makeStorage({ docparse_ref: 'demo-partner', docparse_attr: '{"ref":"demo-partner"}' });
  const cookies = makeCookieJar({ dp_attr: 'x' });
  const { fetches, signIn } = loadFirebaseApp({ storage, cookies, fetchResult: { ok: false, error: { code: 'X' } } });
  await signIn();
  assert.equal(fetches.length, 1);
  assert.equal(storage.getItem('docparse_ref'), 'demo-partner');
  assert.equal(storage.getItem('docparse_attr'), '{"ref":"demo-partner"}');
  assert.equal(cookies.writes.length, 0);
});

test('sign-in without stored attribution makes no claim request', async () => {
  const { fetches, signIn } = loadFirebaseApp();
  await signIn();
  assert.equal(fetches.length, 0);
});
