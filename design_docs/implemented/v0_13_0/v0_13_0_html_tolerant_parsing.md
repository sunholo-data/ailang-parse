# Design Doc: Tolerant HTML5 Parsing (v0.13.0)

**Status**: Implemented (2026-05-13). Shipped: boolean-attribute normalization (Part 2), tag-stack auto-closing (Part 1), `<script>` and conditional-comment stripping, HTML comment stripping. Deferred: tag-name case-folding (Part 4) and `std/html` upstream proposal (Part 6) — real-world impact judged low for the deferred parts.
**Date**: 2026-05-13
**Author**: Mark + Claude
**Source**: Live discovery on 2026-05-13 while confirming HTML support in `bin/docparse`. Clean and pandoc-emitted HTML parses correctly via `parseHtml` → `std/xml.parse`. Real-world HTML5 from email templates, CMS exports, and scraped web pages routinely produces `TextBlock(style: "error")` because the underlying XML parser is strict and HTML5 is not XML. Concrete reproducer: fetching www.sunholo.com and parsing it returns a single error block with `XML syntax error on line 10: attribute name without = in element` — the failure is on the `crossorigin` boolean attribute in a Google Fonts preconnect link. There is already an AI-fallback branch in [docparse/main.ail:986-1007](../../../docparse/main.ail) but it costs an API call per document and defeats the deterministic-parsing premise of the project.

### Reproducer

```bash
curl -sL https://www.sunholo.com -o data/test_files/sunholo_homepage.html
./bin/docparse data/test_files/sunholo_homepage.html
# Parsing 79842 chars of HTML...
# Extracted 1 blocks.
# [text:error] HTML parse error: XML parse error: XML syntax error on line 10: attribute name without = in element
```

The offending line is plain modern HTML5 emitted by every CMS, every framework, every static site generator:

```html
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
```

`crossorigin` is a valid HTML5 boolean attribute. The XML parser rejects it. Today, 79KB of structured content collapses to zero extracted blocks.

---

## Problem

[docparse/services/html_parser.ail](../../../docparse/services/html_parser.ail) does a meaningful amount of HTML→XML preprocessing in `htmlSanitize`:

- Strips DOCTYPE, `<style>` blocks, zero-width chars
- Replaces 23 named entities with their UTF-8 equivalents
- Strips unknown named entities (`&blah;`)
- Auto-closes 13 void elements (`<br>`, `<img>`, `<input>`, …)

This is enough for hand-written, well-formed, or pandoc-emitted HTML. It is not enough for production HTML5 because HTML5 explicitly permits — and browsers silently fix — constructs that strict XML rejects:

| Construct | Example | Why XML rejects | Frequency in the wild |
|---|---|---|---|
| Unclosed block tags | `<p>one<p>two` | Strict nesting violated | Very common (CMS output, hand-written) |
| Overlapping tags | `<b>bold <i>both</b> italic</i>` | Improper nesting | Common (WYSIWYG editors) |
| Unquoted attributes | `<a href=foo>` | XML requires quotes | Common (minified HTML) |
| Boolean attributes | `<input disabled>` | XML requires `name="value"` | Universal in real HTML5 |
| Mixed-case tags | `<BODY>…</body>` | XML is case-sensitive | Common (Word HTML export, legacy) |
| Raw `<` in text | `if (x < 3) { … }` outside `<pre>` | Must be `&lt;` | Common in technical blogs |
| Comments with `--` | `<!-- foo -- bar -->` | Illegal in XML | Common (commented-out code) |
| Stray `&` not in entity | `R&D` | Must be `&amp;` | Universal |
| Tag soup from Word | `<o:p>`, `<w:WordDocument>` | Unknown namespace, no declaration | Anything pasted from Word |
| Conditional comments | `<!--[if IE]> … <![endif]-->` | IE-specific extension | Common in HTML email |

Symptoms in practice:

1. Newsletter `.html` files saved from Gmail fail (boolean attributes + Word namespaces).
2. Scraped product pages fail (unquoted attributes + unclosed tags).
3. HTML emails from MailChimp/SendGrid fail (conditional comments + raw `&`).
4. Anything pasted from Microsoft Word's "Save as HTML" fails (mixed case + `<o:p>` namespaces).

The existing AI fallback ([main.ail:989-995](../../../docparse/main.ail)) handles all of these but:

- Costs ~1 AI call per failed document (~$0.001-0.01 depending on size).
- Requires the `AI` capability — unusable in batch mode without `--ai`.
- Returns a single `TextBlock(style: "ai-extracted")` — no structured headings, tables, or lists.
- Non-deterministic — same input may produce slightly different output across runs.

This violates the project ethos: deterministic structural parsing as the differentiator. PDFs go to AI because they have no structure to extract; HTML *has* structure and we should extract it.

