# Office fidelity follow-ups after the OfficeDocBench source audit

**Status**: Active audit; remaining parser changes are unscheduled.
**Date**: 2026-10-23
**Implementation and evidence**: [PR #114](https://github.com/sunholo-data/ailang-parse/pull/114),
`benchmarks/officedocbench/results/`, and `audit_legacy_truth.py`.

## Addressed in PR #114, pending merge/release

- DOCX relationship-based hyperlinks retain `InlineRun.href`, including plain
  and mixed-format labels. Existing plain-text URL suffixes remain readable.
  Adapter normalization joins adjacent runs for the same link label.
- The shared run coalescer retains `href` when combining runs for the same
  target, including labels split around an inline image.
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

| Priority | Gap and reproduction | Acceptance criterion |
|---|---|---|
| P1 | XLSX link identity: `challenge_hyperlinks.xlsx` preserves visible URL strings but exposes no typed cell-to-target relationship. | Preserve relationship targets, including a label that differs from its URL, with sheet/cell identity; do not infer a hyperlink from URL-shaped text. |
| P1 | Rich DOCX cells: `table_header_rowspan.docx` loses cell run formatting; `pandoc_table_list.docx` flattens six list items into cell text. | Design additive cell content supporting inline formatting and nested lists; retain current cell text, spans, and coordinates, and prove parse/generate/read-back behavior. |
| P2 | DrawingML whitespace: a fresh v0.54.18 run turns `Everworker venn` into `Everworkervenn` in `pandoc_basic.pptx`. `poi_comment.pptx` similarly emits `Access toFinancefor Local Governments`. | Preserve standalone space runs through both paragraph text and run metadata, in native and browser parsing. Add exact-text assertions; a count-based golden cannot detect this. |
| P2 | Nested HTML structures: source-audited complex HTML has nested lists and tables, while native output flattens nested list type/depth and duplicates nested-table text/cells. | Preserve source item depth and ordered/unordered identity, and emit each table's own rows/cells once. Keep checks derived from source HTML. |

The historical upstream whitespace report
[AILANG #646](https://github.com/sunholo-data/ailang/issues/646) is closed.
The current DrawingML reproduction still needs investigation; its presence
must not be treated as evidence that this upstream fix remains open.

## Existing plans and stale entries

- DOCX list grouping and per-item depth shipped in v0.51.0. The
  [older list design](../v0_40_0/v0_40_0_list_grouping.md) now marks that portion
  shipped; it still contains ODT and other deferred work.
- [Style inheritance](../v0_19_0/v0_19_0_style_inheritance.md) includes broader
  paragraph/table style-chain work. Custom heading inheritance already shipped
  in v0.51.0; the older design must not imply that headings remain unfixed.
- [Colour extraction](../v0_43_0/v0_43_0_colour_extraction.md) has shipped XLSX
  support and later planned phases. Source assertions in OfficeDocBench are
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
