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

## 5. The goldens nothing read — 37 of 99

The eml blind spot was a symptom. `generate_golden.sh` globs
`data/test_files/challenge/` and writes goldens for everything it finds there,
but `eval_office.py` scanned `TEST_DIR` **non-recursively** with a suffix list
excluding `.eml`/`.mbox`. Generation and checking covered different corpora, so
**37 of 99 goldens were written and never read.**

Fixed by scanning `challenge/` too. The suite goes from 62 → 99 files.

### The 12 eml diffs: all stale, none regressions

The `MIME-Version` disappearance looked like a regression and was not. Both
causes trace to one commit, [`7ee1d97`](https://github.com/sunholo-data/ailang-parse/commit/7ee1d97)
(2026-05-02, *strip transport headers + fix multipart/alternative duplication*):

1. **10 files** — `emlIsKeyHeader` is an allowlist that deliberately drops
   transport noise, `MIME-Version` and `Content-Transfer-Encoding` among it.
   Proven exhaustive rather than assumed: deleting exactly the stripped-header
   blocks from each golden makes it **identical** to current output, so nothing
   else moved in any of the ten.
2. **`challenge_multipart_alt.eml`** — the same commit's second fix. The golden
   contains the body **twice**, once as text and again as a `mime-part` section
   holding the HTML alternative. Now one part is selected. 16 blocks → 8.
3. **`challenge_html_only.eml`** — `[here](https://example.com/track)` where the
   golden has bare `here.`; the link target used to be discarded.

All 12 regenerated, plus 2 files that had no golden at all
(`challenge_encoded_filenames.eml`, `challenge_pdf_attachment.eml` — both parse
deterministically; they were simply added after the last generation run).

### Eight failures the suite had never reported

With `challenge/` in scope the suite reads 99 goldens and scores **97.0%**. The
100.0% was not a passing grade, it was 37 unread files. Newly visible:

| file | score | status |
|---|---|---|
| `challenge_speaker_notes.pptx` | 67% → **100%** | **fixed** — deleted feature restored, see below |
| `challenge_complex.html` | 0% → **100%** | **fixed** — golden recorded `HTML parse error: element <meta> closed by </head>`, the strict-XML failure since fixed by `parseLenient`. Golden regenerated; 1 error block → 9 real blocks |
| `challenge_comment_ranges.docx` | 60% | untriaged |
| `challenge_comments.xlsx` | 67% | untriaged |
| `challenge_fields.docx` | 75% | untriaged |
| `challenge_hyperlinks.docx` | 75% | URL text `(https://…)` no longer appended; lost a `section-break` — untriaged |
| `challenge_formulas.xlsx` | 80% | MERGE check — untriaged |
| `challenge_merged_cells.xlsx` | 80% | MERGE check — untriaged |

Suite: **97.0% → 98.4%** across 99 files, both gains from real fixes rather than
golden edits that paper over a defect.

**`challenge_speaker_notes.pptx` is the serious one: PPTX speaker-note
extraction was deleted from the source.**
[`e9de665`](https://github.com/sunholo-data/ailang-parse/commit/e9de665)
(2026-03-30, *Sync source .ail modules with docs/ailang/ browser versions*) ran
the sync in the wrong direction and overwrote `pptx_parser.ail` with a reduced
browser variant, taking `findNotesSlideEntries`, `pptxParseNotesSlides` and the
`kind: "notes"` section with it. `notesSlide` survives today only in
`docs/pptx-parsing.html`, which still advertises the feature, and in three
design docs. The golden proves it worked; nothing read the golden.

This is the concrete damage behind the later "docs/ailang is registry-vendored,
never hand-sync" rule — a feature silently deleted by a sync commit, four months
undetected because the only test that covered it was never run.

**Restored.** `findNotesSlideEntries` went back into `zip_extract`, and
`pptxParseNotesSlides` / `pptxExtractNoteText` / `pptxFindNotesBodyText` /
`pptxFindNotesTextInShapes` into `pptx_parser`, recovered from `e9de665^`. Every
other helper they need (`getPlaceholderType`, `extractDrawingMLText`,
`optFlatMap`) had survived. One deliberate change from the recovered original: it
called `parse`, which this module no longer imports — it uses `parseLenient`
throughout since the bare-ampersand fix, and notes XML is no more trustworthy
than any other part.

`challenge_speaker_notes.pptx` now parses **byte-identical to its four-month-old
golden** — the strongest available evidence that the golden was right and the
code had lost the feature. `poi_sampleshow.pptx` gains two real notes sections
("I am the notes of the first slide", "These are the notes of the 2nd slide…")
with every other section unchanged; that golden was regenerated, since it too had
been written after the deletion.

### One harness bug, exposed by the same change

Including the email corpus made the batch runner crash: `subprocess.run(...,
text=True)` strict-decodes stdout, and an EML attachment carries non-UTF-8
bytes. The batch only uses the exit code, so it now decodes with
`errors="replace"` rather than failing on output it does not read.

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
- ~~16 eml/mbox goldens are scored by no suite at all~~ — **done, and it was
  worse than 16.** See §5 below.
- ~~Triage the 12 remaining eml diffs~~ — **done**, all 12 explained. See §5.
- **Consolidate the two mime guessers.** `odtGuessMime` and `mediaMimeType`
  disagree on coverage and fallback (`image/unknown` vs
  `application/octet-stream`), and resolution silently prefers the weaker one.
- ~~`main.ail` imports `resolveBlockImages` without calling it~~ — **done**. All
  seven names in that `zip_extract` import were unused, so the whole line went.
  Verified it was not load-bearing for AILANG's transitive-import rule: type-check
  clean and ODF images still resolve (`officeparser.odt` byte-identical to golden).
