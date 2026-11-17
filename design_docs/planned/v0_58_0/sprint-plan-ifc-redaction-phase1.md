# Sprint Plan: IFC redaction, phase 1 (v0.58.0)

**Design**: [v0_58_0_ifc_redaction.md](v0_58_0_ifc_redaction.md), phase 1 only
**Date**: 2026-11-17
**Status**: Complete (2026-11-17) — M1, M2, M3 done; results below
**Scope ruling (Mark, 2026-11-17)**: build what is not blocked on AILANG now. The three
AILANG asks (egress policy, `FS[mode=read]`, labels inside imported types) are dependencies,
not workarounds to build; the confinement lint is the stop-gap.
**Out of scope**: detectors (patterns, known-name search), policy file, CLI `--redact`,
PDF, local-model detection — phases 2 and 3.

## Spike results (2026-11-17, before planning)

`docparse/redact/{source,core,egress}.ail` sketched against the real `ParseOutcome` and
`ParsedDocument` types, with a probe that writes a raw `o.document.filename` to the egress
sink:

| Toolchain | Clean path | Leak |
|---|---|---|
| AILANG dev (v0.60.5+) | passes | **rejected** (information-flow violation, names the sink) |
| v0.60.4 release | passes | **rejected** |
| v0.58.0 release | passes | **rejected** |
| v0.57.4 release | passes | **passes — fails open** |

Consequences, ruled into this plan:

1. **The package floor rises from `>=0.50.0` to `>=0.58.0`.** CI's floor job type-checks
   the whole package on the floor; on anything older the redaction guarantee silently does
   not hold. CHANGELOG states it.
2. `Declassify` joins `[effects].max` in `ailang.toml` (compile-time only; no runtime
   capability, never in `--caps`).
3. The negative tests (M3) are the guard against a toolchain that fails open: on v0.57 they
   would go red, which is the point.

## Milestones

### M1 — Boundary modules (~180 LOC)

- `ailang.toml`: floor `>=0.58.0`; `Declassify` in `[effects].max`; the three modules in
  `[exports]`; `assets/bin/docparse` `MODULES` so `--check` covers them.
- `docparse/redact/source.ail`: `redactSource(path) -> Result[ParseOutcome<doc_content>, string] ! {FS}`.
  Calls `parseDocumentPure` with `extractImages = false`, `useAI = false`. Formats outside
  `parseDocumentPure` (PDF, images, audio, video, LaTeX) come back as its `Err`, re-worded as
  "not supported in redaction mode". Nothing else in the module.
- `docparse/redact/egress.ail`: `writeRedactedJson`, `writeRedactedMarkdown`,
  `writeRedactionReport` (`! {FS}`) and `logRedacted` (`! {IO}`), every string parameter
  `{not doc_content}`.
- `docparse/redact/policy.ail` (pure, no effects): `RedactPolicy`, `RedactionReport`,
  `RedactedResult` types and `defaultRedactPolicy()`. No labels written inside these types
  (design rule 1).

**Acceptance**: `./bin/docparse --check` clean on dev and on the v0.58.0 release; floor job
green.

### M2 — Redaction core (~320 LOC + ~150 LOC tests)

`docparse/redact/core.ail`, effect row of every function `! {}` except the one declassifier:

```ailang
export func redactOutcome(policy: RedactPolicy, o: ParseOutcome<doc_content>)
  -> RedactedResult ! {Declassify[label=doc_content]}
```

Per block, phase-1 policy (drop/keep only; detection is phase 2):

| Block / field | Phase 1 |
|---|---|
| `CommentBlock.author`, `ChangeBlock.author`, `DocMetadata.author` | pseudonymised, `Reviewer N`, numbered per document by first appearance |
| `CommentBlock.text` / `anchorText` | policy `commentText`: keep / drop (default keep) |
| `ChangeBlock` with `changeType` deletion | policy `deletions`: drop (default) / keep |
| `SectionBlock(kind="notes")` | policy `speakerNotes`: keep (default) / drop |
| `ImageBlock`, `AudioBlock`, `VideoBlock` | data always dropped; dimensions and mime kept |
| `LinkBlock.href` | `mailto:` / `tel:` → `[EMAIL]` / `[PHONE]`; other URLs keep scheme+host+path, query dropped |
| `SectionBlock` | recurse |
| everything else | kept (phase 2 runs detectors here) |

