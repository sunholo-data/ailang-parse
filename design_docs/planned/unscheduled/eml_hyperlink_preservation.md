# Multipart/alternative hyperlink loss — investigation

**Status**: INVESTIGATING (2026-08-14)
**Theme**: `emlSelectAlternativePart` picks `text/plain` and never looks at
the sibling `text/html` part when both exist — so every `LinkBlock`/`href`
the HTML part would have produced is silently thrown away for the single
most common multipart shape (Gmail/Outlook-style `multipart/alternative`).
**Source**: `ailang messages` in `email-parse`'s own inbox —
`msg_20260507_210145_af2c83c3`, from `claude-opus-4-7-housemove2026`
(a separate local project consuming eparse's parsed output), filed
2026-05-07, sat unactioned until `email-parse` triaged its inbox
2026-08-14. Not yet re-filed as a proper cross-repo `ailang messages` report
to this repo — moved here directly (both repos are local checkouts on the
same machine) with the investigation already done, per email-parse's
no-in-repo-workarounds convention (the fix belongs here, not as a
workaround downstream). email-parse's own copy of this investigation:
`design_docs/planned/m13-preserve-html-hyperlinks.md` in that repo, to be
removed once this doc is the source of truth.
**Relationship to existing docs**: extends
[`email_parsing.md`](../../implemented/v0_9_0/email_parsing.md) (original
eml parser design — silent on hyperlinks) and
[`v0_30_0_inline_runs.md`](../../implemented/v0_30_0/v0_30_0_inline_runs.md)
(added `InlineRun.href`, the type this fix reuses rather than extends).

## The request, as filed

housemove2026 (a broker-email ingester) parses eparse's output and found
`document.blocks` carries only the plaintext MIME part. For
marketing/transactional HTML mail, plaintext links are frequently hollowed
tracking redirectors (`?ext=https%3A%2F%2F%3F...` — the target stripped
out), while the real URLs live only in the `text/html` part. Concrete
example: a Nybolig "Dit bestilte boligmateriale" email has 5 real PDF
download URLs (`nybolig.mindworking.eu/api/Public/Documents/<uuid>`) visible
only in HTML; the parsed plaintext block shows only broken redirectors. The
sender worked around it with stdlib `email.message_from_bytes` + regex on
the raw `.eml`, duplicating parsing work this repo already does.

Two API shapes were proposed (non-binding): a `document.hyperlinks` sidecar
array (`{href, source, anchor_text, image_alt}`), or exposing
`document.body_html` and letting the consumer re-derive links. The sender's
stated preference was the sidecar array.

Test fixture offered: `~/dev/sunholo/email-parse/data/raw/me%40markedmondson.me@imap.gmail.com/INBOX/521573.eml` (confirmed present, 79,964 bytes).

## What's actually going on

Neither proposed shape is needed — the machinery already exists, wired to
JSON, and the bug is one function not looking at data it already has.

**Link extraction and serialization are already built.**
`docparse/types/document.ail:80–92` — `Block` already includes
`LinkBlock({text, href, title})`, and `InlineRun` (`:45–57`, used inside
`TextBlock`/`HeadingBlock`) already carries `href` per inline anchor.
`docparse/services/output_formatter.ail:99–105` already serializes
`LinkBlock` to `{"type":"link","text","href","title"}`. `html_parser.ail`
already turns every `<a href>` into one of these — block-level anchors at
`:233–257`, inline-run hrefs at `:523–534`. None of this needs building.

**The gap is `emlSelectAlternativePart`**
(`docparse/services/eml_parser.ail:296–329`), which handles
`multipart/alternative` — exactly the shape of the Nybolig example and of
Gmail/Outlook mail generally:

```
pure func emlSelectAlternativePart(parts: [string]) -> [Block] {
  let plainPart = emlFindPartByMime(parts, "text/plain");
  match plainPart {
    Some(part) => { ... [mkText(decoded, "Normal", 0)] },   -- html part never touched
    None => { ... html fallback, calls parseHtml ... }
  }
}
```

When a `text/plain` alternative exists — the common case — the function
returns without ever inspecting the `text/html` sibling. `parseHtml` (which
produces the `LinkBlock`s) only runs when there is *no* plaintext
alternative at all. The function's own comment cites RFC 2046 §5.1.4 and
argues plaintext is the right default "for programmatic/AI use" — a
defensible call for *body text* that this doc does not propose changing —
but it currently throws away the HTML part's structure entirely rather than
mining it for links before discarding the rest.

So: the feature request and the defect are the same thing, and reusing
`LinkBlock` means no `ParsedDocument` schema change is needed. Worth stating
explicitly since `orchestrator.ail:120–125` notes `ExtractionResult` is
"constructed in 17 places, so adding a field would break every record
literal and every external consumer" — the same caution doesn't apply here
because `ParsedDocument` is only literal-constructed in ~4 places
(`orchestrator.ail:136,414,703`, `a2ui_formatter.ail:205`) and `LinkBlock`
is an existing `Block` variant, not a new field on a struct with wide fan-out.

## Design

**Recommendation: when a `multipart/alternative` has both `text/plain` and
`text/html`, parse both; keep plaintext as the block body unchanged, append
the HTML part's `LinkBlock`s only.**

```
emlSelectAlternativePart(parts):
  plainPart = find text/plain
  htmlPart  = find text/html
  match (plainPart, htmlPart):
    (Some p, Some h) => [mkText(decode(p))] ++ linksOnly(parseHtml(decode(h)))
    (Some p, None)   => [mkText(decode(p))]                     -- unchanged
    (None,   Some h) => parseHtml(decode(h))                    -- unchanged
    (None,   None)   => first-part fallback                     -- unchanged
```

`linksOnly` filters `parseHtml`'s block list down to `LinkBlock` (dropping
the HTML part's own text/headings/structure — plaintext already supplied
the body, so nothing else from the HTML side is wanted). Body text for
every already-parsed message is untouched; links become additively visible
wherever the HTML alternative has them.

