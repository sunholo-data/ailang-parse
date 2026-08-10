# DOCX Generation Fidelity — fixing the package graph, and what native buys us over Quarto

**Status**: PARTIAL — P0 implemented 2026-08-10, P1/P2 planned (2026-08-10)
**Theme**: `generateDocx` emits correct heading XML into a package where nothing can find it. Fix the OPC wiring, then be explicit about which jobs belong to the native generator and which belong to Quarto.
**Prompted by**: a user request for DOCX generation.
**Complements**: [`v0_21_0_quarto_integration.md`](../v0_21_0/v0_21_0_quarto_integration.md) — that doc adds `quarto render` as an output renderer. This doc is not an alternative to it. The two cover different jobs; the split is argued in [Native vs Quarto](#native-vs-quarto).

## Problem

[`docparse/services/docx_generator.ail`](../../../docparse/services/docx_generator.ail)
is more complete than its reputation: real `<w:tbl>` with borders, `gridSpan`
for colspans, `vMerge` for merged cells, and genuine binary image embedding via
`createArchiveWithBytes`. It is exported in `ailang.toml`, so it ships in the
registry package and the WASM bundle.

It also produces documents where **every heading renders as body text**, and
its documented CLI invocation **cannot run at all**.

### 1. `bin/docparse --convert` has never worked (worst)

The wrapper's argument loop has no `--convert` case. The flag falls through to
the `-*` catch-all at [`bin/docparse:377`](../../../bin/docparse#L377) and joins
`EXTRA_FLAGS`, which is passed to `ailang` *ahead of* the `.ail` file. The
**output path** then falls to the `*)` case and is appended to `FILES` — where
it is treated as an input document:

```console
$ ./bin/docparse data/test_files/pandoc_table_list.docx --convert /tmp/out.html
Error: File or folder not found: /tmp/out.html
$ echo $?
0
```

This affects every format, not just DOCX. Every example in
[`docs/examples/cli/convert.sh`](../../../docs/examples/cli/convert.sh) and the
`--convert` block in `CLAUDE.md` fails this way. The exit code is `0`, so a
script that shells out to `docparse --convert` sees success and an absent file.

The underlying code path is fine — the same conversion works when `ailang` is
invoked directly, which is how everything below was tested:

```bash
ailang run --entry main --caps IO,FS,Env --max-recursion-depth 50000 \
  docparse/main.ail input.docx --convert out.docx
```

### 2. `word/styles.xml` is an orphaned part — headings silently die

`generateDocx` writes `word/styles.xml` with `Heading1`–`Heading6` definitions,
and `docxStyledParagraph` emits correct references to them:

```xml
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>...</w:p>
```

But `word/_rels/document.xml.rels` is written **only on the image path**
([`docx_generator.ail:45`](../../../docparse/services/docx_generator.ail#L45)),
and even there it contains only image relationships — never a styles
relationship. In the no-image path the part is not written at all:

```console
$ unzip -l rich.docx
  [Content_Types].xml
  _rels/.rels
  word/document.xml
  word/styles.xml          ← declared in [Content_Types].xml, related to by nothing
```

OPC resolves parts through the relationship graph. An unreferenced part is not
part of the document, so `w:pStyle w:val="Heading1"` resolves to nothing and
falls back to the default paragraph style. Confirmed in two independent
renderers:

| Consumer | Our output | With a styles relationship added |
|---|---|---|
| LibreOffice → HTML | *no* `<h1>`/`<h2>`/`<h3>` | `<h1>`, `<h2>Revenue`, `<h3>Highlights` |
| python-docx | every paragraph `Normal` | `Heading 1`, `Heading 2`, `Heading 3` |
| pandoc | headings recovered | headings recovered |

Pandoc recovers them because it pattern-matches the `styleId` heuristically
rather than resolving the part — which is very likely why this survived
undetected. Word and LibreOffice do not.

### 3. `Normal` is not marked as the default style

`docxMinimalStyles` defines `Normal` without `w:default="1"`, so there is no
default paragraph style in the part. python-docx returns `None` for
`paragraph.style` on any unstyled paragraph. Cosmetic next to #2, but it is one
attribute in the same function.

### 4. Latent rId collision

Image relationships are numbered from `rId1`
([`docxCollectImages(doc.blocks, 1)`](../../../docparse/services/docx_generator.ail#L36)).
Adding a styles relationship naively as `rId1` would collide on the image path.
The fix must allocate a non-numeric or reserved id.

## Native vs Quarto

The question this doc has to answer before committing effort: **does a native
generator earn its keep when `qmd_generator.ail` already exists and Quarto can
render `.qmd` → `.docx` today?**

Tested rather than assumed. Same source document through both paths, plus
round-trip tests of the structures this project treats as its differentiator:

| Capability | Native `generateDocx` | Quarto / pandoc |
|---|---|---|
| Headings | broken today (#2); correct after fix | real |
| Tables, colspan, merged cells | real `w:tbl` / `gridSpan` / `vMerge` | real |
| Embedded images | real binary parts | real |
| Lists | literal `•` / `1.` text prefixes | real `numbering.xml` |
| Inline bold/italic/code | **impossible** — see ADT note below | real runs |
| Track changes | flattened to styled text + attribution | **real `w:ins`/`w:del`, author + date preserved** |
| Comments | flattened to text | **real `word/comments.xml`** |
| Headers / footers / text boxes | **content preserved** as labelled body text | **dropped entirely** |
| Document metadata | dropped | real `docProps/core.xml` |
| Can run in the browser (WASM) | **yes** (not yet wired — see below) | no, categorically |
| External dependencies | **none** | quarto + pandoc |
| Statically verifiable (Z3) | **yes** — `ensures` contracts | no |

Two corrections to assumptions worth recording, because they cut against the
easy answer:

- **Pandoc round-trips track changes and comments, and we do not.** `pandoc
  --track-changes=all` preserved `<w:ins w:id="1" w:author="eng-dept"
  w:date="2014-06-25T10:40:00Z">` intact through a DOCX→DOCX round trip, and
  wrote a real `word/comments.xml`. Our `docxChangeToXml` renders a strikethrough
  or underlined run with a trailing `" (insert by eng-dept, 2014-06-25...)"`
  string. On these two features Quarto is ahead of us *today*, and they are
  features this project markets.
- **Pandoc drops headers, footers and text boxes entirely.** On
  `docx-hdrftr.docx` the output contained no `header*.xml` / `footer*.xml` and
  none of their text. We keep the content — as a `Header:`-labelled body
  paragraph rather than a real header part, so the semantics are lost, but
  nothing is silently deleted.

That asymmetry is the actual distinction, and it is about failure modes rather
than feature counts: **Quarto preserves the semantics of what its AST models and
silently discards what it doesn't; we preserve the content of everything and
lose the semantics of what our ADT doesn't model.** For a parsing product whose
stated differentiator is "structural Office parsing competitors miss entirely"
([`.claude/rules/benchmarks.md`](../../../.claude/rules/benchmarks.md)), silent
deletion is the worse failure.

### The inline-formatting ceiling is in the ADT, not the generator

```ailang
export type Block = TextBlock({text: string, style: string, level: int})
```

[`document.ail:45`](../../../docparse/types/document.ail#L45) has no run-level
structure. Bold-inside-a-paragraph is unrepresentable, so *no* generator can
emit it — this is not a `docx_generator` deficiency and cannot be fixed there.
It also bounds the Quarto path for non-Markdown inputs: `.qmd` recovers inline
formatting only when the source parser happened to leave literal `**` markers in
the text (Markdown input), not for DOCX→DOCX.

Closing this needs an `InlineRun` ADT change touching every parser and every
generator. Out of scope here; tracked as P2 below.

### Conclusion

Native generation is worth fixing, but **not** as a Quarto competitor, and we
should stop implying it is one. Its defensible jobs are:

1. **Embeddable generation** — WASM/browser and the hosted API container. Quarto
   is a ~100MB Deno + pandoc bundle that cannot run in a browser at all, so
   browser-side generation is native-only *permanently* — it is not a gap Quarto
   could close later. Note this is currently a capability rather than a shipped
   feature: `docx_generator` is in `ailang.toml`'s `[exports]` (so it is in the
   registry package), but the docs-site WASM bundle loads a curated 23-module
   subset pinned by `MODULES` in `docs/scripts/vendor-wasm-packages.sh` and
   `MODULES_TO_LOAD` in `docs/js/wasm-demo.js`, which includes `qmd_generator`
   and **not** `docx_generator`. Browser DOCX generation needs adding to both
   lists; tracked as P1(9).
2. **Zero-dependency SDK story** — Python/JS/Go users get generation without
   installing a toolchain.
3. **Structural round-trip** — the header/footer/text-box class, where Quarto
   deletes data.
4. **Verifiability** — `ensures` contracts and `--prove` under Z3. A shell-out
   is opaque to both.

Typographic quality, numbering, citations, cross-references and multi-format
publishing belong to Quarto via [`v0_21_0`](../v0_21_0/v0_21_0_quarto_integration.md).
We should not chase them natively.

## Scope

### P0 — DONE (2026-08-10)

1. **`--convert` / `--generate` / `--prompt` added to the `bin/docparse` argument
   loop**, routed to the AILANG module rather than to `ailang`. Targets are
   resolved to absolute paths before the `cd "$PROJECT_DIR"` (a relative target
   previously would have landed next to the sources), parent directories are
   created, and misuse exits `2` instead of `0`. `--convert` is rejected with
   multiple inputs, since batch mode repeats the args per file and every file
   would overwrite the same target.
2. **`word/_rels/document.xml.rels` is now always written**, carrying the styles
   relationship on both the image and no-image paths under the reserved id
   `rIdStyles` — non-numeric, so it cannot collide with image `rId`s counting up
   from 1.
3. **`Normal` marked `w:default="1"`.**

Verified:

| Check | Result |
|---|---|
| LibreOffice → HTML on generated file | `<h1>`, `<h2>Revenue`, `<h3>Highlights` |
| python-docx paragraph styles | `Heading 1` / `Heading 2` / `Heading 3`; `Normal` no longer `None` |
| Image path rels | `rIdStyles` + `rId1` + `rId2`, no collision, opens clean |
| All 7 documented `--convert` targets | html, docx, pptx, xlsx, odt, md, qmd all non-empty |
| `benchmarks/verify_generated.py` | ALL CHECKS PASSED |
| `run_benchmarks.py --suite office` | 100.0% across 58 files (unchanged) |
| `./bin/docparse --check` | 35 modules clean |

**Release note**: no docs-site re-vendor is needed for this fix —
`docs/ailang/docparse/services/` carries a curated 23-module subset that does not
include `docx_generator`, so the browser demo is unaffected either way.

### P1 — next

4. `word/numbering.xml` + `<w:numPr>` so `ListBlock` becomes a real Word list.
5. `docProps/core.xml` so title/author survive generation.
6. Real `<w:hyperlink>` for `LinkBlock` (needs the rels work from P0(2), so it
   gets much cheaper afterwards).
7. Real `w:ins`/`w:del` and `word/comments.xml` — closing the two places Quarto
   currently beats us, on features we advertise.
8. Real `header1.xml` / `footer1.xml` parts for `SectionBlock(header|footer)`,
   so the one class where we beat Quarto is preserved with its semantics rather
   than as labelled body text.
9. Add `docparse/services/docx_generator` to the WASM module subset (`MODULES` in
   `docs/scripts/vendor-wasm-packages.sh` **and** `MODULES_TO_LOAD` in
   `docs/js/wasm-demo.js` — the two lists must stay in sync) to turn
   browser-side DOCX generation from a capability into a feature.

### P2 — separate design doc

10. `InlineRun` in the Block ADT. Large, cross-cutting, and the only route to
    inline formatting.

## Risks

- **Regenerating goldens.** P0(2) changes the byte output of every generated
  DOCX. `benchmarks/office/golden/` covers *parsing*, not generation, so the
  office suite should be unaffected — to be confirmed, not assumed, by running it.
- **`createArchive` ordering.** Adding a part to the no-image path exercises
  `createArchive` with five entries where it previously had four; entry order is
  not significant to OPC, but the generated ZIP must still open in Word.
- **Round-trip drift.** Our own `docx_parser` reads `pStyle` directly and is
  therefore insensitive to #2 — meaning the parse-side golden tests could not
  have caught this bug and still won't. Renderer-level verification
  (LibreOffice/python-docx) is the only thing that closes the loop, which is an
  argument for extending `verify_generated.py` rather than relying on goldens.
