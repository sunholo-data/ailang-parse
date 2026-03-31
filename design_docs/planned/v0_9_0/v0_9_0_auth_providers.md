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

Add Apple, Microsoft, and Phone (SMS) sign-in to broaden access for enterprise users and those without Google/GitHub accounts.

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
    ],
    callbacks: {
      signInSuccessWithAuthResult: function () { return false; }
    }
  };
}
```

### Backend: No Changes Required

The backend verifies Firebase ID tokens via JWT/RSA signature checking (`sunholo/firebase_auth@0.1.1`). All providers produce standard Firebase ID tokens with the same structure — the backend doesn't care which provider was used. The `firebase_uid` in the token is the canonical user identity.

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

| Priority | Provider  | Effort | External Account Needed      |
|----------|-----------|--------|------------------------------|
| 1        | Microsoft | ~30min | Azure portal (free)          |
| 2        | Phone SMS | ~15min | None (Firebase only)         |
| 3        | Apple     | ~45min | Apple Developer ($99/year)   |

Microsoft first — broadest enterprise coverage with minimal setup. Phone SMS second — Firebase-only config. Apple last — requires paid developer account and more moving parts.

## Checklist

- [ ] **Microsoft:** Register app in Azure Entra ID, add client ID + secret to Firebase
- [ ] **Phone:** Enable Phone provider in Firebase Console
- [ ] **Apple:** Register Service ID in Apple Developer, add credentials to Firebase
- [ ] **Frontend:** Update `signInOptions` in `firebase-app.js`
- [ ] **Test:** Verify each provider signs in and produces a valid Firebase ID token
- [ ] **Test:** Verify the backend accepts tokens from all providers (device auth flow)
- [ ] **Mobile:** Confirm FirebaseUI renders all provider buttons correctly at 768px
