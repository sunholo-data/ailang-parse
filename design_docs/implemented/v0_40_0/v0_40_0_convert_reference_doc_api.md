# `--reference-doc` over HTTP: `referenceDoc` / `referenceSection` / `tableStyle` on `POST /api/v1/convert`

**Status**: SHIPPED (2026-09-01) — the endpoint half landed in
`sunholo/docparse` **v0.22.0** and is live in prod. `GET /api/v1/capabilities`
on docparse.ailang.sunholo.com now lists `referenceDoc`, `referenceSection` and
`tableStyle` on convert, all seven error codes named below, and
`reference_doc_applied` / `template_parts_carried` in the output schema.
Verified end-to-end on dev, test and prod with a real templated conversion:
10 template parts carried, the output carrying the template's `theme1.xml`,
`fontTable.xml`, `styles.xml` and its body `<w:sectPr>`. **No AILANG library
change was needed**, exactly as "the transport question" below predicted.
**Residuals**, carved out rather than buried in an implemented doc: step 2 is
now [`v0_40_0_parser_version_discoverability.md`](../../planned/v0_40_0/v0_40_0_parser_version_discoverability.md);
step 4 (SDK pass-through) is code-complete in this repo (Python, JS, Go, R —
see the handoff doc for detail) but not yet published to any registry. One
deviation from the
design: the three parameters are **not** on the MCP surface, because serve-api
marks every generated tool parameter required and adding one broke every
existing `tools/call` — filed with AILANG core as
`inbox_1788255233818_0805761b`.
**Originally**: PLANNED (2026-08-31)
**Source**: ailang message `inbox_1788155556743_b0f9d03a` from `aitana-platform` —
"convert API: expose --reference-doc templating over HTTP".
**Follows**: [`CONTRACT_convert_endpoint.md`](../../planned/v0_32_0/CONTRACT_convert_endpoint.md)
— the contract this extends; and
[`v0_39_0_reference_doc_followups.md`](../v0_39_0/v0_39_0_reference_doc_followups.md),
whose **deferred item 4** ("how a hosted API receives a template — upload? sample
id? gs:// ref? — is a design question, not a parameter") is exactly the question
this doc answers.
**Spans two repos**: the AILANG library change lives here; the endpoint change
lives in the private `sunholo/docparse` deployment repo. See "Handoff".

## The ask, in the requester's own priority order

1. `referenceDoc` on `POST /api/v1/convert`, accepted the same three ways
   `filepath` is (multipart upload, `sourceUrl`, `gcsRef`).
2. `referenceSection` and `tableStyle` alongside it.
3. Python SDK: `convert(..., reference_doc=, reference_section=, table_style=)`.

**Explicitly not asked for, and we should not build it**: `POST /api/v1/generate`.
Their stated reason is sound and worth recording, because it is a good boundary
for this product generally — prompt→document means the parse service calls an
LLM, and their platform already owns model routing, budget accounting and EU
residency policy. They have the model; they need the converter. A dependency
that duplicates model routing is the wrong seam.

## Verified current state

Probed live at `https://docparse.ailang.sunholo.com` on 2026-08-31, and read
against the working tree at `d5ec0bd`.

**Re-probed 2026-09-01 after the docparse v0.22.0 deploy** (an earlier probe
the same day, before the deploy, recorded all four steps as open — superseded
by this):

- **A1, A2 closed.** convert's `input_schema.properties` is now `filepath,
  target, gcsRef, sourceUrl, pdfBackend, referenceDoc, referenceSection,
  tableStyle` on dev, test and prod.
- **A4, A5 closed.** `ailang_commit` is `v0.34.0` on all three environments,
  above this package's `>=0.33.1` floor. docparse v0.21.0 shipped on
  `ailang_parse` 0.39.2; v0.22.0 moved it to 0.39.3.
- **A6, A7 still open.** Neither `/health` nor `capabilities` reports a
  package version, so a caller still cannot tell which parser is serving.
  Tracked separately now — see the status header.
- **A8 closed for the code, open for publishing.** All four SDKs
  (`ailang-parse` PyPI, `@ailang/parse` npm, `ailang-parse-go`,
  `ailangparse` CRAN) gained `reference_doc` / `reference_section` /
  `table_style` and bumped to 0.13.0 in this repo; existing test suites pass.
  Verified live: Python's `convert_file(reference_doc=...)` against prod
  returns `reference_doc_applied: true, template_parts_carried: 7`. None of
  the four registries have been published yet.

| # | Claim | Evidence |
|---|---|---|
| A1 | `/api/v1/convert` is live and its input schema has exactly five properties | `GET /api/v1/capabilities` → convert `input_schema.properties` = `filepath, target, gcsRef, sourceUrl, pdfBackend`; `required: ["target"]` |
| A2 | `referenceDoc` / `referenceSection` / `tableStyle` appear nowhere in the served schema | same payload, grep → 0 hits |
| A3 | The library surface the endpoint would call already exists and is complete | `docparse/main.ail:106-120,209,404-435`; `generateDocxWithReference(doc, path, referenceDoc, referenceSection, tableStyle)` |
| A4 | The deployed build predates the feature | `GET /api/v1/health` → `{"version":"0.9.0","ailang_commit":"v0.33.0"}`. `--reference-doc` shipped in ailang_parse **v0.39.0**. Whatever package version is deployed, it is being run by an AILANG **runtime** older than our own declared floor |
| A5 | Our manifest floor is above the deployed runtime | `ailang.toml:6` → `ailang = ">=0.33.1"`; deployed `ailang_commit` is `v0.33.0` |
| A6 | The API cannot report which parser version is serving | `/api/v1/health` returns a service version and an AILANG runtime commit, but no `ailang_parse` package version. There is no way for a caller to tell whether a given parser fix is live |
| A7 | The requester's confusion about "0.9.0" is a real discoverability defect, not a misreading | Four independent version series are in play, and the API surfaces two of them without labelling either as distinct from the package |
| A8 | Python SDK matches the served schema | PyPI `ailang-parse` latest = **0.12.0**; `convert()` takes target / filepath / sourceUrl / gcsRef / pdfBackend only |

**A4 is the finding that reorders the work.** The ask reads as "add three
parameters", but the deployed service is running a build from before the feature
existed. Adding the parameters to a service that cannot honour them produces a
worse failure than the current one — a silently ignored `referenceDoc` and
unbranded output that looks like a fidelity bug. **Redeploy first, expose second.**

### The four version series (A7), for the reply and for the docs

| series | current | what it is |
|---|---|---|
| hosted service | `0.9.0` | `sunholo/docparse`, the private deployment repo. `/api/v1/health.version` |
| Python SDK | `0.12.0` | PyPI `ailang-parse` |
| AILANG module / registry package | `0.39.2` | `sunholo/ailang_parse`, this repo. **The one that carries parser and generator fixes** |
| AILANG runtime | `v0.33.0` deployed | the compiler running it. `/api/v1/health.ailang_commit` |

They do not track each other and are not meant to. But the API exposes the two
*least* useful of the four for answering "is the fix I need live?", which is why
this cost the requester a detour. Adding `ailang_parse_version` to `/health` and
to the `capabilities` payload is a small change that retires a whole class of
support question — do it in the same pass.

## Design

### The transport question (deferred item 4, answered)

`docxTplLoad(path: string, section: int, tableOverride: string) -> Result[DocxRefDoc, string] ! {FS}`
takes a filesystem path. Three ways to reach it from HTTP:

- **Server-side temp file.** The endpoint already materialises `filepath` /
  `sourceUrl` / `gcsRef` to disk for the parse half. Materialise the template the
  same way and pass its path. Costs nothing new, reuses every existing size cap
  and fetch path, and makes `referenceDoc` accept all three input modes for
  free — exactly what was asked for. **This is the recommendation.**
- **Template parts as bytes.** Refactor `docxTplLoad` into a pure
  `docxTplFromParts(parts) -> DocxRefDoc` plus a thin `! {FS}` loader. More work,
  and unnecessary for the server — but it is the same refactor that unblocks
  **v0_39_0 deferred item 5 (browser/WASM templating)**, where there is no FS at
  all. Worth doing eventually; do not couple it to this ask.
- Sample-id-only templating. Rejected: it would ship a demo, not the feature.
  A customer's letterhead is the whole point.

So: **no library change is required for the HTTP ask.** The endpoint change is
self-contained in `sunholo/docparse`, on top of a redeployed package.

### Parameter semantics (must match the CLI exactly)

| field | type | notes |
|---|---|---|
| `referenceDoc` | string | Same three input modes as `filepath`. **DOCX target only** |
| `referenceSection` | integer ≥ 1 | 1-based, as `--reference-section`. Absent ⇒ last `sectPr`, matching CLI default |
| `tableStyle` | string | styleId first, then `w:name`. **Requires `referenceDoc`** |

Error codes, extending the existing set rather than reusing `CONVERSION_FAILED`
(a caller must be able to distinguish "your template is wrong" from "your
document is wrong"):

- `REFERENCE_DOC_NOT_APPLICABLE` — `referenceDoc` with a non-`docx` target.
- `REFERENCE_DOC_NOT_FOUND` / `INVALID_REFERENCE_DOC` — unreachable, or not a
  readable DOCX package.
- `INVALID_REFERENCE_SECTION` — not an integer ≥ 1, or beyond the template's
  `sectPr` count.
- `TABLE_STYLE_NOT_FOUND` — no matching styleId or `w:name` in the template.
  The response should name the styles that *are* available;
  `docxTplTableStyleNames` (`docx_template.ail:420`) exists for this.
- `--table-style` without `--reference-doc` is a CLI-side validation
  (`main.ail:113`); mirror it as `TABLE_STYLE_REQUIRES_REFERENCE_DOC`.

### The "0 template parts carried" trap

Reported as a detour that cost them real time: a reference doc that is itself a
docparse output reports `reference doc applied, 0 template parts carried`. That
is **correct** — such a file has no theme, headers or fonts to carry — but it
reads as failure. Same wording will reach API callers.

Fix the message rather than the behaviour: when the count is zero, say why —
`reference doc applied, 0 template parts carried (template declares no theme,
headers or fonts)`. Applies to the CLI too, and is a one-line change worth
making here regardless of the endpoint work.

### Response

No shape change. Optionally echo `reference_doc_applied: bool` and
`template_parts_carried: int` so a caller can assert templating actually
happened rather than inferring it from the bytes. Cheap, and it is the
assertion a branded-output pipeline wants in its own tests.

## Handoff to `sunholo/docparse`

The endpoint lives in the private deployment repo (see
[`HANDOFF_docparse_api_convert.md`](../../planned/v0_32_0/HANDOFF_docparse_api_convert.md)
for the precedent). Ordered:

1. **Redeploy on ailang_parse ≥ 0.39.2 and AILANG runtime ≥ 0.33.1** (A4, A5).
   Nothing below can be honoured before this, and this alone delivers every
   parser fix from v0.34–v0.39 to their upload path — including the list
   grouping work in
   [`v0_40_0_list_grouping.md`](../../planned/v0_40_0/v0_40_0_list_grouping.md), which they also
   reported and which affects the same pipeline.
2. Add `ailang_parse_version` to `/api/v1/health` and to the `capabilities`
   payload (A6, A7).
3. Add the three parameters, the error codes, and the capabilities-schema
   entries.
4. SDK pass-through: Python first (that is what they use), then JS/Go/R.

## Priority argument

Their fallback if this does not land is the WASM distribution — which our own
formats endpoint advertises as the self-host path. Their objection to it is the
right one: they already send every document to the hosted parse API, so
generation crosses no new boundary, whereas WASM means a second document
toolchain in their backend image and a second code path that will drift from the
first. Pushing a paying API consumer onto a self-host path to get a feature the
API already computes is an argument against our own product.

Set against that, they are explicit that this is **not blocking**: they ship
untemplated output now and turn templating on when it lands. This gates
fidelity, not delivery. Step 1 of the handoff is the urgent part — it is a stale
deployment affecting every caller, not a feature request.

## Filing note

`design_docs/planned/v0_32_0/` describes `/api/v1/convert` as planned work, but
A1 confirms the endpoint has been live since 2026-08-11. Per the `design_docs`
README convention, the shipped portion belongs in `implemented/`. Flagged, not
moved — the folder also contains genuinely unshipped browser-WASM items, so
splitting it is its own small piece of work. Worth doing in the next
`audit-design-docs` pass.

## Verification log

| Claim | How verified |
|---|---|
| A1, A2 | `curl -s $BASE/api/v1/capabilities` → dumped the full `convert` entry |
| A3 | Read `docparse/main.ail:106-120, 209, 404-435`; `grep reference-doc bin/docparse` |
| A4, A6 | `curl -s $BASE/api/v1/health` → `version 0.9.0`, `ailang_commit v0.33.0`, no package version field |
| A5 | `grep ailang ailang.toml` → `>=0.33.1` |
| A8 | `curl -s https://pypi.org/pypi/ailang-parse/json` → `0.12.0`; requester's own SDK signature check |
