# Internal feedback report: "validated local OCR" positioning page

- **Received**: 2026-11-08 (same lead conversation, Mitch Camp, m@sunholo.com)
- **Channel**: mcp.ailang.sunholo.com/submit_feedback
- **Package**: sunholo/ailang_parse @ 0.55.5
- **Auto-dispatch**: **NO** — no `auto:` category prefix on the message.
  Filed internally only; no public PR, no user reply sent (ailang_only lane
  cannot reach the message plane — coordinator to relay if desired).
- **Triage**: feature (site content/marketing page). Needs human-loop design
  before any copy ships.

## User request (substance)

Mitch's team needs a **local/on-prem** deployment specifically due to security
protocols. They are evaluating **Google Document AI OCR vs local OCR vs
LLM-constrained** approaches and are explicitly open to being shown something
better than the local open-source OCR options they already tried.

Observation: the **docling backend** (tier 2: local ML/OCR, free, nothing
leaves the machine) already exists but "isn't marketed as its own thing
anywhere on the site". Suggestion: a **"validated local OCR" page positioned
directly against Google Document AI**, aimed at security/on-prem-constrained
buyers specifically — a narrow-segment page, not a homepage change (the rest
of the site targets SaaS-first visitors).

## Verification (claims checked before filing)

| Claim | Result |
|---|---|
| Docling backend exists as tier-2 local ML | ✅ Confirmed: `assets/pdf_backends/adapter.py` `BACKENDS` maps `"docling": run_docling`; `DOCPARSE_PDF_BACKEND=docling docparse-pdf …` documented in AGENT.md/ailang.toml `[bin]` (docparse-pdf carries `Process`, `--process-timeout 20m` because docling needs ~185 s on a 9-page contract) |
| Not marketed as its own page anywhere | ✅ Confirmed: `docs/llms.txt` page list has no local-OCR/on-prem page. `docs/pdf-parsing.html` covers Docling only as one of four local backends, framed on structure/speed (~28 s vs ~127 s Gemini) — not security positioning, no Document AI comparison. `docs/selfhost.html` is "Run Locally" (CLI install, free/private) but not an OCR-vs-Document-AI page. |
| "Validated" evidence exists to draw on | Partial: `benchmarks/pdf/compare_backends.py`, `benchmarks/omnidocbench/` (results/), `benchmarks.html` (OfficeDocBench vs Docling/LlamaParse/MarkItDown). OCR-accuracy-vs-Document-AI numbers specifically do **not** appear to exist yet. |
| "Nothing leaves the machine" is unqualified-true | ⚠️ Needs care: docling/liteparse run via `uv run --no-project --with <backend>` — first use downloads the backend (and docling model weights) from PyPI/HF once; only later runs reuse the cache (AGENT.md says so explicitly). Air-gapped buyers need a mirror/pre-seed story, otherwise the page's core claim is overstated. |

## Recommendation (needs-design, do not implement from this report)

Open a GitHub issue (`enhancement`, title `[pkg/sunholo/ailang_parse] Validated
local OCR page for security/on-prem segment`) with a needs-design note. Design
questions the issue should raise:

1. **Claim substantiation**: "validated" implies accuracy numbers. We have
   structure benchmarks vs Docling but no head-to-head OCR accuracy vs Google
   Document AI. Either run one (OmniDocBench-style, docling backend adapter
   already exists) or soften the page to "local, deterministic, free" without
   the "validated" superlative.
2. **Air-gap honesty**: document the first-run download (PyPI + model weights)
   and what a fully air-gapped install requires (pre-seeded uv cache / mirror).
   This is also a possible product gap worth a separate issue if it turns out
   to be hard.
3. **Segment scope**: page targets security-constrained buyers only; keep it
   out of the homepage/nav mainline; cross-link from `selfhost.html`,
   `pdf-parsing.html` (#local-backends) and `privacy.html`.
4. **Positioning table**: local docling vs Google Document AI on: data egress,
   model access (API key vs none), cost model, determinism, DPA/compliance
   story, deployment (on-prem binary vs GCS-backed API).
5. Docling today is positioned for *structure* on born-digital PDFs; if the
   page claims *OCR on scans*, verify the adapter actually enables docling's
   OCR pipeline for scanned pages before publishing (current site copy only
   claims scanned-PDF handling via the AI tier).