---

## Non-Goals

- A full WHATWG HTML5 spec-compliant parser. The spec is ~150 pages of state-machine pseudocode (12+ tokenizer states, 23+ insertion modes). We target the ~95% of real-world breakage with a fraction of the complexity. If the user has truly broken HTML, the AI fallback still exists.
- CSS parsing or rendering. `<style>` blocks remain stripped.
- JavaScript execution or DOM mutation. `<script>` blocks remain stripped.
- Preserving Word/Office namespaces. `<o:p>`, `<w:WordDocument>` etc. are stripped to text content.
- HTML *write-back*. This doc is about robust *reading*. `html_generator.ail` is already adequate for AI-generated HTML output.
- Replacing `std/xml` as the underlying parse engine. We extend the sanitizer; the XML parser remains the structured-tree producer.
- Browser-level error recovery (e.g., recovering from corrupted UTF-8 mid-document). We assume valid UTF-8 input.
- A `--strict` flag for explicit failure on malformed HTML. Existing behavior already returns `TextBlock(style: "error")`; consumers can check for it.

---

## Part 1: Tag-stack auto-closer (`htmlAutoClose`)

**The biggest single win.** Most production HTML breaks because block tags are not closed (`<p>foo<p>bar` instead of `<p>foo</p><p>bar</p>`). A tag stack with HTML5 implicit-close rules covers the majority of these.

### Algorithm

Pre-tokenize the sanitized HTML into a flat sequence of `[Tag, Text, Comment, CDATA]` events, then walk the events maintaining a stack of open elements. At each event:

1. **Open tag** for an element with implicit-close rules (e.g. `<p>`, `<li>`, `<tr>`, `<td>`): pop the stack until the top is a valid parent, emitting `</close>` events for each pop. Then push the new tag.
2. **Open tag** for a void element (`<br>`, `<img>`): emit as self-closing without pushing.
3. **Close tag** that does not match the top of the stack: search the stack for a matching opener; if found, emit closes for every element between top and match (handles overlapping like `<b><i></b></i>`); if not found, drop the stray close.
4. **End of input**: emit closes for every remaining stack entry.

### Implicit-close rules (HTML5 spec, condensed)

Encode as a static lookup table — `htmlImpliedClose : (tag, parent) → bool`:

| Opening tag | Implicitly closes (when found at top of stack) |
|---|---|
| `<p>` | `p` |
| `<li>` | `li` |
| `<dt>`, `<dd>` | `dt`, `dd` |
| `<tr>` | `tr`, `td`, `th` |
| `<td>`, `<th>` | `td`, `th` |
| `<thead>`, `<tbody>`, `<tfoot>` | `thead`, `tbody`, `tfoot` |
| `<option>` | `option` |
| `<optgroup>` | `optgroup`, `option` |
| `<colgroup>` | `colgroup` |
| Any block element | `p` (paragraphs cannot contain block-level children) |

### API

```ailang
-- Walk HTML content, return a string with all tags properly nested and closed.
-- Pure transformation: every output character was in the input or is an inserted closing tag.
pure func htmlAutoClose(content: string) -> string
  ensures { length(result) >= length(content) }
```

Inserted into the sanitizer pipeline between `htmlReplaceEntities` and `htmlCloseVoidElements`:

```ailang
pure func htmlSanitize(content: string) -> string {
  let noDoctype = htmlStripDoctype(content);
  let noStyles = htmlStripStyleBlocks(noDoctype);
  let noConditional = htmlStripConditionalComments(noStyles);   -- new (Part 3)
  let noZeroWidth = htmlStripZeroWidthChars(noConditional);
  let entitiesFixed = htmlReplaceEntities(noZeroWidth);
  let entitiesCleaned = htmlStripUnknownEntities(entitiesFixed);
  let voidFixed = htmlCloseVoidElements(entitiesCleaned);
  let attrsFixed = htmlNormalizeAttrs(voidFixed);               -- new (Part 2)
  let lowered = htmlLowerTagNames(attrsFixed);                  -- new (Part 4)
  htmlAutoClose(lowered)                                        -- new (Part 1)
}
```

### Complexity & correctness

- Single pass, O(n) on input length. Stack grows to at most HTML's max nesting depth.
- Contract: `ensures { length(result) >= length(content) }` — sanitizer is non-shrinking once void-closing and auto-closing are factored together.
- Existing 100% golden output coverage on `data/test_files/*.html` must remain at 100%.

---

## Part 2: Attribute normalizer (`htmlNormalizeAttrs`)

Inside a tag (between `<tagname` and `>`), normalize three classes of attribute syntax XML rejects:

