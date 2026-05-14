# Changelog

All notable changes to AILANG Parse are documented here. This changelog is
derived from [design docs](design_docs/README.md) (the authoritative source
for feature context) and git history.

Format: version headers link to git compare views. SDK versions are tracked
separately — see `sdks/` for per-SDK changelogs.

---

## [Unreleased](https://github.com/sunholo-data/ailang-parse/compare/v0.18.1...HEAD)

---

## [0.18.1](https://github.com/sunholo-data/ailang-parse/compare/v0.18.0...v0.18.1) — 2026-05-14

Pure-perf patch for the HTML parsing pipeline. No semantic change —
JSON output for non-HTML formats is byte-identical to v0.18.0. The HTML
goldens that differ in this commit are the result of stale v0.17/v0.18
features (page title extraction, table caption capture) that hadn't been
baked into all the goldens because the eval is structure-sensitive,
not byte-sensitive.

### Performance fixes

1. **Single-pass HTML parse** in [docparse/main.ail](docparse/main.ail).
   v0.17.0 added `parseHtmlMetadata(content)` to extract `<title>` /
   `<meta>` into `DocMetadata`. main.ail was calling both `parseHtml(content)`
   AND `parseHtmlMetadata(content)` for the same input — two full
   walks through std/html. New `parseHtmlDoc(content)` returns
   `{blocks, metadata}` from a single `parse()` call. For an 80 KB
   sunholo.com page this halves the std/html invocation cost.

2. **`htmlCollapseNewlines` fast-path**. Called by every `htmlDeepText`
   invocation (including on short fragments that contain no triple-newline).
   The new `find(s, "\n\n\n") < 0` short-circuit returns immediately
   without allocating a `replace` result or running an O(n) comparison
   at the bottom of the recursion. The recursion still handles
   pathological pages with deeply-stacked block breaks.

3. **`imageJsonFields` single-concat**. v0.16.0 emitted optional HTML5
   image attrs (width/height/srcset/title/loading) via five sequential
   `concat` calls — each chained on the previous result, allocating
   five intermediate lists per image. Refactored to build an
   `imageOptionalFields` list once and `concat` it onto the base once.
   For image-heavy pages this drops 4 list allocations per image.

### Stale goldens cleaned up

Four HTML goldens (`test.html`, `ailang_guide.html`, `pandoc_nordics.html`,
`pandoc_planets.html`) refreshed to capture the v0.17 page title and
v0.18 table caption that the parser was already producing but the eval
hadn't been flagging because semantic equivalence beats byte equality.
No code change for these; they're just up to date now.

### Real-world measurements (sunholo.com, 79 KB)

Three warm runs, before vs after:

| Run | v0.18.0 | v0.18.1 |
|---|---|---|
| Cold | 1.17s | 0.96s |
| Warm 1 | 0.73s | 0.63s |
| Warm 2 | 0.62s | 0.70s |

Modest warm savings (~50–100 ms). The bigger structural win is memory:
one less full XmlNode tree allocation per HTML parse. For batch parsing
of many HTML files (email archives, scraped page corpora), that's a
meaningful reduction in peak memory.

### What we considered and didn't do

- **Streaming HTML5 parser** — would require an upstream `std/html`
  feature (chunked/streaming parse). Today std/html returns the whole
  tree in one allocation. Filed for future consideration but out of
  scope for ailang-parse.
- **`parseFold` / `parseElements`** (the XLSX/streaming patterns) —
  don't apply to HTML's heterogeneous nested structure. They work for
  XLSX because sheets have repeated `<row>` elements at a fixed level
  that fold cleanly.
- **`mapSlicesJoin` / `foldSlices`** — these are string-scanning
  optimizations from `std/string`. The hot loops in HTML extraction
  are tree walks, not string scans. They apply to the (deleted-in-v0.14.0)
  in-repo sanitizer but not to the post-std/html pipeline.

---

## [0.18.0](https://github.com/sunholo-data/ailang-parse/compare/v0.17.0...v0.18.0) — 2026-05-14

Tables now carry their captions, header cells carry their accessibility
scope, and a couple of long-tail semantic blocks (`<figure>`/`<figcaption>`,
`<address>`) get proper paired output.

### Changed
- **`TableBlock` extended** with an optional `caption: string` field.
  Populated by the HTML parser from `<caption>` elements (any depth
  under `<table>`); empty for tables emitted by other parsers
  (DOCX/PPTX/ODT/ODS/CSV/Markdown/TeX/XLSX/AI).
