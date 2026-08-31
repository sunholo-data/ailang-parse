# List grouping: DOCX never coalesces, ODT never reads ordered-ness

**Status**: PLANNED (2026-08-31)
**Source**: ailang message `inbox_1788155549716_f8030598` from `aitana-platform` —
"docx: consecutive list paragraphs never coalesced — one ListBlock per item
(v0.39.2, repro + root cause)". Reported against `d5ec0bd` (v0.39.2, HEAD).
**Follows**: [`v0_39_0_reference_doc_followups.md`](../../implemented/v0_39_0/v0_39_0_reference_doc_followups.md)
— item 2/2b resolved *which* list a DOCX paragraph belongs to (numId → abstractNum
→ `w:numFmt`, plus style-level `numPr`). This doc is the step after: turning that
resolved identity into block structure.

## Scope

Two defects in the same seam — the parse side turning list paragraphs into
`ListBlock`s — plus the benchmark blind spot that let both stay green.

1. **DOCX**: a run of consecutive list paragraphs becomes N singleton
   `ListBlock`s instead of one. *(reported)*
2. **DOCX**: `w:ilvl` is resolved for numbering purposes and then discarded —
   `itemLevels` is always `[]`, so nesting is flat. *(found here, not reported)*
3. **ODT**: `ordered` is hardcoded `false`. A LibreOffice numbered list parses
   as a bullet list. `itemLevels` likewise `[]`. *(found here, not reported)*
4. **Benchmark**: `check_lists` normalises to `list_item` elements, so neither
   grouping nor level is observable to any suite. *(reported, confirmed)*

Explicitly out of scope: PPTX. Slide bullets are `a:p` paragraphs inside a text
body and are emitted as text blocks with literal `• ` / `1. ` prefixes; whether
they should become `ListBlock`s is a separate question about the slide model,
not a regression. Recorded under "Adjacent, deliberately not fixed here".

## Verified current state

Every row checked against the working tree at `d5ec0bd`, not taken from the message.

| # | Claim | Evidence |
|---|---|---|
| C1 | Reported repro reproduces exactly | `printf '# Repro\n\n- alpha\n- bravo\n- charlie\n' > repro.md`; `docparse repro.md` → `[list] 3 items`; `--convert repro.docx` then parse → `[list] 1 items` ×3 |
| C2 | The generator is not at fault | `unzip -p repro.docx word/document.xml` → three paragraphs, all `<w:numId w:val="1"/>`; nested case writes correct `<w:ilvl>` 0/1/1/0 and numId 1 vs 2 for bullet vs ordered |
| C3 | Root cause is `[text]`, a per-paragraph one-element list, with no coalescing pass after it | `docparse/services/docx_parser.ail:273` `mkListRuns([text], ...)`; `processBodyChildren` (`:218`) is a bare `flatMap` over body nodes — no accumulator anywhere |
| C4 | The markdown parser does have the accumulator the DOCX path lacks | `docparse/services/markdown_parser.ail:678-680` accumulates `texts` then calls `mkListNested`/`mkList` once |
| C5 | `ListBlock` can already express both grouping and nesting | `docparse/types/document.ail:91` — `{items: [string], ordered: bool, itemRuns: [[InlineRun]], itemLevels: [int]}`; `mkListNested` at `:396` |
| C6 | DOCX drops `itemLevels` | `mkListRuns` (`document.ail:390`) sets `itemLevels: []`; `docxParaIlvl` (`docx_parser.ail:619`) exists and is consumed **only** by `docxNumFmtOrdered` |
| C7 | Round-trip loses nesting, not just grouping | 4-item nested + 2-item ordered markdown → md JSON `itemLevels: [0,1,1,0]`; same doc via DOCX → six singleton lists, no levels |
| C8 | ODT hardcodes unordered | `docparse/services/odt_parser.ail:340,341` — `mkListRuns(texts, false, itemRuns)` / `mkList(texts, false)`; literal `false`, `styles` never consulted for list format |
| C9 | C8 is wrong on a real LibreOffice file, not just a synthetic one | `data/test_files/lo_listformat.odt` declares `<text:list-level-style-number>`; `docparse` reports one `[list] 4 items`, `ordered: false`. The office golden records the defect |
| C10 | ODT and HTML *do* coalesce correctly | Both give `[list] 4 items` + `[list] 2 items` for C7's document — the container element (`text:list`, `<ul>`) does the grouping for free. HTML also gets `ordered` right; ODT does not |
| C11 | The ODT **generator** cannot express either property | `nest.odt` content.xml contains bare `<text:list>` with no `text:style-name` and no `<text:list-style>` declaration; all four items are siblings, no nested `text:list` |
| C12 | `check_lists` cannot see grouping or level | `benchmarks/office/eval_office.py:94-96` — filters to `type == "list_item"` and compares counts. 3×1 and 1×3 produce identical element streams, identical ordered totals, identical positional classifications |

