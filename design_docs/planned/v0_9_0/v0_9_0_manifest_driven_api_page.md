# v0.9.0 — Manifest-Driven API Page Redesign

## The Principle

The capability manifest (`/api/v1/capabilities`) is the product surface. The browser page should be a **thin renderer** over the manifest and its sibling endpoints. Adding an endpoint to the AILANG server should automatically surface it in the page — no HTML edits required.

## Current State

`docs/api.html` (1422 lines) is already partially manifest-driven:

| Section | Data Source | Status |
|---------|-------------|--------|
| API Explorer cards | `GET /api/v1/capabilities` | **Manifest-driven** |
| Sample file dropdowns | `GET /api/v1/samples` | **Manifest-driven** |
| Badges (auth, cost, determinism) | Capabilities manifest | **Manifest-driven** |
| Supported Formats grid | Hand-coded HTML | **Hand-coded** |
| Pricing tiers table | Hand-coded HTML | **Hand-coded** |
| Quick Start curl | Hard-coded URL + params | **Hand-coded** |
| SDK install commands | Hard-coded strings | **Hand-coded** |
| Unstructured migration | Hard-coded examples | **Static (OK)** |
| Claude Code Skill | Hard-coded install + examples | **Static (OK)** |
| Playground forms (parse/estimate/unstructured) | Hand-coded per endpoint | **Partially dynamic** |
| Code examples (curl/Python/JS tabs) | Hard-coded for parse only | **Hand-coded** |

## Goal

Every section that can be derived from an API endpoint should be. The page becomes:

```
fetch(/api/v1/capabilities) → endpoint cards, auth schemes, error taxonomy, badges, examples
fetch(/api/v1/samples)      → sample dropdowns in playground forms
fetch(/api/v1/formats)      → supported formats grid
fetch(/api/v1/pricing)      → pricing tiers table
fetch(/api/v1/tools)        → MCP/A2A/OpenAPI integration cards
```

Static sections (Unstructured migration, Claude Code Skill, SDK install commands) stay hand-coded — they're editorial content, not API state.

## Changes

### 1. Formats Grid from `/api/v1/formats`

**Currently:** 5 hand-coded cards (Office, Text, Images & PDF, Audio, Video) with hard-coded file extensions.

**After:** Fetch `/api/v1/formats`, group by `strategy` (deterministic vs AI), render cards dynamically.

```javascript
function renderFormats(formats) {
  // formats.input_formats: [{extension, mime, strategy, category}, ...]
  // Group by category, render card per group
  // Show strategy badge: "Deterministic" or "AI-Powered"
}
```

**Benefit:** When a new format is added to the AILANG parser, it appears on the page automatically.

### 2. Pricing Table from `/api/v1/pricing`

**Currently:** Hand-coded `<table>` with Free/Pro/Business columns and 9 rows.

**After:** Fetch `/api/v1/pricing`, render tiers dynamically.

```javascript
function renderPricing(pricing) {
  // pricing.tiers: [{name, price, limits: {requests_per_day, pages_per_month, ...}}, ...]
  // Build table headers from tier names
  // Build rows from limit keys
}
```

**Benefit:** Pricing changes in `pricing.ail` propagate to the page without HTML edits.

### 3. Generic Playground Form Generation

**Currently:** `renderPlayground(ep)` has hard-coded logic for `parse`, `unstructured`, `estimate` endpoint IDs. Other POST endpoints get nothing.

**After:** Generate playground forms from `input_schema` in the capabilities manifest. Any endpoint with an `input_schema` gets an auto-generated form.

