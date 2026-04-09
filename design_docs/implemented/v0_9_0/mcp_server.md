# v0.9.0 — Production MCP Server

**Status**: IMPLEMENTED (v0.9.0–v0.9.2)
**Theme**: Ship a polished, 3-tool MCP server that agents actually want to use
**Depends on**: v0.8.0 agent-friendly API, v0.7.0 serve-api

## Motivation

AILANG's `serve-api --mcp` and `--mcp-http` transport layers work — initialize, tools/list, and tools/call all succeed. But the DX is unusable in practice:

- **159 tools** exposed (every exported function), including internals like `xmlEscape`, `docxNs`, `cellText`
- **Tool names** are machine-specific absolute paths for package-loaded modules (`Users.mark.dev.sunholo.ailang-parse.docparse.services.samples.sampleResolvePath`)
- **Descriptions** are raw AILANG type signatures (`parseCsv(∀α46. (string, string) -> [α46] ! {...ε41}) [pure]`)
- **Input schemas** use a generic positional `args` array — no named parameters, no per-param descriptions
- `--routes-only` flag has no effect on the MCP tool list

These are filed as ailang-core issues #145–#149. This design doc covers what *we* ship in ailang-parse on top of those runtime fixes, plus the docs page update.

## Integration Test Results (2026-04-03)

| Transport | Init | tools/list | tools/call | Notes |
|-----------|------|------------|------------|-------|
| stdio (`--mcp`) | OK | OK (159 tools) | OK (parseDocx) | For Claude Desktop, Cursor |
| HTTP (`--mcp-http`) | OK | OK (159 tools) | OK (parseDocx) | SSE Streamable HTTP at `/mcp/` |
| REST (`/api/v1/tools`) | OK | — | — | Tool definitions in Claude/OpenAI/MCP/A2A formats |

## Auth, Billing & the MCP Gap

### Current State

The billing/auth system lives in the **root `docparse` repo** (not `ailang-parse`):

| Component | Location | What It Does |
|-----------|----------|-------------|
| Device auth flow | `docparse/services/device_auth.ail` | RFC 8628 — agent gets `dp_` key via browser approval |
| API key validation | `docparse/services/api_keys.ail` | SHA-256 lookup in Firestore, tier resolution |
| Quota enforcement | `docparse/services/api_keys.ail` | Per-day, per-month, per-request budget caps |
| Parse authorization | `docparse/services/parse_authorization.ail` | Checks quota before allowing parse |
| Auth-gated parse | `docparse/services/api_server.ail` | `POST /api/v1/parse` — requires `dp_` key |

**The problem:** MCP at `/mcp/` is **completely open**. When an agent calls `tools/call` with `parseDocx`, it hits the raw parser function directly — bypassing API key validation, quota checks, and billing entirely.

```
REST path (gated):      Agent → dp_ key → /api/v1/parse → quota check → parser
MCP path (open):        Agent → /mcp/ → tools/call → parser directly ← NO AUTH
```

### Two Modes, Two Auth Stories

```
┌──────────────────────────────────────────────────────────────┐
│  LOCAL MODE (stdio / localhost HTTP)                          │
│                                                              │
│  No auth needed. User's own machine, own files.              │
│  ailang serve-api --mcp --caps IO,FS,Env docparse/           │
│                                                              │
│  Billing: none (local compute only)                          │
│  AI parsing: user's own GOOGLE_API_KEY / ANTHROPIC_API_KEY   │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  HOSTED MODE (docparse.ailang.sunholo.com/mcp/)              │
│                                                              │
│  Auth required. MCP tool calls must carry dp_ API key.       │
│  Quota enforcement same as REST /api/v1/parse.               │
│                                                              │
│  Billing: per-request, same 3-tier model                     │
│  AI parsing: server-side Vertex AI (cost borne by us)        │
└──────────────────────────────────────────────────────────────┘
```

### MCP Auth Flow: Guiding the Agent

The MCP server should **actively help agents acquire and use credentials**. Not just reject unauthenticated requests — walk the agent through the flow.

**Step 1: Agent connects, tries to parse**