C11 is the one that changes the shape of the work: fixing the ODT *parser* to
read `text:list-style` is necessary but does not make ODT round-trip, because
our own ODT output declares no list style for it to read. Parser and generator
have to move together or the round-trip suite will still show ordered lists
arriving as bullets.

## Design

### Item 1 — DOCX coalescing

Keep the per-paragraph mapping (it is correct, and it is where numbering
resolution already lives) and add a merge pass over the emitted block stream,
as the source message suggests.

The merge key must be the resolved list identity, not just "adjacent and both
lists". Two lists separated by nothing but sharing no numbering are two lists —
Word represents "end this list, start another" precisely by changing numId.

- `parseParagraph` gains nothing; instead `processBodyNode` tags a list block
  with its resolved `numId` so the merge pass can see it. Two options:
  - (a) carry `numId`/`ilvl` on the block via a new `ListBlock` field, or
  - (b) return `(Block, listKey)` pairs from the body walk and drop the key
    after merging.
  **Prefer (b).** `numId` is a DOCX-internal identifier with no meaning to a
  consumer of `Block`, and every other parser would have to invent one. Adding
  it to the shared ADT to serve one parser's intermediate step is the wrong
  place for it.
- New pure `docxMergeLists(blocks: [(Block, string)]) -> [Block]`: fold with an
  accumulator holding the open run's key, items, itemRuns and itemLevels;
  flush when the key changes or a non-list block arrives.
- Merge condition: same `numId` **and** same `ordered`. Same numId with
  differing `ordered` cannot happen once numbering resolution is correct, but
  asserting both keeps the pass honest if resolution regresses.
- Non-list blocks between two list paragraphs break the run — including the
  `changeBlocks` / `textBoxBlocks` that `processBodyNode` already appends after
  the main block. Those are siblings of the paragraph, not content between two
  paragraphs, so the merge must key off the *main* block of each body node, not
  the flattened stream. This is the one place where getting it wrong silently
  re-fragments every list in a document with tracked changes.
- Follow the accumulator rule from CLAUDE.md: `[x] ++ xs` and reverse on flush,
  never `concat(xs, [x])`.

### Item 2 — DOCX `itemLevels`

