# Authalla Evaluation — Authentication for DocParse

## Context

DocParse currently uses a custom API key system (api_keys.ail) with tier-based quotas stored in Firestore. The website design (v0.9.0) plans Firebase Auth for user identity on the API playground/dashboard page. This document evaluates **Authalla** as an alternative or complementary authentication layer.

Source: https://docs.authalla.com/docs/installation

## What Is Authalla?

Authalla is a hosted passwordless authentication platform built on OAuth2/OIDC standards. It provides:

- **Passkeys** (WebAuthn) — phishing-resistant, device-bound credentials (primary method)
- **Magic links** — email-based fallback for devices without passkey support
- **Social login** — third-party identity providers
- **SSO connections** — enterprise single sign-on (SAML/OIDC federation)
- **OAuth2 + PKCE** — standards-compliant authorization code flow

Each application lives in a **tenant** (`{tenant-id}.authalla.com`) with a hosted login UI, admin dashboard, and CLI tooling. Custom domains are supported for branding.

### Technical Architecture

- Discovery endpoint: `https://{tenant-id}.authalla.com/.well-known/openid-configuration`
- JWKS for JWT verification: `https://{tenant-id}.authalla.com/.well-known/jwks.json`
- Authorization Code + PKCE flow (no client secret needed for SPAs)
- Multiple passkeys per user, discoverable credentials (no username required at login)
- Hosted login UI with branding/theming customization

### Implementation Pattern

1. Create OAuth client in Authalla Admin UI
2. Configure redirect URI + allowed origins
3. App redirects to Authalla for login → user authenticates via passkey/magic link
4. Authalla redirects back with authorization code
5. App exchanges code for access token (PKCE-verified)
6. App validates JWT using JWKS endpoint

---

## Option A: Authalla Replaces Firebase Auth (Website Only)

Replace the planned Firebase Auth on the static website with Authalla for user identity.

### Pros

| Pro | Detail |
|-----|--------|
| **Passwordless-first** | Passkeys + magic links out of the box. No password management, reset flows, or credential storage. Better security posture than email/password. |
| **Standards-based** | Pure OAuth2/OIDC — any JWT library can validate tokens. No vendor lock-in at the protocol level. |
| **Simpler frontend** | No Firebase SDK (~90KB). Just standard OAuth2 redirect flow + JWT validation. Lighter static site. |
| **Enterprise SSO ready** | SSO connections are a first-class feature. Useful for enterprise-tier DocParse customers. |
| **Hosted login UI** | Don't need to build login/signup forms. Authalla handles the entire auth UX. Custom domain keeps it on-brand. |
| **Phishing resistant** | Passkeys are bound to origin — immune to credential phishing, unlike passwords or even OTP. |

### Cons

| Con | Detail |
|-----|--------|
| **Unknown pricing** | No public pricing page found. Could be expensive at scale. Need to contact sales. |
| **New/small vendor** | Limited public information. No clear track record, community size, or stability guarantees. Single point of failure for auth. |
| **No Firestore integration** | Firebase Auth auto-populates `auth.uid` in Firestore security rules. Authalla tokens would need manual UID extraction and a custom auth layer for Firestore access. |
| **Passkey browser support** | Passkeys require modern browsers + platform authenticator. Magic link fallback exists but is a degraded experience. Not all users have passkey-capable devices yet. |
| **Extra network hop** | Auth redirects go to `{tenant}.authalla.com` — adds latency to login flow and a dependency on Authalla's uptime. |
| **Migration effort** | Website design already specifies Firebase Auth. Switching means reworking the `firebase-app.js` component and the Firestore security model. |
| **Limited docs** | Docs are minimal. Node.js example only. No Python, Go, or AILANG patterns. |

---

## Option B: Authalla for End-User Auth + Keep API Keys for API Access

Use Authalla for interactive user sessions (website dashboard) while keeping the existing `dp_` API key system for programmatic API access.

### Pros

- **Clean separation**: humans authenticate with passkeys, machines authenticate with API keys
- **No API key changes**: existing tier system, Firestore quota tracking, and billing integration untouched
- **Progressive adoption**: add Authalla only to the website, no changes to Cloud Run API auth
- **SSO for enterprise**: enterprise customers get SSO for dashboard, API keys for integrations

