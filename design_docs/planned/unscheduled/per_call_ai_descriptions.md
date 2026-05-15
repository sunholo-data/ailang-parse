# Design Doc: Per-Call AI Descriptions (`describe=True`)

**Status**: Unscheduled — deferred from SDKs v0.7.0
**Date**: 2026-05-16
**Author**: Mark + Claude
**Source**: Alternative shape proposed in multivac's v0.7.0 field-test feedback (`msg_20260516_012720_2ed63396`, finding #1). SDKs v0.7.0 ships the cheap fix (always emit `ImageBlock` with placeholder); this doc covers the bigger, more product-coupled alternative.

---

## Problem

Today, image descriptions are produced as a side effect of choosing an AI-capable parse path. The user has no direct control: parse a DOCX on the free tier and `ImageBlock.description` is empty; parse a PDF on the AI tier and *every* image gets a caption whether you wanted them or not.

This conflates three orthogonal things:

1. **Format dispatch.** Office formats (DOCX, PPTX, XLSX) parse deterministically; PDF/images parse via AI.
2. **AI availability.** Tier — free has none, pro/business have it.
3. **Image-caption intent.** Whether *this caller, this call* wants captions.

There's no way today to say "I'm parsing a DOCX, but please caption the images this time" or "I'm parsing a PDF, but skip image captions to save quota." Both are reasonable asks.

Multivac's v0.7.0 ask flagged the symptom (free-tier consumers get no image content) and proposed two fixes:
- **(a)** SDK-only: always emit `ImageBlock`, let consumer decide. Shipped in v0.7.0.
- **(b)** API surface: `describe=True` opt-in. This doc.

Fix (a) is necessary regardless — consumers always want the *option* to see an image was there. Fix (b) is sufficient to give paid-tier consumers per-call control and free-tier consumers a clear, billable path to image content.

---

## Non-Goals

- **Replacing the existing AI-required format dispatch.** PDFs continue to route through AI by default; this is purely additive.
- **Audio/video transcription opt-in.** Same general shape would apply (`transcribe=True`), but the cost profile is very different (per-second pricing, async transcription, longer-running calls). Out of scope; revisit after `describe=True` ships.
- **Caching captions across calls.** Same image content hash → same caption → skip AI. Worth doing, but lives downstream of the basic opt-in mechanism.
- **A consumer-supplied captioner.** "Use my OpenAI key / my prompt / my model" is a separate product surface (BYO-AI). Out of scope.
- **Inline OCR for scanned documents.** OCR is a different model class than visual description. Tracked separately.

---

## Surface

### CLI

```bash
docparse report.docx --describe       # opt-in to image captions
docparse report.docx --no-describe    # opt-out (default for deterministic formats)
docparse report.pdf  --no-describe    # opt-out for AI-routed formats (saves quota)
```

The flag is **tri-state internally** (`unset` / `true` / `false`) so the format default can apply when the user doesn't pass either. CLI exposes only the two explicit forms; `unset` = no flag.

### API

`POST /api/v1/parse` gains a `describe` query parameter (and request body field):

```http
POST /api/v1/parse?describe=true
{
  "filepath": "...",
  "outputFormat": "blocks",
  "describe": true
}
```

Body wins over query string when both are present. Server-side resolution order:

1. Explicit `describe` (true or false) → use it
2. Format default: AI-required formats (PDF, PNG, JPG, etc.) → `true`; deterministic formats → `false`
3. Caller's tier policy can override (see "Tier policy" below)

### SDKs (Python first)

```python
client.parse_file("report.docx", describe=True)
client.parse_url(signed_url, describe=False)
client.parse_gs_uri("gs://bucket/key.pdf", describe=False)  # PDF without burning AI quota
```

`describe` is `None` by default (let server decide); explicit `True` / `False` overrides. Same signature lands on JS + Go when they catch up to v0.6.0 features.

### Block-side

No new block variants. Same `ImageBlock` with `description` populated or not. Combined with the v0.7.0 "always emit `ImageBlock`" change, the consumer-visible matrix becomes:

