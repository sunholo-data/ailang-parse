# v0.10.0 — Authentication Security & Seamless Agent Onboarding

**Status: IMPLEMENTED (2026-03-27)**

Implementation summary:
- Option B chosen: `/api/v1/keys/generate` route removed entirely
- Approach A implemented: JWT/RSA verification via `sunholo/firebase_auth@0.1.1`
  (`verifyFirebaseJWTFull` — local signature verification against Google's public keys)
- `ALLOW_SELF_APPROVE=true` for local dev/testing only (not on Cloud Run)
- `FIREBASE_WEB_API_KEY` env var NOT needed (JWT verification uses public keys, not REST API)
- `display_message` and `display_code` added to device auth response for agent UX
- Auth package split: `sunholo/auth@0.4.1` (pure) + `sunholo/firebase_auth@0.1.1` (Net+Env)

## Problem

DocParse has three key generation paths, none of which verify user identity:

| Path | Endpoint | Identity Verified? | Tied to Billing? |
|------|----------|--------------------|------------------|
| Direct | `POST /api/v1/keys/generate` | No — accepts any `userId` string | No |
| Device flow | device → approve → poll | No — approve trusts the `userId` from browser | Partially (Firebase uid from browser) |
| Dashboard | Browser → Firebase login → generate | Yes — Firebase auth enforced | Yes |

**Risk:** An agent can generate unlimited free-tier keys by calling `/api/v1/keys/generate` with random userIds. Each key gets 60 req/day, so 10 keys = 600 free requests. There's no way to enforce per-user limits, block abusive users, or upgrade them to paid tiers.

**Goal:** Every API key must be tied to a verified identity (Firebase uid), while keeping agent onboarding as frictionless as possible.

## Current Architecture

```
Agent                                Browser (approve.html)
  |                                       |
  | POST /auth/device                     |
  |  → device_code, user_code, URL        |
  |                                       |
  |  "Open this URL" ─────────────────→   |
  |                                       | Firebase login
  |                                       | Click Approve
  |                                       |
  |                                       | POST /auth/device/approve
  |                                       |   {userCode, userId: firebase.uid}
  |                                       |   ← generates key, stores in Firestore
  |                                       |
  | POST /auth/device/poll                |
  |  ← api_key (tied to firebase uid)     |
```

**What's broken:** The approve endpoint doesn't verify the Firebase ID token. It trusts whatever `userId` the caller provides. This means:
- An agent can call approve directly, skipping the browser entirely
- Any `userId` string works — no proof of identity
- `/api/v1/keys/generate` has no auth at all

## Design

### Principle: Login Once, Parse Forever

Users authenticate once (Firebase) to prove identity. After that, their `dp_` API key is all they need. The key carries their identity internally — every parse request is tracked against their uid.

### Tier Progression

```
Anonymous → Free (verified) → Pro ($29/mo) → Enterprise (custom)
     ↑           ↑                 ↑
  No access   Firebase login    Stripe checkout
```

No anonymous API access. Even free tier requires Firebase login. This gives us:
- Abuse prevention (rate limit per real identity)
- Upgrade path (we know who they are for billing)
- Usage analytics (per-user, not per-key)

### Changes Required

#### 1. Enforce Firebase ID token on `/api/v1/auth/device/approve`

The approve endpoint must verify the Firebase ID token before generating a key.

**Current signature:**
```ailang
func deviceAuthApprove(userCode: string, userId: string) -> string
```

**New signature:**
```ailang
func deviceAuthApprove(req: {body: string, headers: Json}) -> string
```

The function reads `Authorization: Bearer <firebase_id_token>` from headers, verifies it against Firebase Auth (using the `gcp_auth` package or a direct call to `https://www.googleapis.com/identitytoolkit/v3/relyingparty/getAccountInfo`), extracts the uid, and uses that as the userId.

**Impact:** approve.html already sends the Firebase ID token — just need to verify it server-side instead of trusting the userId from the body.

#### 2. Restrict `/api/v1/keys/generate` to authenticated users

Two options:

**Option A: Require Firebase Bearer token** (like approve)
- Dashboard and admin tools send the Firebase token
- Agent-facing docs remove direct generation from the golden path
- Testing uses `DOCPARSE_AUTH=direct` env var which only works when `ALLOW_UNAUTHENTICATED_KEYGEN=true` (dev only)

**Option B: Remove the route entirely**
- All key generation goes through device flow or dashboard
- Simpler security model — one path for humans (dashboard), one for agents (device flow)

**Recommendation:** Option B. The device flow IS the agent key generation path. Direct generation adds an unauthenticated backdoor for no real benefit. For testing/CI, use the device flow with self-approve (which is fine when `ALLOW_SELF_APPROVE=true` on dev instances).

#### 3. Firebase ID Token Verification

Two approaches, in order of preference:

**Approach A: AILANG JWT/RSA package (IMPLEMENTED)**
- Package: `pkg/sunholo/firebase_auth/firebase_jwt` (`verifyFirebaseJWTFull`)
- Uses `std/jwt` to verify RS256 signature against Google's public keys
- Validates issuer (`securetoken.google.com/{projectId}`), audience, and expiry
- Fetches keys from `googleapis.com/robot/v1/metadata/x509/securetoken@...`
- No `FIREBASE_WEB_API_KEY` env var needed — uses `GOOGLE_CLOUD_PROJECT` for audience check
- Z3 contracts on pure `verifyFirebaseJWT` function (requires non-empty token + projectId)

**Approach B: Firebase Auth REST API** (available but not used)
- Also in package: `pkg/sunholo/firebase_auth/firebase_token` (`verifyIdToken`)
- Calls Identity Toolkit REST API — simpler but adds latency per verification
- Requires `FIREBASE_WEB_API_KEY` env var

#### 4. Dev/Test Mode

For local development and CI:
- `ALLOW_SELF_APPROVE=true` — approve endpoint skips Firebase verification, trusts userId from body
- `/api/v1/keys/generate` route removed entirely — no `ALLOW_UNAUTHENTICATED_KEYGEN` needed
- Default is `false` (production) — Cloud Run does NOT set `ALLOW_SELF_APPROVE`
- Test scripts: `test_device_auth_flow.sh` starts server with `ALLOW_SELF_APPROVE=true`

Cloud Run env vars (production):
```
GOOGLE_CLOUD_PROJECT=YOUR_GCP_PROJECT  (for JWT audience validation)
# No FIREBASE_WEB_API_KEY needed — JWT verification uses public keys
# No ALLOW_SELF_APPROVE — defaults to false
```

### Agent Onboarding Flow (Final)

```
Agent                          User's Browser              Firebase
  |                                 |                        |
  | POST /auth/device              |                        |
  |  {label: "my-agent"}          |                        |
  |  → device_code + user_code     |                        |
  |                                 |                        |
  | "Open: https://...?code=ABCD"  |                        |
  |  ─────────────────────────→    |                        |
  |                                 | User clicks link      |
  |                                 | → Firebase login       |
  |                                 |  ←───────────────────  |  id_token
  |                                 |                        |
  |                                 | POST /auth/device/approve
  |                                 |  Authorization: Bearer <id_token>
  |                                 |  {userCode: "ABCD"}
  |                                 |  ← {status: approved}  |
  |                                 |                        |
  | POST /auth/device/poll         |                        |
  |  {device_code}                 |                        |
  |  ← {api_key: "dp_...",        |                        |
  |     tier: "free"}              |                        |
  |                                 |                        |
  | POST /api/v1/parse             |                        |
  |  {apiKey: "dp_...", ...}       |                        |
  |  ← parsed document             |                        |
```

**Key properties:**
- Agent never sees Firebase credentials
- User logs in once in their browser
- API key is tied to Firebase uid
- Quotas and billing follow the user across all their keys
- Agent polls with the secret `device_code` — never exposed to the browser

### Upgrade Flow (Free → Pro)

When a free user hits quota limits:

1. Parse returns `QUOTA_EXCEEDED` with `suggested_fix: "Upgrade at https://www.sunholo.com/docparse/dashboard.html"`
2. User visits dashboard → already logged in (Firebase session) → clicks Upgrade
3. Stripe Checkout → subscription created → entitlements updated in Firestore
4. Existing API keys automatically get pro-tier quotas (same uid)
5. Agent retries the parse — works immediately

No new key needed. The key's userId maps to the Firestore entitlement record, which is updated by the billing webhook.

### Machine-Readable Discovery

The capabilities manifest (`GET /api/v1/capabilities`) already describes auth:

```json
{
  "auth": {
    "schemes": [{
      "id": "api_key",
      "type": "apiKey",
      "in": "body",
      "name": "apiKey",
      "prefix": "dp_",
      "how_to_get": {
        "device_flow": "/api/v1/auth/device",
        "dashboard": "https://www.sunholo.com/docparse/dashboard.html"
      }
    }]
  }
}
```

An AI agent reading this knows:
1. It needs an `apiKey` in the request body
2. The key starts with `dp_`
3. It can use the device flow to get one (the agent-friendly path)
4. Or direct the user to the dashboard

### Implementation Order

1. **Firebase token verification function** — new utility in `device_auth.ail` or a shared module
2. **Enforce on approve** — verify `Authorization: Bearer` header, extract uid
3. **Update approve.html** — pass the Firebase ID token in the Authorization header (it already has the token from login)
4. **Gate keys/generate** — require Bearer token or remove the route
5. **Add dev mode flags** — `ALLOW_SELF_APPROVE`, `ALLOW_UNAUTHENTICATED_KEYGEN`
6. **Update test scripts** — `test_cloud_run.sh` and `test_device_auth_flow.sh` use dev mode for self-approve
7. **Update agent docs** — remove direct generation from golden path

### Files Modified

| File | Change | Status |
|------|--------|--------|
| `docparse/services/device_auth.ail` | `@raw` + JWT verification via `verifyFirebaseJWTFull` | Done |
| `docparse/services/api_keys.ail` | Removed `@route` from `generateApiKey` | Done |
| `docparse/main.ail` | Transitive imports for `firebase_auth` package | Done |
| `docs/js/firebase-app.js` | Dashboard uses 3-step device auth flow | Done |
| `docs/api.html` | Playground uses device auth for key generation | Done |
| `tests/test_device_auth_flow.sh` | `ALLOW_SELF_APPROVE=true` in server env | Done |
| `tests/test_cloud_run.sh` | Updated comments for auth enforcement | Done |
| `examples/quickstart.sh` | Removed direct keygen path | Done |
| `AGENT.md` | Device flow is primary, self-approve documented | Done |
| SDKs (Go/Python/JS) | `generate()` throws deprecation, READMEs updated | Done |
| `ailang-packages/packages/firebase-auth/` | New package with JWT + REST verification | Done |
| `ailang-packages/packages/auth/` | Pure package (removed Firebase modules) | Done |

### Security Properties

After this change:

| Property | Status |
|----------|--------|
| Every key tied to verified identity | Yes (Firebase uid) |
| Agents can self-generate unlimited keys | No (approve requires Firebase token) |
| Per-user rate limiting works | Yes (all keys map to one uid) |
| Upgrade path from free → paid | Yes (same uid, entitlements update in place) |
| Agent onboarding friction | Low (one browser approval, then key works forever) |
| Local dev/testing works | Yes (dev mode flags skip verification) |
| AI agent discovery | Yes (capabilities manifest describes device flow) |
