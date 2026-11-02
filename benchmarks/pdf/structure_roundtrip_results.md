# PDF structure round trip — results

`benchmarks/pdf/structure_roundtrip.py`, run 2026-11-02 on macOS (poppler 26.08,
LibreOffice for rendering, docling 2.113 with the pypdfium text backend,
liteparse 2.6, ai = gemini-3.5-flash-lite — the hosted default moved off
gemini-2.5-flash on 2026-07-21, see `tests/verify_pricing.ail` in the
docparse repo). Ten of our own DOCX documents are rendered to PDF, each
backend parses the PDF, and the result is scored against the source DOCX.

| Backend | heading recall | heading level | table count | table cells F1 | list recall | furniture leak | text Jaccard |
|---|---|---|---|---|---|---|---|
| pdftotext | 0% | — | 0% | 0% | 0% | 45 | 86% |
| **poppler** | 80% | 75% | **100%** | **83%** | 75% | 2 | 80% |
| docling | 80% | 70% | 78% | 69% | 75% | 2 | 84% |
| liteparse | 80% | 75% | 0% | 0% | 52% | 0 | 87% |
| ai | 100% | 75% | 89% | 81% | 100% | 8 | 84% |

The `ai` row is a live model call, not cached — a second run the same day
scored 100%/92%/86%/79%/100%/4/81% on the same files. Treat the `ai` row as
a band (roughly 75-92% heading level, 4-8 furniture leak) rather than a
fixed number; the other four backends are deterministic and don't vary.

Furniture leak is the total number of source header/footer lines found in the
PDF parse's body text across all ten documents (0 is right).

On the three proposal templates (multi-page, running header and footer, tables,
lists) `poppler` scores 100% on every structural metric and leaks no furniture.

Known gaps, by document:

- `sample`: LibreOffice renders it with no visual formatting (every line 11.3pt
  regular, no title), so no layout-based backend can see its headings.
- `docx-hdrftr`: one page, so its header and footer cannot be told from body
  text by repetition (the 2 leaked lines).
- `pandoc_table_list`, `merged_cells`: merged and multi-paragraph cells.
- `inline_formatting`: superscripts are separate words in the PDF ("mc 2").
- Heading level: a document whose only heading is H2 yields H1 (`tables`); levels
  are relative to what the PDF shows.

Re-run: `python3 benchmarks/pdf/structure_roundtrip.py --per-file`
(add `--backends ai` for the paid backend).
