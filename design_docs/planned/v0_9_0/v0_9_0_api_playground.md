# v0.9.0 — In-Browser API Playground

## Summary

Add an interactive "Try the API" playground to the API page (`docs/api.html`) so authenticated users with API keys can send real requests, see responses, and copy working curl/SDK commands — all without leaving the browser.

## Motivation

The API page currently has live "Try It" buttons only for unauthenticated GET endpoints (health, formats). POST endpoints like `/api/v1/parse` only show static code snippets. Users must switch to curl or Postman to actually test the API. An in-browser playground reduces friction for evaluation and onboarding.

## Design

### Progressive Enhancement (3 states)

| State | What the user sees |
|---|---|
| **Not signed in** | Existing static endpoint cards unchanged. Subtle banner: "Sign in to try endpoints live" |
| **Signed in, no keys** | Banner: "Generate an API key in the Dashboard to try endpoints live" + link to dashboard.html |
| **Signed in + active key** | Playground bar appears + each POST endpoint card gains an interactive form |

### Playground Bar

A horizontal bar below the "API Explorer" heading:
- **API key input** — password-type field where user pastes their `dp_...` key. Stored in `sessionStorage` only (cleared on tab close). Validates format: `dp_` + 32 hex chars with green/red indicator.
- **Quota display** — "12/60 requests today" fetched from `/api/v1/keys/usage`
- **User email** — from Firebase auth state

> **Why paste the key?** The `/api/v1/keys/list` endpoint returns keyIds (hashed), not raw keys. Raw keys are only shown once at generation time.

### Interactive Endpoint Forms

Each POST endpoint card gets a `dp-endpoint-playground` div below existing code snippet tabs.

#### POST /api/v1/parse
- **File selector** — `<select>` with server-resident sample files:
  - `data/test_files/sample.docx` — DOCX: Basic document
  - `data/test_files/tables.docx` — DOCX: Tables
  - `data/test_files/comments.docx` — DOCX: Comments & Track Changes
  - `data/test_files/poi_sampleshow.pptx` — PPTX: Presentation
  - `data/test_files/pandoc_basic.xlsx` — XLSX: Spreadsheet
  - `data/test_files/test.csv` — CSV
  - `data/test_files/pandoc_planets.md` — Markdown
  - `data/test_files/test.odt` — ODT: OpenDocument
  - `data/test_files/test.html` — HTML
- Toggle "Use custom path" reveals a text input
- **Output format** — `<select>`: blocks, markdown, html, a2ui
- **Send Request** + **Copy curl** buttons
- **Response panel** with tabs: Formatted (pretty JSON + Prism), Raw (copy-to-clipboard), Timing

#### POST /general/v0/general
- Same file selector + strategy selector (auto, hi_res, fast)

#### Key Management Endpoints
- Key generation uses device auth flow (v0.10.0+): auth/device → auth/device/approve → auth/device/poll
- **keys/list**: no inputs, just Send
- **keys/usage**: keyId dropdown + Send
- **keys/revoke**: keyId dropdown + confirmation + Send
- **keys/rotate**: keyId dropdown + Send

### Response Display

```
dp-playground-response
  dp-response-meta       — HTTP status, elapsed_ms, response size
  dp-response-tabs       — [Formatted] [Raw] [Timing]
  dp-response-body       — JSON with Prism syntax highlighting, max-height 500px scroll
  dp-response-copy-btn   — Copy raw JSON to clipboard
```

### Curl Generation

Dynamically builds curl from form state:

```bash
curl -X POST https://api.parse.sunholo.com/api/v1/parse \
  -H "Content-Type: application/json" \
  -H "x-api-key: dp_a1b2c3..." \
  -d '{"args":["data/test_files/sample.docx","blocks"]}'
```

## Files Modified

1. `docs/api.html` — playground bar HTML, interactive forms, CSS (~120 lines), JS (~180 lines)
2. `docs/js/firebase-app.js` — expose `window.dpGetIdToken()`, dispatch `dp-auth-change` event (~15 lines)

## Security

- API key in `sessionStorage` only (cleared on tab close), never `localStorage`
- Key sent only via HTTPS `x-api-key` header to DocParse API
- Firebase ID tokens short-lived (1 hour)
- No credentials logged to console

## Mobile

- Playground bar stacks vertically at < 900px
- Form fields go full-width
- Response panel max-height 300px mobile, 500px desktop

## Out of Scope

- File upload (multipart) — endpoints take filepath strings; sample files suffice for now
- Collapsible JSON tree viewer — pretty-printed JSON is enough
- WebSocket streaming — responses are small JSON
- Saved request history