- **`TableCell` extended** with an optional `scope: string` field
  matching HTML5's accessibility model (`"row"` | `"col"` | `"rowgroup"` |
  `"colgroup"`). Populated by HTML parser from `<th scope=…>`; empty
  for `<td>` and for cells emitted by other parsers.

### Added
- **`mkTable(rows, headers)`** in [docparse/types/document.ail](docparse/types/document.ail)
  constructs a TableBlock with an empty caption — one-line swap for
  every non-HTML parser. 17 constructor sites migrated.
- **`mkTableFull(rows, headers, caption)`** for HTML parser when
  `<caption>` is present.
- **`scopedCell(text, scope)`** for explicit scoped header cells
  (HTML parser uses it via direct record literal because cell scope
  is per-cell, not per-table).
- **HTML parser captures `<caption>`** — `htmlParseTable` extracts the
  first `<caption>` descendant and passes its trimmed deep text into
  `mkTableFull`. pandoc_planets.html test file now exposes its
  `"Data about the planets of our solar system."` caption that was
  previously dropped entirely.
- **HTML parser captures `<th scope=…>`** — `htmlParseTableCell` reads
  the scope attribute only when the cell tag is `<th>`, so `<td>`
  cells stay scope-less.
- **`<figure>`/`<figcaption>` pairing** — `<figure>` now emits a
  `SectionBlock(kind: "figure")` containing the inner image plus a
  `TextBlock(style: "caption")` for the figcaption text. Previously
  the figure was flattened and the caption floated free.
- **`<address>` block** — emits its own `SectionBlock(kind: "address")`
  for contact info / authorship blocks. Falls back to a
  `TextBlock(style: "address")` when the content is plain text only.

### JSON output
- `TableBlock`'s `caption` is **emitted only when non-empty**, so
  non-HTML tables produce byte-identical JSON to v0.17.0.
- `TableCell`'s `scope` is **emitted only when non-empty**. The
  compact "string-only" cell shortcut (used when colSpan=1 and merged=false)
  upgrades to the verbose `{text, colSpan, merged, scope}` shape
  whenever scope is set.

### Real-world numbers
- **pandoc_planets.html**: `"Data about the planets of our solar system."`
  caption now in JSON. Previously empty.
- **messy_html5_demo.html** (updated to exercise these features):
  table with caption + 3 scoped col-headers + 2 scoped row-headers;
  figure/figcaption pair; address section.

### Goldens
- `messy_html5_demo.html.json` refreshed.
- All other 6 HTML + 2 EML goldens byte-identical (no `<caption>`,
  `<th scope>`, `<figure>`, or `<address>` in those source files).

### Cascade
- 17 in-repo `TableBlock` constructor sites updated to use `mkTable`.
- 9 sites with direct `TableCell` record literals updated to include
  `scope: ""`. All paid in one commit.

---

## [0.17.0](https://github.com/sunholo-data/ailang-parse/compare/v0.16.0...v0.17.0) — 2026-05-14

Three HTML-parser themes shipped together: page metadata extraction,
inline formatting preservation, and semantic block recognition.

### Added — Page metadata extraction
- **`parseHtmlMetadata(content)`** in [html_parser.ail](docparse/services/html_parser.ail)
  walks the parsed HTML tree to extract:
  - `<title>` → `DocMetadata.title` (falls back to `og:title` if absent)
  - `<meta name="author">` → `DocMetadata.author`
  - `<meta name="date">` → `DocMetadata.created` (falls back to
    `<meta property="article:published_time">`)
- **Wired into [docparse/main.ail](docparse/main.ail)** so every HTML
  parse now produces a populated `DocMetadata` instead of an empty one.
  www.sunholo.com now reports its title; the AILANG guide reports
  "Getting Started with AILANG Parse"; previously both were empty.

### Added — Inline formatting markers
- **`<strong>` / `<b>` → `**bold**`** (CommonMark-compatible)
- **`<em>` / `<i>` → `*italic*`**
- **`<code>` / `<kbd>` / `<samp>` → `` `code` ``**
- **`<del>` / `<s>` → `~~strikethrough~~`**
- **`<mark>` → `==highlighted==`**
- **`<a href="X">text</a>` inline → `[text](X)`** — even inside `<p>`
  paragraphs. Anchor-only hrefs (e.g. `href="#section"`) and href-less
  anchors collapse to plain text so output isn't polluted with
  placeholders.
- **`<time datetime="2026-05-14">yesterday</time>` → `yesterday (2026-05-14)`**
  so machine-readable timestamps survive alongside the human label.
- **`<abbr title="Application">App</abbr>` → `App (Application)`**
- **`<cite>` / `<q>` → `"quoted"`**

  Implemented in `htmlInlineWrap` — the inline children of paragraphs,
  headings, list items, table cells, etc. now retain semantic emphasis
  in the extracted text. Real-world impact: 15 `<strong>` and 31
  inline anchors on www.sunholo.com are now preserved instead of being
  flattened to plain text.

