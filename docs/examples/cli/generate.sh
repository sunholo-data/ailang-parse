# Write the document in Markdown, then convert it to any of the 9 formats.
# Front matter sets the document properties.
cat > report.md <<'MD'
---
title: Q1 Revenue Review
author: Finance
date: 2026-04-02
---

# Q1 Revenue Review

Revenue grew **31%** against a [flat forecast](https://example.com/plan).

| Region | Q4      | Q1      | Change |
|:-------|--------:|--------:|:------:|
| EMEA   | 1.20M   | 1.61M   | +34%   |
| AMER   | 0.90M   | 1.14M   | +27%   |

> Renewals, not new logos, drove the quarter.
MD

# One source, every output format
docparse report.md --convert report.docx     # Word
docparse report.md --convert deck.pptx       # headings become slides
docparse report.md --convert report.xlsx     # tables become sheets
docparse report.md --convert report.odt      # OpenDocument
docparse report.md --convert report.html     # HTML
docparse report.md --convert report.qmd      # Quarto

# Read the structure back to check it survived —
# "the file opens" is not the same as "the file is correct"
docparse report.docx