`docxParaIlvl` already returns the effective level (direct `w:ilvl`, else the
style's, else 0). Carry it into the merge accumulator and emit via
`mkListNested`. Zero new resolution logic — the value is computed today and
thrown away.

Emit `itemLevels` only when some level is non-zero, matching the existing
convention that `itemRuns` stays `[]` when it carries no information (see the
comment at `docx_parser.ail:270-272`). A flat list should keep its current
JSON byte-for-byte.

### Item 3 — ODT ordered + levels

Parser: resolve `text:list/@text:style-name` → `<text:list-style>` →
the `<text:list-level-style-number>` vs `<text:list-level-style-bullet>` child
at the item's level. This is the ODF analogue of the DOCX
`numId → abstractNum → w:numFmt` chain that v0.39.0 built, and should reuse its
shape: parse the styles once, thread an immutable `Map[string, string]` through
the pure walk. Both `content.xml` (automatic styles) and `styles.xml` (named
styles) can declare list styles; check content first, then styles.

Nesting in ODF is structural — a nested `text:list` sits inside a
`text:list-item` — so `itemLevels` comes from recursion depth, not an attribute.

Generator: emit `<text:list-style>` in automatic styles (number vs bullet per
level) and reference it with `text:style-name`; nest by emitting a child
`text:list` inside the parent's `text:list-item` when `itemLevels` steps up.
Without this, item 3's parser fix is unobservable in the round-trip suite.

### Item 4 — closing the benchmark blind spot

`check_lists` keeps its current item-level assertions (they guard the adjacent
failure — items *vanishing* — and do it well). Add, in the same function:

- **block count**: how many `ListBlock`s, not how many items. This is the
  assertion that fails on the reported defect.
- **items-per-block sequence**: `[3]` vs `[1,1,1]`. Catches a merge that
  groups too eagerly as well as one that does not group at all.
- **level sequence**, where the golden has one: catches item 2 and the ODT
  nesting half of item 3.

These need the normaliser to stop flattening `ListBlock` → `list_item` before
the check sees it, or to record the parent block index on each element. The
latter is less disruptive to the other checks that consume the normalised
stream.

**Goldens will move**, and legitimately: every DOCX golden with a list currently
records the fragmented shape, and `lo_listformat.odt`'s records `ordered: false`
on a numbered list. Regenerate with `benchmarks/generate_golden.sh` and list the
moved files in the CHANGELOG entry — a golden diff that is *not* explained by
one of these four items is a regression, not a rebase.

## Impact

From the report: Aitana v6 sends every uploaded document through the parse API
and feeds blocks to an agent as context, so every Word document with bullets
currently reaches the model as N fragmented single-item lists. It also caps a
feature they are designing (generate → ingest → iterate), because the generated
document is read back by the same parser.

That second point is the one worth internalising: **we are our own downstream
consumer**. `--convert x.md x.docx` followed by a parse is a supported workflow
we ship, and it loses structure our own generator emitted correctly.

## Adjacent, deliberately not fixed here

- **PPTX list blocks.** `nest.pptx` parses to `[text:none] • alpha` — literal
  bullet glyphs in text blocks. v0.39.2 taught the *markdown* parser that `•`
  begins a list; the PPTX parser has no equivalent, so the same glyph means a
  list in one format and prose in another. Worth a decision, not a patch:
  slide bullets may legitimately be paragraphs. File separately.
- **EPUB/RTF as convert targets** do not exist (`--convert` supports
  `html docx pptx xlsx odt odp ods md qmd`). Not a defect; noted because the
  scan looked like one.

## Verification plan

- **Inline tests**: `docxMergeLists` over hand-built streams — same key merges,
  key change splits, intervening text block splits, tracked-change sibling does
  **not** split, empty input, single item. ODT list-style resolution: numbered,
  bullet, dangling style name, absent styles.
- **Round-trip proof of the reported case** (`roundtrip_check.py`): markdown
  with a nested bullet list and an ordered list → DOCX → parse → assert one
  block per source list, `itemLevels` preserved, `ordered` preserved. Repeat
  for ODT. This is the assertion the office suite structurally cannot make.
- **`check_lists` self-test**: confirm the new block-count assertion FAILS
  against the pre-fix parser. A guard that has never been seen red is not a
  guard — this is the specific mistake C12 documents.
- **Three suites** (CLAUDE.md hard rule): `run_benchmarks.py --suite office`
  100% after golden regeneration, `roundtrip_check.py` 0 failures,
  `verify_generated.py` green.
- **`./bin/docparse --check` and `--prove`**: zero contract violations.

## Verification log

| Claim | How verified |
|---|---|
| C1 repro | Ran the three-line repro verbatim; 3 items in, 3 singleton lists out |
| C2 generator correct | `unzip -p repro.docx word/document.xml \| grep -o '<w:numId w:val="[0-9]*"'` → 3× numId 1; nested case → ilvl 0/1/1/0, numId 1 and 2 |
| C3 root cause | Read `docx_parser.ail:262-275` and `:218-238` |
| C5/C6 type + drop | Read `types/document.ail:91,377-400` |
| C7 nesting loss | Built `nest.md`, compared `nest.md.json` (`itemLevels: [0,1,1,0]`) with `nest.docx` parse (6 singleton lists) |
| C8 ODT literal false | Read `odt_parser.ail:326-344` |
| C9 real file | `./bin/docparse data/test_files/lo_listformat.odt` → one unordered list; `unzip -p ... content.xml \| grep text:list-level-style-number` → 9 hits |
| C10 ODT/HTML coalesce | Converted `nest.md` to each and re-parsed |
| C11 ODT generator | `unzip -p nest.odt content.xml \| grep -o '<text:list[^>]*>'` → bare `<text:list>`, no `text:list-style` anywhere |
| C12 blind spot | Read `benchmarks/office/eval_office.py:83-120` |
