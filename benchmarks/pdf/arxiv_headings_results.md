# arXiv headings — results

`benchmarks/pdf/arxiv_headings.py`, run 2026-11-12 on macOS (poppler 26.08).
Twelve arXiv papers with LaTeX source in `data/test_files/arxiv`: the source's
section headings are the truth, each backend parses the published PDF.

| Backend | Parsed | heading recall | heading precision | s/paper |
|---|---|---|---|---|
| pdftotext | 12/12 | 0/200 = 0% | — | 0.4 |
| **poppler** | 12/12 | 168/200 = 84% | 168/236 = 71% | 0.9 |
| docling | 12/12 | 186/200 = 93% | 186/251 = 74% | 11.4 |
| liteparse | 12/12 | 18/200 = 9% | 18/152 = 12% | 0.5 |
| ai (gemini-3.5-flash-lite) | 12/12 | 179/200 = 90% | 179/296 = 60% | 82.7 |

docling 2.113 and liteparse were run through the v0.55.6 CLI; neither changed since.

This is the hard counterpart to the structure round trip, where the PDFs are
rendered from our own styled DOCX. Papers set headings in small caps or at
body size, number them, and run two columns.

What the numbers mean:

- **pdftotext** returns text only, so it reports no headings at all.
- **poppler** reads two-column pages column by column, uses the PDF's outline
  where there is one, and recognises numbered headings at body size. What it
  still reports wrongly is mostly title-page lines (authors, affiliations) and
  large text inside figures.
- **docling** runs a layout model: nine points more recall than `poppler` at
  about twelve times the time per paper.
- **ai** is a live model call per page: five points more recall than
  `poppler`, lower precision, and about a hundred times the time per paper.
  It varies between runs: the run before pages were sent one at a time scored
  89% / 65% in 89.8 s.
- **liteparse** ranks by font size alone and reads whole-page rows, as
  `poppler` did before this work.
- The truth is not exact. Some source headings never appear in the PDF as
  written (the stored LaTeX is another version, or the name comes from a
  macro). The other way round, "Abstract",
  "References" and appendix sections are real headings the truth often lacks,
  and they count against precision. Compare backends and runs with each other.

History of the `poppler` row (same 12 papers, current matcher):

| Version | Parsed | recall | precision |
|---|---|---|---|
| v0.55.7 (control characters fixed) | 12/12 | 25% | 34% |
| this run (columns, outline, numbered headings) | 12/12 | 84% | 71% |

v0.55.7's first published figures (18% / 25%) used a matcher that counted an
appendix letter as part of the heading text.

Re-run: `python3 benchmarks/pdf/arxiv_headings.py --fetch`, then
`python3 benchmarks/pdf/arxiv_headings.py --per-file`