### Added — Semantic blocks
- **`<pre><code class="language-X">…</code></pre>`** captures the
  language hint: `TextBlock.style` is set to `"code-X"` (e.g. `"code-python"`,
  `"code-typescript"`) instead of the plain `"code"`. Bare `<pre>`
  without a `<code class="language-*">` child stays `"code"`.
- **`<details>`/`<summary>`** now emit a `SectionBlock(kind: "details")`
  containing a level-3 `HeadingBlock` for the summary plus the
  recursively-extracted body. Previously both fell through to text-only.

### Changed
- `htmlChildTextWithSpacing` and the new `htmlInlineWrap` dispatch
  inline children by tag. Block-level children still get a `\n`
  prefix; inline children get wrapped with the appropriate markdown
  marker; text nodes pass through unchanged.

### Goldens refreshed
- `test_complex.html`, `ailang_guide.html`, `sunholo_homepage.html`,
  `messy_html5_demo.html` — all 4 had structural changes because their
  paragraphs now carry inline formatting markers and their pages have
  extracted titles. `test.html`, `pandoc_nordics.html`,
  `pandoc_planets.html`, and the EML goldens were byte-identical
  (no inline emphasis in the source files).

### Real-world numbers (sunholo.com)
| Metric | v0.16.0 | v0.17.0 |
|---|---|---|
| `DocMetadata.title` | `""` | `"AI Engineering, AI Platforms and AI Solution Architecture - Sunholo"` |
| `<strong>` preserved in JSON | 0 | 15 (as `**...**` markers) |
| Inline anchor URLs in JSON | 0 | 31 (as `[text](href)`) |
| `<a href>` LinkBlocks (top-level) | 31 | 31 (unchanged) |

---

## [0.16.0](https://github.com/sunholo-data/ailang-parse/compare/v0.15.1...v0.16.0) — 2026-05-14

### Changed
- **`ImageBlock` extended with five HTML5 image attributes**:
  ```ailang
  ImageBlock({
    data, description, mime,
    width: int, height: int,
    srcset: string, title: string, loading: string
  })
  ```
  - **`width` / `height`** — pixel dimensions from `<img width=400 height=200>`.
    Parsed as non-negative ints; values like `"100%"` fall back to `0`
    because percentage/fractional sizes aren't modeled.
  - **`srcset`** — responsive-image candidate list from `<img srcset>`.
    For `<picture>` elements, srcsets from sibling `<source>` children
    are concatenated (comma-joined) and inherited by the inner `<img>`
    fallback. The `<img>`'s own `srcset` takes priority if both are
    present (preserves author intent).
  - **`title`** — tooltip / image-credit attribute.
  - **`loading`** — `"lazy"` / `"eager"` from `<img loading=…>`.

### Added
- **`mkImage(data, description, mime)` helper** in
  [docparse/types/document.ail](docparse/types/document.ail) constructs
  an `ImageBlock` with zero/empty defaults for the new fields. Used by
  all parsers that don't have access to the extended HTML5 attributes
  (DOCX, PPTX, ODT, EPUB, Markdown, TeX, AI vision parser, ZIP image
  resolver, a2ui formatter). Net effect on those parsers: 1-line swap
  per constructor site, no schema knowledge required.
- **`mkImageFull(data, description, mime, width, height, srcset, title, loading)`**
  is the long form used by `html_parser.ail` when extracting `<img>` and
  `<picture>` elements.
- **`htmlParsePicture`** in [docparse/services/html_parser.ail](docparse/services/html_parser.ail)
  walks a `<picture>` element's children, collects all `<source srcset>`
  values, and emits a single ImageBlock from the fallback `<img>` with
  the concatenated srcset list inherited.
- **`htmlParseImg`** centralises `<img>` attribute extraction so the
  inline `<img>` branch and the `<picture>` fallback branch use the
  same code path.

### JSON output
- New fields are emitted **only when non-zero / non-empty**:
  ```json
  {
    "type": "image",
    "description": "Responsive hero",
    "mime": "image/unknown",
    "dataLength": 14,
    "src": "hero-small.png",
    "width": 800,
    "height": 400,
    "srcset": "hero-large.png 2x, hero-medium.png 1.5x",
    "title": "Hero illustration"
  }
  ```
  Consumers that don't read the new fields are unaffected — empty
  `width=0`, `srcset=""`, etc. don't appear in the JSON at all. Existing
  goldens for non-HTML formats produce byte-identical JSON.

