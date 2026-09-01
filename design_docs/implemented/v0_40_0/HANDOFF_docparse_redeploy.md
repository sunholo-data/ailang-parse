# Handoff to `sunholo/docparse`: redeploy first, then expose `referenceDoc`

**Status**: DONE (2026-09-01) for the two steps this handoff was urgent about,
both in `sunholo/docparse`, both live in prod.

| step | state |
|---|---|
| 1 — redeploy | **done**, docparse v0.21.0. All three environments run AILANG runtime `v0.34.0` and `ailang_parse` 0.39.x (v0.22.0 moved it to 0.39.3), so every parser fix from v0.34–v0.39 now reaches the reporter's upload path — including the style-based numbering work that was the largest silent loss |
| 2 — parser version discoverable | **open**, carved out as [`v0_40_0_parser_version_discoverability.md`](../../planned/v0_40_0/v0_40_0_parser_version_discoverability.md) so it is not buried here |
| 3 — the three parameters | **done**, docparse v0.22.0, verified end-to-end on dev, test and prod |
| 4 — SDKs | **in progress** in this repo |

Step 3 shipped without step 2, inverting the order below. That was a judgement
call at ship time: step 1 had already closed the failure step 2 guards against
(a silently ignored parameter on a build that cannot honour it), so the
ordering constraint no longer bound. Step 2 remains worth doing on its own
merits — it is the reporter's own complaint, not a prerequisite.

One deviation from Step 3 as designed: the parameters are **not** on the MCP
surface. serve-api marks every generated tool parameter required, so adding one
broke every existing `tools/call` immediately; docparse reverted it and pinned
the arity with a test. Filed with AILANG core as `inbox_1788255233818_0805761b`.

The CLI-side reword under "Not in this repo either" is in flight in this repo
(`docparse/services/docx_generator.ail`).

**Originally**: HANDOFF (2026-08-31) — for an agent working in the private
`sunholo/docparse` deployment repo, not in this one.
**Source**: two ailang messages from `aitana-platform`
(`inbox_1788155556743_b0f9d03a`, `inbox_1788155549716_f8030598`).
**Full design**: [`v0_40_0_convert_reference_doc_api.md`](./v0_40_0_convert_reference_doc_api.md).

## Why this is a handoff and not a feature ticket

The requested feature (three parameters on `POST /api/v1/convert`) is second.
The first item is a **stale deployment affecting every caller** — found while
verifying the feature request, not reported by anyone.

The two must not be reordered. Adding `referenceDoc` to the service as it stands
produces a silently-ignored template and unbranded output that reads as a
fidelity bug — strictly worse than the current honest absence.

## Step 1 — redeploy (urgent, independent of any feature)

`GET https://docparse.ailang.sunholo.com/api/v1/health` returns:

```json
{"status":"healthy","version":"0.9.0","service":"docparse",
 "ailang_commit":"v0.33.0","formats_parse":13,"formats_generate":9}
```

`ailang_commit: v0.33.0` is ambiguous between two series (the `ailang_parse`
package and the AILANG runtime both have a v0.33.0). **Both readings are bad**,
which is why the ambiguity does not need resolving before acting:

- as the package: the deployed parser is six minors behind `0.39.2`;
- as the runtime: it is below this package's own declared floor,
  `ailang = ">=0.33.1"` (`ailang.toml:6`).

Target: `ailang_parse` **0.39.2**, AILANG runtime **>= 0.33.1**.

### What the redeploy delivers to callers

| version | change | why it matters to the reporter |
|---|---|---|
| v0.39.0 | style-based numbering (`pStyle` → style → `numPr`) | DOCX files numbering through `List Bullet` / `List Number` styles currently parse as **zero** list blocks — every item a plain text block. Bigger loss than the fragmentation they filed separately |
| v0.39.2 | Unicode bullet glyphs parse as lists | the Word-paste case |
| v0.35.0 | generated HTML no longer lets document text become markup | an untrusted document's `<img src>` produced a working `onerror` handler in generated HTML. **Security-relevant; reason enough on its own** |
| v0.33.1, v0.33.2 | merged-cell table geometry | a merged header padded every data row with phantom columns |
| v0.37.0, v0.38.0 | six `.eml` defects | MIME descent, declared charset, attachment data |
| v0.39.0 | `--reference-doc`, `--reference-section`, `--table-style` | the prerequisite for step 3 |

### The one migration hazard

**v0.35.0 moved three exported symbols.** Update import sites; a version bump
alone will not compile:

