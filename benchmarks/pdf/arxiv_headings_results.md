# arXiv headings — results

`benchmarks/pdf/arxiv_headings.py`, run 2026-11-12 on macOS (poppler 26.08).
Twelve arXiv papers with LaTeX source in `data/test_files/arxiv`: the source's
section headings are the truth, each backend parses the published PDF.

| Backend | Parsed | heading recall | heading precision | s/paper |
|---|---|---|---|---|
| pdftotext | 12/12 | 0/200 = 0% | — | 0.4 |
| poppler | 12/12 | 37/200 = 18% | 37/150 = 25% | 0.9 |

docling, liteparse and ai were not run.

This is the hard counterpart to the structure round trip, where `poppler`
finds 80% of headings in PDFs rendered from our own styled DOCX. Papers set
headings in small caps or at body size, number them, and run two columns.

What the numbers mean:

- **pdftotext** returns text only, so it reports no headings at all.
- **poppler** finds headings by font size and weight. It misses headings set
  at body size, and reports figure labels, running titles and author lines as
  headings. Where a heading sits level with text in the other column, the two
  come out as one block and the heading gets no credit.
- The truth is not exact: the stored LaTeX can be a different version than the
  PDF, and class files add headings the source never names. Compare backends
  and runs with each other; do not read 18% as an absolute.

Before v0.55.7 `poppler` failed outright on most of these PDFs (control
characters in its XML output), which this benchmark now counts in `Parsed`.

Re-run: `python3 benchmarks/pdf/arxiv_headings.py --fetch`, then
`python3 benchmarks/pdf/arxiv_headings.py --per-file`