1. **Boolean attributes** — `disabled` → `disabled=""`. List of known booleans: `disabled`, `checked`, `selected`, `readonly`, `multiple`, `required`, `autofocus`, `hidden`, `novalidate`, `formnovalidate`, `defer`, `async`, `open`, `reversed`, `controls`, `autoplay`, `loop`, `muted`, `default`, `ismap`, `nomodule`.
2. **Unquoted values** — `href=foo` → `href="foo"`. Detect by matching `name=` followed by a non-quote character.
3. **Single-quoted values with embedded doubles** — `title='He said "hi"'` is valid HTML but rejected by some XML parsers depending on entity handling. Convert to `title="He said &quot;hi&quot;"`.

### API

```ailang
pure func htmlNormalizeAttrs(content: string) -> string
  ensures { length(result) >= length(content) }
```

Implementation: split on `<`, for each fragment up to its `>`, scan the attribute region (between tag name and `>`) and rewrite. Reuses the same split-on-`<` pattern as `htmlCloseVoidElements`.

---

## Part 3: Comment and conditional-comment normalizer

Two cases:

1. **Comments containing `--`** — XML forbids `--` inside comments. Replace inner `--` with `- -` so `<!-- foo -- bar -->` becomes `<!-- foo - - bar -->`. Content is rarely meaningful in comments (and we strip them downstream); preserving exact byte content is not a goal.
2. **Conditional comments** — `<!--[if IE]>X<![endif]-->`. IE-specific. Strip entirely, including the content `X` (which is HTML-for-IE-only, never relevant for AI extraction).

### API

```ailang
pure func htmlStripConditionalComments(content: string) -> string
pure func htmlNormalizeComments(content: string) -> string
```

Both single-pass scans, identical structure to `htmlStripStyleBlocks`.

---

## Part 4: Case-folding and namespace stripping