```json
→ tools/call: ailang_parse {filepath: "report.docx"}
← error: {
    "code": "AUTH_REQUIRED",
    "message": "Hosted mode requires a dp_ API key. Call ailang_auth to get one.",
    "suggested_fix": "Use the ailang_auth tool to start device authorization"
  }
```

**Step 2: Agent calls `ailang_auth` tool**

```json
→ tools/call: ailang_auth {}
← {
    "status": "pending",
    "user_code": "ABCD-1234",
    "verification_url": "https://www.sunholo.com/docparse/approve.html?code=ABCD-1234",
    "message": "Ask the user to open this URL and approve access. Then call ailang_auth_poll.",
    "expires_in_seconds": 900
  }
```

The agent shows the user the URL + code. User opens browser, logs in with Firebase (Google/GitHub/email), approves.

**Step 3: Agent polls for approval**

```json
→ tools/call: ailang_auth_poll {device_code: "xxx"}
← {
    "status": "approved",
    "api_key": "dp_a1b2c3d4...",
    "tier": "free",
    "message": "Authenticated. Pass this api_key in all subsequent tool calls.",
    "limits": {
      "requests_per_day": 50,
      "requests_per_month": 1000,
      "ai_requests_per_month": 50,
      "max_file_size_mb": 10
    }
  }
```

**Step 4: Agent includes key in all subsequent calls**

```json
→ tools/call: ailang_parse {filepath: "report.docx", api_key: "dp_a1b2c3d4..."}
← { blocks: [...], meta: { quota_remaining: 49, ... } }
```

### Revised Tool Surface: 5 Tools (Hosted) / 3 Tools (Local)

| Tool | Local | Hosted | Purpose |
|------|-------|--------|---------|
| `ailang_parse` | yes | yes | Parse documents |
| `ailang_convert` | yes | yes | Convert between formats |
| `ailang_formats` | yes | yes | List supported formats |
| `ailang_auth` | no | yes | Start device auth flow |
| `ailang_auth_poll` | no | yes | Poll for auth approval |

Local mode exposes 3 tools (no auth needed). Hosted mode exposes 5 tools (auth + parse). The server knows which mode it's in based on whether `--api-key-env` is set.

### Billing Integration Points

MCP tool calls in hosted mode must flow through the same billing path as REST:

```
MCP tools/call (hosted)
  → mcp_tools.ail: ailang_parse(filepath, outputFormat, api_key)
  → api_keys.ail: validateApiKey(api_key) → userId, tier, limits
  → parse_authorization.ail: authorizeParse(userId, fileSize, ...)
  → quota check (Firestore: requestsToday, requestsThisMonth)
  → parser dispatch (format_router → docx_parser, etc.)
  → quota increment (Firestore: requestsToday += 1)
  → return result with meta.quota_remaining
```

**Implementation:** `mcp_tools.ail` imports from the root `docparse` repo's auth modules. Since both repos are deployed together on Cloud Run, the imports resolve. For local mode, auth is simply skipped (no Firestore, no API key validation).

### Quota Visibility in MCP

Every tool response in hosted mode includes quota metadata so the agent can self-regulate:

```json
{
  "content": [{"type": "text", "text": "{blocks: [...]}"}],
  "meta": {
    "quota_used_today": 13,
    "quota_remaining_today": 37,
    "quota_used_month": 247,
    "quota_remaining_month": 753,
    "tier": "free",
    "upgrade_url": "https://www.sunholo.com/docparse/pricing"
  }
}
```

When quota is near exhaustion, the response includes a warning:

```json
{
  "meta": {
    "warning": "5 requests remaining today. Resets at midnight UTC.",
    "upgrade_url": "https://www.sunholo.com/docparse/pricing"
  }
}
```

---

## Target: 3-Tool MCP Surface

Agents should see **3 tools (local)** or **5 tools (hosted)**:

