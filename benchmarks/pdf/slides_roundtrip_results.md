# Slides round trip — results

`benchmarks/pdf/slides_roundtrip.py`, run 2026-11-02 on macOS (poppler 26.08,
LibreOffice for rendering, docling 2.113 with the pypdfium text backend). Seven of
our own test decks are rendered to PDF, each backend converts the PDF back to
PPTX, and the result is parsed and scored against the source deck. (An eighth,
`python_pptx_slides.pptx`, has placeholder-only slides with no text and is
skipped.)

| Backend | slides | titles | text | table cells F1 | pictures | overflow |
|---|---|---|---|---|---|---|
| **default** (poppler slide mode) | 94% | **100%** | **96%** | 86% | 4 | **0** |
| docling | 96% | 83% | 94% | 96% | 2 | 0 |
| pdftotext | 53% | 43% | 98% | 0% | 0 | 0 |

- **slides**: slide-count agreement. **titles**: source slide titles found as
  the first block of an output slide. **text**: source words found anywhere in
  the output, speaker notes included (diagram labels go there). Source speaker
  notes are excluded from the truth: they never reach a PDF.
- **pictures** and **overflow** are totals. Overflow counts shapes that extend
  past a slide's bottom edge; 0 is right.
- `pdftotext` keeps no page boundaries, which is why the CLI reads PDFs with
  poppler's slide mode when converting to slides.

Known gaps, by deck:

- `python_pptx_table`: page 1 is a table of wrapped, vertically anchored
  cells; read as text it is fragments, so it is kept as a picture of the page
  with its text in the notes.
- `pptx_inline_formatting`: superscripts and small caps become separate words.

Re-run: `python3 benchmarks/pdf/slides_roundtrip.py --per-file`.