### Cons

- **Two auth systems to maintain**: Authalla for web sessions + API keys for API = more complexity
- **User-to-key mapping**: need to link Authalla user identity to their API keys in Firestore
- **Same vendor risk**: still dependent on Authalla for the web auth path

---

## Option C: Stay with Firebase Auth (Current Plan)

Keep the v0.9.0 website design as-is: Firebase Auth for user identity, existing API keys for API access.

### Pros

| Pro | Detail |
|-----|--------|
| **Already designed** | Website design doc specifies Firebase Auth. No rework needed. |
| **Firestore native** | `auth.uid` flows into security rules automatically. Firestore is already the docparse database. |
| **Free tier generous** | Firebase Auth: 10K phone auths/month free, unlimited email/password. |
| **Google ecosystem** | ADC, Cloud Run, Firestore, Firebase Auth — all same project. Single IAM boundary. |
| **Mature & documented** | Extensive docs, community, client libraries for every language. |
| **Passkey support** | Firebase Auth added passkey support (via Google Identity Platform). Not passwordless-first, but available. |

### Cons

| Con | Detail |
|-----|--------|
| **Heavier SDK** | Firebase JS SDK is ~90KB+ and requires initialization boilerplate. |
| **Not passwordless-first** | Default UX is email/password. Passkeys are opt-in and less polished than Authalla's native flow. |
| **No built-in SSO** | Enterprise SSO (SAML) requires upgrading to Google Identity Platform (paid). |
| **Vendor lock-in** | Firebase Auth tokens are Google-specific. Migration away is non-trivial. |

---

## Comparison Matrix

| Criterion | Authalla | Firebase Auth | Notes |
|-----------|----------|---------------|-------|
| Passwordless UX | ★★★★★ | ★★★ | Authalla is passwordless-first |
| Passkey support | ★★★★★ | ★★★ | Both support it; Authalla is native |
| Enterprise SSO | ★★★★ | ★★ | Firebase needs Identity Platform upgrade |
| Firestore integration | ★ | ★★★★★ | Firebase Auth is native to Firestore |
| Pricing transparency | ★ | ★★★★★ | Authalla has no public pricing |
| Vendor maturity | ★★ | ★★★★★ | Google vs unknown startup |
| Migration effort | ★★ | ★★★★★ | Firebase is already in the design |
| SDK weight | ★★★★★ | ★★ | Authalla needs no SDK, just OAuth2 |
| Standards compliance | ★★★★★ | ★★★ | Authalla is pure OIDC |
| Docs & community | ★★ | ★★★★★ | Firebase has massive ecosystem |

---

## Recommendation

**Short term: stick with Firebase Auth (Option C)** for the v0.9.0 website. The Firestore integration is too valuable to give up — it's the docparse database, and Firebase Auth tokens flow directly into security rules. The website is 4 static pages, not a complex auth domain.

**Watch Authalla for v1.0+ enterprise features.** If DocParse gets enterprise customers who need SAML SSO or a passwordless-first experience, Authalla (or a similar OIDC provider like Auth0, Clerk, or WorkOS) could sit in front as an identity broker. The API key system would remain for machine access regardless.

**Key unknowns to resolve before considering Authalla:**
1. **Pricing** — contact Authalla for a quote. If it's per-MAU, compare against Firebase free tier.
2. **Uptime SLA** — what guarantees do they offer? Auth downtime = total service outage.
3. **Data residency** — where are user credentials stored? Relevant for EU enterprise customers.
4. **Vendor longevity** — what's the company's funding/team size? Auth is a critical dependency.

---

## If We Do Adopt Authalla Later

The cleanest integration path:

1. Use Authalla as the OIDC provider for the website dashboard
2. On first login, create/link a Firestore user document using Authalla's `sub` claim as the user ID
3. Mint a Firebase custom token from the Authalla JWT (via Cloud Function) for Firestore access
4. API keys remain unchanged — generated from the dashboard, stored in Firestore, validated by api_keys.ail
5. Enterprise SSO: configure Authalla SSO connections per organization → same flow

This gives passwordless UX + Firestore compatibility without rewriting the data layer.
