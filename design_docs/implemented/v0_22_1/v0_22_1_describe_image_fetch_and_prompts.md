# `--describe` — Fetch Linked Images & Read the Picture, Not Just the Text

**Status**: SHIPPED in v0.22.1 (2026-07-15). (v0.21.0 was a concurrent OMML-equations release; v0.22.0's registry publish failed on a stale `docs/ailang` mirror, so this landed as v0.22.1.) Both findings fixed and verified end-to-end across HTML, direct images, DOCX, PPTX, ODT/ODF, and LaTeX/arXiv (plus a pre-existing DOCX extraction bug found en route).

## Format coverage (verified 2026-07-15)

| Format | Image source | `--describe` result |
|---|---|---|
| HTML | `<img src>` (path / `data:` / remote) | ✅ local read from disk, data: decoded, remote/missing → warning |
| Direct image (PNG/JPG/…) | the file itself | ✅ reads the curve, then the labels |
| DOCX | embedded ZIP media | ✅ **after fixing a pre-existing extraction bug** (see below) |
| PPTX | embedded ZIP media | ✅ |
| ODT / ODP / ODS | embedded ZIP media (`resolveBlockImages`) | ✅ |
| EPUB | inline `<img>` in XHTML (`resolveBlockImages`) | ✅ same path as ODF; Gutenberg test files carry only an OPF **cover** (no inline images), so nothing to describe there |
| **LaTeX / arXiv** | `\includegraphics` external refs | ✅ resolved against the `.tex` dir / arXiv extraction dir; raster figures described, PDF/EPS or missing figures → warning |
| PDF | rasterised pages | out of scope — separate page-extraction path, not image-describe |
| Markdown / CSV / RTF / EML | (no `ImageBlock`s emitted) | n/a |

### Pre-existing DOCX extraction bug found while verifying coverage

DOCX embedded-image describe could never have worked: `filterMedia` yields full ZIP
paths (`word/media/image1.jpg`) but `readEmbeddedImage` re-prepended `word/media/`,
looking up `word/media/word/media/…` → always missed → **every DOCX image had empty
`data`**. Separately, the `word/media/` **directory entry** (a 0-byte name ending in
`/`) passed `isMediaEntry`, emitting a phantom `application/octet-stream` image. The
`pandoc_inline_images.docx` golden even enshrined the bug as `images: 3` (2 real + 1
phantom). Both fixed in [`zip_extract.ail`](../../../docparse/services/zip_extract.ail)
(`readEmbeddedImage` reads the entry path directly; `isMediaEntry` excludes trailing-`/`
dir entries); golden corrected to `images: 2`. PPTX already read entry paths directly
(`readImageEntry`) and was unaffected except for the shared phantom-dir guard.

### LaTeX / arXiv figures (done)

`\includegraphics{…}` produces an `ImageBlock` whose `data` is the figure path — exactly
the HTML external-ref shape the resolver already handles. `parseLatexDocument` now takes
`useAI` and runs the describe pass, resolving figure paths against `basedir` (the main
`.tex` file's directory, which for arXiv `.tar.gz`/`.tgz` bundles is the **extraction
dir** — the same var already used for `\input`/`\include` expansion). Raster figures
(PNG/JPG) are described; PDF/EPS figures the vision model can't read, and figures missing
from the source bundle, become warnings via the fail-soft path — verified against the
Ramachandran *Swish* arXiv source (6 PDF/EPS figures → 6 warnings, no crash) and a
hand-built `.tex` with a present PNG figure (curve described) plus a missing one (warned).
**Theme**: Make `--describe` do what its name promises on two paths where it currently under-delivers.
**Source**: Sunholo/multivac field feedback (2026-07-15), two findings against docparse's `--describe`:
1. `--describe` on HTML **silently no-ops for external images** — `aiCallsUsed: 0`, empty descriptions, no warning. Reads as "described" when nothing happened.
2. Direct-image `--describe` **OCRs axis labels, not the curve** — on the OCO-2 graph it returned `Intensitet`, `nW·m⁻²·nm⁻¹`, tick values, `λ / nm` (the axes) but no readable description of the plotted curve. Not enough to answer a graph-reading question.

**Related**: [`../../planned/unscheduled/per_call_ai_descriptions.md`](../../planned/unscheduled/per_call_ai_descriptions.md) — that doc designs the *opt-in surface* (`describe=True`/tier policy). This doc fixes what happens **once you've opted in** and the described content is wrong or missing. They compose; neither supersedes the other.

---

## TL;DR

Both findings are real and both root-cause cleanly to code we can quote:

| # | Symptom | Root cause | Fix class |
|---|---------|-----------|-----------|
| 1 | HTML external images never described, no warning | `describeImages` filters out anything that isn't a >100-char base64 blob; HTML stores `img.data = src` (a path/URL). Never fetched from disk. | Resolve + read the linked file; **warn** when we can't. |
| 2 | Direct image → axis-label OCR, no curve description | Direct-image path runs the **document-OCR** prompt first; it only falls back to the **visual-description** prompt when zero text is found. A graph always has *some* text, so the good prompt is never reached. | Route figures to a description-first (or combined) prompt. |

Finding #1 is a **correctness bug** (silent no-op — worst kind). Finding #2 is a **prompt-routing bug**. Neither needs new AILANG language features.

---

## Finding #1 — HTML external images silently no-op

### What the user sees

```bash
./bin/docparse page.html --describe        # page has <img src="assets/plot.png">
# ... Images: 1 ...
# ImageBlock.description: ""     ← empty
# aiCallsUsed: 0                 ← nothing happened, no warning
```

### Root cause (two layers — both must be fixed)

**Layer 1 — the HTML parse path never runs the describe pass at all.** `parseHtmlDocument` ([`main.ail:1019–1072`](../../../docparse/main.ail#L1019)) only calls `enhanceBlocks` (tables) and **hardcodes `aiCallsUsed: 0`** ([`main.ail:1062`](../../../docparse/main.ail#L1062)). Unlike the DOCX/PPTX/EPUB/ODF paths, it never invokes `describeImages`. So even a *perfectly embedded* base64 image in HTML would go undescribed. This is the first thing to wire up.

**Layer 2 — even if it were wired, the describe guard would filter HTML images out.** The HTML parser stores the `src` **string** as the image's `data` field — it never reads the referenced file:

[`docparse/services/html_parser.ail:368,378`](../../../docparse/services/html_parser.ail#L368)
```ailang
let src = getOrElse(lookup(attrs, "src"), "");
...
mkImageFull(src, alt, "image/unknown", width, height, srcset, title, loading)
--         ^^^ becomes ImageBlock.data ; alt becomes .description
```

So for `<img src="assets/plot.png" alt="">` we get `ImageBlock { data: "assets/plot.png", description: "", mime: "image/unknown" }`.

The describe pass then filters this out. [`docparse/services/layout_ai.ail:29–37`](../../../docparse/services/layout_ai.ail#L29):
```ailang
ImageBlock(img) => {
  -- Only describe if data is actual base64 (long) and not a URL reference
  let description = if length(img.data) > 100 && layoutIsUrlRef(img.data) == false
    then call("Describe this image concisely in one sentence. ... (base64): ${img.data}")
    else img.description;          -- ← "assets/plot.png" is 15 chars → falls here, stays ""
  mkImage(img.data, description, img.mime)
}
```
```ailang
pure func layoutIsUrlRef(data: string) -> bool {
  startsWith(data, "http://") || startsWith(data, "https://") || startsWith(data, "data:")
}
```

Three distinct cases are all dropped, silently:

| `img.data` looks like | Guard result | Today | Should be |
|---|---|---|---|
| `assets/plot.png` (relative path) | `length ≤ 100` → skip | empty, no warning | **read file from disk, describe** |
| `data:image/png;base64,iVBOR…` (inline data URI) | `layoutIsUrlRef` → skip | empty, no warning | **strip prefix, describe the bytes** |
| `https://cdn.site/plot.png` (remote URL) | `layoutIsUrlRef` → skip | empty, no warning | **warn** (fetch is out of scope, see below) |

The `> 100 && !isUrlRef` heuristic was written for the Office path, where `img.data` genuinely *is* an embedded base64 blob. It was never adapted for HTML, where `img.data` is a reference. The result is a **silent** no-op — the single most damaging failure mode, because the caller reads empty `description` + `aiCallsUsed: 0` as "described, nothing notable" rather than "never attempted."

**`aiCallsUsed` can't be trusted to catch this either.** It is a static estimate, not a real call counter: format handlers set `aiCalls = if useAI then imageCount else 0` ([e.g. `main.ail:333,351`](../../../docparse/main.ail#L333)); the HTML handler hardcodes `0`; the direct-image path hardcodes `1`. Because `describeOneBlock` silently skips URL-ref and short-data images, on the *Office* path `aiCallsUsed` can even **overcount** real model calls. So the field neither confirms nor denies that description happened. The real signal must come from `warnings` (this doc) — not from the counter. Making `aiCallsUsed` reflect actual calls is a worthwhile cleanup but secondary to the warnings work.

### Design

Introduce an explicit **image-source resolver** that turns an `ImageBlock` into describable bytes (or a typed reason it can't), and make the describe pass consume it. Warnings are surfaced, never swallowed.

```ailang
type ImageSource
  = InlineBase64(string)              -- already have the bytes (Office path, or decoded data: URI)
  | LocalFile(string)                 -- relative/abs path → read from disk
  | RemoteUrl(string)                 -- http(s) → out of scope for CLI fetch (see Non-Goals)
  | NotAnImage                        -- alt-only / empty

pure func classifyImageSource(data: string) -> ImageSource
```

Resolution rules:
- `data:` prefix → decode the base64 payload → `InlineBase64`. (Today this is dropped by `layoutIsUrlRef`.)
- Long base64-looking blob (Office path, unchanged) → `InlineBase64`.
- `http://` / `https://` → `RemoteUrl`.
- Otherwise a non-empty string → `LocalFile` (resolve relative to the **source document's directory**, see below).
- Empty → `NotAnImage`.

`describeImages` gains the `FS` effect and a **base directory** so relative `src` resolves against the HTML file's location, not the process CWD:

```ailang
export func describeImages(baseDir: string, blocks: [Block]) -> DescribeResult ! {AI, FS}
--          ^^^^^^^ dir of the input file, threaded from main.ail

type DescribeResult = { blocks: [Block], warnings: [string], aiCalls: int }
```

Per block:
- `InlineBase64(b64)` → describe (existing call), `aiCalls += 1`.
- `LocalFile(path)` → `readFileBytes(join(baseDir, path))`:
  - `Ok(bytes)` → describe, `aiCalls += 1`.
  - `Err(_)` → **warning** `"describe: could not read linked image 'assets/plot.png' (relative to page.html) — skipped"`, description left empty.
- `RemoteUrl(url)` → **warning** `"describe: remote image 'https://…' not fetched (CLI does not download; use --allow-remote-images or pre-download)"`.
- `NotAnImage` → skip silently (alt-only images legitimately have no bytes).

The key behavioural change: **`warnings` is non-empty whenever `--describe` was asked for and an image couldn't be described.** `main.ail` already carries `warnings` in the result record ([e.g. `main.ail:557`](../../../docparse/main.ail#L557) `aiCallsUsed`), so these surface in CLI output and in the JSON/blocks result the SDKs consume. The invariant to hold: **`--describe` + an image present ⇒ either a description or a warning, never a silent empty.**

### Threading `baseDir`

`main.ail` knows `filepath`; the base dir is its parent directory. Every call site that currently calls `describeImages(combinedBlocks)` ([`main.ail:336,410,902,979`](../../../docparse/main.ail#L336)) becomes `describeImages(dirOf(filepath), combinedBlocks)`. `dirOf` is a small pure string helper (rsplit on `/`). This is the only signature change rippling out.

**Wire the HTML path in.** `parseHtmlDocument` ([`main.ail:1019–1072`](../../../docparse/main.ail#L1019)) currently skips the describe pass entirely (Layer 1 above). Add the same `if useAI && imageCount > 0 then describeImages(dirOf(filepath), blocks)` branch the other format handlers already have, and replace the hardcoded `aiCallsUsed: 0` with the real count from `DescribeResult.aiCalls`. This is the change that makes `--describe` reach HTML images at all.

### Reusing the good bytes→description path

Note `direct_ai_parser.ail` already has the right shape for "bytes + mime → description" via a `multimodal` request:

[`direct_ai_parser.ail:340–358`](../../../docparse/services/direct_ai_parser.ail#L340) (`parseImage`) builds `jo([kv("mode", js("multimodal")), kv("mimeType", …), kv("data", js(base64Data)), kv("prompt", …)])` and calls `call(request)`. The `layout_ai.describeImages` path, by contrast, **string-interpolates base64 into a text prompt** (`call("… (base64): ${img.data}")`) — which (a) risks the documented `call()` truncation and (b) is not a clean multimodal request. Part of this fix is to route describe-a-blob through the **same multimodal request builder** `direct_ai_parser` already uses, rather than the interpolated text prompt. That kills a latent correctness issue for the Office path too.

---

## Finding #2 — Direct image OCRs the axes, never reads the curve

### What the user sees

```bash
./bin/docparse oco2_spectrum.png --describe
# blocks: TextBlock "Intensitet", TextBlock "nW·m⁻²·nm⁻¹", "λ / nm", tick values …
# No block that says "this is an absorption spectrum; the curve dips sharply near 765 nm …"
```

### Root cause

Passing an image file routes to `parseImageDocument` ([`main.ail:575`](../../../docparse/main.ail#L575)), which calls **`parseDocumentImage` first** and only falls back to `parseImage` when the first returns `[]`:

[`main.ail:581–588`](../../../docparse/main.ail#L581)
```ailang
let blocks = parseDocumentImage(filepath, mime);
let finalBlocks = match blocks {
  [] => { println("No document content found, falling back to image description...");
          parseImage(filepath, mime) },
  _ => blocks           -- ← graph has axis text, so we NEVER reach the fallback
};
```

`parseDocumentImage` runs a **pure OCR / document-extraction** prompt — [`direct_ai_parser.ail:328`](../../../docparse/services/direct_ai_parser.ail#L328):
> "Extract ALL text content from this document page image. Return a JSON array of blocks. … CRITICAL RULES: 1. Create a SEPARATE text block for EACH paragraph or visual text section. … 6. For formulas, include LaTeX … If the page has no text content, return []."

The **good** description prompt exists but is only the fallback — [`direct_ai_parser.ail:352`](../../../docparse/services/direct_ai_parser.ail#L352):
> "Describe this image in detail. Include what it shows, any visible text or labels, key data or information conveyed, and visual structure. Be concise but thorough."

A chart *always* contains text (axis labels, ticks, legend). So `parseDocumentImage` returns non-empty, the `match` takes the `_ => blocks` arm, and the descriptive prompt is **never** reached. The user gets an OCR dump of the chrome around the plot, not a reading of the plot.

(The `layout_ai` describe prompt — [`layout_ai.ail:34`](../../../docparse/services/layout_ai.ail#L34) — has the same bias baked in: *"one sentence. Focus on the key content and any text visible."* "One sentence" + "any text visible" pulls the model toward transcribing labels rather than reading the data.)

### Design

The core problem is **classification**: a document page (scan, screenshot of prose/table) wants OCR-first; a **figure/chart/photo** wants description-first. Today we assume everything is a document page.

Two options, in order of preference:

**Option A — Single combined prompt for direct images (recommended).**
Replace the two-prompt / fallback dance for the *image* entrypoint with one prompt that asks for **both** structured text *and* a visual reading, returning them as distinct blocks. The model decides how much of each applies:

> "This is an image that may be a document page, a chart/graph, a diagram, or a photo. Return a JSON array of blocks. First, if it is a chart, graph, diagram, or photo, emit a `{"type":"text"}` block that **describes what the visual conveys**: for a chart, name the chart type, the axes and their units, and describe the shape/trend of the plotted data (rise/fall, peaks, notable values) — enough that a reader who cannot see the image could reason about it. Then extract any literal text (titles, axis labels, legend, tick values, captions, body text) as further blocks in reading order. For genuine document pages with no figure, just extract the text as before. …"

This keeps the axis-label OCR the user already gets **and** adds the curve reading they're missing — one AI call, no classifier, no fallback. `aiCallsUsed` stays `1`.

**Option B — Explicit classify step, then route.**
A cheap first call returns `{ "kind": "document" | "figure" | "photo" }`; route `document` → current OCR prompt, `figure`/`photo` → description prompt (optionally then OCR the labels). More faithful routing, but doubles the AI calls for every image and adds a failure mode (misclassification). Only worth it if Option A's combined output proves muddy in eval.

**Recommendation: ship Option A.** It's one prompt change ([`direct_ai_parser.ail:328`](../../../docparse/services/direct_ai_parser.ail#L328) region), no control-flow change, no extra calls, and directly answers the "read the graph" ask. Keep `parseImage`'s standalone description prompt as the true-empty fallback. Reserve Option B for if eval shows Option A dilutes clean document-page OCR.

Also tighten the `layout_ai.ail:34` describe prompt (used by the HTML/Office describe pass) to drop "one sentence / any text visible" in favour of "describe what the image conveys, including the trend/shape of any plotted data, then note visible labels" — so #1's newly-fetched images also get a *reading*, not a caption.

---

## Non-Goals

- **Remote image download.** Fetching `https://…` images from the CLI adds a `Net` effect, SSRF surface, and offline-mode questions. Out of scope — we **warn** instead (finding #1, `RemoteUrl` case). A future `--allow-remote-images` opt-in can revisit; tracked separately.
- **The opt-in / tier surface.** `--describe` vs `--no-describe`, 402s, per-call control — all owned by [`per_call_ai_descriptions.md`](../../planned/unscheduled/per_call_ai_descriptions.md).
- **Replacing OCR for scanned document pages.** `parseDocumentImage`'s text-extraction behaviour for real document scans is correct and stays.
- **Per-image caching / dedup.** Same as the opt-in doc: downstream of this.

---

## Acceptance criteria

Finding #1:
- [ ] `parseHtmlDocument` invokes `describeImages` under `--describe` (it doesn't today) and reports the **real** `aiCalls`, not a hardcoded `0`.
- [ ] `docparse page.html --describe` with a **relative** `<img src="assets/x.png">` reads the file and populates `description`; `aiCallsUsed ≥ 1`.
- [ ] Inline `<img src="data:image/png;base64,…">` is decoded and described (no longer dropped by the URL-ref guard).
- [ ] A **missing** linked image produces a `warnings` entry naming the file, and `description` stays empty — **never a silent empty**.
- [ ] A **remote** `https://` image produces a "not fetched" warning.
- [ ] Relative paths resolve against the **HTML file's directory**, not the process CWD.
- [ ] Office-path base64 images still describe (no regression) and now go through the multimodal request builder, not interpolated text.

Finding #2:
- [ ] `docparse <chart>.png --describe` returns at least one block that **describes the plotted data** (chart type, axes+units, trend/shape), in addition to the axis-label text.
- [ ] Genuine document-page images still get clean per-paragraph text extraction (no regression) — verified on an existing scanned-page test file.
- [ ] `aiCallsUsed` unchanged for the direct-image path (Option A = 1 call).
- [ ] The OCO-2 spectrum used in the feedback is added to `data/test_files/` and its described output is eyeballed for graph-readability.

Cross-cutting:
- [ ] `ailang check docparse/` clean; contracts (`describeImages` length-preservation `ensures`) still hold — note the return type changes from `[Block]` to `DescribeResult`, so the `ensures { listLength(result) == listLength(blocks) }` on [`layout_ai.ail:24`](../../../docparse/services/layout_ai.ail#L24) moves to `listLength(result.blocks) == listLength(blocks)`.
- [ ] Office structural benchmark still 100% (`uv run benchmarks/run_benchmarks.py --suite office`).
- [ ] CHANGELOG entry.

---

## Implementation estimate

| Task | Est. |
|---|---|
| `classifyImageSource` + `ImageSource` ADT | 0.5d |
| `describeImages` → `DescribeResult`, `FS` effect, `baseDir` threading, warnings | 1d |
| Route describe-a-blob through the multimodal request builder | 0.5d |
| Finding #2: combined direct-image prompt (Option A) + tighten `layout_ai` prompt | 0.5d |
| Test files (OCO-2 graph, HTML+assets fixture, missing-image fixture) + eval | 1d |
| CHANGELOG / docs | 0.25d |
| **Total** | **~3.75d** |

---

## Open questions

1. **Combined-prompt dilution.** Does Option A's one-prompt-does-both muddy clean document-page OCR? Decide from eval on the existing scanned-page fixtures; fall back to Option B only if it does.
2. **Warning channel for SDK consumers.** `warnings` already exists on the result record — confirm the Python/JS/Go SDKs surface it (they should, per the opt-in doc's `X-DocParse-Used-Ai` direction). If not, that's a small SDK follow-up so #1's warnings aren't dropped at the SDK boundary.
3. **`data:` URI size.** Decoded inline data URIs can be large; the existing per-document AI `@limit` budget still applies, but confirm we don't blow the request size on a page full of inline images.

---

## References

- Feedback source: multivac field test, 2026-07-15 (findings #1 external-image no-op, #2 graph OCR).
- Opt-in surface: [`../../planned/unscheduled/per_call_ai_descriptions.md`](../../planned/unscheduled/per_call_ai_descriptions.md)
- Code touch points: [`layout_ai.ail:23–48`](../../../docparse/services/layout_ai.ail#L23), [`direct_ai_parser.ail:317–358`](../../../docparse/services/direct_ai_parser.ail#L317), [`html_parser.ail:357–378`](../../../docparse/services/html_parser.ail#L357), [`main.ail:334–436, 575–588, 900–1005`](../../../docparse/main.ail#L575)
- AILANG bug policy (multimodal `call`/`callJson` caveats): [`CLAUDE.md`](../../../CLAUDE.md) / [`.claude/rules/ailang-coding.md`](../../../.claude/rules/ailang-coding.md)