**Alternatives considered:**

- **Prefer `text/html` over plaintext whenever both exist.** Simpler code,
  but flips the documented default for the majority of multipart mail and
  re-litigates body-text fidelity (HTML→text quality at scale, whitespace,
  entity handling) for a request that was only ever about links. Bigger
  blast radius than the ask.
- **New `document.hyperlinks` field or `body_html` field**, as originally
  proposed. Duplicates what `LinkBlock` already does; would touch
  `ParsedDocument` and its four SDK mirrors (`sdks/go/types.go`,
  `sdks/python/ailang_parse/types.py`, `sdks/js/src/types.ts`,
  `sdks/r/R/types.R`) for a capability that already exists under a
  different (and already-shipped) name.
- **`InlineRun`-only (no `LinkBlock`)**: rejected — the HTML anchors in
  question are typically standalone (a plaintext line has no inline HTML
  structure to attach a run to), so the block-level `LinkBlock` list is the
  natural shape; `InlineRun.href` stays as-is for whenever HTML *is* the
  primary parsed part (`multipart/related`/HTML-only messages), unaffected
  by this change.

## Downstream impact

- **email-parse** (the requesting/downstream repo) will need to bump its
  `docparse` pin (`ailang.lock`) and re-run `eparse parse` over its archive
  once this ships — `data/parsed/*.eml.json` is a cache of parse-time
  output, not re-derived automatically. Their own re-parse verification plan
  (diff message/attachment counts pre/post, this should move 0 rows in
  `messages`, only add `LinkBlock`s to `blocks`) lives in their
  `design_docs/planned/m13-preserve-html-hyperlinks.md` and is theirs to
  execute, not this repo's concern beyond shipping a correct, additive
  change.
- **No API/CLI surface change required by this fix.** `LinkBlock` already
  serializes; existing consumers that don't know about it simply see one
  more block type in the list, same as any other message that happens to
  contain a link today.
- **Golden benchmarks.** `.eml` benchmark fixtures with `multipart/alternative`
  and a `text/html` part carrying `<a href>` content should gain `LinkBlock`
  entries in their expected output — check `benchmarks/` for existing eml
  fixtures with both parts before assuming new fixtures are needed.

## Open questions

1. **`multipart/related` with `cid:`-referenced images.** `parseHtml` already
   runs unmodified there (HTML is the primary part) — does anything about
   `cid:` handling interact with this change? Likely no, since this fix only
   touches the `multipart/alternative` branch, but not verified here.
2. **Anchor text → semantic role** (the request's suggestion of mapping link
   text to intent — "Salgsopstilling" vs. "unsubscribe"). Consumer-side
   classification once links exist as data, not a parser concern — out of
   scope for this doc.
3. **Scheduling.** Narrow, additive, low-risk fix with an existing type to
   reuse — plausibly small enough to bundle into whatever the next patch
   release is, rather than needing its own `vX_Y_Z/` milestone. Filed here
   under `unscheduled/` since no version has been committed to it yet.
