# v0.9.0 — Additional Sign-In Providers

**Status: PLANNED**

## Current State

The API page uses FirebaseUI with three providers:
- **Google** — working (popup)
- **GitHub** — configured in frontend, needs enabling in Firebase Console
- **Email magic link** — passwordless, configured in frontend

Firebase project: **`ailang-multivac-dev`** (project ID `812435936917`).
FirebaseUI config: `docs/js/firebase-app.js` → `getUiConfig()`.

## Goal

Broaden sign-in coverage so that any developer or enterprise user can authenticate regardless of which identity provider they use. Prioritise options that match the target audience (developers, enterprise, AI agent builders).

## Provider Setup

### 1. Apple Sign-In

**Firebase Console:**
1. Authentication → Sign-in method → Add provider → Apple
2. Enter the Service ID, Apple Team ID, Key ID, and private key

**Apple Developer Console** (https://developer.apple.com):
1. Register an App ID with "Sign In with Apple" capability
2. Create a Services ID (this becomes the OAuth client ID)
   - Configure the web domain: `www.sunholo.com`
   - Add return URL: `https://ailang-multivac-dev.firebaseapp.com/__/auth/handler`
3. Create a Key with "Sign In with Apple" enabled
   - Download the `.p8` private key file
   - Note the Key ID and Team ID

**Frontend change** — add to `signInOptions` in `firebase-app.js`:
```javascript
firebase.auth.OAuthProvider.PROVIDER_ID  // 'apple.com'
```

Full entry with scopes:
```javascript
{
  provider: 'apple.com',
  scopes: ['email', 'name']
}
```

**Cost:** Free. Apple requires HTTPS (we have it) and a paid Apple Developer account ($99/year).

**Docs:** https://firebase.google.com/docs/auth/web/apple

---

### 2. Microsoft Sign-In (Entra ID / Azure AD)

**Azure Portal** (https://portal.azure.com → Entra ID → App registrations):
1. Register a new application:
   - Name: `AILANG Parse`
   - Supported account types: **"Accounts in any organizational directory and personal Microsoft accounts"** (multi-tenant + personal)
   - Redirect URI (Web): `https://ailang-multivac-dev.firebaseapp.com/__/auth/handler`
2. Note the **Application (client) ID**
3. Under Certificates & secrets → New client secret
   - Note the **secret value** (not the secret ID)
4. Under API permissions → ensure `openid`, `email`, `profile` are granted

**Reference:** https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app

**Firebase Console:**
1. Authentication → Sign-in method → Add provider → Microsoft
2. Enter the Application (client) ID and Client secret from Azure

**Frontend change** — add to `signInOptions`:
```javascript
{
  provider: 'microsoft.com',
  loginHintKey: 'login_hint'
}
```

Optional: restrict to specific tenant by adding `customParameters`:
```javascript
{
  provider: 'microsoft.com',
  customParameters: {
    tenant: 'YOUR_TENANT_ID'  // omit for multi-tenant
  },
  loginHintKey: 'login_hint'
}
```

**Cost:** Free for basic sign-in. Azure AD app registration is free.

**Docs:** https://firebase.google.com/docs/auth/web/microsoft-oauth

---

### 3. Phone (SMS) Sign-In

**Firebase Console:**
1. Authentication → Sign-in method → Add provider → Phone
2. Enable it (no external configuration needed)
3. Optional: add test phone numbers for development

**reCAPTCHA:**
Phone auth requires reCAPTCHA verification to prevent SMS abuse. FirebaseUI handles this automatically with an invisible reCAPTCHA. No API keys needed — Firebase uses its own reCAPTCHA integration.

**Frontend change** — add to `signInOptions`:
```javascript
firebase.auth.PhoneAuthProvider.PROVIDER_ID
```

With country defaults:
```javascript
{
  provider: firebase.auth.PhoneAuthProvider.PROVIDER_ID,
  defaultCountry: 'DK',           // Denmark (company is Holosun ApS)
  whitelistedCountries: null       // allow all countries (null = no restriction)
}
```

**Cost:** Firebase Phone Auth uses verification SMS which are billed:
- **Free tier:** 10 SMS/day (for testing)
- **Blaze plan (pay-as-you-go):** $0.01–0.06/SMS depending on country
- US/UK/DK are ~$0.01/SMS
- SMS abuse is mitigated by reCAPTCHA + Firebase's built-in rate limiting

**Risk:** SMS costs can spike if abused. Mitigations:
- reCAPTCHA (automatic with FirebaseUI)
- Firebase's built-in per-IP and per-phone rate limits
- Monitor usage in Firebase Console → Authentication → Usage
- Consider setting a budget alert in GCP Billing

**Docs:** https://firebase.google.com/docs/auth/web/phone-auth

---

### 4. Anonymous Auth (Try Before You Sign Up)

Anonymous auth gives visitors a temporary Firebase uid so they can try the API immediately without any sign-up form. They can later "link" a real provider (Google, email, etc.) to keep their account and data.

**Firebase Console:**
1. Authentication → Sign-in method → Add provider → Anonymous
2. Enable it (no configuration needed)

**Frontend change** — no change to `signInOptions` (anonymous users don't appear in FirebaseUI). Instead, add a "Try without signing in" button that calls:
```javascript
firebase.auth().signInAnonymously();
```

**Backend change — quota restriction:**
Anonymous users should get heavily restricted quotas to prevent abuse. The backend can detect anonymous tokens by checking the `provider_id` field in the Firebase ID token (it will be `anonymous`).

Recommended anonymous limits:
- **5 requests/day** (vs 60 for free tier with real identity)
- **No key generation** — anonymous users use a session-scoped token, not a persistent API key
- **No device auth flow** — agents must authenticate with a real identity
- **Prompt to link account** after 3 requests or on first POST to a paid endpoint

**Account linking flow:**
```javascript
// When anonymous user clicks "Sign in to keep your account":
var credential = firebase.auth.GoogleAuthProvider.credential(googleIdToken);
firebase.auth().currentUser.linkWithCredential(credential);
// uid stays the same, usage history preserved
```

**Risk:** Abuse via repeated anonymous sign-ins from different IPs. Mitigations:
- Very low quota (5 req/day)
- Rate limit by IP on Cloud Run (future)
- No persistent keys — session only
- Firebase's built-in anonymous account cleanup (auto-delete after 30 days of inactivity)

**Cost:** Free. Anonymous users count toward Firebase Auth MAU but are auto-cleaned.

**Docs:** https://firebase.google.com/docs/auth/web/anonymous-auth

---

### 5. SAML / Generic OIDC (Enterprise SSO)

Enterprise customers with their own identity provider (Okta, Auth0, PingIdentity, Azure AD tenant-specific, etc.) can sign in using corporate SSO. This is the #1 ask from enterprise buyers who can't use personal Google/Microsoft accounts for work tools.

**Prerequisite:** Upgrade to **Firebase Identity Platform** (free upgrade from Firebase Auth, usage-based pricing after 50k MAU). This unlocks SAML and generic OIDC provider support.

**Firebase Console (Identity Platform):**
1. Authentication → Sign-in method → Add provider → SAML or OpenID Connect
2. For each enterprise customer, configure:
   - **SAML:** Entity ID, SSO URL, X.509 certificate from the customer's IdP
   - **OIDC:** Client ID, Issuer URL, Client secret from the customer's IdP

**Frontend change** — add the provider ID returned by Firebase:
```javascript
{
  provider: 'saml.customer-okta',  // or 'oidc.customer-auth0'
  providerName: 'Acme Corp SSO',
  buttonColor: '#2F3037',
  iconUrl: 'https://example.com/acme-logo.png'
}
```

Note: Each enterprise customer gets their own SAML/OIDC provider entry. This is per-customer configuration — not self-service. Suitable for pro/enterprise tier customers who request SSO.

**Cost:**
- Firebase Identity Platform upgrade: free (same free tier as Firebase Auth)
- After 50k MAU: $0.0055/MAU
- SAML/OIDC providers: no additional per-provider cost

**When to implement:** When an enterprise customer requests it. Don't pre-build — configure per customer.

**Docs:** https://firebase.google.com/docs/auth/web/saml, https://firebase.google.com/docs/auth/web/openid-connect

---

### Not Recommended

| Provider | Reason |
|----------|--------|
| Twitter/X | Wrong audience — developers and enterprise users rarely use X for tool auth |
| Facebook | Wrong audience — not a developer/enterprise identity |
| Yahoo | Negligible user base for this market |
| LinkedIn | No native Firebase support; would require custom OIDC via Identity Platform. Low priority since Microsoft covers the same enterprise users |
| Passkeys/WebAuthn | Firebase support still limited; revisit when FirebaseUI adds native passkey UI |

---

## Implementation

### Frontend: `docs/js/firebase-app.js`

After all providers are enabled in their respective consoles, update `getUiConfig()`:

```javascript
function getUiConfig() {
  var emailLinkUrl = window.location.origin + window.location.pathname;

  return {
    signInFlow: 'popup',
    signInOptions: [
      // OAuth providers
      firebase.auth.GoogleAuthProvider.PROVIDER_ID,
      firebase.auth.GithubAuthProvider.PROVIDER_ID,
      { provider: 'apple.com', scopes: ['email', 'name'] },
      { provider: 'microsoft.com', loginHintKey: 'login_hint' },

      // Phone (SMS)
      {
        provider: firebase.auth.PhoneAuthProvider.PROVIDER_ID,
        defaultCountry: 'DK'
      },

      // Email magic link (passwordless)
      {
        provider: firebase.auth.EmailAuthProvider.PROVIDER_ID,
        signInMethod: firebase.auth.EmailAuthProvider.EMAIL_LINK_SIGN_IN_METHOD,
        forceSameDevice: false,
        emailLinkSignIn: function () {
          return { url: emailLinkUrl, handleCodeInApp: true };
        }
      }

      // SAML/OIDC entries added per enterprise customer:
      // { provider: 'saml.customer-name', providerName: 'Customer SSO' }
    ],
    callbacks: {
      signInSuccessWithAuthResult: function () { return false; }
    }
  };
}
```

Anonymous auth is handled separately (not in FirebaseUI). Add a "Try without signing in" link:
```javascript
// In api.html, below the Sign In button:
firebase.auth().signInAnonymously();
```

### Backend: Minimal Changes

The backend verifies Firebase ID tokens via JWT/RSA signature checking (`sunholo/firebase_auth@0.1.1`). All providers produce standard Firebase ID tokens with the same structure — the backend doesn't care which provider was used. The `firebase_uid` in the token is the canonical user identity.

**Exception — anonymous auth:** The backend needs to detect anonymous tokens and enforce stricter limits. The Firebase ID token's `firebase.sign_in_provider` field will be `"anonymous"`. Add a check in the quota logic:
- If `sign_in_provider == "anonymous"`: cap at 5 requests/day, block key generation, block device auth
- All other providers: use existing tier-based quotas

### Authorized Domains

Current authorized domains (already configured):
- `www.sunholo.com`
- `ailang-multivac-dev.firebaseapp.com`
- `localhost`
- `ailang-dev-website-builder-ejjw6zt3bq-ew.a.run.app`

No additional domains needed.

### Firebase Redirect URI

All OAuth providers (Google, GitHub, Apple, Microsoft) use the same Firebase redirect handler:
```
https://ailang-multivac-dev.firebaseapp.com/__/auth/handler
```

This must be registered as the redirect URI in each provider's developer console.

## Rollout Order

| Priority | Provider   | Effort | External Account Needed      | Value |
|----------|------------|--------|------------------------------|-------|
| 1        | Microsoft  | ~30min | Azure portal (free)          | Enterprise coverage — biggest unserved audience |
| 2        | Anonymous  | ~2hr   | None (Firebase only)         | Zero-friction trial — backend quota changes needed |
| 3        | Phone SMS  | ~15min | None (Firebase only)         | Universal fallback for users without OAuth accounts |
| 4        | Apple      | ~45min | Apple Developer ($99/year)   | iOS/Mac ecosystem completeness |
| 5        | SAML/OIDC  | Per customer | Identity Platform upgrade | Enterprise SSO — implement on demand |

Microsoft first — broadest enterprise coverage with minimal setup. Anonymous second — biggest UX win, but needs backend work to enforce strict limits. Phone SMS third — Firebase-only config. Apple fourth — requires paid developer account. SAML/OIDC last — configure per enterprise customer when they request it.

## Checklist

### Phase 1: Core providers
- [ ] **Microsoft:** Register app in Azure Entra ID, add client ID + secret to Firebase
- [ ] **Phone:** Enable Phone provider in Firebase Console
- [ ] **Apple:** Register Service ID in Apple Developer, add credentials to Firebase
- [ ] **Frontend:** Update `signInOptions` in `firebase-app.js`
- [ ] **Test:** Verify each provider signs in and produces a valid Firebase ID token
- [ ] **Test:** Verify the backend accepts tokens from all providers (device auth flow)
- [ ] **Mobile:** Confirm FirebaseUI renders all provider buttons correctly at 768px

### Phase 2: Anonymous trial
- [ ] **Firebase:** Enable Anonymous provider in Firebase Console
- [ ] **Frontend:** Add "Try without signing in" button that calls `signInAnonymously()`
- [ ] **Frontend:** Show "Link account" prompt after N requests or on key generation attempt
- [ ] **Backend:** Detect anonymous tokens (`sign_in_provider == "anonymous"`)
- [ ] **Backend:** Enforce anonymous quota (5 req/day, no key generation, no device auth)
- [ ] **Test:** Verify anonymous → linked account preserves uid and usage history

### Phase 3: Enterprise SSO (on demand)
- [ ] **Upgrade** to Firebase Identity Platform (free, enables SAML/OIDC)
- [ ] **Per customer:** Configure SAML or OIDC provider in Firebase Console
- [ ] **Per customer:** Add provider entry to `signInOptions` with customer branding
