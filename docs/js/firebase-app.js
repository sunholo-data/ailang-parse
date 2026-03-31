/**
 * AILANG Parse — Firebase Auth + API Key Management
 *
 * Reuses the ailang-multivac-dev Firebase project (same as website-builder).
 * AILANG Parse uses its own Firestore database ("docparse") — not the default.
 *
 * Auth pattern: Google sign-in popup → ID token → call Cloud Run key mgmt endpoints.
 * API keys stored server-side in Firestore. User's Google API key (for WASM AI)
 * stored in localStorage only.
 */
(function () {
  'use strict';

  // ── Firebase Config (same project as website-builder) ──
  var firebaseConfig = {
    apiKey: "AIzaSyCkvFxVilpZkqao1ntOPQbhwMy2GJI0FIE",
    authDomain: "ailang-multivac-dev.firebaseapp.com",
    projectId: "ailang-multivac-dev",
    storageBucket: "ailang-multivac-dev.appspot.com",
    messagingSenderId: "812435936917",
    appId: "1:812435936917:web:2dcf2a315dfc7cb2b66d9c"
  };

  var API_BASE = 'https://ailang-dev-docparse-api-ejjw6zt3bq-ew.a.run.app';

  var app = null;
  var auth = null;
  var currentUser = null;

  // ── Initialize ──
  function init() {
    if (typeof firebase === 'undefined') {
      console.warn('Firebase SDK not loaded — auth disabled');
      return;
    }
    try {
      app = firebase.initializeApp(firebaseConfig);
      auth = firebase.auth();
      auth.onAuthStateChanged(onAuthChange);
    } catch (e) {
      console.warn('Firebase init failed:', e.message);
    }
  }

  // ── Auth State Change ──
  function onAuthChange(user) {
    currentUser = user;
    var dashPlaceholder = document.getElementById('dashboard-placeholder');
    var dashActive = document.getElementById('dashboard-active');
    var signinBtn = document.getElementById('signin-btn');

    if (user) {
      // Signed in
      if (dashPlaceholder) dashPlaceholder.style.display = 'none';
      if (dashActive) {
        dashActive.style.display = 'block';
        document.getElementById('dash-email').textContent = user.email || '';
        loadDashboard();
      }
      if (signinBtn) signinBtn.style.display = 'none';
    } else {
      // Signed out
      if (dashPlaceholder) dashPlaceholder.style.display = 'block';
      if (dashActive) dashActive.style.display = 'none';
      if (signinBtn) signinBtn.style.display = 'inline-flex';
    }

    // Dispatch event for playground and other listeners
    window.dispatchEvent(new CustomEvent('dp-auth-change', { detail: { user: user } }));
  }

  // ── Sign In ──
  window.dpSignIn = function () {
    if (!auth) {
      alert('Firebase not loaded. Check your internet connection.');
      return;
    }
    var provider = new firebase.auth.GoogleAuthProvider();
    auth.signInWithPopup(provider).catch(function (err) {
      console.error('Sign in error:', err);
      alert('Sign in failed: ' + err.message);
    });
  };

  // ── Sign Out ──
  window.dpSignOut = function () {
    if (auth) auth.signOut();
  };

  // ── Get ID Token (for API calls) ──
  function getIdToken() {
    if (!currentUser) return Promise.reject(new Error('Not signed in'));
    return currentUser.getIdToken();
  }

  // ── API Key Management ──
  // Generates a key via the device auth flow (3 steps, instant for logged-in users):
  //   1. POST /api/v1/auth/device       → get device_code + user_code
  //   2. POST /api/v1/auth/device/approve → approve with Firebase Bearer token
  //   3. Result includes api_key directly (no poll needed for signed-in users)
  // Returns Promise<{api_key, key_id, tier}>. Also stores key in localStorage.
  window.dpGenerateKeyAsync = function (label) {
    label = label || 'default';
    var idToken;

    return getIdToken().then(function (token) {
      idToken = token;
      return fetch(API_BASE + '/api/v1/auth/device', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ args: [label, 'parse'] })
      });
    }).then(function (r) { return r.json(); })
      .then(function (data) {
        var result = typeof data.result === 'string' ? JSON.parse(data.result) : data;
        if (!result.device_code || !result.user_code) throw new Error('Failed to get device code');
        return fetch(API_BASE + '/api/v1/auth/device/approve', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + idToken
          },
          body: JSON.stringify({ userCode: result.user_code })
        });
      }).then(function (r) { return r.json(); })
      .then(function (data) {
        var result = typeof data.result === 'string' ? JSON.parse(data.result) : data;
        if (result.status === 'approved' && result.api_key) {
          localStorage.setItem('dp_api_key', result.api_key);
          return { api_key: result.api_key, key_id: result.key_id, tier: result.tier || 'free' };
        } else if (result.error) {
          throw new Error(result.error.message || JSON.stringify(result.error));
        } else {
          throw new Error('Unexpected response: ' + JSON.stringify(result));
        }
      });
  };

  // Dashboard-specific wrapper: generates key, shows modal, refreshes key list
  window.dpGenerateKey = function () {
    var labelInput = document.getElementById('key-label-input');
    var label = labelInput ? labelInput.value.trim() : 'default';
    if (!label) label = 'default';

    window.dpGenerateKeyAsync(label).then(function (result) {
      if (labelInput) labelInput.value = '';
      showKeyModal(result.api_key, result.key_id, result.tier);
      loadDashboard();
    }).catch(function (err) {
      alert('Error: ' + err.message);
    });
  };

  window.dpRevokeKey = function (keyId) {
    if (!confirm('Revoke key ' + keyId + '? This cannot be undone.')) return;
    getIdToken().then(function (token) {
      return fetch(API_BASE + '/api/v1/keys/revoke', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify({ args: [keyId, currentUser.uid] })
      });
    }).then(function (r) { return r.json(); })
      .then(function () { loadDashboard(); })
      .catch(function (err) { alert('Error: ' + err.message); });
  };

  // ── Load Dashboard Data ──
  function loadDashboard() {
    if (!currentUser) return;

    // Load usage for display (if we have a known keyId)
    var keysTable = document.getElementById('keys-table-body');
    if (keysTable) {
      keysTable.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:20px">Loading...</td></tr>';
    }

    // List keys
    getIdToken().then(function (token) {
      return fetch(API_BASE + '/api/v1/keys/list', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify({ args: [currentUser.uid] })
      });
    }).then(function (r) { return r.json(); })
      .then(function (data) {
        var result = typeof data.result === 'string' ? JSON.parse(data.result) : data;
        if (keysTable) {
          if (result.keys && Array.isArray(result.keys) && result.keys.length > 0) {
            keysTable.innerHTML = result.keys.map(function (k) {
              var isActive = k.active === true || k.active === 'true';
              return '<tr>' +
                '<td>' + (k.label || '-') + '</td>' +
                '<td><code>' + (k.keyId || '-') + '</code></td>' +
                '<td>' + (isActive ? '<span style="color:var(--success)">Active</span>' : '<span style="color:var(--text-muted)">Revoked</span>') + '</td>' +
                '<td>' + (isActive ? '<button class="dp-btn dp-btn--ghost" style="font-size:12px;padding:4px 10px" onclick="dpRevokeKey(\'' + k.keyId + '\')">Revoke</button>' : '') + '</td>' +
                '</tr>';
            }).join('');
          } else {
            keysTable.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:20px">No keys yet. Generate one below.</td></tr>';
          }
        }
      }).catch(function (err) {
        if (keysTable) {
          keysTable.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:20px">' + err.message + '</td></tr>';
        }
      });
  }

  // ── Key Modal ──
  function showKeyModal(key, keyId, tier) {
    var modal = document.getElementById('key-modal');
    var keyDisplay = document.getElementById('key-display');
    if (modal && keyDisplay) {
      keyDisplay.textContent = key;
      modal.style.display = 'flex';
    }
  }

  window.dpCloseKeyModal = function () {
    var modal = document.getElementById('key-modal');
    if (modal) modal.style.display = 'none';
  };

  window.dpCopyKey = function () {
    var keyDisplay = document.getElementById('key-display');
    if (keyDisplay && navigator.clipboard) {
      navigator.clipboard.writeText(keyDisplay.textContent).then(function () {
        var btn = document.getElementById('copy-key-btn');
        if (btn) { btn.textContent = 'Copied!'; setTimeout(function () { btn.textContent = 'Copy'; }, 2000); }
      });
    }
  };

  // ── Exposed helpers for playground ──
  window.dpGetCurrentUser = function () { return currentUser; };
  window.dpGetIdToken = function () { return getIdToken(); };
  window.dpListKeysAsync = function () {
    if (!currentUser) return Promise.reject(new Error('Not signed in'));
    return getIdToken().then(function (token) {
      return fetch(API_BASE + '/api/v1/keys/list', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ args: [currentUser.uid] })
      });
    }).then(function (r) { return r.json(); })
      .then(function (data) {
        var result = typeof data.result === 'string' ? JSON.parse(data.result) : data;
        return (result.keys && Array.isArray(result.keys)) ? result.keys : [];
      });
  };

  // ── Init on load ──
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
