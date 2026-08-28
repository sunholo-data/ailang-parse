# Runtime capability manifest — mcpFormats reports state, not intent

**Status**: PLANNED (2026-08-28)
**Source**: issue #17 (`fb_70005cb86d05b0fe`) — capability manifest reports
intent, not runtime state. A deployment with `AILANG_STORAGE` unset advertised
`submit_feedback` as available; a whole session of field reports went nowhere
because the reporting channel itself was silently dead.

## The gap

`mcpFormats` (GET /mcp/v1/formats, this package) and the hosted
`/api/v1/capabilities` describe what the service can do **in principle**. What
an agent needs to route around a degraded deployment is what it can do **right
now**. The reporter's proposal, adapted to what this package's process can
actually know:

```json
{ "runtime": {
    "mode": "local",                       // DOCPARSE_MODE
    "ai_generation": "provisioned",        // AI key env present?
    "storage_backend": "unset",            // AILANG_STORAGE / DOCPARSE_* env
    "pdf_backends": {"pdftotext": true, "docling": false, "liteparse": false, "ai": true}
} }
```

## Scope line

Only what the package process can know **without side effects**: environment
variables (Env) and binary presence (Process `lookPath`, one probe per backend,
cached). No network probes — a hosted health check that phones Google on every
formats call is its own failure mode. The deployment-side half of #17 (startup
asserts, gating the MCP tool list on capability) is the deployment repo's, and
stays there.

## Design

- `mcpFormats` gains a `runtime` object alongside the existing payload:
  - `mode`: `DOCPARSE_MODE` (local default) — decides hosted-vs-local paths
    the same way the tools do.
  - `ai_generation`: `"provisioned"` when a recognised AI key env var
    (GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY) is set and
    non-empty, else `"unconfigured"`. Presence, not validity — key validity
    costs a network call and belongs to a real request.
  - `pdf_backends`: map of backend → bool from `std/process.lookPath`
    (`pdftotext`, `docling`, `liteparse`), plus `"ai"` mapped from the AI key
    check. This is the truth the `--pdf-backend` flag already assumes.
  - `storage_backend`: `AILANG_STORAGE` value or `"unset"` — surfaced so the
    deployment half and the package half report the same fact from the same
    variable.
- The block is additive JSON: existing consumers ignore unknown keys. No
  breaking change, no version bump beyond the usual.
- Failure honesty: a probe that cannot run (Process unavailable) reports
  `"unknown"`, not `false` — an agent distinguishing "not installed" from
  "this response could not check" is the same principle as the issue itself.

## Verification

- Unit test on the runtime-block builder with canned env maps (no FS): each
  state combination maps to the documented value.
- Hosted-mode smoke: run `serve-api` locally without AI keys and assert
  `runtime.ai_generation == "unavailable"`.
- The three benchmark suites stay green (this touches only the formats
  payload).