```
┌──────────────────────────────────────────────────────────────┐
│  MCP Server: ailang-parse                                     │
│                                                               │
│  Tools (always):                                              │
│    1. ailang_parse     — Parse any document → structured blocks│
│    2. ailang_convert   — Convert between document formats      │
│    3. ailang_formats   — List supported input/output formats   │
│                                                               │
│  Tools (hosted only):                                         │
│    4. ailang_auth      — Start device auth, get dp_ API key   │
│    5. ailang_auth_poll — Poll for browser approval             │
│                                                               │
│  Resources:                                                   │
│    - Sample documents (26 fixtures with stable IDs)           │
│                                                               │
│  Prompts:                                                     │
│    - parse_guide       — How to use the parse tool well       │
│    - format_matrix     — Which formats support which features  │
│    - auth_guide        — How to authenticate (hosted only)     │
└──────────────────────────────────────────────────────────────┘
```

### Tool 1: `ailang_parse`

```json
{
  "name": "ailang_parse",
  "description": "Parse any document (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, Markdown, CSV, EPUB, PDF, images, audio, video) into structured blocks. Office formats are deterministic and instant. PDF/images use AI. Returns typed blocks (Heading, Text, Table, Image, Change, Comment, Section, Code, Footer/Header) preserving document structure that flat text extraction loses.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "filepath": {
        "type": "string",
        "description": "Absolute path to file, or a sample_id from the samples resource"
      },
      "outputFormat": {
        "type": "string",
        "enum": ["blocks", "markdown", "html"],
        "default": "blocks",
        "description": "blocks = structured JSON with typed Block ADT; markdown = rendered Markdown; html = rendered HTML"
      }
    },
    "required": ["filepath"]
  }
}
```

### Tool 2: `ailang_convert`

```json
{
  "name": "ailang_convert",
  "description": "Convert a document from one format to another. Supports: DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, Markdown, QMD (Quarto). Input is parsed to structured blocks, then generated into the target format.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "input": {
        "type": "string",
        "description": "Path to input file"
      },
      "outputFormat": {
        "type": "string",
        "enum": ["docx", "pptx", "xlsx", "odt", "odp", "ods", "html", "markdown", "qmd"],
        "description": "Target format for conversion"
      },
      "outputPath": {
        "type": "string",
        "description": "Path to write the output file. If omitted, uses input filename with new extension."
      }
    },
    "required": ["input", "outputFormat"]
  }
}
```

### Tool 3: `ailang_formats`

```json
{
  "name": "ailang_formats",
  "description": "List all supported input and output formats with metadata: which require AI, which are deterministic, supported structural features (tables, track changes, comments, headers/footers, images).",
  "inputSchema": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

---

## Implementation Plan

### P0: AILANG Runtime Fixes (blocked on ailang-core)

These are prerequisites from #145–#149:

| Issue | What | Workaround Until Fixed |
|-------|------|----------------------|
| #145 | `--routes-only` must filter MCP tools/list | Use `@noexpose` on all internal helpers |
| #146 | Tool names use absolute paths | None — must be fixed in runtime |
| #147 | Descriptions should use doc comments | Add `@mcp_description` annotations |
| #148 | inputSchema should use named params | Hand-craft tool definitions in MCP handler |
| #149 | `@noexpose` should hide from MCP | Add `@noexpose` to all non-API exports |

### P1: MCP-Specific AILANG Module

Create `docparse/services/mcp_tools.ail` — a dedicated MCP tool handler that wraps the internal parsers with agent-friendly interfaces.

**Why a wrapper?** Even after ailang-core fixes #145–#149, we want:
- Curated tool surface (not 1:1 with every exported parser function)
- Agent-optimized descriptions (not just doc comments)
- Named parameters with validation
- Proper error messages an agent can act on
- Sample ID resolution built in
- **Auth gating in hosted mode** — route through billing before parsing

```
docparse/services/mcp_tools.ail
├── ailang_parse(filepath, outputFormat, api_key?) → JSON
├── ailang_convert(input, outputFormat, outputPath?, api_key?) → string
├── ailang_formats() → JSON
├── ailang_auth() → {user_code, verification_url, device_code}  [hosted only]
└── ailang_auth_poll(device_code) → {api_key, tier, limits}      [hosted only]
```

Each parse/convert function:
1. **If hosted mode** (`--api-key-env` set): validates `api_key`, checks quota via Firestore, increments counters
2. **If local mode**: skips auth, parses directly
3. Validates inputs with agent-friendly error messages
4. Resolves `sample_id` references → real file paths
5. Dispatches to the correct parser/generator via format_router
6. Returns result with quota metadata (hosted) or plain result (local)

Auth tools (`ailang_auth`, `ailang_auth_poll`):
1. Only registered when server is in hosted mode
2. Wrap device auth flow from root `docparse` repo (`device_auth.ail`)
3. Return agent-friendly messages that guide the user through browser approval
4. Include tier limits in the approval response so agents know their budget

**Files to create:**
- `docparse/services/mcp_tools.ail` — MCP tool implementations (parse, convert, formats)
- `docparse/services/mcp_auth.ail` — MCP auth tools (device flow wrappers)

**Files to modify:**
- `docparse/services/tools.ail` — Update `/api/v1/tools` to reflect actual MCP tool schemas
- Add `@noexpose` to internal modules that shouldn't appear in MCP (xml_helpers, zip_extract, output_formatter internals, eval, etc.)

**Cross-repo dependency:** `mcp_auth.ail` imports from root `docparse` repo's `device_auth.ail` and `api_keys.ail`. Both repos deploy together on Cloud Run, so imports resolve in production. For local dev, auth tools simply aren't registered.

### P2: MCP Resources & Prompts

MCP supports **resources** (read-only data the agent can browse) and **prompts** (reusable prompt templates). These are cheap to add and make the server significantly more useful.

**Resources:**
- `samples://list` — Returns the 26 sample documents with IDs, labels, tags
- `samples://{id}` — Returns parsed output for a specific sample (golden output)
- `formats://matrix` — Feature matrix (which formats support tables, track changes, etc.)

