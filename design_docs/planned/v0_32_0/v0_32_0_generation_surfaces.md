# Generation as a product surface — API endpoint, browser WASM, and what each can be charged for

**Status**: PLANNED (2026-08-11)
**Theme**: We generate 9 formats with real fidelity, and **no paying surface can reach it.** Fix that first; browser generation is a demo of a capability customers currently cannot buy.
**Follows**: [`v0_30_0_inline_runs.md`](../../implemented/v0_30_0/v0_30_0_inline_runs.md) — which completed inline formatting in both directions, entirely inside surfaces the API does not expose.

## The gap, measured

Generation is reachable from the CLI, the registry package, and stdio MCP. It is
reachable from **nothing else**:

| surface | parse | convert / generate |
|---|---|---|
| CLI (`--convert`, `--generate`) | ✓ | ✓ 9 formats |
| registry package | ✓ | ✓ |
| stdio MCP (`mcpConvert`) | ✓ | ✓ (local work) |
| **hosted API** | ✓ `/api/v1/parse` | **✗ no endpoint** |
| **Python SDK** | ✓ `parse`, `parse_url`, `parse_gs_uri`, `parse_file` | **✗** |
| **JS / Go / R SDKs** | ✓ | **✗** |

Documented endpoints are `/parse`, `/estimate`, `/samples`, `/pricing`,
`/auth/device`. There is no `/convert`.

So everything v0.29.0–v0.31.0 shipped on the generate side — DOCX OPC wiring,
inline runs across DOCX/HTML/PPTX/ODT/ODP/QMD, ODF whitespace fidelity, run
coalescing — is invisible to every surface that bills. That is the finding that
should set priority.

**Related inconsistency worth fixing in passing**: `mcpConvert` in hosted mode
demands an API key and then does the conversion **locally**
([`mcp/tools.ail:163`](../../../docparse/services/mcp/tools.ail#L163)). The key
gates work that runs on the user's own machine, because there is no server-side
conversion to call.

## Browser WASM is not blocked — the design doc was wrong about why

`v0_29_0` item 9 records browser generation as blocked on ailang-core #644
(`std/zip` has no in-memory archive builder). That is true only if AILANG must
do the zipping. It doesn't have to.

`generateDocx` is already cleanly split. Every part-builder is `pure`:

```ailang
pure func docxTextParts(doc, documentXml, parts) -> [{name: string, content: string}]
pure func docxImageEntries(images)               -> [{name: string, data: string}]
...
match createArchive(outputPath, textParts) { ... }   -- the ONLY ! {FS} step
```

All the fidelity — OPC relationships, `w:rPr` runs, numbering, styles, headers —
is string construction that runs anywhere. The single filesystem-bound line
packages already-built strings into a ZIP.

**So the browser route is: export the parts list, and let JavaScript zip it**
(JSZip, or native `CompressionStream('deflate-raw')` plus a small
central-directory writer). No upstream fix, no waiting on #644.

This does not violate "never reimplement parsers outside AILANG": the document
itself — every byte of XML — still comes from AILANG. JavaScript only does
container packaging, the one step that is pure plumbing.

## The crux: browser generation cannot be metered

Parse is billed per document / per page. **Generation that runs in the browser
is unbillable by construction** — no request reaches us, so there is nothing to
count, rate-limit or attribute to a key.

That makes the ordering a commercial decision, not a technical one:

- Ship **browser generation first** and we give away, for free and irreversibly,
  the capability we would want to price. Expectations set this way are hard to
  walk back.
- Ship the **API endpoint first** and generation becomes sellable, with the
  browser version arriving later as a deliberately limited demo — exactly what
  the parse demo already is.

## Recommendation

**Priority 1 — `/api/v1/convert` plus SDK methods.** This is the work with
revenue attached and it closes a real product hole. Reuses `orchestrator`
recipes and the existing generators; no new document logic.

**Priority 2 — browser generation as a demo surface**, size- or sample-capped
the way the parse demo is. Its job is the privacy and no-round-trip story
("your document never leaves the browser"), which is genuine and differentiating
— but it is marketing, not revenue.

**Priority 3 — pricing.** Generation is not obviously "per page": a 3-block
prompt can produce a 40-page document. Candidate models, to be decided rather
than assumed:
- per generated document (simple, predictable, matches parse)
- per output byte / part count (tracks real cost, hard to explain)
- bundled into the parse tier as a conversion allowance (best for adoption,
  weakest for margin)

The honest answer to "is browser generation enough for today's platform energy?"
is **no, and it is also not the bottleneck**. The bottleneck is that a paying
customer cannot generate a document at all.

## Validation: a hidden test page

Before committing to the browser route, prove it on a real document rather than
on reasoning. A page at `docs/lab/docx-generation.html`, unlinked from any nav
and excluded from the sitemap, that:

1. loads the existing WASM bundle plus the generator modules,
2. calls the new pure parts export,
3. zips in JS and triggers a download,
4. reports **bundle delta, time-to-first-byte and peak memory** on screen.

Three numbers decide whether this ships:

| measure | why it decides |
|---|---|
| bundle delta | generators added to `MODULES_TO_LOAD` grow every page load, including parse-only visitors |
| generation time | a document with images forces base64 through `createArchiveWithBytes`, the memory-heavy path |
| output fidelity | the downloaded file must open in Word and survive `python-docx` run assertions, same bar as the CLI |

If the bundle cost is unacceptable, the fallback is a second lazily-fetched
bundle for generation only — worth knowing before, not after.

## Definition of done

- `/api/v1/convert` accepts a document plus target format, returns the generated
  file; metered and key-gated like `/parse`.
- All four SDKs expose it, with a round-trip test each.
- `mcpConvert` in hosted mode calls the endpoint instead of gating local work
  behind a key.
- Hidden lab page renders the three numbers above on a real document.
- Renderer-level verification holds: generated DOCX opens in Word/LibreOffice and
  passes `python-docx` run assertions — the v0.29.0 bar, unchanged.

## Open questions

1. **Pricing model** for generation — the three candidates above.
2. **Does the browser route ship at all**, or does the lab page stay a lab page?
   Defensible either way once the numbers exist.
3. **AI generation** (`--generate --prompt`) is a separate cost profile entirely:
   it burns model tokens, so it cannot share a per-document price with
   deterministic conversion.