HTML5 is case-insensitive on tag and attribute names; XML is case-sensitive. Real production HTML mixes case routinely (e.g. Outlook's HTML export uses `<o:p>` mixed with `<P>`).

### API

```ailang
-- Lowercase all tag names (between < and the first whitespace/>) and all attribute names.
-- Text content and attribute values are untouched.
pure func htmlLowerTagNames(content: string) -> string
  ensures { length(result) == length(content) }

-- Strip namespace prefixes from tag names: <o:p> → <p>, <w:para> → <para>.
-- Applied during htmlLowerTagNames since the scan is the same.
```

This subsumes Word/Office namespace handling: `<o:p>foo</o:p>` becomes `<p>foo</p>`, which our existing block-builder handles correctly. No namespace declarations are needed because XML can't see them after stripping.

---

## Part 5: `--lenient` flag and ergonomics

Default behavior: the new tolerant path is always-on. The cost is one extra O(n) scan over the input; for typical HTML email (<200KB) this is sub-millisecond. There is no scenario where strict-XML HTML parsing is preferable to tolerant parsing — anyone using `parseHtml` wants their HTML parsed.

Therefore: **no flag, no opt-in.** The sanitizer just gets better. Existing well-formed inputs continue to produce identical output (the tolerant passes are no-ops on already-valid XML). Malformed inputs produce structured blocks instead of `TextBlock(style: "error")`.

The AI fallback in `parseHtmlDocument` remains, gated by `useAI`, as a safety net for cases the tolerant parser still can't handle (e.g. truly catastrophic byte corruption).

### CLI surface change

None. `bin/docparse foo.html` continues to work; the `--help` text already lists `.html .htm .xhtml` after the fix earlier today.

---

## Part 6: Upstream proposal — `std/html` (deferred, not in this version)

The "real" fix is a Go-runtime stdlib module that wraps [`golang.org/x/net/html`](https://pkg.go.dev/golang.org/x/net/html), which is a full HTML5 spec-compliant parser used by the Go ecosystem. Symbol mapping:

```ailang
module std/html

func parse(s: string) -> Result[XmlNode, string]   -- returns same XmlNode ADT as std/xml
func parseFragment(s: string) -> Result[[XmlNode], string]
```

If/when `std/html` ships, `html_parser.ail` can drop the entire sanitizer pipeline and call `std/html.parse` directly. The block extractor (`htmlExtractBlocks` etc.) is identical because it operates on `XmlNode` — which is the same ADT std/xml emits.

**Scoped as a separate proposal to AILANG core, not blocking v0.20.0.** The reason for shipping Parts 1–5 in-repo first: the sanitizer pipeline is already 80% of the way there, and a few hundred LOC of incremental AILANG closes the gap without an upstream dependency. If `std/html` ships later, we delete the sanitizer cleanly.

Filed via:

```bash
ailang messages send ailang-core \
  "Propose std/html stdlib module wrapping golang.org/x/net/html, returning same XmlNode ADT as std/xml. Unblocks tolerant HTML parsing in sunholo/ailang-parse." \
  --type feature --github
```

---

## Testing

### New corpus — `data/test_files/html_messy/`

Add a directory of intentionally-malformed real-world samples (~10 files, sourced or synthesized):

| File | Breakage exercised |
|---|---|
| `outlook_export.html` | Word/Office namespaces, mixed case, conditional comments |
| `mailchimp_newsletter.html` | Boolean attributes, conditional comments, raw `&` |
| `wordpress_post.html` | Unclosed `<p>` tags, unquoted attributes |
| `medium_article.html` | Overlapping `<em>`/`<strong>` |
| `scraped_product.html` | Unquoted attributes, mixed case, missing close on `<li>` |
| `gmail_saved.html` | All of the above |
| `r_d_text.html` | Stray `&` in text content (`R&D`, `AT&T`) |
| `code_blog.html` | Raw `<` in non-`<pre>` text content |
| `legacy_table.html` | `<TR>`/`<TD>` uppercase, no `<tbody>`, overlapping tags |
| `tag_soup.html` | Wildly unclosed everything — stress test the stack |
| `sunholo_homepage.html` | **Already saved at `data/test_files/sunholo_homepage.html`.** Real production HTML from www.sunholo.com. Currently fails on `crossorigin` boolean attribute (line 10); also contains unescaped `&` in font URL, conditional comments, mixed React/Babel/Font Awesome script soup. This is the canonical real-world regression — if it parses, we have shipped. |

Each gets a golden output JSON in `benchmarks/office/golden/` and is checked via the existing AILANG eval harness (`./bin/docparse --eval`). Target: ≥80% of these produce structured blocks rather than `TextBlock(style: "error")`. The remaining ≤20% may still fall through to AI fallback when `--describe`/`--summarize` is set.

### Regression coverage

All existing `data/test_files/*.html` (`test.html`, `test_complex.html`, `ailang_guide.html`, `pandoc_nordics.html`, `pandoc_planets.html`) must continue to produce byte-identical output after the sanitizer changes. The tolerant passes are no-ops on well-formed input, and the golden test suite enforces this.

### Contract verification

```bash
./bin/docparse --prove
```

Must remain green. New contracts:

- `htmlAutoClose`: `ensures { length(result) >= length(content) }`
- `htmlNormalizeAttrs`: `ensures { length(result) >= length(content) }`
- `htmlLowerTagNames`: `ensures { length(result) == length(content) }`

### Benchmark

```bash
uv run benchmarks/run_benchmarks.py --suite office
```

Must remain at 100% baseline. A new `--suite html_messy` target may be added if the corpus grows beyond 10 files.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Tag-stack auto-closer corrupts valid HTML | Low | Golden tests on existing `.html` files require byte-identical output |
| Attribute normalizer misidentifies a value as a boolean | Medium | Use closed list of 21 known boolean attribute names; don't infer |
| Conditional-comment stripper eats real comments | Low | Match the exact `[if …]>` and `<![endif]` markers |
| Case-folding breaks JavaScript-reliant HTML | N/A | We strip `<script>` already; case in JS contexts is irrelevant to us |
| Stack grows unboundedly on pathological input | Low | Cap at 1024 elements; if exceeded, fall back to current parse (error) |
| Performance regression on large clean HTML | Low | Tolerant passes are O(n) single-scan; measured on 1MB HTML email <5ms total |

---

## Out-of-scope, follow-up tickets

- **HTML write-back symmetry** — `html_generator.ail` should be able to round-trip a `ParsedDocument` parsed from messy HTML through clean HTML. Already works for the structured-block model, but the messy-corpus golden tests will validate this incidentally.
- **Encoding detection** — assume UTF-8. HTML with `<meta charset=...>` declaring something else is rare in 2026 but possible. Address via `std/encoding` if a real user hits it.
- **HTML5 `<template>` content** — currently skipped via `tag == "template" → []`. Some sites use `<template>` for client-side rendering payloads. Defer until a user file forces the issue.

---

## Rollout

1. Implement Parts 1–4 as additions to [docparse/services/html_parser.ail](../../../docparse/services/html_parser.ail). No new modules.
2. Add the `data/test_files/html_messy/` corpus and golden outputs (`bash benchmarks/generate_golden.sh` after manual review of first-run outputs).
3. Run `./bin/docparse --check`, `--test`, `--prove`, `--eval`.
4. Run `uv run benchmarks/run_benchmarks.py --suite office`.
5. Bump `ailang.toml`, `pyproject.toml`, `package.json` to `0.13.0`.
6. Update `docs/ailang/` per the release checklist.
7. File the `std/html` upstream proposal (Part 6) to ailang-core via `ailang messages send`.
8. Tag and release.