| describe | has caption | `description` field | Placeholder text in `flatten()` |
|----------|-------------|---------------------|---------------------------------|
| `True`   | ✓           | AI caption          | AI caption                       |
| `True`   | ✗ (AI failed) | empty             | `[image: image/png, 12345 bytes]` |
| `False`  | n/a         | empty               | `[image: image/png, 12345 bytes]` |

A new `ChunkMetadata.extras["image_has_description"]` boolean (already landing in v0.7.0) lets consumers distinguish the rows.

---

## Tier policy

This is the gnarly part — what does each tier *do* with `describe=true`?

### Proposed semantics

| Tier | `describe=true` on DOCX | `describe=true` on PDF | `describe=false` on PDF |
|------|------------------------|------------------------|--------------------------|
| Free | **Reject** with 402 / suggested upgrade | Allow (current behaviour) | Allow — saves AI quota |
| Pro  | Allow, consume AI quota | Allow, consume AI quota   | Allow                    |
| Business | Allow, consume AI quota | Allow, consume AI quota | Allow                |

Rationale:
- Free-tier opt-in *to* AI for a deterministic format is the only path that adds cost we haven't priced. Reject it. The error response includes a `suggested_fix` pointing at the upgrade page.
- Free-tier *opt-out* from AI on a PDF (`describe=false` on PDF) costs nothing — image captions are skipped, text extraction still runs. Allow it. This is the bonus path: free-tier consumers can parse PDFs and accept no captions.
- Paid tiers can do whatever they want; AI quota counter is the throttle.

### Quota accounting

Today's `X-DocParse-Quota-Remaining-Ai` counter is per-parse-call. With `describe=true` adding AI calls inside an otherwise-deterministic parse, the counter needs to reflect the *actual* AI calls made:

- DOCX with 5 images, `describe=true` → 5 captioning calls → AI counter decremented by 5? or by 1 ("this parse used AI")?

**Proposal: by 1 per parse call.** Captioning 5 images is one parse; the user sees one charge. The internal model cost is bounded by per-document image limits (say 20 images max per parse, configurable per-tier).

Open question for the pricing-strategy work: should the per-document image cap be different per tier? Pro = 20, Business = 100? Tracked in [project_pricing_strategy.md].

### Quota error shape

A free-tier caller hitting `describe=true` on a DOCX gets:

```http
HTTP/1.1 402 Payment Required
X-DocParse-Tier: free
X-Request-Id: req_abc...

{
  "error": "AI captioning requires a paid tier",
  "suggested_fix": "Upgrade at https://www.sunholo.com/ailang-parse/pricing, or call without describe=true.",
  "details": {
    "tier": "free",
    "requested_feature": "describe",
    "upgrade_url": "https://www.sunholo.com/ailang-parse/pricing"
  }
}
```

402 (not 429): "you can't do this on your current plan" vs "you've used your quota." Both end up in the SDK's `DocParseError`/`QuotaError`; the SDK can introspect `details.requested_feature` to give a precise hint.

---

## Parser-side work

### Where `describe` enters the AILANG dispatch

```
docparse/main.ail
  ├── parses CLI flags → DescribePolicy { Auto | Force | Skip }
  └── services/docx_parser.parse(..., describe: DescribePolicy)
      ├── on Force: for each ImageBlock, call services/ai_descriptions.caption(image)
      └── on Skip:  emit ImageBlock with empty description (current free-tier behaviour)

      services/pdf_parser.parse(..., describe: DescribePolicy)
      ├── on Force / Auto: same path as today (AI captions images while parsing)
      └── on Skip: short-circuit AI captioning, keep AI text extraction
```

The `DescribePolicy` ADT is what flows through the parser. The API/CLI translate user input to it:

```ailang
type DescribePolicy
  = Auto    -- defer to format default
  | Force   -- caption every image (subject to tier policy)
  | Skip    -- don't caption, leave description empty
```