`RedactionReport`: counts per category (authors pseudonymised, comments dropped, deletions
dropped, notes dropped, media dropped, links rewritten) plus the indices of touched blocks.
Never a value.

Tests: `scripts/verify_redaction.ail` (entry `main`, `--caps IO,FS`), over existing public
fixtures (`comments.docx`, `track_changes_move.docx`, `pptx_slide_order_notes.pptx`,
`poi_comment.pptx`, `pandoc_inline_images.docx`):

- no author string from the source survives anywhere in the rendered output;
- pseudonyms are stable (same input twice gives identical output);
- each policy switch changes exactly the blocks it names;
- media data is empty, dimensions survive;
- the report's counts match the blocks.

**Acceptance**: all assertions pass on dev and v0.60.4; output rendered through the existing
`formatResult` and Markdown writer goes out only through `egress`.

### M3 — The proof, and the stop-gap (~220 LOC)

- `benchmarks/check_redact_ifc.sh`: copy `docparse/redact/` to a scratch package, inject
  each leak, assert `ailang check` fails with the right error, then the clean copy passes:
  1. labelled outcome rendered and written via `writeRedactedJson` without `redactOutcome` → IFC;
  2. `logRedacted` of a labelled block's text → IFC;
  3. `std/fs.writeFile` called from `core.ail` → effect error;
  4. a helper in a new module returning labelled text as `string<clean>` without `Declassify`
     → declassification (laundering) error;
  5. `Declassify[label=doc_content]` used to drop a different label → scope error;
  6. clean pipeline → passes.
- `benchmarks/check_redact_confinement.py` (design §6, stop-gap until AILANG asks 1–2 ship):
  only `source.ail` and `egress.ail` declare `FS`/`IO`/`Net`/`AI`/`Process`/`Env`; no
  `docparse/redact/` module imports a stdlib egress function except `egress.ail`; exactly one
  `! {Declassify` site; every `egress.ail` string parameter carries `{not doc_content}`.
- No-egress run: `verify_redaction.ail` under a fresh `TMPDIR` and a fresh image temp dir;
  assert no file appears there.
- CI: the three checks as steps in the Structural Benchmark job; `verify_redaction.ail` run.
- Docs: CHANGELOG (floor bump, new modules, what is proved and what is not), design doc
  status, roadmap entry.

**Acceptance**: all three checks green locally on dev and v0.60.4, and in CI. Reverting
`redactOutcome`'s call in the clean pipeline makes check 1 red (control).

## Validation

```
./bin/docparse --check
ailang run --quiet --entry main --caps IO,FS scripts/verify_redaction.ail
bash benchmarks/check_redact_ifc.sh
python3 benchmarks/check_redact_confinement.py
```

plus the existing suite through CI.

## Estimate

~720 LOC including tests, against the design's 2–3 days. One PR.

## Risks

- **Label through `match` on a labelled ADT inside `core.ail`.** Taint should flow through
  pattern matching (the IFC guide: `let`/`match`/record/call); the spike only exercised a
  record update. M2 tests cover it by rendering every block type.
- **Imported HOFs over-approximate** (`map(f, labelledList)` keeps the label). That is the
  safe direction; inside `redactOutcome` everything is labelled until the declared
  unlabelled return.
- **Floor bump** stops consumers on AILANG < 0.58 from installing new versions. Accepted:
  the guarantee does not exist there.

## Results (2026-11-17)

| Check | dev | v0.60.4 | v0.58.0 | v0.57.4 |
|---|---|---|---|---|
| `./bin/docparse --check` (92 modules) | clean | — | clean | — |
| `check_redact_ifc.sh` | 17/17 | 17/17 | 17/17 | **14/17** — leaks 1, 2, 4b compile (fails open), as predicted |
| `verify_redaction.ail` | 45/45 | 45/45 | 45/45 | — |

Deviations from the plan: `source.ail` also imports `std/result (Ok, Err)` (not prelude on
release binaries; the lint allows it). The fixture `track_changes_move.docx` has no deletions,
so `pandoc_tc_deletion.docx` was added to cover a real one.
