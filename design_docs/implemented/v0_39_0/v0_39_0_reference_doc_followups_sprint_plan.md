# Sprint Plan — M-REFDOC-FOLLOWUPS (`--reference-doc` follow-ups)

**Sprint JSON**: `.ailang/state/sprints/sprint_M-REFDOC-FOLLOWUPS.json`
**Design doc**: [`v0_39_0_reference_doc_followups.md`](v0_39_0_reference_doc_followups.md)
**Target**: v0.39.0 · **Mode**: sequential · **Created**: 2026-08-28

Execution order M1 → M3 → M2 → M4: the two generator-side items land first so
one verification pass covers them before the parser-side change regenerates
numbering goldens.

## M1 — `--reference-section N` (generator + CLI)

| Step | Detail | Files |
|---|---|---|
| 1.1 | `docxTplCollectSectPrs(docXml) -> [string]`: all sectPr spans in document order, `<w:sectPrChange>` spans dropped first, self-closing supported. `docxTplSectPrAt(docXml, n)`: 0 = last, N≥1 = Nth; out of range → "" | `docparse/services/docx_template.ail` |
| 1.2 | `docxTplLoad(path, section)`; error names the section count when N > count. `docxTplLoad(path)` keeps load-last for existing callers | `docparse/services/docx_template.ail` |
| 1.3 | Thread through `generateDocxWithReference(doc, path, section, tableStyle)` and both call sites; `getReferenceSection(args)` in main.ail; flag + validation in bin/docparse (integer ≥ 1) | `docparse/services/docx_generator.ail`, `docparse/main.ail`, `bin/docparse` |
| 1.4 | Inline tests (pure, synthetic XML): order, sectPrChange exclusion, self-closing, out-of-range, default=last | `docparse/services/docx_template.ail` |
| 1.5 | Checkpoint: `--check`, `--test`, office goldens (no flag → byte-identical) | — |

**Done when**: `--reference-section 1` on a two-section template lifts the
first sectPr; out-of-range errors write nothing; no-flag output unchanged.

## M3 — Template table styles (generator)

| Step | Detail | Files |
|---|---|---|
| 3.1 | Table-style picker in docx_template: name `Table` → else first table style skipping `Normal Table`/`Table Normal` → else ""; `DocxRefDoc.tableStyleId` | `docparse/services/docx_template.ail` |
| 3.2 | `--table-style NAME`: styleId-then-name match, no match → error; requires `--reference-doc`; threaded like M1 | `bin/docparse`, `docparse/main.ail`, `docx_generator.ail` |
| 3.3 | Emit `<w:tblStyle>` first in `<w:tblPr>` + drop hardcoded borders, only when `ref.active && tableStyleId != ""` | `docparse/services/docx_generator.ail` |
| 3.4 | Inline tests for the picker; L6 asserts TableGrid binding + no borders | template module, `benchmarks/verify_generated.py` |
| 3.5 | Checkpoint: `--check`, `--test`, `--prove`, office goldens (no-template path byte-identical) | — |

**Done when**: generated tables under `docx-hdrftr.docx` carry
`<w:tblStyle w:val="TableGrid"/>`; default path unchanged.

## M2 — Numbering resolution (parser; moves goldens)

| Step | Detail | Files |
|---|---|---|
| 2.1 | `readDocxNumbering(path)` in zip_extract (missing → "") | `docparse/services/zip_extract.ail` |
| 2.2 | Parse once in `parseDocx`; build numId→abstractNumId and abstractId→lvl-XML maps; thread to the walk (C10 shape) | `docparse/services/docx_parser.ail` |
| 2.3 | `isOrderedList(p, numMaps)`: resolve ilvl → numFmt; bullet → unordered, other known → ordered; unresolvable → legacy fallback | `docparse/services/docx_parser.ail` |
| 2.4 | Inline tests: bullet/decimal resolution, ilvl match, dangling numId, no numbering.xml | `docparse/services/docx_parser.ail` |
| 2.5 | Run office suite; regenerate moved numbering goldens; list them in CHANGELOG | goldens |
| 2.6 | Round-trip proof: markdown bullets → reference-doc output (template with numId 1 = decimal) → parse back → unordered | scratch + verify |

**Done when**: reference-doc output re-reads with correct bullet-vs-ordered;
golden movement is exactly the resolvable-numbering set; fallback files
(e.g. `sample.docx`, no numbering.xml) unchanged.

## M4 — Full verification + docs

| Step | Detail |
|---|---|
| 4.1 | `./bin/docparse --check`, `--test`, `--prove` |
| 4.2 | All three suites: office 100%, roundtrip, verify_generated (incl. new L6 assertions: table style, synthesized multi-section template with `--reference-section 1`) |
| 4.3 | CHANGELOG Unreleased entry: section picking, numbering resolution (+ golden list), table styles |
| 4.4 | Sprint JSON `passes` → true; evaluation round |

## Risks

- **Golden churn (M2)**: bounded by the legacy fallback; every moved golden is
  individually justified by a resolvable numFmt that disagrees with `numId != "1"`.
- **`<w:numStyleLink>` files**: fall back to legacy (documented; v0_19_0 owns
  style inheritance).
- **Multi-section L6 fixture**: synthesized in Python from `docx-hdrftr.docx`
  (C7) — kept in the verify stage so the fixture always matches what it stresses.