| symbol | was | now |
|---|---|---|
| `renderMarkdown` | `services/output_formatter` | `services/markdown_writer` |
| `printSummary` | `services/output_formatter` | `services/console_report` |
| `printBlocks` | `services/output_formatter` | `services/console_report` |

Everything else in `output_formatter` (`formatResult`, `blocksToJson`,
`metadataToJson`, `renderMarkdownMetaJson`, cell/JSON helpers) is unchanged.

Also v0.36.0 reworked MCP tool schemas and `mcpFormats`; if the deploy repo
asserts on those payloads, expect those assertions to move.

## Step 2 — make the parser version discoverable

The reporter could not determine which parser version was serving, and said so
explicitly. Four series are in play — service `0.9.0`, Python SDK `0.12.0`,
package `0.39.2`, runtime `v0.33.0` — and the API exposes the two least useful
for answering "is my fix live?".

Add `ailang_parse_version` to `/api/v1/health` **and** to the
`/api/v1/capabilities` payload. Small change; retires a whole class of support
question.

## Step 3 — the three parameters

Only after steps 1–2. Full semantics, error codes and rationale in
[`v0_40_0_convert_reference_doc_api.md`](./v0_40_0_convert_reference_doc_api.md).
In brief:

| field | type | notes |
|---|---|---|
| `referenceDoc` | string | same three input modes as `filepath` (multipart, `sourceUrl`, `gcsRef`). **DOCX target only** |
| `referenceSection` | int ≥ 1 | 1-based; absent ⇒ last `sectPr`, matching the CLI default |
| `tableStyle` | string | styleId first, then `w:name`. Requires `referenceDoc` |

**No AILANG library change is required.** The endpoint already materialises
`filepath` / `sourceUrl` / `gcsRef` to disk for the parse half; materialise the
template the same way and pass its path to
`docxTplLoad(path, section, tableOverride)`. All three input modes come free,
reusing every existing size cap and fetch path.

New error codes (not a blanket `CONVERSION_FAILED` — a caller must be able to
tell "your template is wrong" from "your document is wrong"):
`REFERENCE_DOC_NOT_APPLICABLE`, `REFERENCE_DOC_NOT_FOUND`,
`INVALID_REFERENCE_DOC`, `INVALID_REFERENCE_SECTION`, `TABLE_STYLE_NOT_FOUND`
(name the available styles — `docxTplTableStyleNames` exists for this),
`TABLE_STYLE_REQUIRES_REFERENCE_DOC`.

Echo `reference_doc_applied: bool` and `template_parts_carried: int` in the
response so a caller can assert templating happened rather than inferring it
from the bytes.

Update the `capabilities` `input_schema` in the same change — it is what the
reporter checked first, and it must not lag the endpoint.

## Step 4 — SDKs

`convert(..., reference_doc=, reference_section=, table_style=)`. **Python
first** — that is what the reporter uses (PyPI `ailang-parse` 0.12.0). Then
JS / Go / R.

## Explicitly do NOT build

`POST /api/v1/generate` on this account. The reporter asked us not to, and the
reason is sound: prompt→document means the parse service calls an LLM, and their
platform already owns model routing, budget accounting and EU residency policy.
They have the model; they need the converter. A dependency that duplicates model
routing is the wrong seam.

## Not in this repo either

One CLI-side change belongs here, not in the deploy repo, and is tracked in the
design doc: when a reference doc carries no template parts, the message
`reference doc applied, 0 template parts carried` is correct but reads as
failure — it cost the reporter a detour. Reword to name the cause. It will reach
API callers too once step 3 lands.

## Deploy topology reminder

Hosted API is the separate private repo `sunholo/docparse`, consuming the
`ailang_parse` registry dependency; multivac cloudbuild deploys three
environments in `europe-west1`. Verify against dev before promoting.

## Definition of done

- ~~`/api/v1/health` reports `ailang_parse_version` 0.39.2 (or later) on all
  three environments.~~ Moved to
  [`v0_40_0_parser_version_discoverability.md`](../../planned/v0_40_0/v0_40_0_parser_version_discoverability.md);
  the redeploy itself is confirmed by `ailang_commit` `v0.34.0` on dev, test
  and prod.
- A DOCX using `List Bullet` / `List Number` styles, posted to `/api/v1/parse`,
  returns list blocks rather than plain text blocks. This is the assertion that
  proves step 1 actually took, and it is the reporter's live complaint.
- `/api/v1/capabilities` convert `input_schema.properties` includes
  `referenceDoc`, `referenceSection`, `tableStyle`.
- A convert with `referenceDoc` returns `template_parts_carried > 0` for a
  template that has a theme.
