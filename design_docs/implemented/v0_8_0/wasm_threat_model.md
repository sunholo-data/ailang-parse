# WASM Security Threat Model

**Date**: 2026-03-24
**Status**: Accepted — WASM stays open, risks documented
**Related**: [v0.2.0 Billing Integration](v0_2_0/responsibility-docparse.md), [v0.8.0 API Keys](v0_8_0/v0_8_0_api_keys_cloud_deployment.md)

---

## Summary

The DocParse WASM build runs entirely client-side in the browser (`docs/try.html`). It includes deterministic Office parsers (DOCX, PPTX, XLSX, ODT, ODP, ODS, EPUB, HTML, Markdown, CSV) with **no billing enforcement, no rate limits, and no authentication**.

**Decision**: Keep WASM open. Office parsing is costless and serves as a funnel to the paid AI-powered API.

---

## Architecture Context

### What WASM includes
- AILANG WASM runtime (`docs/wasm/ailang.wasm`, ~35MB)
- 8 parser modules served as `.ail` source from `docs/ailang/`
- Browser adapter: `docparse/services/docparse_browser.ail`
- ZIP extraction via JSZip (JavaScript, client-side)

### What WASM does NOT include
- API key management or validation
- Firestore access or entitlement checks
- Document generation (DOCX/PPTX/XLSX output)
- Server-side AI integration (no Vertex AI credentials)
- Any secrets, service account tokens, or API keys

### What the paid API enforces (4 layers)

| Layer | Mechanism | Scope |
|-------|-----------|-------|
| 1. API Keys | `x-api-key` header → Firestore lookup | Per-request auth |
| 2. Cumulative Quotas | Firestore counters, lazy daily/monthly reset | requests/day, pages/month |
| 3. Capability Budgets | AILANG type-level `@limit` annotations | AI calls, FS ops per request |
| 4. Entitlements | `docparse-access-gate` package, Firestore | Plan-based authorization |

None of these layers apply to WASM — it never contacts the API server.

---

## Threat Model

| # | Vector | Description | Severity | Accepted? | Rationale |
|---|--------|-------------|----------|-----------|-----------|
| 1 | Third-party WASM embedding | Someone embeds our WASM + `.ail` modules in their own service to offer free Office parsing | Medium | **Yes** | Office parsing has zero marginal cost (no AI, no server). Competing with a free feature isn't viable. |
| 2 | Bulk Office parsing via WASM | Users parse large volumes of Office docs client-side instead of using the paid API | Low | **Yes** | No server cost incurred. These users likely wouldn't pay for Office-only parsing anyway. |
| 3 | Source extraction | `.ail` source is served unobfuscated from `docs/ailang/` — anyone can read, copy, or compile locally | Low | **Yes** | DocParse is an AILANG module in a private repo, but the source is served for WASM. This is acceptable given the value is in the AI pipeline + managed service, not the parser source. |
| 4 | Credential extraction from WASM | Reverse-engineer WASM binary to extract API keys or secrets | **None** | N/A | No secrets are compiled into or served alongside the WASM build. |
| 5 | AI billing bypass via WASM | Use WASM to access AI-powered PDF/image parsing without paying | **None** | N/A | AI parsing in WASM requires the user's own Gemini API key (stored in `localStorage`, never touches our infrastructure). |

---

## Why WASM stays open

1. **Office parsing is costless** — deterministic, no AI calls, no server resources consumed
2. **Funnel to paid API** — users who need PDF/image parsing, document generation, or higher throughput must use the API
3. **Locking WASM doesn't help** — `.ail` source is already served publicly; restricting the runtime alone is insufficient
4. **Complexity cost** — domain restrictions, token-gated loading, or obfuscation add maintenance burden with no revenue benefit

---

## What IS protected (server-side only)

| Capability | Protection |
|------------|------------|
| AI-powered parsing (PDF, images, audio, video) | Requires API key with quota; AI capability budget per request |
| Document generation (DOCX, PPTX, XLSX, etc.) | API-only, not in WASM |
| High-throughput / batch parsing | API rate limits + quotas |
| Entitlements & plan management | Firestore-backed, server-enforced |
| Usage tracking & billing | Server-side recording, atomic Firestore increments |

---

## Future considerations

These are **not planned** — only to be revisited if the threat landscape changes:

- **Origin checks**: If third-party embedding becomes a measurable problem, add `document.referrer` or CSP-based restrictions to the WASM loader
- **Token-gated WASM**: Require a free-tier token to initialize the WASM runtime (adds friction, only if needed)
- **Output watermarking**: Add `parsed_by: "docparse-wasm-v{version}"` metadata to parsed output for attribution tracking
- **WASM-specific quotas**: If Office parsing becomes a paid tier feature, enforce quotas client-side with server-validated tokens

---

## Review checklist

- [x] No secrets in WASM build or served assets
- [x] AI parsing requires user-provided API key (not ours)
- [x] Document generation is API-only
- [x] All 4 billing layers are server-side only
- [x] `.ail` source exposure is acceptable
- [x] Threat model reviewed and risks accepted