**Prompts:**
- `parse_guide` — "Given a document, here's how to choose the right outputFormat and interpret the block types"
- `format_matrix` — "Here's what each format supports, so you can recommend conversions"

### P3: Local vs Hosted Modes

Two deployment paths, same MCP server:

```
Local (stdio):
  Claude Desktop / Cursor / VS Code
  ↓ stdin/stdout
  ailang serve-api --mcp --caps IO,FS,Env docparse/

Local (HTTP):
  Any MCP client
  ↓ HTTP POST /mcp/
  ailang serve-api --mcp-http --port 8080 --caps IO,FS,Env docparse/

Hosted (HTTP):
  Any MCP client, no local install
  ↓ HTTPS POST /mcp/
  https://docparse.ailang.sunholo.com/mcp/
  (API key required: dp_xxx)
```

**Configuration examples to ship:**

```json
// Claude Desktop — Local
{
  "mcpServers": {
    "ailang-parse": {
      "command": "ailang",
      "args": ["serve-api", "--mcp", "--caps", "IO,FS,Env", "docparse/"],
      "cwd": "/path/to/ailang-parse"
    }
  }
}
```

```json
// Claude Desktop — Hosted (via @ailang/parse npm package, requires Node >= 18)
{
  "mcpServers": {
    "ailang-parse": {
      "command": "npx",
      "args": ["-y", "@ailang/parse", "mcp"]
    }
  }
}
```

```bash
// Claude Code — install plugin (recommended)
claude install github:sunholo-data/docparse-skill

// Or add to .mcp.json (hosted)
{
  "mcpServers": {
    "ailang-parse": {
      "url": "https://docparse.ailang.sunholo.com/mcp/"
    }
  }
}

// Or add to .mcp.json (local)
{
  "mcpServers": {
    "ailang-parse": {
      "command": "ailang",
      "args": ["serve-api", "--mcp", "--caps", "IO,FS,Env", "docparse/"]
    }
  }
}
```

```json
// Cursor — .cursor/mcp.json
{
  "mcpServers": {
    "ailang-parse": {
      "command": "ailang",
      "args": ["serve-api", "--mcp", "--caps", "IO,FS,Env", "docparse/"]
    }
  }
}
```

### P4: Docs Page Update

Update `docs/mcp.html` to reflect the actual tested behavior:

