# Golden drift — regressions the benchmark could not see

**Status**: DONE (2026-08-11). All 61 corpus files now byte-match their goldens.
**Theme**: Three defects sat in committed goldens for months. None of them was
"staleness"; two were live regressions. Spun out of
[`v0_30_0_inline_runs.md`](./v0_30_0_inline_runs.md), where they were found.

## Why they went unnoticed

The office suite scores **text similarity, not byte-equality**. A file whose
images stopped resolving still reads 100%, because the text is unchanged. That
is exactly what happened: the suite reported **100.0% before and after** every
fix below, and never once flagged them.

This is the same blind spot that let the orphaned `styles.xml` survive in
v0.29.0 — a check that cannot fail on a defect is not covering it. The drift was
only visible by diffing parser output against the goldens directly:

```
2 of 61 files differ from golden      (before the fixes here)
0 of 61 files differ from golden      (after)
```

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
(*refactor(cli): main.ail becomes a printer over parseDocument*), `main.ail`
called `resolveBlockImages` at two sites — one for EPUB, one for ODF. The
refactor carried the EPUB call into `orchEpub` and **dropped the ODF one**.
`main.ail` still imports `resolveBlockImages` today without calling it, which is
the fingerprint left behind.

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

## Verification

- **0 of 61** files differ from golden (was 2, having restored 2 others).
- Two goldens updated, both strict improvements: `officeparser.odt` (image now
  resolves) and `lo_image_mimetype.odt` (correct mime). `officeparser.odp` and
  `test.tsv` needed no golden change — the fixes restored them to what their
  goldens already said, which is the strongest evidence these were regressions
  rather than drift.
- Office suite 100.0% across 61 files; `--eval` 61/61; `verify_generated.py`
  all-pass including L2b; 36 modules type-check clean.

## Follow-up

- **Add a byte-equality check to the office suite**, reported alongside the
  similarity score rather than merged into it. Every defect here was invisible
  to a 100.0% run; the sweep that found them is a dozen lines.
- **Consolidate the two mime guessers.** `odtGuessMime` and `mediaMimeType`
  disagree on coverage and fallback (`image/unknown` vs
  `application/octet-stream`), and resolution silently prefers the weaker one.
- **`main.ail` imports `resolveBlockImages` without calling it** — dead import,
  and the trace of this bug. Harmless, worth removing.
