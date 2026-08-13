# Merged header table

A table whose HEADER row carries a colspan plus its merged continuations. The
existing xlsx fixtures put the merged row last, as a data row, where a wrong
width calculation is invisible: a too-wide row is simply left alone. In the
header it sets the table's width, so every data row below gets padded out to
match — three phantom columns per row, and a DOCX grid that no row fits.

| Financial Summary FY2026 {colspan=4} |  {merged} |  {merged} |  {merged} |
| --- | --- | --- | --- |
| Quarter | Revenue | Expenses | Profit |
| Q1 | 50000 | 30000 | 20000 |
| Q2 | 65000 | 35000 | 30000 |

A second table with a partial span, so the walk has to resume counting plain
cells after a span ends rather than assuming the span runs to the row's end.

| Half year {colspan=2} |  {merged} | Notes |
| --- | --- | --- |
| Q1 | Q2 | first half |
| Q3 | Q4 | second half |
