# Golden drift — regressions the benchmark could not see

**Status**: DONE (2026-08-11). All 62 office-suite files match their goldens.
**Theme**: Four defects sat in committed goldens for months. None of them was
"staleness"; three were live regressions. Spun out of
[`v0_30_0_inline_runs.md`](./v0_30_0_inline_runs.md), where the first three were
found; the fourth surfaced when the byte-equality sweep was widened past the 62
files the office suite scores.

## Why they went unnoticed

The office suite scores **text similarity, not byte-equality**. A file whose
images stopped resolving still reads 100%, because the text is unchanged. That
is exactly what happened: the suite reported **100.0% before and after** every
fix below, and never once flagged them.

This is the same blind spot that let the orphaned `styles.xml` survive in
v0.29.0 — a check that cannot fail on a defect is not covering it. The drift was
only visible by diffing parser output against the goldens directly:

```
2 of 62 files differ from golden      (before the fixes here)
0 of 62 files differ from golden      (after, on parsed content)
```

Defect #4 needed a second widening: past the suite entirely, to the 16 eml/mbox
goldens sitting in the same directory that **no suite reads**. The score's
blindness and the corpus's coverage gap are separate failures that happened to
hide the same class of bug.

A byte-equality sweep is cheap and catches a class the similarity score
structurally cannot. Worth adding to the suite as a separate signal rather than
folding into the score — see [Follow-up](#follow-up).

## 1. ODF images stopped resolving — regression

ODT/ODP/ODS `ImageBlock.data` held the **ZIP-internal href string** instead of
the image bytes. The tell is that `dataLength` equalled `len(src)` exactly:

| file | golden | was reporting | src |
|---|---|---|---|
| `officeparser.odp` | 2652–14968 | `16` ×7 | `media/image1.png` (16 chars) |
| `lo_image_mimetype.odt` | 8564 | `53` | `Pictures/….svg` (53 chars) |
| `officeparser.odt` | 16 (already regressed) | `16` | `media/image2.jpg` |

**Root cause**, confirmed by reading the pre-refactor tree: before
[`1a28c47`](https://github.com/sunholo-data/ailang-parse/commit/1a28c47)
(*refactor(cli): main.ail becomes a printer over parseDocument*, v0.28.0 phase 2,
2026-08-07), `main.ail` called `resolveBlockImages` at two sites — one for EPUB,
one for ODF. The refactor carried the EPUB call into `orchEpub` and **dropped the
ODF one**. `main.ail` was still importing `resolveBlockImages` without ever
calling it, which is the fingerprint it left behind — now removed, along with the
rest of that import (see [Follow-up](#follow-up)).

Fix: `orchOdf` resolves images for all three ODF types, as `orchEpub` does.
`officeparser.odt`'s golden was itself generated after the regression, so it
recorded the broken value; it now resolves to 100140 bytes — base64 of the real
75103-byte JPEG (×4/3, as expected).

DOCX/PPTX were never affected: their parsers embed image data directly rather
than deferring to ZIP resolution.

## 2. SVG mime downgraded on resolution — latent, exposed by fix 1

Two mime guessers had diverged. `odt_parser.odtGuessMime` knows `.svg` and
`.webp`; `zip_extract.mediaMimeType` did not and fell back to
`application/octet-stream`. Since resolution *overwrites* the parser's mime,
fixing #1 would have downgraded `image/svg+xml` → `application/octet-stream` —
turning one fix into another regression, and matching the old golden while doing
so.

Fix: `.svg` and `.webp` added to `mediaMimeType`, with inline tests (9 → 11).
`lo_image_mimetype.odt` — a file whose whole purpose is mime detection — now
reports `image/svg+xml` with real bytes, better than the golden it drifted from.

The deeper duplication (two guessers, different coverage, one silently
overriding the other) is left alone deliberately; noted in
[Follow-up](#follow-up).

## 3. `test.tsv` reported `format: "csv"` — regression

`detectFormat` maps `tsv → "csv"` **by design** — it names a parsing *strategy*,
and its inline tests assert it. The bug was one layer up: `orchCsv` picked its
delimiter from `ext` correctly but then hardcoded `mkOutcome("csv", …)`, so the
user-visible `format` lost the distinction the delimiter had just honoured.

Fix: `mkOutcome(ext, …)`. `orchCsv` is only reachable for `csv`/`tsv`, so `ext`
is exactly the right value. `test.tsv` → `"tsv"`, `test.csv` → `"csv"`.

## 4. `orchEmail` had the identical bug — regression

Found by widening the sweep past the files the office suite scores.
`benchmarks/office/golden/` also holds **16 eml/mbox goldens that no suite
scores**, and 3 of them were failing for exactly the reason #3 was:

```ailang
func orchEmail(filepath: string, ext: string, opts: ParseOptions) -> ... {
  ...
  mkOutcome("email", filepath, meta, blocks,
    ["Parsed ${ext}: ..."], [], 0)   -- ext used in the note, discarded in the format
}
```

Same shape, same layer, same file — `detectFormat` maps `eml`/`mbox` → `"email"`
by design (a strategy name, asserted by its inline tests), and the sibling
function one below `orchCsv` threw the distinction away. `challenge_basic.eml`
reported `format: "email"` where its golden says `"eml"`; the two mbox files
likewise.

Fix: `mkOutcome(ext, …)`, with the same reasoning — `orchEmail` is reachable only
via `format == "email"`, which `detectFormat` produces only for those two
extensions. `orchEmailDeep` rebuilds the outcome from `outcome.document.format`,
so `--deep` is fixed by the same change.

**These two were the only hardcodes that could be wrong.** Of the 18
`mkOutcome("…")` call sites in `orchestrator.ail`, 16 serve exactly one extension
and their literal is correct by construction. `orchCsv` and `orchEmail` are the
only two that take an `ext` parameter spanning two extensions — so the audit is
complete, not a spot check.

## Verification

- **0 of 62** office-suite files differ from golden, from 2. (The suite scores
  **62** as of the ODT list-items fixture; the "61" in this doc's earlier drafts
  and in the inline-runs entries dated before it were correct when written.)
- **Five files were restored to their existing goldens with no golden change** —
  `officeparser.odp`, `test.tsv`, and (from #4) `challenge_html_multipart.eml`,
  `challenge_mbox.mbox`, `challenge_threaded.mbox`. This is the strongest
  evidence these were regressions rather than drift: the goldens were right all
  along and the code had moved away from them.
- Only **two** goldens were edited, both strict improvements: `officeparser.odt`
  (image now resolves) and `lo_image_mimetype.odt` (correct mime). Both had
  *matched* before the fixes — their goldens had been regenerated after the
  regression, so they recorded the broken values as if correct. A file matching
  its golden is not evidence the golden is right.
- Byte sweep over the whole golden directory, not just the scored suite:
  **61 → 64 identical, 16 → 13 differing.**
- Office suite **100.0% across 62 files**; `--eval` **62/62**;
  `verify_generated.py` all-pass including L2b; `ailang check docparse/` 48 files
  clean.

**The goldens are invocation-dependent, which a byte check has to handle.**
`filename` records the path exactly as it was passed in, so the same document
produces a different golden depending on how it was parsed. Of the 97 goldens,
**95 hold an absolute `/Users/mark/…` path and 2 hold a relative one**
(`pandoc_inline_images.docx`, `challenge_equations.docx`) — so **no single
invocation matches all of them**. Running the sweep with absolute paths flags the
2; running it with relative paths flags the 95. This is not a parser defect and
it costs nothing today, but it constrains the follow-up below — a byte check must
normalise `filename` — and 95 goldens carrying one developer's home directory
will not survive CI on another machine.

The 12 eml files that still differ are unrelated to anything here and split into
at least two causes needing their own triage — see [Follow-up](#follow-up).

## Follow-up

- **Add a byte-equality check to the office suite**, reported alongside the
  similarity score rather than merged into it. Every defect here was invisible
  to a 100.0% run; the sweep that found them is a dozen lines. Two requirements
  it must meet, both learned the hard way above: **normalise `filename`** (or the
  95-absolute/2-relative split reports false positives either way you run it),
  and cover the **whole golden directory**, not just the scored suite — which is
  how #4 was found.
- **Stop baking absolute paths into goldens.** 95 of 97 embed
  `/Users/mark/…`; they are machine-specific and cannot be verified in CI.
- **16 eml/mbox goldens are scored by no suite at all.** They sit in
  `benchmarks/office/golden/` beside the 62 the office suite reads, and nothing
  reads them. That is a blind spot of a different kind from the similarity score,
  and a strictly worse one: not a weak check, but no check. Defect #4 lived there
  for months in consequence.
- **Triage the 12 remaining eml diffs.** Two distinct causes seen so far, and
  they need opposite responses: `MIME-Version: 1.0` is no longer emitted as an
  `email-header` block (looks like a **regression** — the header is present in
  the source), while `challenge_html_only.eml` now renders `[here](https://…)`
  where the golden has bare `here.` (looks like an **improvement**, from the
  LinkBlock/marker work). Do not bulk-regenerate: that would bake the first in
  while appearing to fix everything.
- **Consolidate the two mime guessers.** `odtGuessMime` and `mediaMimeType`
  disagree on coverage and fallback (`image/unknown` vs
  `application/octet-stream`), and resolution silently prefers the weaker one.
- ~~`main.ail` imports `resolveBlockImages` without calling it~~ — **done**. All
  seven names in that `zip_extract` import were unused, so the whole line went.
  Verified it was not load-bearing for AILANG's transitive-import rule: type-check
  clean and ODF images still resolve (`officeparser.odt` byte-identical to golden).