### Migration notes
- **Type signature is a breaking ADT change** but every in-repo
  constructor was migrated to `mkImage` / `mkImageFull`. Downstream
  consumers that explicitly pattern-match on `ImageBlock(b)` and read
  `b.data`, `b.description`, `b.mime` are unaffected — those three
  fields stay in the same position with the same types. Reads of
  `b.width` / `b.height` / `b.srcset` / `b.title` / `b.loading` are
  new and safe to add.
- **Goldens**: only `messy_html5_demo.html.json` actually changed —
  all other HTML/DOCX/PPTX/ODT goldens produce byte-identical output
  because their image-emitting paths use `mkImage` which fills empty
  defaults that get omitted from JSON.

---

## [0.15.1](https://github.com/sunholo-data/ailang-parse/compare/v0.15.0...v0.15.1) — 2026-05-14

### Added
- **`<picture>` element handling** in [html_parser.ail](docparse/services/html_parser.ail).
  HTML5 responsive-image markup wraps an `<img>` fallback in a `<picture>`
  parent with one or more `<source srcset>` siblings. The browser picks
  one candidate at runtime; for deterministic parsing we recurse into
  `<picture>` and surface the inner `<img>` fallback as a normal
  `ImageBlock`. `<source>` elements have no `src` attribute (only
  `srcset`, which we don't model) so they emit nothing.

  Example: `<picture><source srcset="big.png"><img src="small.png" alt="x"></picture>`
  now produces `ImageBlock(src="small.png", description="x")` instead of
  dropping silently.

  `data/test_files/messy_html5_demo.html` extended with a `<picture>`
  example covering the art-direction pattern; golden refreshed.

### Deferred
- Extending `ImageBlock` with `width`/`height`/`srcset`/`title`/`loading`
  attributes was attempted and reverted: the schema change cascades
  through 13+ files (every parser that constructs `ImageBlock` —
  DOCX/PPTX/ODT/EPUB/Markdown/TeX/AI/a2ui/zip_extract, plus the JSON
  serializer). The blast radius is disproportionate to the value;
  parking until there's a real consumer asking for these fields.

---

## [0.15.0](https://github.com/sunholo-data/ailang-parse/compare/v0.14.1...v0.15.0) — 2026-05-14

### Added
- **`LinkBlock` ADT variant** for HTML anchors. `LinkBlock({text, href, title})`
  captures the visible text and target URL of an `<a href>`. JSON output:
  ```json
  {"type":"link","text":"Try it free","href":"/ailang-parse/","title":""}
  ```
  Every match site that pattern-matches on `Block` gained a sensible
  `LinkBlock` arm:
  - `output_formatter.ail`: JSON serialization + console pretty-print
    (`[link] text → href`) + markdown rendering (`[text](href)`).
  - `html_generator.ail`: round-trips back to `<a href="...">text</a>`,
    preserving `title` if present.
  - `qmd_generator.ail`: markdown link syntax.
  - `odt_generator.ail`: `<text:a xlink:href="...">` proper ODF link.
  - `docx_generator.ail`/`pptx_generator.ail`/`odp_generator.ail`/
    `xlsx_generator.ail`: text downgrade with URL in parens (full
    `<w:hyperlink>` / shape-link round-tripping deferred).
  - `a2ui_formatter.ail`: callout with `href` + `title` metadata.
  - `unstructured_compat.ail`: NarrativeText with `link_urls`
    metadata field (matches unstructured.io's hyperlink schema).
  - `layout_ai.ail`: compact `[link] text → href` representation
    suitable for LLM context.

### Changed
- **HTML parser anchor handling rewritten.** The `<a>` branch now
  treats anchors as HTML5 "transparent" elements: recurses into
  children to surface any block content (images, headings, nested
  structure), and additionally emits a `LinkBlock` when `href` is
  present so the URL is captured.

  Three concrete improvements measured on www.sunholo.com:

  | Metric | v0.14.1 | v0.15.0 | Source |
  |---|---|---|---|
  | Images captured | 4 | **10** | 12 `<img>` in source |
  | Anchor URLs captured | 0 | **31** | 62 `<a href>` in source |
  | LinkBlock support | none | full ADT | — |

  The remaining 2 images / 31 anchors are inside constructs we don't
  yet handle (`<picture>`, anchors with no visible text, etc.).

### Known limitations (not addressed in this release)
- `<img>` attributes beyond `src` + `alt` — `width`, `height`,
  `srcset`, `loading`, `title` — are still ignored. Adding them
  requires extending the `ImageBlock` record, which cascades through
  every parser that constructs `ImageBlock` (DOCX/PPTX/ODT/EPUB/Markdown/TeX).
  Deferred.
- `<picture>` and `<source>` (responsive image art-direction) — not
  yet parsed.
- DOCX/PPTX hyperlink round-trip — the writers currently downgrade
  `LinkBlock` to plain text with the URL in parens. Full
  `<w:hyperlink>` / `<a:hlinkClick>` round-tripping is deferred to a
  future write-back release.

---

## [0.14.1](https://github.com/sunholo-data/ailang-parse/compare/v0.14.0...v0.14.1) — 2026-05-14

### Added
- **Image/audio/video `src` URLs surfaced in JSON output.** Previously,
  the URL was captured into `ImageBlock.data` by HTML/ODT/Markdown/EPUB
  parsers but `output_formatter.ail` only serialized its character
  count (`dataLength`) — the actual URL was thrown away. Inspecting
  parsed output of www.sunholo.com showed image alt text + mime + a
  numeric length, but zero way to recover "where did this image come
  from?" without re-parsing the source. The JSON now emits:
  ```json
  {"type":"image","description":"AILANG Logo","mime":"image/unknown",
   "dataLength":15,"src":"ailang-logo.svg"}
  ```
  The `src` field is **length-gated to 2048 chars**: short URLs/paths
  from HTML, Markdown, ODT, and EPUB surface in the output, while
  DOCX/PPTX inline base64 binary payloads (often megabytes) stay
  represented by `dataLength` alone — emitting them as `src` would
  bloat JSON outputs by orders of magnitude.

  Same change applies to `AudioBlock` and `VideoBlock` for symmetry.

  This is a purely **additive** schema change: existing consumers that
  read `description`/`mime`/`dataLength` continue to work; new
  consumers can opt into the `src` field. Refresh affected goldens
  (`ailang_guide.html`, `test.html`, `messy_html5_demo.html`,
  `sunholo_homepage.html`, `lo_image_mimetype.odt`, `image_vml.docx`,
  `pandoc_inline_images.docx`, `pandoc_basic.pptx`, `officeparser.odt`,
  `officeparser.odp`, `challenge_html_multipart.eml`) — all eval at
  100% against the new shape.

### Known limitations (not addressed in this patch)
- Images nested inside `<a>` tags are still dropped (the anchor branch
  falls through to text-only mode). On www.sunholo.com this loses 8 of
  12 images — they live in `<a class="card"><img></a>` patterns.
- `<a href>` URLs themselves are not captured (62 hrefs on sunholo.com
  → 0 in output). A future `LinkBlock` type or extended `TextBlock`
  with optional `href` would close this.
- `<img>` attributes beyond `src` and `alt` (`width`, `height`,
  `srcset`, `loading`, `title`) and `<picture>`/`<source>` elements
  are not captured. Schema change, deferred.

---

## [0.14.0](https://github.com/sunholo-data/ailang-parse/compare/v0.13.0...v0.14.0) — 2026-05-13

### Changed
- **HTML parser now uses `std/html`** (WHATWG HTML5 spec via Go's
  `golang.org/x/net/html`, shipped in AILANG v0.19.1). The in-repo
  sanitizer pipeline introduced in v0.13.0 — ~475 lines of boolean-
  attribute normalization, tag-stack auto-closing, script stripping,
  conditional-comment stripping, HTML-comment stripping, void-element
  closing, and entity normalization — is **deleted entirely**. Every
  block extractor (`htmlExtractBlocks`, `htmlProcessNode`, `htmlParseTable`,
  `htmlDeepText`, etc.) is unchanged because `std/html` returns the
  same `XmlNode` ADT as `std/xml`.

  Side-effects of switching to a real HTML5 parser:
  - Unicode characters in inline anchors (e.g. `→` in "See how →") are
    now preserved rather than stripped by the entity pipeline.
  - Adjacent inline elements (e.g. "Connect With Us" + `<a>LinkedIn</a>`)
    parse as separate text blocks instead of being concatenated.
  - Document tree shape is the canonical HTML5 tree (always wrapped in
    `<html><head><body>…</body></html>`), which matters only if you
    walked the tree manually — `parseHtml`'s block-list output is
    unaffected.

  Sunholo homepage golden refreshed to reflect the better text
  extraction. All other goldens (test.html, test_complex.html,
  ailang_guide.html, pandoc_nordics.html, pandoc_planets.html,
  messy_html5_demo.html) produce 100%-identical output.

### Requires
- **AILANG ≥ 0.19.1** (was `>=0.12.0`). `std/html` was added upstream
  on 2026-05-13. End-users on AILANG 0.12.x – 0.19.0 must upgrade.

---

## [0.13.0](https://github.com/sunholo-data/ailang-parse/compare/v0.12.9...v0.13.0) — 2026-05-13

### Added
- **Tolerant HTML5 parsing** in [docparse/services/html_parser.ail](docparse/services/html_parser.ail).
  Production HTML pages — sourced from CMSes, scraped websites, HTML email
  templates, and saved browser pages — previously failed deterministic
  parsing because the underlying XML parser is strict and HTML5 is not XML.
  The sanitizer now closes three real-world gaps without an AI fallback:
  - **Boolean attributes** (`<link ... crossorigin>`, `<input disabled>`,
    `<details open>`) are rewritten to `name=""` form for 23 known
    HTML5 booleans (`disabled`, `checked`, `selected`, `readonly`,
    `multiple`, `required`, `autofocus`, `hidden`, `novalidate`,
    `formnovalidate`, `defer`, `async`, `open`, `reversed`, `controls`,
    `autoplay`, `loop`, `muted`, `default`, `ismap`, `nomodule`,
    `crossorigin`, `itemscope`, `playsinline`). Fixed-point iteration
    handles adjacent booleans on the same tag.
  - **Tag-stack auto-closing** walks the token stream maintaining a
    stack of open elements. Stray close tags are dropped; overlapping
    closes (`<p>` closed by `</a>`) trigger implicit closes for
    everything above the target; elements still open at end-of-input
    are closed.
  - **Inline script + conditional-comment stripping** removes
    `<script>...</script>` (JSX, template literals, raw `<`/`&` in JS
    routinely broke the parser) and `<!--[if IE]>...<![endif]-->`
    (HTML email IE-conditionals). HTML comments are now stripped
    rather than left to fail on inner `--`.

  Canonical regression: `curl https://www.sunholo.com` saved at
  [data/test_files/sunholo_homepage.html](data/test_files/sunholo_homepage.html)
  previously produced a single `TextBlock(style: "error")` (XML parse
  failed on the `crossorigin` boolean attribute on line 10). Now
  extracts 13 structured blocks including header, nav, sections,
  h1–h4 headings, lists, and the full footer.

  Well-formed HTML (existing test files: `test.html`, `test_complex.html`,
  `ailang_guide.html`, `pandoc_nordics.html`, `pandoc_planets.html`)
  continues to produce byte-identical output — the tolerant passes are
  no-ops on already-valid input.

  See [v0_13_0_html_tolerant_parsing](design_docs/implemented/v0_13_0/v0_13_0_html_tolerant_parsing.md).

### Known limitations
- Tag-name case-folding (`<P>` → `<p>`) and Word/Office namespace
  stripping (`<o:p>` → `<p>`) are deferred. Real-world impact is
  limited (Word's HTML export is the primary remaining offender;
  `<script>` stripping already handles JSX-style custom-cased React
  components).
- A `std/html` stdlib module wrapping `golang.org/x/net/html` would
  let this whole sanitizer pipeline collapse to a single call. Filed
  as an upstream proposal to the AILANG core.

---

## [0.12.4](https://github.com/sunholo-data/ailang-parse/compare/v0.12.3...v0.12.4) — 2026-04-27

### Added
- **Content-aware format detection** in `format_router.ail`: new `sniffFormat`
  and `resolveFormat` exports plus a `ResolvedFormat` type. The sniffer
  identifies PDF/PNG/JPG/GIF/WAV/WEBP/MP3 via base64-prefix and
  DOCX/PPTX/XLSX/ODT/ODP/ODS/EPUB by inspecting ZIP entries
  ([Content_Types].xml for OOXML, mimetype for ODF/EPUB). `resolveFormat`
  composes extension + content sniffing with a clear precedence so
  callers can confidently route files whose extension is missing,
  ambiguous, or wrong. See [v0_12_4_format_detection_signed_urls](design_docs/implemented/v0_12_4/v0_12_4_format_detection_signed_urls.md).

### Fixed
- **DOCX heading detection** in `docx_parser.ail`: now recognizes the
  space-separated style names some non-conformant tools emit
  (`"Heading 1"` in addition to `"Heading1"`) and maps Word's `Title` /
  `Subtitle` styles to H1/H2 instead of body text.

### Bug Reports Addressed
- `msg_20260427_173916_463d1f6b` (aitana-platform v6) — DOCX served via
  signed GCS URL was producing flat-text output. Root cause: when the
  signed-URL fetch saved the file to a temp path that lost or mangled
  the extension, format detection fell back to the generic `unknown`
  category and bypassed the structured DOCX parser. The new
  `resolveFormat` is the building block; the API server in the
  downstream `docparse` repo wires it in to fix the user-facing bug.

---

## [0.9.3](https://github.com/sunholo-data/ailang-parse/compare/v0.9.2...v0.9.3) — 2026-04-08

### Added
- **Markdown+metadata renderer**: new output mode combining clean markdown with
  structured metadata (change attribution, merged-cell annotations)

---

## [0.9.2](https://github.com/sunholo-data/ailang-parse/compare/v0.9.1...v0.9.2) — 2026-04-07

### Added
- **MCP Registry**: publish to MCP registry with CI job, badge, and install docs
- **llms.txt + llms-full.txt**: AI agent discoverability files
- **Workbench polish**: copy-to-clipboard, mini tutorial, full format list in
  dropzone, progress bar during WASM boot, demo set loader

### SDKs (v0.4.1 → v0.4.6)
- MCP registry metadata
- `markdown` text field, `FormatsResult` helpers, `key_info()`
- Fix Python `parse_file` NameError

---

## [0.9.1](https://github.com/sunholo-data/ailang-parse/compare/v0.9.0...v0.9.1) — 2026-04-04

### Added
- **Workbench page**: dedicated multi-file WASM playground with shared frontend module and CI guards
- **R SDK** (v0.4.0): full feature parity with Python/JS/Go SDKs
- MCP modules reorganized into `docparse/services/mcp/` subdirectory
- Shared credential helpers and auto-load saved API key in MCP bridges (SDK v0.3.1)

---

## [0.9.0](https://github.com/sunholo-data/ailang-parse/compare/v0.8.2...v0.9.0) — 2026-04-01

This was a major release spanning website GTM, email parsing, OfficeDocBench v2,
MCP tooling, multipart file upload, and significant frontend/auth work.

### Added — Email Parsing
- Full EML/MBOX email parsing wired into format router
- Attachment chain parsing and thread reconstruction
- Two-pass Office attachment parsing (`--deep` flag)
- HTML email sanitization (non-XHTML, `<style>` blocks, zero-width Unicode)
- Quoted-printable decoder and HTML sanitizer performance optimization
- Z3 contracts on email and HTML parser pure functions
- 3 AILANG-themed email sample files

### Added — OfficeDocBench v2
- 9 ECMA-376 spec-driven scoring dimensions
- Content Fidelity and Structural Quality metrics
- Pandoc + Raw OOXML benchmark adapters
- Kreuzberg v4.7.2 added as competitor (77.2% composite)
- Results: 69 files, 8 parsers, 7 metrics

### Added — MCP & Agent Tooling
- MCP stdio bridge in JS SDK
- MCP auth, billing, and estimate tools for agent self-discovery

### Added — SDKs (v0.2.0 → v0.3.0)
- `parse_file` / `parseFile` / `ParseFile` multipart upload methods
- Device auth helpers: `client.device_auth()` across Go, Python, JS
- Key persistence: auto-save/load credentials across sessions
- Integration tests for multipart upload and Unstructured compat

### Added — Website & Frontend
- GTM Phases 1-3: messaging cleanup, WASM demo, funnel, comparison table
- A2UI tab: rich document rendering with streaming animation
- Format-specific landing pages (DOCX, XLSX, PPTX, PDF, HTML)
- Dedicated pricing page with build-time price stamping
- Frontend design refresh: distinctive identity, sidebar consistency
- FirebaseUI multi-provider sign-in (email magic link, avatar, sign-out)
- `?env=test|dev|prod` support for Firebase auth and API URLs
- Privacy policy, terms of service, DPA, beta badge

### Added — Parser Improvements
- Batch mode, folder parsing, and Windows CLI for docparse
- Nested SDT element handling in DOCX parser
- Strip Wingdings/symbol font PUA characters from DOCX output
- AILANG native string builtins for email/HTML parsing performance
- HTML deep text extraction: whitespace insertion, newline collapsing
- Case-insensitive file extensions
- Large PDF optimization: upload once, reference by URI (Gemini Files API)
- PPTX large file fix (50 MB in 9.4s), hardened XLSX memory

### Changed
- 10x request limits, reframe daily as rate limit
- Boost free tier to 2,000 req/month
- Rebrand selfhost page as "Install" / "Run Locally"
- Honest speed claims: sub-second for WASM, sub-ms for CLI
- XLSX parser: use `std/map`, `scanFold`, `parseFold` from new AILANG stdlib

### Fixed
- npm publish: OIDC trusted publishing with pinned npm@11.5.0
- JS SDK multipart file upload in ESM contexts
- A2UI export, WASM binary, call pattern fixes
- Firebase auth: apiKey auth, cached key clearing, dashboard paths

---

## [0.8.2](https://github.com/sunholo-data/ailang-parse/compare/v0.8.1...v0.8.2) — 2026-03-17

### Fixed
- AILANG_REGISTRY_VALIDATOR secret in publish workflow
- Repo URLs in SDK manifests (`docparse` → `ailang-parse`)
- Use `astral-sh/setup-uv@v4` in all workflows

---

## [0.8.1](https://github.com/sunholo-data/ailang-parse/compare/v0.8.2...v0.8.1) — 2026-03-17

### Added
- AILANG package publish workflow for registry releases

---

## 0.8.0 — Platform & Ecosystem (March 2026)

- **API keys & Cloud deployment**: Terraform, Firestore, Firebase Auth
- **Agent-friendly API**: capabilities manifest, typed errors, device auth, pricing, tools
- **SDKs**: Python v0.1.3 (PyPI), JS v0.1.3 (npm), Go SDK
- **Website**: 19-page static site on GitHub Pages
- **API playground**: in-browser with Firebase auth, code gen, response panel
- **OfficeDocBench**: AILANG Parse 96.6% vs Unstructured 63.4%, Docling 63.4%, LlamaParse 53.6%
- **Gemini Files API**: upload once, reference by URI for large PDFs
- **WASM threat model**: keep open — Office parsing is costless funnel
- Design docs: [API Keys](design_docs/implemented/v0_8_0/api_keys_cloud_deployment.md) | [Agent API](design_docs/implemented/v0_8_0/agent_friendly_api.md) | [Auth](design_docs/implemented/v0_8_0/auth_security.md) | [SDKs](design_docs/implemented/v0_8_0/sdks.md) | [Website](design_docs/implemented/v0_8_0/website.md) | [Playground](design_docs/implemented/v0_8_0/api_playground.md) | [Ecosystem](design_docs/implemented/v0_8_0/ecosystem.md)

## 0.7.0 — API Server

- REST API via `ailang serve-api` with `@route` annotations
- Unstructured API drop-in compatibility (`POST /general/v0/general`)
- Auto-generated OpenAPI spec + Swagger UI, 25 smoke tests
- Cloud Run `concurrency=80` safe
- Design doc: [API Server](design_docs/implemented/v0_7_0/v0_7_0_api_server.md)

## 0.6.0 — Document Generation

- Block ADT → file output for 8 formats (HTML, DOCX, PPTX, XLSX, ODT, ODP, ODS, Markdown)
- AI-assisted generation: `--generate output.docx --prompt "Q1 sales report"`
- Cross-format conversion via `--convert` flag
- Design docs: [Generation](design_docs/implemented/v0_6_0/v0_6_0_document_generation.md) | [Features](design_docs/implemented/v0_6_0/features.md) | [Verification](design_docs/implemented/v0_6_0/verification_loop.md)

## 0.5.0 — Spec Coverage & Benchmarks

- ECMA-376 spec coverage audit — 19 gaps closed across Rounds 1-3
- OmniDocBench integration (Text ED 0.183, Table TEDS 0.871)
- Large file performance — DOCX/PPTX/XLSX within tier limits
- Design docs: [Spec Audit](design_docs/implemented/v0_5_0/spec_coverage_audit.md) | [External Benchmarks](design_docs/implemented/v0_5_0/external_benchmarks.md) | [Large File Perf](design_docs/implemented/v0_5_0/large_file_performance.md)

## 0.3.0 — Parser Coverage & Format Expansion

- 13 format parsers (DOCX, PPTX, XLSX, CSV, TSV, Markdown, HTML, EPUB, ODT, ODP, ODS, EML, MBOX)
- All parsers in pure AILANG (zero runtime dependencies)
- 53 golden benchmark files at 100% baseline
- AILANG eval module — 8 structural checks with contracts
- ODT/ODP/ODS native parsing — strategic gap, nobody else does this
- Design docs: [Format Expansion](design_docs/implemented/v0_3_0/format_expansion.md) | [Parser Coverage](design_docs/implemented/v0_3_0/v0_3_0_parser_coverage.md) | [Eval](design_docs/implemented/v0_3_0/ailang_benchmark_eval.md)

## 0.1.0 — Initial Release (March 2026)

- Deterministic Office parsing (DOCX, PPTX, XLSX)
- AI-powered PDF extraction via pluggable models
- 18 golden benchmarks at 100% baseline
- Comment extraction, track changes, headers/footers
- PDF benchmark infrastructure with multi-model support
- Competitor adapter framework (Docling, LlamaParse, Unstructured)
- Design doc: [Implementation Report](design_docs/implemented/v0_1_0/v0_1_0_implementation_report.md)