### New module: `services/ai_descriptions.ail`

Single-purpose: take an image (mime + bytes), call the configured AI model, return a caption. Lives behind the `AI` effect capability so the existing AILANG sandboxing applies. Replays cleanly through `--ai` model selection.

### Cost: implementation estimate

- Parser surface change: ~1 day. Touches DOCX, PPTX, XLSX, ODT, ODP, ODS, EPUB parsers — each currently emits `ImageBlock` deterministically and would gain an "if describe-force, caption now" branch.
- PDF parser change: ~0.5 day. Already routes through AI; add a `describe=Skip` short-circuit.
- API/CLI plumbing + tier policy enforcement: ~1 day.
- Tests + docs: ~1 day.
- **Total**: ~3.5 days end-to-end on the parser side. SDKs add ~half-day each once parser ships.

### Dependency on v0.7.0 SDK work

None — v0.7.0 ships the "always emit `ImageBlock`" change with a placeholder for empty descriptions. That's a strict prerequisite for `describe=False` to be useful (otherwise consumers calling `describe=False` on a PDF would lose image visibility entirely). v0.7.0 is the *floor*; this doc is the *ceiling*.

---

## Risks

- **Tier-policy reject is a UX papercut.** A free-tier caller passing `describe=true` gets a 402. Mitigation: clear `suggested_fix`, prominent in docs that this is paid-only on deterministic formats.
- **Per-image quota accounting drift.** If we charge "1 per parse" but a document has 200 images, the cost-to-revenue ratio gets ugly. Mitigation: hard cap on images-captioned-per-parse, surfaced as `X-DocParse-Images-Captioned`.
- **AI quality on small inline images.** A 64×64 icon caption is noise. Mitigation: parser-side filter — skip captioning for images below a size threshold (default 128×128 or 5KB), surface that in `ChunkMetadata.extras["image_skipped_below_threshold"]`.
- **API surface drift between `outputFormat`-driven AI and `describe`-driven AI.** The "did this call use AI" answer is no longer one bit. Mitigation: `X-DocParse-Used-Ai: true|false` response header so consumers can audit.

---

## Acceptance criteria (when scheduled)

- [ ] CLI: `--describe` / `--no-describe` flag accepted and propagated
- [ ] API: `describe` query param + request body field accepted
- [ ] AILANG: `DescribePolicy` ADT threaded through every parser module
- [ ] Free-tier `describe=true` on DOCX returns 402 with structured `suggested_fix`
- [ ] Paid-tier `describe=true` on DOCX captions every image (bounded by per-parse image cap)
- [ ] Paid-tier `describe=false` on PDF parses text but skips image captions (verified via `X-DocParse-Used-Ai: true` for text, no caption text in `ImageBlock.description`)
- [ ] `X-DocParse-Used-Ai` and `X-DocParse-Images-Captioned` headers populated
- [ ] Python SDK: `parse_file(..., describe=True)` and friends
- [ ] CHANGELOG entry under "API surface changes"
- [ ] Pricing page updated with the new opt-in semantics

---

## Out of scope (this doc and the SDK doc)

- BYO-AI captioning
- Cross-image cache (hash-based dedup of caption work)
- Audio/video transcription opt-in
- Local OCR fallback for `describe=true` on free tier

---

## References

- v0.7.0 SDK doc (ships the cheap half — always emit `ImageBlock`): [v0_20_0_sdk_v07_extras_images_comments_tablecells.md](../v0_20_0/v0_20_0_sdk_v07_extras_images_comments_tablecells.md)
- v0.6.0 SDK doc (sets the error-handling baseline this would build on): [v0_20_0_sdk_ergonomics.md](../v0_20_0/v0_20_0_sdk_ergonomics.md)
- multivac feedback proposing (b): `msg_20260516_012720_2ed63396`, finding #1, option (b)
- Pricing strategy (memory note): `project_pricing_strategy.md`
- Tier definitions (memory note): see existing tier quotas in `serve-api/` config
