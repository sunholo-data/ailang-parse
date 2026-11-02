# Office fidelity follow-ups after the OfficeDocBench source audit

**Status**: PPTX spaces and DOCX cell inline formatting merged in [PR #115](https://github.com/sunholo-data/ailang-parse/pull/115). XLSX hyperlink parsing is implemented in [PR #116](https://github.com/sunholo-data/ailang-parse/pull/116); generation and the remaining items below are unscheduled.
**Date**: 2026-10-23
**Implementation and evidence**: [PR #114](https://github.com/sunholo-data/ailang-parse/pull/114),
`benchmarks/officedocbench/results/`, and `audit_legacy_truth.py`.

## Addressed in merged PR #114, pending release

- DOCX relationship-based hyperlinks retain `InlineRun.href`, including plain
  and mixed-format labels. Existing plain-text URL suffixes remain readable.
  Adapter normalization joins adjacent runs for the same link label.
- The shared run coalescer retains `href` when combining runs for the same
  target, including labels split around an inline image.
- HTML generation renders those inline targets as clickable anchors and keeps
  the label's formatting. DOCX field-code and internal-bookmark links, and
  target preservation through other generation formats, need separate coverage.
- Six legacy annotations are independently audited against source HTML/XML:
  `test_complex.html`, `challenge_complex.html`, `challenge_footnotes.docx`,
  `challenge_nested_lists.docx`, `pandoc_inline_images.docx`, and `nested_sdt.docx`.
  Historical HTML parse errors, nonexistent note bodies, fragmented list
  counts, empty SDT text expectations, and an extra image expectation are corrected.
- AILANG warning blocks remain diagnostics in adapter output and do not become
  document prose. Images contribute to the native block reading-order stream.
- Formula comparison accepts an optional leading `=` while rejecting changed
  or missing expressions.

## Confirmed remaining work

Merged PR #115 preserves PPTX standalone-space runs through native and
browser parsing, and checks five exact source paragraphs on two real decks.
Saved pre-fix outputs fail all five checks. Speaker notes, field runs, CDATA,
entities, line breaks and empty runs have dedicated parser checks.

DOCX cell inline formatting uses the existing `TableCell.runs` model, now
preserved by public JSON, JSON reconstruction/A2UI, all four SDKs, and DOCX/HTML
generation. All 78 source-derived run assertions in `table_header_rowspan.docx`
survive parsing and DOCX generation/read-back. Plain cells retain compact JSON.
This implements inline formatting; it does not add nested block content to cells.

XLSX parsing now resolves explicit worksheet hyperlink relationships and internal
locations without inferring links from URL-shaped text or evaluating HYPERLINK
formulas. The source-derived gate `benchmarks/check_xlsx_hyperlinks.py` checks
11 cell/target associations, including non-URL labels, repeated relationship IDs
on different sheets, inherited namespaces, blank cells, omitted row attributes,
ranges, leading rows and collapsed gaps. The same expectations run in Chromium.
It also checks HTML target writing, the 5000-row/5000-link/100-range limits and
full-sheet range metadata without expanding the worksheet. Missing targets and
links outside retained cells produce diagnostics. The dedicated fixture stays
outside the public 87-file corpus; all competitors remain compared on that same
corpus. XLSX and Markdown generation remain explicit follow-ups below.

The legacy audit now covers selected fields in eight cases. In addition to the
six addressed in PR #114, `pandoc_basic.pptx` and `poi_comment.pptx` have source-
derived text, reading order and image expectations. Unused ZIP media entries
are not slide pictures.

| Priority | Gap and reproduction | Acceptance criterion |
|---|---|---|
| P1 | XLSX hyperlink generation and Markdown cell-link writing. Native/browser parsing now exposes explicit targets in `TableCell.runs[].href`, scoped to the correct sheet and retained cell. HTML output keeps those targets. XLSX generation still reduces cells to plain text and renames source sheets; Markdown table cells also remain text-only. | Preserve links through generation/read-back, including internal sheet destinations, source sheet names, and retained row coordinates. Do not imply that parser fidelity establishes generator fidelity. |
| P1 | Nested lists in DOCX cells: `pandoc_table_list.docx` flattens six list items into cell text. Inline run formatting is implemented in [PR #115](https://github.com/sunholo-data/ailang-parse/pull/115). | Design additive nested cell blocks; preserve item depth, order and numbering without changing current text, spans, coordinates or inline runs. Prove parse/generate/read-back behavior. |
| P2 | Nested HTML structures: source-audited complex HTML has nested lists and tables, while native output flattens nested list type/depth and duplicates nested-table text/cells. | Preserve source item depth and ordered/unordered identity, and emit each table's own rows/cells once. Keep checks derived from source HTML. |

The historical upstream whitespace report
[AILANG #646](https://github.com/sunholo-data/ailang/issues/646) is closed.
That fix handles explicit XML preserve scopes. PR #115 supplies
that scope when reading DrawingML content so its string text survives the
generic XML reader's default whitespace filtering. DrawingML text is defined
as string content in the [Microsoft Open XML reference](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.text).

## Existing plans and stale entries

- DOCX list grouping and per-item depth shipped in v0.51.0. The
  [older list design](../v0_40_0/v0_40_0_list_grouping.md) now marks that portion
  shipped; it still contains ODT and other deferred work.
- [Style inheritance](../v0_19_0/v0_19_0_style_inheritance.md) includes broader
  paragraph/table style-chain work. Custom heading inheritance already shipped
  in v0.51.0; the older design must not imply that headings remain unfixed.
- [Colour extraction](../v0_43_0/v0_43_0_colour_extraction.md) has shipped XLSX
  support and later planned phases. PR #115 also writes direct
  DOCX/HTML run colour and preserves it in SDK run types. Other formats and
  style-inherited colours remain separate work. Source assertions in OfficeDocBench are
  selective and do not establish full theme, tint, or inherited-style fidelity.
- The [email hyperlink plan](eml_hyperlink_preservation.md) addresses MIME
  alternative selection. It does not schedule the XLSX or rich-cell work above.

## Evaluation maintenance

Run both source oracles and the corruption tests after annotation changes.
`legacy_verification.fields` records the precise scope of each legacy audit;
other historical fields remain unaudited. Preserve input hashes and original
provider responses, rescore all providers under the same expectations, and
publish the new reference parse and competitor rescores with their provenance.
Image-byte integrity, generation, and browser parity retain separate gates.
