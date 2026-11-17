# Design Doc: Redaction with information-flow control (v0.58.0)

**Status**: Planned — **priority** (moved ahead of the older roadmap items, 2026-11-17)
**Date**: 2026-11-17
**Author**: Mark + Claude
**Builds on**: AILANG IFC labels (`! {Declassify}`, `{not ℓ}` sinks, cross-module labels since
AILANG v0.58.0); `parseDocumentPure` (`! {FS}` only); the batch output layout of 0.57.x (`-r`,
mirrored folders)

## Problem

People preparing a document archive for AI search ask two things before volume or speed:

1. **Personal and confidential data must not reach a model, an index or a log** unless it has
   been redacted first. Archives are full of it, and much of it is not in the body text:
   comment authors, tracked-change authors, "last modified by" in the file properties, deleted
   text that tracked changes keep, speaker notes.
2. **They need to show that this holds**, not just say so. "We call a redaction function"
   is a statement about today's code. It says nothing about the next change, or about the
   code path nobody tested.

Today AILANG Parse parses documents as they are. The hosted terms say so explicitly ("We do
not anonymise, pseudonymise, or redact data", `docs/terms.html`). A caller can filter blocks
after parsing, but nothing guarantees they did.

AILANG has the tool for the second half: information-flow control (IFC) labels, checked by
the compiler. A value labelled `<doc_content>` cannot reach a parameter typed
`string{not doc_content}`; the only way to remove the label is a function that declares
`! {Declassify}`, which `grep` finds. That turns "every output went through the redactor"
from a promise into a compile error, which we know of no other document parser offering.

## Goal

`docparse --redact` parses documents and writes only redacted output, and the compiler
proves that no code path in the redaction pipeline writes, sends or logs document content
that has not been through the redactor. Concretely:

- Outputs (`.json`, `.md`, chunks) hold redacted text; personal data found by the detectors is
  replaced with typed placeholders (`[EMAIL]`, `[PHONE]`, `[PERSON 2]`).
- Comment authors, tracked-change authors and document-property authors are always
  pseudonymised (they are known personal data, not a detection problem).
- Each file gets a redaction report: counts per category and block positions, never values.
- Same input and same policy give the same output (deterministic, re-checkable).
- It works with the archive workflow: `docparse -r /archive --redact --output-dir /parsed`.

## Non-goals

- **Perfect detection.** IFC proves the redactor ran on everything that leaves; it does not
  prove the redactor found every name. Detection quality is measured and published, not
  implied by the type system (see Claims below).
- **Images.** Text inside pictures cannot be redacted without OCR. Redaction mode drops
  image data; descriptions are not generated.
- **The hosted API.** Redaction is for the local CLI and self-hosting, where the raw
  documents never leave the machine. Hosted redaction would mean we receive the raw data,
  which defeats the point.
- **Access control between clients or teams.** Separate indexes per client and the folder
  layout from `-r` do that; labels here are categories, not tenants (see "What AILANG gives
  us", limit 2).

## What AILANG gives us (verified 2026-11-17, AILANG v0.60.4 release binary)

Two-module probes, `ailang check`:

| # | Case | Result |
|---|---|---|
| A | Imported function returns `string<apikey>`; importer passes it to its own `{not apikey}` sink | **rejected** |
| B | Same, through an imported `! {Declassify}` function | passes |
| C | Imported function returns a record with a labelled field; importer sends `.body` to `{not pii}` | **rejected** (the return carries the label) |
| D | Label written only inside an imported *type* (`type Doc = {body: string<pii>}`), value built in the importer | **passes** — not checked |
| E | Same as D with the type declared in the importer's own module | rejected |
| F | A labelled value passed straight to `std/fs.writeFile` | **passes** — stdlib effects declare no sinks |
| G | A function without `FS` in its effect row calls `writeFile` | **rejected** (effect error) |

What follows from this:

1. **Labels cross modules on values, not on types.** Label the value where it is produced
   (a function's return type). Never rely on a label written inside a type declaration
   (D; AILANG tracks it as `m-ifc-cross-module-labels`).
2. **Labels are static names**, written in code: `<doc_content>`, `<pii>`. They suit
   categories, not one label per client discovered at run time.
3. **Stdlib egress is unguarded (F).** `writeFile`, `httpRequest`, the AI calls and `println`
   accept labelled values. The guarantee therefore needs two halves: our own sinks with
   `{not doc_content}`, and **effect rows (G)** that stop labelled code from reaching stdlib
   egress at all.
4. **Positive parameter labels admit unlabelled values** (the IFC guide, "positive call
   parameters"), so a sink requiring `string<redacted>` would not catch content that was never
   labelled. The labelling has to happen at the single entry point, inside the pipeline.
5. Labelled values are recorded as `<redacted:LABEL>` in execution traces and OTEL spans
   (M-TRACE-LABEL-AWARE), so debugging a run does not leak content into telemetry. The
   bytecode VM does not carry those marks; a traced labelled run falls back to the evaluator.

## Approach

New modules under `docparse/redact/`. The existing parser is not changed except where noted.

### 1. One label, one entry point

```ailang
-- docparse/redact/source.ail
-- The only function that turns a file into document content for this pipeline.
-- Uses parseDocumentPure (! {FS}: no AI, no network, no subprocess, proved by its
-- effect row) with extractImages = false and useAI = false: DOCX image extraction
-- follows extractImages, PPTX image extraction follows useAI, and both write image
-- temp files under /tmp/docparse-images. With both off, nothing is written (proved
-- by the no-egress check under Verification, which also covers ODF).
export func redactSource(path: string) -> Result[ExtractionResult<doc_content>, string] ! {FS}
```

`<doc_content>` means "text that came from a parsed document and has not been through the
redactor". The whole `ExtractionResult` carries it (AILANG values carry one label), so every
field reached from it, including metadata, is tainted (case C).

Formats that need more than `{FS}` (PDF with external backends, images, audio) are refused
in redaction mode in v1, with a typed error. PDF via `pdftotext` (`Process`) is phase 2: the
backend is a subprocess that reads the file and returns text, and its output enters through
the same labelled entry point.

### 2. A pure redaction core, the only declassifier

```ailang
-- docparse/redact/core.ail — no FS, Net, AI, IO, Process in any effect row
export func redactResult(policy: RedactPolicy, r: ExtractionResult<doc_content>)
  -> RedactedResult ! {Declassify[label=doc_content]}
```

`RedactedResult` holds the redacted `ExtractionResult` and the `RedactionReport`. Scoped
`Declassify[label=doc_content]` means this function can drop only that label; any other label
in its input survives. It is the one place `grep '! {Declassify'` should find in
`docparse/redact/`, and CI checks that it is.

Per block type (policy defaults in brackets):

| Block / field | Default |
|---|---|
| `TextBlock`, `HeadingBlock`, `ListBlock`, table cells, `LinkBlock.text` | run detectors, replace matches |
| `LinkBlock.href` | `mailto:` and `tel:` replaced; other URLs kept, query string dropped |
| `CommentBlock.author`, `ChangeBlock.author`, `DocMetadata.author` | always pseudonymised (`Reviewer 1`) |
| `CommentBlock.text`, `anchorText` | [redact] / drop / keep |
| `ChangeBlock` deletions | [drop] / redact (deleted text is text the author removed) |
| `SectionBlock(kind="notes")` (speaker notes) | [redact] / drop |
| `ImageBlock.data`, `AudioBlock`, `VideoBlock` | always dropped; dimensions kept |
| `DocMetadata.title` | redact |

### 3. Detectors (deterministic, in the pure core)

v1 detectors are patterns and checksums, all pure AILANG:

- email addresses; phone numbers (E.164 and common national formats); IBAN (mod-97 check);
  payment card numbers (Luhn); national IDs with a validity check (Danish CPR with date check,
  UK NI number, US SSN shape); IP addresses.
- **Known names.** Every author name collected from comments, tracked changes and document
  properties is also searched for in the body text of the same document. This finds the most
  common personal data in office documents (the people who wrote and reviewed them) with no
  model at all.

Model-based name detection (NER) is phase 3 and optional. A local model only: sending the
raw text to it is itself egress, so it goes through a second, separately scoped declassifier
(`toLocalModel`, `! {Declassify[label=doc_content]}`) whose only caller is the detector and
whose `AI` effect is checked to be a local provider. A hosted model is refused unless the policy
names it explicitly, and the report records that it was used.

### 4. Pseudonyms

`Person 1`, `Reviewer 2` are numbered per document in order of first appearance:
deterministic, needs no key, and not linkable across documents. Linking the same person across
an archive needs a keyed hash; the key would be resolved with `std/secret` (labelled
`<secret>`, so it cannot be written out either). That is an open question, not v1.

### 5. Egress: one module with effects

```ailang
-- docparse/redact/egress.ail — the ONLY module in docparse/redact/ with FS/IO effects
export func writeRedactedJson(path: string, body: string{not doc_content}) -> unit ! {FS}
export func writeRedactedMarkdown(path: string, body: string{not doc_content}) -> unit ! {FS}
export func writeReport(path: string, body: string{not doc_content}) -> unit ! {FS}
export func logLine(msg: string{not doc_content}) -> unit ! {IO}
```

### 6. The lint that closes F (stop-gap until AILANG asks 1–2 ship)

`benchmarks/check_redact_confinement.py` (CI) fails if, in `docparse/redact/`:

- any module other than `egress.ail` and `source.ail` declares `FS`, `Net`, `AI`, `IO`,
  `Process` or `Env` in an effect row, or imports a stdlib egress function;
- `source.ail` calls anything other than `parseDocumentPure` and the labelling step, or
  imports a write function;
- any `! {Declassify` appears outside `core.ail`'s `redactResult` and the phase-3
  `toLocalModel`;
- any `egress.ail` export takes a `string` parameter without `{not doc_content}`.

The compiler proves each rule inside the boundary; the lint proves the boundary is where we
say it is.

### 7. Negative tests (the proof)

`benchmarks/check_redact_ifc.sh`: copy the pipeline to a scratch dir, inject each leak, assert `ailang check` fails with an
information-flow or effect error, restore:

1. write a labelled result through `egress.writeRedactedJson` without redacting → IFC error;
2. `logLine` a labelled block's text → IFC error;
3. `writeFile` directly from `core.ail` → effect error;
4. a helper in a new module that returns the labelled text unlabelled without `Declassify`
   → declassification (laundering) error;
5. the clean pipeline → passes (guards against a test that fails for the wrong reason).

If a test ever passes on the leak, the guarantee has stopped holding and CI is red.

### 8. CLI and output

```
docparse --redact [policy.json] FILES|FOLDERS [-r] [--output-dir DIR]
```

- Writes `<name>.json`, `<name>.md` (redacted) and `<name>.redaction.json` per file, in the
  same mirrored layout as `-r`.
- `--redact` refuses `--describe`, `--summarize`, `--pdf-backend ai` and `--convert` in v1
  (all are AI or generator paths outside the pipeline).
- Prints a run summary: files, redactions per category, files refused (format not supported in
  redaction mode).
- The policy file is JSON: per-block choices from the table in §2, detector list, extra
  terms to redact (client names, project code names).

## Claims we may make, and may not

May, once shipped and tested:

- "In redaction mode, the compiler checks that no document content is written, logged or
  sent without passing through the redactor." (backed by §6 and §7)
- "Comment, tracked-change and document authors are always pseudonymised."
- Detection recall and precision **per category**, as measured on the synthetic corpus below.

May not:

- "Removes all personal data", "GDPR compliant", or anything implying the detectors are
  complete. The terms page keeps its current wording for the hosted API.

## Verification

- §7 negative tests in CI.
- `check_redact_confinement.py` in CI.
- **Synthetic PII corpus**, generated by a script with invented people, numbers and
  addresses (never real data; see the fixtures rule): DOCX with body text, tables, comments,
  tracked changes and properties; PPTX with speaker notes; XLSX; EML. Ground truth is known
  per value, so recall and precision per category are computed, written to
  `benchmarks/redaction/results/latest.json`, and the site reads numbers from there.
- Determinism: two runs, byte-identical outputs.
- A no-egress check: run `--redact` on the corpus under a fresh `TMPDIR`, assert the only
  files created are the declared outputs.

## AILANG dependencies (decision 2026-11-17: wait for the fixes)

Ruling: build on AILANG fixes rather than carry our own workarounds. Filed 2026-11-17 to the
AILANG core inbox, each with a stand-alone repro on v0.60.4:

| # | Ask | Message | Replaces |
|---|---|---|---|
| 1 | **Opt-in egress policy**: make stdlib egress (`writeFile`, `httpRequest` bodies, AI prompts, `println`, logging) refuse named labels in a package, e.g. `[ifc] egress_forbid = ["doc_content"]` in `ailang.toml` | `inbox_1794904480678_78279b88` | the effect-row half of the §6 lint (case F) |
| 2 | **Read-only filesystem mode** (`FS[mode=read]`) | `inbox_1794904481642_78d008c2` | the §6 rule that `source.ail` writes nothing |
| 3 | **Labels declared inside an imported type are enforced** (case D) | `inbox_1794904479590_98ebc047` | the "label values, never types" rule; lets `RedactedResult` and the document model carry labels across modules |

Phase 1 can still start before they land (labels on values, one declassifier, the egress
module and the §7 negative tests need none of them). The §6 lint is then the stop-gap,
deleted rule by rule as each fix ships; if a fix slips past phase 2, the lint stays.

## Open questions

1. Cross-document pseudonyms (keyed hash with a `std/secret` key) — v1 or later?
2. Do chunks (`chunker.ail`) run inside the pipeline, after redaction? Proposed: yes, on the
   redacted result, so chunk text is never labelled.
3. PDF via `pdftotext` in phase 2: the subprocess sees the raw file, as the user's own tool
   would. Acceptable for local use; documented.
4. Should `--redact` also be exposed in the browser (WASM) build, where nothing leaves the
   device anyway? Cheap, since the core is pure.

## Phases and effort

| Phase | Scope | Estimate |
|---|---|---|
| 1 | `source`/`core`/`egress` modules with labels; per-block policy with drop/keep only; author pseudonyms; §6 lint; §7 negative tests | 2–3 days |
| 2 | Pattern detectors and known-name search; policy file; CLI `--redact`; report; synthetic corpus and measured recall/precision; PDF via `pdftotext` | 3–4 days |
| 3 | Local-model name detection behind `toLocalModel`; site page with measured numbers; WASM | 3 days |

Phase 1 alone is a demonstrable guarantee: a pipeline where content leaving without passing
the redactor does not compile.