1. **Quick Start** — Real commands that work (tested 2026-04-03)
2. **Configuration snippets** — Claude Desktop (local + hosted), Claude Code, Cursor, VS Code, generic MCP
3. **Tool reference** — Document each of the 3 tools with example inputs/outputs
4. **Troubleshooting** — Common issues (159 tools appearing, absolute path names)
5. **Remove** references to tools that don't exist yet (ailang_estimate)
6. **Add** "Try it" section — curl commands agents can copy to test

---

## Testing Strategy

### MCP Integration Tests

Create `tests/mcp_integration.sh`:

```bash
#!/bin/bash
# MCP Integration Test Suite
# Tests both stdio and HTTP transports

# 1. stdio: initialize → tools/list → tools/call
# 2. HTTP: initialize → tools/list → tools/call
# 3. Verify tool count = 3 (not 159)
# 4. Verify tool names are portable (no absolute paths)
# 5. Verify tool descriptions are human-readable
# 6. Verify inputSchema has named parameters
# 7. Call ailang_parse with sample_docx_basic → verify blocks
# 8. Call ailang_convert sample.docx → html → verify output
# 9. Call ailang_formats → verify format list
# 10. Verify MCP resources (samples list, sample content)
```

### Claude Desktop Smoke Test

Manual test checklist:
- [ ] Install local MCP config in Claude Desktop
- [ ] Ask Claude: "What tools do you have from ailang-parse?"
- [ ] Ask Claude: "Parse this DOCX file" (with a real file path)
- [ ] Ask Claude: "What formats does ailang-parse support?"
- [ ] Ask Claude: "Convert this DOCX to HTML"

---

## Priority & Effort

| Priority | Task | Effort | Blocked On |
|----------|------|--------|------------|
| P0 | ailang-core runtime fixes (#145–#149) | — | ailang-core team |
| P1 | `mcp_tools.ail` — parse, convert, formats wrappers | 1 day | — |
| P1 | `mcp_auth.ail` — device auth + poll wrappers | 0.5 day | Root docparse repo |
| P1 | `@noexpose` on internal modules | 0.5 day | — |
| P1 | Auth gating: hosted tool calls → billing pipeline | 1 day | Root docparse repo |
| P1 | MCP integration test script | 0.5 day | P1 wrappers |
| P2 | MCP resources (samples) | 0.5 day | P0 #145 |
| P2 | MCP prompts (parse_guide, format_matrix, auth_guide) | 0.5 day | — |
| P2 | Quota metadata in every tool response | 0.5 day | P1 auth gating |
| P3 | Hosted deployment config (Cloud Run + `/mcp/`) | 0.5 day | Existing infra |
| P3 | Config examples (Claude Desktop, Cursor, VS Code, Claude Code) | 0.5 day | — |
| P4 | docs/mcp.html refresh + landing page skill | 0.5 day | P1 wrappers |

## Open Questions

1. **Should `ailang_parse` accept base64 file content?** The hosted version can't see local files. Current workaround: agent uploads via REST `/api/v1/parse`, not MCP. But MCP spec supports binary content in tool args — should we use it?

2. **Should we add `ailang_generate`?** A 6th tool for AI document generation (`--generate` flag). This requires AI capability and costs money — counts against `aiRequestsPerMonth` quota. Maybe v0.10.0.

3. **MCP OAuth extension vs device-auth-as-tool** — The MCP spec has an emerging OAuth extension for server-initiated auth. We've chosen device-auth-as-tool (agent calls `ailang_auth`) which is simpler and works today. Should we also support the MCP OAuth extension when it stabilizes?

4. **Notifications** — Should parsing large PDFs (which take 5-30s with AI) use MCP progress notifications? The spec supports `notifications/progress`.

5. **Shared API key across sessions** — Once an agent acquires a `dp_` key via device auth, should the MCP server persist it (e.g., in a local config file) so the agent doesn't re-auth every session? Or is that the client's responsibility?

6. **Free tier "try before auth"** — Should we allow a small number of unauthenticated MCP tool calls (e.g., 5/day) to let agents explore before the user commits to the device auth flow? Or always gate?