```javascript
function renderPlaygroundFromSchema(ep) {
  if (!ep.input_schema || !ep.input_schema.properties) return '';

  var html = '<div class="dp-endpoint-playground pg-authed">';
  html += '<div class="dp-playground-form">';

  for (var name in ep.input_schema.properties) {
    var prop = ep.input_schema.properties[name];

    if (prop.enum) {
      // Render <select> with enum values
      html += renderSelectField(name, prop);
    } else if (name === 'path' || name === 'filepath' || name === 'sample_id') {
      // Render sample dropdown + custom text input
      html += renderFileField(name, ep.id);
    } else {
      // Render text input
      html += renderTextField(name, prop);
    }
  }

  html += '</div>';
  html += renderPlaygroundActions(ep);
  html += '</div>';
  return html;
}
```

**Special cases:**
- Fields named `path`, `filepath`, or `sample_id` get a sample dropdown (from `/api/v1/samples`)
- Fields with `enum` constraint get a `<select>`
- Fields with `type: "string"` get a text `<input>`
- Auth-required endpoints: form only visible when API key is pasted (existing behavior)

**Benefit:** Device auth endpoints (`/api/v1/auth/device`, `/api/v1/auth/device/poll`) get auto-generated forms without any playground-specific code.

### 4. Code Examples from Schema

**Currently:** Only the `parse` endpoint gets curl/Python/JS tabs, hard-coded in `renderCodeExamples()`.

**After:** Generate code examples for every POST endpoint from its `input_schema`.

```javascript
function generateCurl(ep, baseUrl) {
  var body = buildExampleBody(ep.input_schema);
  var headers = ['"Content-Type: application/json"'];
  if (ep.auth && ep.auth.required && ep.auth.scheme === 'api_key') {
    headers.push('"x-api-key: YOUR_KEY"');
  }
  return 'curl -X ' + ep.method + ' ' + baseUrl + ep.path + ' \\\n' +
    headers.map(h => '  -H ' + h).join(' \\\n') + ' \\\n' +
    "  -d '" + JSON.stringify(body) + "'";
}

function buildExampleBody(schema) {
  // Use golden example from capabilities manifest if available
  // Otherwise generate from property types/defaults
}
```

**Benefit:** Every endpoint gets copy-able code snippets in 4 languages.

### 5. Device Auth Flow UI

New section visible to unauthenticated users: **"Get an API Key (Headless Agents)"**

Renders a simplified device auth flow in the browser:

1. Click "Request Device Code" → `POST /api/v1/auth/device`
2. Shows `user_code` (ABCD-1234) and `verification_url`
3. Auto-polls `POST /api/v1/auth/device/poll` every 5s
4. On approval → displays API key with copy button

This is the browser-side companion to the CLI device auth flow. Useful for users who want to try the API without Firebase sign-in.

### 6. Request History Panel

For authenticated users with API keys, add a collapsible "Recent Requests" panel:

- Fetches from `POST /api/v1/requests/history`
- Shows: timestamp, file parsed, format, elapsed_ms, request_id
- "Replay" button → `POST /api/v1/requests/replay` with the request_id
- Replay response replaces the playground response panel

### 7. Tool Definitions from `/api/v1/tools`

**Currently:** "Connect Your AI" section has hand-coded MCP/CLI/REST cards.

**After:** Fetch `/api/v1/tools` and render links to:
- MCP endpoint: `{base_url}/mcp/`
- A2A agent card: `{base_url}/.well-known/agent.json`
- OpenAPI spec: `{base_url}/api/_meta/openapi.json`

Keep the editorial content (CLI examples, MCP config snippet) as static HTML — those explain *how to use* the tools, not *where they are*.

### 8. Quick Start from Manifest

**Currently:** Hard-coded curl with hard-coded URL.

**After:** Build Quick Start curl from `capabilities.base_url` + first endpoint with `examples[]`:

```javascript
function renderQuickStart(capabilities) {
  var parseEp = capabilities.endpoints.find(ep => ep.id === 'parse');
  var example = parseEp.examples[0];
  // Render curl from base_url + parseEp.path + example.request
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    api.html (renderer)                    │
│                                                           │
│  Boot:                                                    │
│    Promise.all([                                          │
│      fetch(/api/v1/capabilities),                        │
│      fetch(/api/v1/samples),                             │
│      fetch(/api/v1/formats),                             │
│      fetch(/api/v1/pricing),                             │
│      fetch(/api/v1/tools)                                │
│    ]).then(renderAll)                                     │
│                                                           │
│  renderAll(caps, samples, formats, pricing, tools):      │
│    renderQuickStart(caps)                                 │
│    renderFormats(formats)                                 │
│    renderEndpoints(caps, samples)    ← existing, enhanced│
│    renderPricing(pricing)                                 │
│    renderToolLinks(tools)                                 │
│                                                           │
│  Static (editorial):                                      │
│    - Unstructured migration guide                         │
│    - Claude Code Skill                                    │
│    - SDK install commands                                 │
│    - "Connect Your AI" explanations                       │
└─────────────────────────────────────────────────────────┘
```

## Error States

Every fetch can fail (server down, CORS, network). Each section must degrade gracefully:

| Section | Failure Mode |
|---------|-------------|
| Endpoints | "Could not reach API. [View raw manifest]" (existing) |
| Formats | Falls back to static format grid (keep in HTML as `<noscript>` or hidden fallback) |
| Pricing | Falls back to static tier table |
| Samples | Playground works without sample dropdown (existing) |
| Tools | Static integration cards remain visible |

## CSS Changes

Minimal. The existing CSS classes (`.dp-endpoint`, `.dp-endpoint-header`, `.dp-method-get`, `.dp-method-post`, `.dp-badge-*`, `.dp-playground-*`, `.dp-schema-table`, `.dp-tier-table`) are already well-structured and can be reused by the dynamic renderer.

New classes needed:
- `.dp-device-auth-panel` — device auth flow UI
- `.dp-request-history` — recent requests panel
- `.dp-format-card` — format grid cards (replace inline styles)

## Implementation Order

### Phase A: Extract + Generalize (non-breaking)
1. Refactor `renderPlayground()` to use `input_schema` instead of hard-coded endpoint IDs
2. Refactor `renderCodeExamples()` to generate from schema for all POST endpoints
3. Keep existing behavior as fallback if schema-based rendering fails
4. **Test:** All existing playground features work identically

### Phase B: Dynamic Sections
1. Add `loadFormats()` → render format grid from `/api/v1/formats`
2. Add `loadPricing()` → render pricing table from `/api/v1/pricing`
3. Add `loadTools()` → render tool links from `/api/v1/tools`
4. Update Quick Start to use `capabilities.base_url` and first example
5. Keep static HTML as hidden fallback for each section
6. **Test:** Page renders correctly with API up and gracefully with API down

### Phase C: New Features
1. Device auth flow UI
2. Request history panel (for authenticated users)
3. Request replay from history
4. **Test:** End-to-end device auth flow, replay a request

## What Stays Static

These sections are editorial content that doesn't derive from API state:

- **Unstructured Migration** — fixed comparison code, marketing copy
- **Claude Code Skill** — install command, usage examples
- **SDK Libraries** — pip/npm/go install, quick start examples (future: auto-generate from OpenAPI)
- **"Connect Your AI"** editorial text (how to configure MCP, etc.)

## Verification

1. Kill the API server → page loads with static fallbacks, no console errors
2. Start server → all dynamic sections populate within 2s
3. Add a new endpoint to `capabilities.ail` → it appears on the page without HTML changes
4. Change a price in `pricing.ail` → pricing table updates
5. Add a new sample in `samples.ail` → sample dropdown includes it
6. Mobile (375px): all sections readable, playground forms usable
7. Run `bash tests/test_serve_api.sh` — all 64 tests pass (no API changes needed)

## Out of Scope

- Replacing Firebase Auth with device auth for the dashboard (different design)
- File upload via the playground (endpoints take filepath strings)
- WebSocket streaming or SSE
- A build system (page stays vanilla HTML + JS)
- OpenAPI-based SDK generation (future v0.11.0+)
