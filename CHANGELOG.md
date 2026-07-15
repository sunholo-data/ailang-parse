# Changelog

All notable changes to AILANG Parse are documented here. This changelog is
derived from [design docs](design_docs/README.md) (the authoritative source
for feature context) and git history.

Format: version headers link to git compare views. SDK versions are tracked
separately — see `sdks/` for per-SDK changelogs.

---

## [Unreleased](https://github.com/sunholo-data/ailang-parse/compare/v0.22.0...HEAD)

### SDKs — v0.8.0 (retry parity across JS, Go, R)

The server now returns `502`/`503`/`504` for transient AI-provider failures
(and marks safe-to-retry `5xx` with `X-AilangParse-Replayable`). The **Python**
SDK already retried these via `RetryPolicy`; this brings the **JS, Go, and R**
SDKs to parity. Retry stays **off by default** (opt in per SDK):

- **JS:** `new DocParse({ retry: { maxRetries: 3 } })` — `RetryPolicy` with
  `retryableStatuses`, `respectReplayable`, `backoffBaseMs`/`backoffMaxMs`.
- **Go:** `docparse.New(key, docparse.WithRetry(docparse.RetryPolicy{MaxRetries: 3}))`.
  Replayable 5xx are always honoured when retries are enabled (a Go bool field
  could not distinguish unset from false).
- **R:** `DocParse$new(retry = list(max_retries = 3))`, built on `httr2::req_retry()`.

`parse` / `parseFile` re-issue the request (rebuilding the body) on each retry
with exponential backoff. All four SDKs bumped to 0.8.0 (`server.json` too).

---

## [v0.22.0](https://github.com/sunholo-data/ailang-parse/compare/v0.21.0...v0.22.0) — 2026-07-15

### Fixed — `--describe` fetches linked images and reads the picture

Two field-reported gaps in `--describe`
([design doc](design_docs/implemented/v0_22_0/v0_22_0_describe_image_fetch_and_prompts.md)):

- **HTML external images are no longer a silent no-op.** The HTML path never ran
  the describe pass, and the describe filter only accepted embedded base64
  anyway — so `<img src="assets/x.png">` produced an empty description,
  `aiCallsUsed: 0`, and no warning. Now `describeImages` resolves each image
  source: local file references are **read from disk relative to the document's
  directory**, `data:` URIs are decoded, and remote URLs / unreadable files
  produce a **warning** (surfaced on the terminal and in the JSON `warnings`
  array) instead of a silent empty. `aiCallsUsed` now reflects the **real**
  number of describe calls. Describe is fail-soft per image — one corrupt/rejected
  image warns rather than aborting the parse.
- **Direct images now describe the picture, not just OCR the axes.** Passing a
  chart/graph image ran a document-OCR prompt that returned axis labels and tick
  values but never a reading of the plotted curve (the descriptive prompt was an
  unreachable fallback, since any chart has *some* text). The direct-image prompt
  now leads with a visual reading — chart type, axes + units, and the trend/shape
  of the data — then extracts the literal text. The shared describe prompt
  (Office/HTML/EPUB/ODF) was retuned the same way.

Image describe requests now go through a proper multimodal request instead of
base64 interpolated into a text prompt. Verified end-to-end across HTML, direct
images, DOCX, PPTX, ODT/ODF, and **LaTeX/arXiv** — `\includegraphics` figures are
now described, resolved against the `.tex` directory (the extraction dir for arXiv
`.tar.gz` bundles); PDF/EPS or missing figures degrade to warnings.

Also fixes a **pre-existing DOCX image-extraction bug** surfaced while verifying
describe coverage: `readEmbeddedImage` double-prepended `word/media/`, so every
DOCX embedded image had empty `data` (describe had nothing to work with), and the
`word/media/` directory entry was emitted as a phantom `octet-stream` image. Both
fixed in `zip_extract.ail`; the `pandoc_inline_images.docx` golden is corrected
from `images: 3` to `images: 2`. Structural benchmark stays at 100% across 58 files.

---

## [v0.21.0](https://github.com/sunholo-data/ailang-parse/compare/v0.20.3...v0.21.0) — 2026-07-14

### Added — OMML equation extraction (DOCX + PPTX, §22.1)

Office Math (OMML) equations were silently dropped by every parser: the DOCX
and PPTX walkers read only `w:t` / `a:t` text runs, so `m:oMath` / `m:oMathPara`
subtrees — fractions, superscripts, subscripts — produced empty output. In
answer keys and scientific documents, the equations *are* the payload, so a
worked example like `U = 168 W / 1,40 A` came out as ambiguous flattened text.

- New shared module `docparse/services/omml` renders the math tree as
  machine-usable linear math: `m:f` → `(num)/(den)`, `m:sSup` → `base^(sup)`,
  `m:sSub` → `base_(sub)`, `m:sSubSup`, `m:rad` → `√(e)`, `m:d` → `(e)`.
  Structural children (`m:num`/`m:den`/`m:e`/`m:sup`/`m:sub`) resolve via
  direct-child lookup, so nested equations render correctly.
- Wired into `docx_parser` (`childNodeText`, which also covers table cells) and
  `pptx_parser` (`drawingMLNodeText`) — one renderer, no duplication.
- The equations challenge file + gap check were strengthened to exercise real
  `m:f` fractions and `m:sSub` subscripts (the old fixture used pre-flattened
  text and would pass a broken parser).
- Gap analysis (equations) `0% → 100%` (4/4); office structural benchmark stays
  at **100%** across 58 files; OfficeDocBench composite `92.5% → 92.6%`.

---

## [v0.20.3](https://github.com/sunholo-data/ailang-parse/compare/v0.20.2...v0.20.3) — 2026-06-04

### Fixed — lenient XML parsing (bare `&` in Office files)

Requires **AILANG ≥ 0.24.0** (`std/xml.parseLenient` / `sanitizeXml` landed
there via M-STDLIB-XML-LENIENT; `ailang.toml` bumped accordingly). Office files
produced by non-reference tools sometimes contain an unescaped `&` (a company
name like `Apex Consulting & Partners`, an `R&D` line item, a URL query string).
Go's strict `encoding/xml` — which `std/xml.parse` wraps — aborts the whole
document with `invalid character entity & (no semicolon)`, so the parse returned
a single error block with zero recovered content. Surfaced by a real ODT invoice
submitted via the API/SDK.

- All eight XML-backed parsers (`docx`, `pptx`, `xlsx`, `odt`, `odp`, `ods`,
  `epub`, `docparse_browser`) now call `parseLenient` instead of `parse`.
- `xlsx`'s streaming `parseFold` over `<row>` elements runs `sanitizeXml` on the
  sheet XML first (no lenient fold variant exists).
- `html_parser` is unchanged — it already uses the tolerant `std/html.parse`.
- `sanitizeXml` only escapes a bare `&` that does not begin a valid entity
  (`&amp;`, `&#123;`, `&lt;` pass through; idempotent), so well-formed files are
  byte-identical — the office structural benchmark stays at 100% across 58 files.
- The API Docker image now pins AILANG to the `v0.24.0` release (was tracking
  `dev`) for deterministic builds.

Known gap (deferred to AILANG v2 of the feature): stray `<` and unknown named
entities like `&nbsp;` are still rejected by strict decode.

---

## [v0.20.2](https://github.com/sunholo-data/ailang-parse/compare/v0.20.1...v0.20.2) — 2026-05-29

### Added — AI extraction-path resilience (completes the v0.20.1 work)

Requires **AILANG ≥ 0.23.0** (`callJsonSimpleResult` landed there; `ailang.toml`
bumped accordingly). v0.20.1 hardened only the PDF page-count probe; the
page/image *extraction* calls still used `callJsonSimple` (no Result variant),
so a terminal Gemini failure during extraction escaped as a bare HTTP 500.

- `parsePdfOnePage` now shares its request builder (`pdfPageRequest`) with a new
  Result twin `parsePdfOnePageResult`, which uses `std/ai.callJsonSimpleResult`
  with bounded exponential-backoff retry (`aiCallJsonSimpleWithRetry`).
- `parsePdfResult` now drives the extraction through Result twins
  (`aiExtractWithRetryResult` / `parsePdfAllPagesResult`), so a terminal AI
  failure *anywhere* in the pipeline returns `Err(AIError)` → HTTP 502/503.
- The CLI/browser path (`parsePdf`) is unchanged and stays free of the `Clock`
  effect (it keeps the non-Result twins).

### Fixed (upstream, AILANG v0.23.0) — needs deploy + a skill tweak

- The MCP omitted-param crash (`_str_len` on `Unit`) is fixed in the AILANG
  dispatcher: omitted/null declared params are now rejected with a structured
  "missing required parameter(s)" error. **Takes effect once the hosted docparse
  MCP is deployed on v0.23.0.** Note: an *omitted* `apiKey` now returns that
  generic error, not the friendly `AUTH_REQUIRED` — so the skill must pass
  `apiKey=""` (empty string) when unauthenticated to keep the first-run auth
  flow. (Resolves the long-standing first-run crash; see ailang#258.)

---

## [v0.20.1](https://github.com/sunholo-data/ailang-parse/compare/v0.20.0...v0.20.1) — 2026-05-28

### Added — AI-provider resilience for the hosted parse API

The passthrough service (`/api/v1/parse`) can now absorb transient Gemini
failures and surface typed errors instead of bare 500s — motivated by a
2026-05-27 production incident where the PDF page-count probe failed.

- **`aiCallWithRetry`** — wraps `callResult` with bounded exponential backoff
  (2 retries, 250ms→500ms) on `AIError.retryable`; non-retryable errors return
  immediately. Adds the `Clock` effect.
- **`aiGetPageCountResult`** — Result-returning page-count probe (the call that
  failed in the prod incident).
- **`parsePdfResult`** — `Result[[Block], AIError]` twin of `parsePdf`, used by
  the hosted API to map terminal AI failures to HTTP 502/503. `parsePdf` is
  unchanged, so the CLI / browser / SDK keep their effect signature (no `Clock`
  ripple). Extraction-path coverage is blocked on upstream `callJsonSimpleResult`.

### Fixed

- **`ailang lock`:** dropped a self-dependency (the package listed
  `sunholo/ailang_parse` as its own dependency), which failed with a circular
  dependency error.
- **Claude Code install docs:** the documented command was `claude install
  github:…`, which fails with `Invalid channel` (that command is the CLI
  channel updater, not a plugin installer). Corrected across all pages to the
  real `/plugin marketplace add …` + `/plugin install …@…` flow, and fixed the
  plugin marketplace/manifest so the skill actually installs and registers its
  MCP server ([#1](https://github.com/sunholo-data/ailang-parse/issues/1)).
  Clarified that the skill is cloud-API only — local processing uses the
  `docparse` CLI ([#4](https://github.com/sunholo-data/ailang-parse/issues/4)).

### Added — documentation guards (CI)

- **`check-install-docs.py`** — bans broken install incantations and
  cross-checks the documented command against the live plugin marketplace.
- **`check-doc-examples.py`** — enforces that transcluded (`data-src`) code
  examples resolve to real files, that inline fallbacks byte-match those files,
  and that every example file is syntax-checked (bash / python / node / gofmt /
  json).

---

## [v0.20.0](https://github.com/sunholo-data/ailang-parse/compare/v0.19.0...v0.20.0) — 2026-05-18

### Added — RTF (Rich Text Format) parser

Closes the gap for legacy document workflows. RTF was specified by
Microsoft in 1987 and remains the default "Save As" target for forms,
templates, government documents (Danish Købsaftale, French CERFA),
TextEdit/Pages exports, and many ERP report exports. Until now AILANG
Parse would reject `.rtf` files and recommend a LibreOffice subprocess.

- **`docparse/services/rtf_parser.ail`** — pure AILANG, no external
  dependencies. Char-by-char state machine via `std/string.foldChars`.
- **Encoding support:** `\uNNNN?` Unicode escapes (UTF-8 reassembly via
  `std/bytes.fromInts` + `toString`), `\'XX` CP1252 hex escapes with full
  Windows-1252 translation table for 0x80–0x9F, literal `\\` / `\{` / `\}`.
- **Destination skipping:** `\fonttbl`, `\colortbl`, `\stylesheet`,
  `\info`, `\listtable`, `\themedata`, `\panose`, `\pict`, fields, and all
  starred destinations (`{\*\foo …}`) — including correct handling of
  nested skips (outer skipDepth is preserved when an inner `\*\panose`
  group closes).
- **Routing:** `\par` → paragraph break, `\cell` / `\tab` → tab,
  `\row` → paragraph break.
- **WASM:** browser demo and workbench accept `.rtf`; the same parser
  runs in-browser via the existing AILANG WASM REPL.
- **Sample asset:** `docs/assets/sample_rtf.rtf` exercises Danish,
  French, German, Greek, currency symbols (£/€/¥/©), smart quotes,
  em/en dashes, and form fields.

#### Not handled in v0.20

- Style-based heading detection (`\s1`, `\s2` — needs stylesheet parse)
- Table grid topology (cells/rows currently flattened to TAB-separated
  paragraphs; proper `TableBlock` emission is on the roadmap)
- Embedded images (`\pict` — hex-encoded pixel data, separate decoder)
- Field results (`\fldrslt` — currently skipped along with `\fldinst`)



### SDKs — v0.7.1 (Python only)

Patch release. Source: multivac field finding (`msg_20260516_013726_3d7763f3`)
after wiring `/pubsub_to_store` on Cloud Run.

#### Fixed
- **`parse_gs_uri` now works on Cloud Run / GCE / GKE.** v0.6.0 always
  attempted local v4 signing, which fails on the metadata-server default
  service account (token-only credentials, no private key) and on
  end-user `gcloud auth application-default login` credentials. v0.7.1
  detects token-only credentials and routes them through Google's IAM
  `SignBlob` API instead — the "just works" path on any GCP runtime
  without an SA JSON file.

  **Runtime requirement (one-time IAM grant):** the runtime service
  account needs `roles/iam.serviceAccountTokenCreator` on **itself**.
  Documented in the Python README.

  **New optional argument**: `parse_gs_uri(..., service_account_email=...)`
  overrides the auto-detected SA email (useful for impersonation).

  **Cross-SDK note:** `parse_gs_uri` is Python-only; JS/Go/R never had
  this method. When they pick it up in a future release, they will
  adopt the same auto-detection strategy.

---

### SDKs — v0.7.0 (Python)

Implements [design_docs/planned/v0_20_0/v0_20_0_sdk_v07_extras_images_comments_tablecells.md](design_docs/planned/v0_20_0/v0_20_0_sdk_v07_extras_images_comments_tablecells.md).
Source: multivac end-to-end field-test feedback (msg `msg_20260516_012720_2ed63396`)
and migration ack (msg `msg_20260515_183500_d9476a0d`). Python-only;
JS+Go versions bumped to 0.7.0 for sync but ship no new features.

#### Added
- **`ChunkMetadata.extras: Dict[str, Any]`** — consumer-defined fields
  for `flatten()` chunks (per-tenant tags, confidence scores, etc.).
  Omitted from `to_dict()` when empty.
- **`FlattenPolicy(embed_comments=True)`** — emit a chunk for each
  `CommentBlock` with `change_author`, `extras["resolved"]`,
  `extras["date"]`. Forward-compatible: the parser-side `CommentBlock`
  variant lands separately (see [v0.19.0 comment-threading doc](design_docs/planned/v0_19_0/v0_19_0_comment_threading.md));
  the SDK knob is a no-op until then.
- **`FlattenPolicy(on_table_cell_newlines=..., on_table_cell_pipes=...)`** —
  `"preserve"` (default) | `"escape"` (`\n` → `\\n`, `|` → `\\|`,
  round-trippable) | `"space"` (collapse to ` `, retrieval-friendly).
  Invalid values raise `ValueError` at construction.
- **`Block.resolved: bool`** — new field on the dataclass, populated
  from JSON `resolved` when present. Forward-compat for comment
  threading.

#### Changed (behaviour change)
- **`FlattenPolicy(embed_images=True)` now always emits an `ImageBlock` chunk**,
  even when `description` and `transcription` are empty. The chunk
  text falls back to a machine-readable placeholder
  (`"[image: <mime>, <bytes> bytes]"`). New `extras["image_has_description"]`
  boolean lets consumers distinguish AI-captioned from placeholder
  chunks. v0.6.0 silently dropped empty-description images on free-tier
  parses; this change makes images visible to consumers regardless of
  AI availability. Filter recipe for v0.6.0 behaviour is in the README.

#### Cross-SDK parity
Python ships everything. JS + Go bump to 0.7.0 for version sync; they
will pick up the v0.6.0 `flatten`/`parse_gs_uri`/`RetryPolicy` features
and the v0.7.0 additions together in a future sprint.

---

### SDKs — v0.6.0 (Python, JS), Go (unreleased tag)

Implements [design_docs/planned/v0_20_0/v0_20_0_sdk_ergonomics.md](design_docs/planned/v0_20_0/v0_20_0_sdk_ergonomics.md).
Source: SDK feedback from `multivac-system-services` after refactoring its
chunker onto the Python SDK (msg `msg_20260515_173649_4dbe12bd`).

#### Added
- **`request_id`, `replayable`, `details`, `suggested_fix` on all errors** —
  Python `DocParseError`/`AuthError`/`QuotaError`, JS equivalents, Go
  `*DocParseError`. Populated automatically from response headers + body
  on every non-2xx response (no more dropping `X-Request-Id` on errors).
- **Python `RetryPolicy`** — opt-in retry on the `DocParse` constructor.
  `respect_replayable=True` retries 5xx responses tagged with
  `X-AilangParse-Replayable: true`. Default policy does not retry.
- **Python `parse_gs_uri(gs_uri, *, ttl=900)`** — sign a `gs://` URI and
  parse in one call. Behind the new optional `[gcs]` extra
  (`pip install 'ailang-parse[gcs]'`).
- **Python `ParseResult.flatten(policy)`** — Block ADT → RAG-ready
  `List[Chunk]`. Composable `FlattenPolicy` (`max_chunk_chars`,
  `embed_images`, `embed_changes`, `on_table` row|whole|callable,
  `section_path`).
- **Python `[s3]` extra placeholder** in `pyproject.toml` — `parse_s3_uri`
  ships in a later release.

#### Changed (breaking — minor)
- **Default HTTP timeout bumped 60s → 120s** in Python, JS, Go SDKs.
  Rationale: AI-backed formats (PDF, images) routinely exceed 60s on
  large documents. Code that relied on a 60s upper bound needs to set
  `timeout=60` explicitly.
- **Python `AuthError`/`QuotaError` accept the same kwargs as
  `DocParseError`** (`request_id=`, `suggested_fix=`, `details=`,
  `replayable=`). The legacy positional `AuthError(msg, 401)` form
  still works.

#### Cross-SDK parity
Python v0.6.0 ships all of the above. JS v0.6.0 ships error metadata +
120s default. Go ships the same on the next tag. JS + Go `parse_gs_uri`,
`flatten`, `RetryPolicy` track in a follow-up release.

---

## [0.19.0](https://github.com/sunholo-data/ailang-parse/compare/v0.18.3...v0.19.0) — 2026-05-15

Pluggable PDF parsing backends. The PDF path now dispatches to one of three
engines selected by `--pdf-backend`: the existing AI multimodal pipeline
(default), IBM Docling (deterministic local layout analysis), or run-llama
LiteParse (fastest plain-text extraction). Both new backends are 4–130× faster
than the AI path on real arxiv papers while matching structural quality.

Internally, the dispatch lives in a new AILANG module that delegates to a
Python subprocess via `std/process.exec`, with the subprocess protocol
extracted into a new reusable package `sunholo/external_backend@0.1.0`.

### Added
- **`--pdf-backend ai|docling|liteparse` flag** on the CLI. Default `ai`
  (no behavior change for existing callers). `docling` and `liteparse` are
  opt-in alternatives; selecting either swaps the `AI` capability for
  `Process` so no API key or network round-trip is needed.
- **`docparse/services/pdf_backend_external.ail`** — AILANG module owning
  the external-backend dispatch path. Pure core (`decodeBlock`,
  `decodeBlocks` with a count-preservation contract, `decodeMetadata`,
  `decodeAdapterDoc`) plus a thin effectful outer (`parsePdfViaBackend`
  with `! {IO, Process}`).
- **`docparse/services/pdf_backends/adapter.py`** — Python adapter that
  speaks the JSON protocol expected by the AILANG side. Currently supports
  Docling and LiteParse; new backends are a small addition.
- **`pkg/sunholo/external_backend` dependency** at 0.1.0 — extracted from
  the local implementation. Generic enough to wrap any subprocess-emits-JSON
  helper (OCR engines, embedders, classifiers, …) with typed `BackendError`
  variants (`ExecFailed`, `NonZeroExit`, `InvalidJson`) carrying exit codes
  and stderr.
- **`benchmarks/pdf/compare_backends.py`** — head-to-head harness for PDF
  backends scored against the existing golden files.
- **`benchmarks/pdf/test_pdf_backends.sh`** — integration test that
  exercises all three backends end-to-end through the CLI.

### Changed
- **`parsePdfDocument` in `docparse/main.ail`** routes on the
  `DOCPARSE_PDF_BACKEND` env var. Two helper functions (`extractPdfAI`,
  `extractPdfExternal`) keep both branches as one-line dispatches and
  preserve the existing output pipeline (printing, JSON/MD writeout).
- **`bin/docparse`** parses `--pdf-backend`, conditionally adds `Process`
  to caps (and skips `AI` for the non-AI backends), and threads
  `DOCPARSE_PDF_BACKEND` + `DOCPARSE_PROJECT_ROOT` into the AILANG
  invocation. `--help` documents the new flag.
- **`ailang.toml`** declares `sunholo/external_backend = 0.1.0` and adds
  `Process` to `[effects].max`.

### Removed
- **`ensures` clauses on 13 functions** across `format_router`,
  `zip_extract`, `docx_parser`, `odt_parser`, `odp_parser`. The v0.19.2
  AILANG property-test generator emits invalid `_test.ail` scaffolding for
  most signature shapes that use `ensures` (see
  [ailang-core #236](https://github.com/sunholo-data/ailang/issues/236)).
  Each stripped contract is replaced with a comment documenting the
  invariant, and the inline `tests [...]` blocks still verify the cases
  end-to-end. Restore in a single sweep once #236 is fixed upstream.

### Performance (Hinton distillation arxiv PDF, 108 KB)

| Backend | Time | Headings detected | Notes |
|---|---|---|---|
| `ai` (Gemini 2.5 Flash, default) | 127s | 21 | unchanged |
| `docling` | 28s | 20 | 4.5× faster, local, structural quality on par with AI |
| `liteparse` | 1.0s | n/a (font-size heuristic) | 130× faster, highest char count of any backend |

### SDKs

No SDK changes in this release. The `--pdf-backend` flag is CLI-only;
the hosted API (`/api/v1/parse`) does not currently expose backend
selection. Python and JS SDKs remain at 0.5.4.

---

## [0.18.3](https://github.com/sunholo-data/ailang-parse/compare/v0.18.2...v0.18.3) — 2026-05-14

Adopt new `std/xml` APIs shipped in AILANG v0.19.2-dev
(`nodeKind`, `getAttrMap`) and add a 1.7 MB real-world stress fixture
to the corpus. Pure perf patch — goldens byte-identical.

### Changed
- **`htmlProcessNode` text-node branch uses `nodeKind`** instead of
  `length(tag) == 0`. Same semantics, cleaner code, exhaustive pattern
  match against `KindText | KindElement | KindComment`.
- **`htmlParseImg` uses `getAttrMap`** to extract all 7 image
  attributes (src, alt, width, height, srcset, title, loading) in
  one FFI call + 7 in-memory hash lookups, instead of 7 separate
  `getAttr` FFI crossings. For image-heavy pages this trades 7N
  FFI calls for N + 7N hash lookups.

### Added
- **Stress fixture**: `data/test_files/stress/mollie-create-payment.html`
  — 1.7 MB Mollie API documentation page with 143 `<code>` blocks of
  embedded JSON. Exposes memory-pressure paths that the day-to-day
  sample doesn't (large text inside deeply-nested `<code>`/`<pre>`).
  Golden output checked in at `benchmarks/office/stress/`.
- **Bumped `ailang = ">=0.19.2"`** in ailang.toml — `nodeKind` and
  `getAttrMap` are v0.19.2 APIs.

### Tried and reverted
- **`foldChildren` for `htmlProcessChildren`** regressed Mollie alloc
  from 229 MB → 395 MB. Root cause: replacing `flatMap(htmlProcessNode,
  getChildren(node))` with an AILANG-side `foldChildren` accumulator
  + final `reverse` overshoots flatMap's Go-iterative builtin which
  amortises append in O(1). Reverted. Sent feedback upstream
  (msg_20260514_104913_f639ad74).

### M4 hotfix from AILANG: `flatMapChildren` lands

In response to the regression report, the AILANG team shipped
`std/xml.flatMapChildren` (M-STDLIB-XML-WALK-PERF M4, AILANG commit
`c77094fd`) — a Go-iterative primitive that mirrors `flatMap`'s
pattern but reads children directly from the parsed node, skipping
the `[XmlNode]` materialisation that `getChildren` would pay. We
adopted it on the 11 tree-walking callsites:

```ailang
-- Before:
htmlProcessChildren(getChildren(node))

-- After:
htmlProcessChildrenOf(node)  -- backed by flatMapChildren
```

(Two callsites kept on the old path because they already have a
filtered `[XmlNode]` to consume — the `<picture>` source-filter
and `htmlFindBody`.)

### Measured (Mollie 1.7 MB, AILANG_NO_TRACE=1)

| Pipeline | alloc_space | Wall (warm) |
|---|---|---|
| v0.18.2 baseline | 229 MB | ~0.77s |
| v0.18.3 with `foldChildren` (reverted) | 395 MB | ~0.77s |
| v0.18.3 with `nodeKind` + `getAttrMap` only | 215 MB | ~0.71s |
| **v0.18.3 with M4 `flatMapChildren`** | **193 MB** | **~0.64s** |

Versus the v0.18.2 baseline: **−36 MB (−16%), −0.13s (−17%)**. The
synthetic 39× / 180× numbers from the AILANG bench don't fully
reproduce on Mollie because real cost is also paid in
`htmlDeepText`/`htmlInlineWrap` string interpolation and per-block
JSON serialisation — both unaffected by this primitive. So the
ceiling for this single API change is what we got.

### Upstream proposals sent
- `msg_20260514_100821_cd45490b` — original 6-feature perf proposal
- `msg_20260514_102155_4aab028e` — pprof follow-up (trace = 5× memory)
- `msg_20260514_104913_f639ad74` — `foldChildren` regression analysis

---

## [0.18.2](https://github.com/sunholo-data/ailang-parse/compare/v0.18.1...v0.18.2) — 2026-05-14

Second pure-perf patch. Profile-driven dispatch reordering and a
text-node fast path. Goldens byte-identical (no semantic change).

### Profile findings (sunholo.com, 79 KB, 1,900-node tree)

Captured via `ailang run --emit-trace jsonl` and analysed with `jq`.
Top function-call counts:

| Function | Calls | Cost source |
|---|---|---|
| `std/string.length` | 2,056 | length checks in fast paths |
| `std/xml.getChildren` | 1,918 | FFI per node |
| `std/xml.getTag` | 1,869 | FFI per node |
| `std/list.length` | 1,803 | child-count checks |
| `concat` | 1,735 | list ops |
| `std/string.trim` | 1,715 | text cleaning |
| `htmlDeepText` | 1,714 | recursion |
| `std/xml.getText` | 1,404 | FFI |
| closures (`f`) | 1,037 | lambda overhead |

### Fixes

1. **Text-node fast path in `htmlProcessNode`**. Text nodes have empty
   tag (`""`) and account for ~half of all flatMap invocations during
   a parse. Pre-v0.18.2 they walked the full 30+ branch dispatch and
   fell through to the bottom default. Now they're handled at the top
   of the function via a `length(tag) == 0` check that goes straight
   to `getText → TextBlock`.

2. **`htmlIsBlockTag` reordered by observed frequency** (sample from
   sunholo.com: 132 `<div>`, 40 `<p>`, 37 `<li>`, 24 `<h3>`, …).
   Chained `||` short-circuits on first match, so high-frequency tags
   now match earlier.

### Measured impact

Function-call profile (sunholo.com, same input):

| Metric | v0.18.1 | v0.18.2 | Δ |
|---|---|---|---|
| `htmlDeepText` calls | 1,714 | 1,180 | **−31%** |
| `std/xml.getChildren` calls | 1,918 | 1,384 | **−28%** |
| `std/list.length` calls | 1,803 | 1,269 | **−30%** |
| Total function calls | 21,651 | 20,910 | **−3.4%** |

Wall-clock:

| Phase | v0.18.1 | v0.18.2 |
|---|---|---|
| Cold | 1.07s | **0.81s** (−24%) |
| Warm (median of 4) | 0.62s | **0.59s** (−5%) |

### Upstream proposal

Profile data + 6 ranked AILANG/stdlib feature proposals sent to ailang-core (msg_20260514_100821_cd45490b). Top requests: `std/xml.foldChildren` (eliminates per-node `getChildren` FFI), `std/xml.getAttrMap` (batched attribute access), tail-call optimization, `@inline` hints for small pure functions. Local fixes here are bounded by what's possible without those language/stdlib additions.

### Goldens

Byte-identical to v0.18.1 for all 7 HTML and 2 EML goldens. This is a
pure dispatch-order optimization with no semantic change.

---

## [0.18.1](https://github.com/sunholo-data/ailang-parse/compare/v0.18.0...v0.18.1) — 2026-05-14

Pure-perf patch for the HTML parsing pipeline. No semantic change —
JSON output for non-HTML formats is byte-identical to v0.18.0. The HTML
goldens that differ in this commit are the result of stale v0.17/v0.18
features (page title extraction, table caption capture) that hadn't been
baked into all the goldens because the eval is structure-sensitive,
not byte-sensitive.

### Performance fixes

1. **Single-pass HTML parse** in [docparse/main.ail](docparse/main.ail).
   v0.17.0 added `parseHtmlMetadata(content)` to extract `<title>` /
   `<meta>` into `DocMetadata`. main.ail was calling both `parseHtml(content)`
   AND `parseHtmlMetadata(content)` for the same input — two full
   walks through std/html. New `parseHtmlDoc(content)` returns
   `{blocks, metadata}` from a single `parse()` call. For an 80 KB
   sunholo.com page this halves the std/html invocation cost.

2. **`htmlCollapseNewlines` fast-path**. Called by every `htmlDeepText`
   invocation (including on short fragments that contain no triple-newline).
   The new `find(s, "\n\n\n") < 0` short-circuit returns immediately
   without allocating a `replace` result or running an O(n) comparison
   at the bottom of the recursion. The recursion still handles
   pathological pages with deeply-stacked block breaks.

3. **`imageJsonFields` single-concat**. v0.16.0 emitted optional HTML5
   image attrs (width/height/srcset/title/loading) via five sequential
   `concat` calls — each chained on the previous result, allocating
   five intermediate lists per image. Refactored to build an
   `imageOptionalFields` list once and `concat` it onto the base once.
   For image-heavy pages this drops 4 list allocations per image.

### Stale goldens cleaned up

Four HTML goldens (`test.html`, `ailang_guide.html`, `pandoc_nordics.html`,
`pandoc_planets.html`) refreshed to capture the v0.17 page title and
v0.18 table caption that the parser was already producing but the eval
hadn't been flagging because semantic equivalence beats byte equality.
No code change for these; they're just up to date now.

### Real-world measurements (sunholo.com, 79 KB)

Three warm runs, before vs after:

| Run | v0.18.0 | v0.18.1 |
|---|---|---|
| Cold | 1.17s | 0.96s |
| Warm 1 | 0.73s | 0.63s |
| Warm 2 | 0.62s | 0.70s |

Modest warm savings (~50–100 ms). The bigger structural win is memory:
one less full XmlNode tree allocation per HTML parse. For batch parsing
of many HTML files (email archives, scraped page corpora), that's a
meaningful reduction in peak memory.

### What we considered and didn't do

- **Streaming HTML5 parser** — would require an upstream `std/html`
  feature (chunked/streaming parse). Today std/html returns the whole
  tree in one allocation. Filed for future consideration but out of
  scope for ailang-parse.
- **`parseFold` / `parseElements`** (the XLSX/streaming patterns) —
  don't apply to HTML's heterogeneous nested structure. They work for
  XLSX because sheets have repeated `<row>` elements at a fixed level
  that fold cleanly.
- **`mapSlicesJoin` / `foldSlices`** — these are string-scanning
  optimizations from `std/string`. The hot loops in HTML extraction
  are tree walks, not string scans. They apply to the (deleted-in-v0.14.0)
  in-repo sanitizer but not to the post-std/html pipeline.

---

## [0.18.0](https://github.com/sunholo-data/ailang-parse/compare/v0.17.0...v0.18.0) — 2026-05-14

Tables now carry their captions, header cells carry their accessibility
scope, and a couple of long-tail semantic blocks (`<figure>`/`<figcaption>`,
`<address>`) get proper paired output.

### Changed
- **`TableBlock` extended** with an optional `caption: string` field.
  Populated by the HTML parser from `<caption>` elements (any depth
  under `<table>`); empty for tables emitted by other parsers
  (DOCX/PPTX/ODT/ODS/CSV/Markdown/TeX/XLSX/AI).
- **`TableCell` extended** with an optional `scope: string` field
  matching HTML5's accessibility model (`"row"` | `"col"` | `"rowgroup"` |
  `"colgroup"`). Populated by HTML parser from `<th scope=…>`; empty
  for `<td>` and for cells emitted by other parsers.

### Added
- **`mkTable(rows, headers)`** in [docparse/types/document.ail](docparse/types/document.ail)
  constructs a TableBlock with an empty caption — one-line swap for
  every non-HTML parser. 17 constructor sites migrated.
- **`mkTableFull(rows, headers, caption)`** for HTML parser when
  `<caption>` is present.
- **`scopedCell(text, scope)`** for explicit scoped header cells
  (HTML parser uses it via direct record literal because cell scope
  is per-cell, not per-table).
- **HTML parser captures `<caption>`** — `htmlParseTable` extracts the
  first `<caption>` descendant and passes its trimmed deep text into
  `mkTableFull`. pandoc_planets.html test file now exposes its
  `"Data about the planets of our solar system."` caption that was
  previously dropped entirely.
- **HTML parser captures `<th scope=…>`** — `htmlParseTableCell` reads
  the scope attribute only when the cell tag is `<th>`, so `<td>`
  cells stay scope-less.
- **`<figure>`/`<figcaption>` pairing** — `<figure>` now emits a
  `SectionBlock(kind: "figure")` containing the inner image plus a
  `TextBlock(style: "caption")` for the figcaption text. Previously
  the figure was flattened and the caption floated free.
- **`<address>` block** — emits its own `SectionBlock(kind: "address")`
  for contact info / authorship blocks. Falls back to a
  `TextBlock(style: "address")` when the content is plain text only.

### JSON output
- `TableBlock`'s `caption` is **emitted only when non-empty**, so
  non-HTML tables produce byte-identical JSON to v0.17.0.
- `TableCell`'s `scope` is **emitted only when non-empty**. The
  compact "string-only" cell shortcut (used when colSpan=1 and merged=false)
  upgrades to the verbose `{text, colSpan, merged, scope}` shape
  whenever scope is set.

### Real-world numbers
- **pandoc_planets.html**: `"Data about the planets of our solar system."`
  caption now in JSON. Previously empty.
- **messy_html5_demo.html** (updated to exercise these features):
  table with caption + 3 scoped col-headers + 2 scoped row-headers;
  figure/figcaption pair; address section.

### Goldens
- `messy_html5_demo.html.json` refreshed.
- All other 6 HTML + 2 EML goldens byte-identical (no `<caption>`,
  `<th scope>`, `<figure>`, or `<address>` in those source files).

### Cascade
- 17 in-repo `TableBlock` constructor sites updated to use `mkTable`.
- 9 sites with direct `TableCell` record literals updated to include
  `scope: ""`. All paid in one commit.

---

## [0.17.0](https://github.com/sunholo-data/ailang-parse/compare/v0.16.0...v0.17.0) — 2026-05-14

Three HTML-parser themes shipped together: page metadata extraction,
inline formatting preservation, and semantic block recognition.

### Added — Page metadata extraction
- **`parseHtmlMetadata(content)`** in [html_parser.ail](docparse/services/html_parser.ail)
  walks the parsed HTML tree to extract:
  - `<title>` → `DocMetadata.title` (falls back to `og:title` if absent)
  - `<meta name="author">` → `DocMetadata.author`
  - `<meta name="date">` → `DocMetadata.created` (falls back to
    `<meta property="article:published_time">`)
- **Wired into [docparse/main.ail](docparse/main.ail)** so every HTML
  parse now produces a populated `DocMetadata` instead of an empty one.
  www.sunholo.com now reports its title; the AILANG guide reports
  "Getting Started with AILANG Parse"; previously both were empty.

### Added — Inline formatting markers
- **`<strong>` / `<b>` → `**bold**`** (CommonMark-compatible)
- **`<em>` / `<i>` → `*italic*`**
- **`<code>` / `<kbd>` / `<samp>` → `` `code` ``**
- **`<del>` / `<s>` → `~~strikethrough~~`**
- **`<mark>` → `==highlighted==`**
- **`<a href="X">text</a>` inline → `[text](X)`** — even inside `<p>`
  paragraphs. Anchor-only hrefs (e.g. `href="#section"`) and href-less
  anchors collapse to plain text so output isn't polluted with
  placeholders.
- **`<time datetime="2026-05-14">yesterday</time>` → `yesterday (2026-05-14)`**
  so machine-readable timestamps survive alongside the human label.
- **`<abbr title="Application">App</abbr>` → `App (Application)`**
- **`<cite>` / `<q>` → `"quoted"`**

  Implemented in `htmlInlineWrap` — the inline children of paragraphs,
  headings, list items, table cells, etc. now retain semantic emphasis
  in the extracted text. Real-world impact: 15 `<strong>` and 31
  inline anchors on www.sunholo.com are now preserved instead of being
  flattened to plain text.

### Added — Semantic blocks
- **`<pre><code class="language-X">…</code></pre>`** captures the
  language hint: `TextBlock.style` is set to `"code-X"` (e.g. `"code-python"`,
  `"code-typescript"`) instead of the plain `"code"`. Bare `<pre>`
  without a `<code class="language-*">` child stays `"code"`.
- **`<details>`/`<summary>`** now emit a `SectionBlock(kind: "details")`
  containing a level-3 `HeadingBlock` for the summary plus the
  recursively-extracted body. Previously both fell through to text-only.

### Changed
- `htmlChildTextWithSpacing` and the new `htmlInlineWrap` dispatch
  inline children by tag. Block-level children still get a `\n`
  prefix; inline children get wrapped with the appropriate markdown
  marker; text nodes pass through unchanged.

### Goldens refreshed
- `test_complex.html`, `ailang_guide.html`, `sunholo_homepage.html`,
  `messy_html5_demo.html` — all 4 had structural changes because their
  paragraphs now carry inline formatting markers and their pages have
  extracted titles. `test.html`, `pandoc_nordics.html`,
  `pandoc_planets.html`, and the EML goldens were byte-identical
  (no inline emphasis in the source files).

### Real-world numbers (sunholo.com)
| Metric | v0.16.0 | v0.17.0 |
|---|---|---|
| `DocMetadata.title` | `""` | `"AI Engineering, AI Platforms and AI Solution Architecture - Sunholo"` |
| `<strong>` preserved in JSON | 0 | 15 (as `**...**` markers) |
| Inline anchor URLs in JSON | 0 | 31 (as `[text](href)`) |
| `<a href>` LinkBlocks (top-level) | 31 | 31 (unchanged) |

---

## [0.16.0](https://github.com/sunholo-data/ailang-parse/compare/v0.15.1...v0.16.0) — 2026-05-14

### Changed
- **`ImageBlock` extended with five HTML5 image attributes**:
  ```ailang
  ImageBlock({
    data, description, mime,
    width: int, height: int,
    srcset: string, title: string, loading: string
  })
  ```
  - **`width` / `height`** — pixel dimensions from `<img width=400 height=200>`.
    Parsed as non-negative ints; values like `"100%"` fall back to `0`
    because percentage/fractional sizes aren't modeled.
  - **`srcset`** — responsive-image candidate list from `<img srcset>`.
    For `<picture>` elements, srcsets from sibling `<source>` children
    are concatenated (comma-joined) and inherited by the inner `<img>`
    fallback. The `<img>`'s own `srcset` takes priority if both are
    present (preserves author intent).
  - **`title`** — tooltip / image-credit attribute.
  - **`loading`** — `"lazy"` / `"eager"` from `<img loading=…>`.

### Added
- **`mkImage(data, description, mime)` helper** in
  [docparse/types/document.ail](docparse/types/document.ail) constructs
  an `ImageBlock` with zero/empty defaults for the new fields. Used by
  all parsers that don't have access to the extended HTML5 attributes
  (DOCX, PPTX, ODT, EPUB, Markdown, TeX, AI vision parser, ZIP image
  resolver, a2ui formatter). Net effect on those parsers: 1-line swap
  per constructor site, no schema knowledge required.
- **`mkImageFull(data, description, mime, width, height, srcset, title, loading)`**
  is the long form used by `html_parser.ail` when extracting `<img>` and
  `<picture>` elements.
- **`htmlParsePicture`** in [docparse/services/html_parser.ail](docparse/services/html_parser.ail)
  walks a `<picture>` element's children, collects all `<source srcset>`
  values, and emits a single ImageBlock from the fallback `<img>` with
  the concatenated srcset list inherited.
- **`htmlParseImg`** centralises `<img>` attribute extraction so the
  inline `<img>` branch and the `<picture>` fallback branch use the
  same code path.

### JSON output
- New fields are emitted **only when non-zero / non-empty**:
  ```json
  {
    "type": "image",
    "description": "Responsive hero",
    "mime": "image/unknown",
    "dataLength": 14,
    "src": "hero-small.png",
    "width": 800,
    "height": 400,
    "srcset": "hero-large.png 2x, hero-medium.png 1.5x",
    "title": "Hero illustration"
  }
  ```
  Consumers that don't read the new fields are unaffected — empty
  `width=0`, `srcset=""`, etc. don't appear in the JSON at all. Existing
  goldens for non-HTML formats produce byte-identical JSON.

### Migration notes
- **Type signature is a breaking ADT change** but every in-repo
  constructor was migrated to `mkImage` / `mkImageFull`. Downstream
  consumers that explicitly pattern-match on `ImageBlock(b)` and read
  `b.data`, `b.description`, `b.mime` are unaffected — those three
  fields stay in the same position with the same types. Reads of
  `b.width` / `b.height` / `b.srcset` / `b.title` / `b.loading` are
  new and safe to add.
- **Goldens**: only `messy_html5_demo.html.json` actually changed —
  all other HTML/DOCX/PPTX/ODT goldens produce byte-identical output
  because their image-emitting paths use `mkImage` which fills empty
  defaults that get omitted from JSON.

---

## [0.15.1](https://github.com/sunholo-data/ailang-parse/compare/v0.15.0...v0.15.1) — 2026-05-14

### Added
- **`<picture>` element handling** in [html_parser.ail](docparse/services/html_parser.ail).
  HTML5 responsive-image markup wraps an `<img>` fallback in a `<picture>`
  parent with one or more `<source srcset>` siblings. The browser picks
  one candidate at runtime; for deterministic parsing we recurse into
  `<picture>` and surface the inner `<img>` fallback as a normal
  `ImageBlock`. `<source>` elements have no `src` attribute (only
  `srcset`, which we don't model) so they emit nothing.

  Example: `<picture><source srcset="big.png"><img src="small.png" alt="x"></picture>`
  now produces `ImageBlock(src="small.png", description="x")` instead of
  dropping silently.

  `data/test_files/messy_html5_demo.html` extended with a `<picture>`
  example covering the art-direction pattern; golden refreshed.

### Deferred
- Extending `ImageBlock` with `width`/`height`/`srcset`/`title`/`loading`
  attributes was attempted and reverted: the schema change cascades
  through 13+ files (every parser that constructs `ImageBlock` —
  DOCX/PPTX/ODT/EPUB/Markdown/TeX/AI/a2ui/zip_extract, plus the JSON
  serializer). The blast radius is disproportionate to the value;
  parking until there's a real consumer asking for these fields.

---

## [0.15.0](https://github.com/sunholo-data/ailang-parse/compare/v0.14.1...v0.15.0) — 2026-05-14

### Added
- **`LinkBlock` ADT variant** for HTML anchors. `LinkBlock({text, href, title})`
  captures the visible text and target URL of an `<a href>`. JSON output:
  ```json
  {"type":"link","text":"Try it free","href":"/ailang-parse/","title":""}
  ```
  Every match site that pattern-matches on `Block` gained a sensible
  `LinkBlock` arm:
  - `output_formatter.ail`: JSON serialization + console pretty-print
    (`[link] text → href`) + markdown rendering (`[text](href)`).
  - `html_generator.ail`: round-trips back to `<a href="...">text</a>`,
    preserving `title` if present.
  - `qmd_generator.ail`: markdown link syntax.
  - `odt_generator.ail`: `<text:a xlink:href="...">` proper ODF link.
  - `docx_generator.ail`/`pptx_generator.ail`/`odp_generator.ail`/
    `xlsx_generator.ail`: text downgrade with URL in parens (full
    `<w:hyperlink>` / shape-link round-tripping deferred).
  - `a2ui_formatter.ail`: callout with `href` + `title` metadata.
  - `unstructured_compat.ail`: NarrativeText with `link_urls`
    metadata field (matches unstructured.io's hyperlink schema).
  - `layout_ai.ail`: compact `[link] text → href` representation
    suitable for LLM context.

### Changed
- **HTML parser anchor handling rewritten.** The `<a>` branch now
  treats anchors as HTML5 "transparent" elements: recurses into
  children to surface any block content (images, headings, nested
  structure), and additionally emits a `LinkBlock` when `href` is
  present so the URL is captured.

  Three concrete improvements measured on www.sunholo.com:

  | Metric | v0.14.1 | v0.15.0 | Source |
  |---|---|---|---|
  | Images captured | 4 | **10** | 12 `<img>` in source |
  | Anchor URLs captured | 0 | **31** | 62 `<a href>` in source |
  | LinkBlock support | none | full ADT | — |

  The remaining 2 images / 31 anchors are inside constructs we don't
  yet handle (`<picture>`, anchors with no visible text, etc.).

### Known limitations (not addressed in this release)
- `<img>` attributes beyond `src` + `alt` — `width`, `height`,
  `srcset`, `loading`, `title` — are still ignored. Adding them
  requires extending the `ImageBlock` record, which cascades through
  every parser that constructs `ImageBlock` (DOCX/PPTX/ODT/EPUB/Markdown/TeX).
  Deferred.
- `<picture>` and `<source>` (responsive image art-direction) — not
  yet parsed.
- DOCX/PPTX hyperlink round-trip — the writers currently downgrade
  `LinkBlock` to plain text with the URL in parens. Full
  `<w:hyperlink>` / `<a:hlinkClick>` round-tripping is deferred to a
  future write-back release.

---

## [0.14.1](https://github.com/sunholo-data/ailang-parse/compare/v0.14.0...v0.14.1) — 2026-05-14

### Added
- **Image/audio/video `src` URLs surfaced in JSON output.** Previously,
  the URL was captured into `ImageBlock.data` by HTML/ODT/Markdown/EPUB
  parsers but `output_formatter.ail` only serialized its character
  count (`dataLength`) — the actual URL was thrown away. Inspecting
  parsed output of www.sunholo.com showed image alt text + mime + a
  numeric length, but zero way to recover "where did this image come
  from?" without re-parsing the source. The JSON now emits:
  ```json
  {"type":"image","description":"AILANG Logo","mime":"image/unknown",
   "dataLength":15,"src":"ailang-logo.svg"}
  ```
  The `src` field is **length-gated to 2048 chars**: short URLs/paths
  from HTML, Markdown, ODT, and EPUB surface in the output, while
  DOCX/PPTX inline base64 binary payloads (often megabytes) stay
  represented by `dataLength` alone — emitting them as `src` would
  bloat JSON outputs by orders of magnitude.

  Same change applies to `AudioBlock` and `VideoBlock` for symmetry.

  This is a purely **additive** schema change: existing consumers that
  read `description`/`mime`/`dataLength` continue to work; new
  consumers can opt into the `src` field. Refresh affected goldens
  (`ailang_guide.html`, `test.html`, `messy_html5_demo.html`,
  `sunholo_homepage.html`, `lo_image_mimetype.odt`, `image_vml.docx`,
  `pandoc_inline_images.docx`, `pandoc_basic.pptx`, `officeparser.odt`,
  `officeparser.odp`, `challenge_html_multipart.eml`) — all eval at
  100% against the new shape.

### Known limitations (not addressed in this patch)
- Images nested inside `<a>` tags are still dropped (the anchor branch
  falls through to text-only mode). On www.sunholo.com this loses 8 of
  12 images — they live in `<a class="card"><img></a>` patterns.
- `<a href>` URLs themselves are not captured (62 hrefs on sunholo.com
  → 0 in output). A future `LinkBlock` type or extended `TextBlock`
  with optional `href` would close this.
- `<img>` attributes beyond `src` and `alt` (`width`, `height`,
  `srcset`, `loading`, `title`) and `<picture>`/`<source>` elements
  are not captured. Schema change, deferred.

---

## [0.14.0](https://github.com/sunholo-data/ailang-parse/compare/v0.13.0...v0.14.0) — 2026-05-13

### Changed
- **HTML parser now uses `std/html`** (WHATWG HTML5 spec via Go's
  `golang.org/x/net/html`, shipped in AILANG v0.19.1). The in-repo
  sanitizer pipeline introduced in v0.13.0 — ~475 lines of boolean-
  attribute normalization, tag-stack auto-closing, script stripping,
  conditional-comment stripping, HTML-comment stripping, void-element
  closing, and entity normalization — is **deleted entirely**. Every
  block extractor (`htmlExtractBlocks`, `htmlProcessNode`, `htmlParseTable`,
  `htmlDeepText`, etc.) is unchanged because `std/html` returns the
  same `XmlNode` ADT as `std/xml`.

  Side-effects of switching to a real HTML5 parser:
  - Unicode characters in inline anchors (e.g. `→` in "See how →") are
    now preserved rather than stripped by the entity pipeline.
  - Adjacent inline elements (e.g. "Connect With Us" + `<a>LinkedIn</a>`)
    parse as separate text blocks instead of being concatenated.
  - Document tree shape is the canonical HTML5 tree (always wrapped in
    `<html><head><body>…</body></html>`), which matters only if you
    walked the tree manually — `parseHtml`'s block-list output is
    unaffected.

  Sunholo homepage golden refreshed to reflect the better text
  extraction. All other goldens (test.html, test_complex.html,
  ailang_guide.html, pandoc_nordics.html, pandoc_planets.html,
  messy_html5_demo.html) produce 100%-identical output.

### Requires
- **AILANG ≥ 0.19.1** (was `>=0.12.0`). `std/html` was added upstream
  on 2026-05-13. End-users on AILANG 0.12.x – 0.19.0 must upgrade.

---

## [0.13.0](https://github.com/sunholo-data/ailang-parse/compare/v0.12.9...v0.13.0) — 2026-05-13

### Added
- **Tolerant HTML5 parsing** in [docparse/services/html_parser.ail](docparse/services/html_parser.ail).
  Production HTML pages — sourced from CMSes, scraped websites, HTML email
  templates, and saved browser pages — previously failed deterministic
  parsing because the underlying XML parser is strict and HTML5 is not XML.
  The sanitizer now closes three real-world gaps without an AI fallback:
  - **Boolean attributes** (`<link ... crossorigin>`, `<input disabled>`,
    `<details open>`) are rewritten to `name=""` form for 23 known
    HTML5 booleans (`disabled`, `checked`, `selected`, `readonly`,
    `multiple`, `required`, `autofocus`, `hidden`, `novalidate`,
    `formnovalidate`, `defer`, `async`, `open`, `reversed`, `controls`,
    `autoplay`, `loop`, `muted`, `default`, `ismap`, `nomodule`,
    `crossorigin`, `itemscope`, `playsinline`). Fixed-point iteration
    handles adjacent booleans on the same tag.
  - **Tag-stack auto-closing** walks the token stream maintaining a
    stack of open elements. Stray close tags are dropped; overlapping
    closes (`<p>` closed by `</a>`) trigger implicit closes for
    everything above the target; elements still open at end-of-input
    are closed.
  - **Inline script + conditional-comment stripping** removes
    `<script>...</script>` (JSX, template literals, raw `<`/`&` in JS
    routinely broke the parser) and `<!--[if IE]>...<![endif]-->`
    (HTML email IE-conditionals). HTML comments are now stripped
    rather than left to fail on inner `--`.

  Canonical regression: `curl https://www.sunholo.com` saved at
  [data/test_files/sunholo_homepage.html](data/test_files/sunholo_homepage.html)
  previously produced a single `TextBlock(style: "error")` (XML parse
  failed on the `crossorigin` boolean attribute on line 10). Now
  extracts 13 structured blocks including header, nav, sections,
  h1–h4 headings, lists, and the full footer.

  Well-formed HTML (existing test files: `test.html`, `test_complex.html`,
  `ailang_guide.html`, `pandoc_nordics.html`, `pandoc_planets.html`)
  continues to produce byte-identical output — the tolerant passes are
  no-ops on already-valid input.

  See [v0_13_0_html_tolerant_parsing](design_docs/implemented/v0_13_0/v0_13_0_html_tolerant_parsing.md).

### Known limitations
- Tag-name case-folding (`<P>` → `<p>`) and Word/Office namespace
  stripping (`<o:p>` → `<p>`) are deferred. Real-world impact is
  limited (Word's HTML export is the primary remaining offender;
  `<script>` stripping already handles JSX-style custom-cased React
  components).
- A `std/html` stdlib module wrapping `golang.org/x/net/html` would
  let this whole sanitizer pipeline collapse to a single call. Filed
  as an upstream proposal to the AILANG core.

---

## [0.12.4](https://github.com/sunholo-data/ailang-parse/compare/v0.12.3...v0.12.4) — 2026-04-27

### Added
- **Content-aware format detection** in `format_router.ail`: new `sniffFormat`
  and `resolveFormat` exports plus a `ResolvedFormat` type. The sniffer
  identifies PDF/PNG/JPG/GIF/WAV/WEBP/MP3 via base64-prefix and
  DOCX/PPTX/XLSX/ODT/ODP/ODS/EPUB by inspecting ZIP entries
  ([Content_Types].xml for OOXML, mimetype for ODF/EPUB). `resolveFormat`
  composes extension + content sniffing with a clear precedence so
  callers can confidently route files whose extension is missing,
  ambiguous, or wrong. See [v0_12_4_format_detection_signed_urls](design_docs/implemented/v0_12_4/v0_12_4_format_detection_signed_urls.md).

### Fixed
- **DOCX heading detection** in `docx_parser.ail`: now recognizes the
  space-separated style names some non-conformant tools emit
  (`"Heading 1"` in addition to `"Heading1"`) and maps Word's `Title` /
  `Subtitle` styles to H1/H2 instead of body text.

### Bug Reports Addressed
- `msg_20260427_173916_463d1f6b` (aitana-platform v6) — DOCX served via
  signed GCS URL was producing flat-text output. Root cause: when the
  signed-URL fetch saved the file to a temp path that lost or mangled
  the extension, format detection fell back to the generic `unknown`
  category and bypassed the structured DOCX parser. The new
  `resolveFormat` is the building block; the API server in the
  downstream `docparse` repo wires it in to fix the user-facing bug.

---

## [0.9.3](https://github.com/sunholo-data/ailang-parse/compare/v0.9.2...v0.9.3) — 2026-04-08

### Added
- **Markdown+metadata renderer**: new output mode combining clean markdown with
  structured metadata (change attribution, merged-cell annotations)

---

## [0.9.2](https://github.com/sunholo-data/ailang-parse/compare/v0.9.1...v0.9.2) — 2026-04-07

### Added
- **MCP Registry**: publish to MCP registry with CI job, badge, and install docs
- **llms.txt + llms-full.txt**: AI agent discoverability files
- **Workbench polish**: copy-to-clipboard, mini tutorial, full format list in
  dropzone, progress bar during WASM boot, demo set loader

### SDKs (v0.4.1 → v0.4.6)
- MCP registry metadata
- `markdown` text field, `FormatsResult` helpers, `key_info()`
- Fix Python `parse_file` NameError

---

## [0.9.1](https://github.com/sunholo-data/ailang-parse/compare/v0.9.0...v0.9.1) — 2026-04-04

### Added
- **Workbench page**: dedicated multi-file WASM playground with shared frontend module and CI guards
- **R SDK** (v0.4.0): full feature parity with Python/JS/Go SDKs
- MCP modules reorganized into `docparse/services/mcp/` subdirectory
- Shared credential helpers and auto-load saved API key in MCP bridges (SDK v0.3.1)

---

## [0.9.0](https://github.com/sunholo-data/ailang-parse/compare/v0.8.2...v0.9.0) — 2026-04-01

This was a major release spanning website GTM, email parsing, OfficeDocBench v2,
MCP tooling, multipart file upload, and significant frontend/auth work.

### Added — Email Parsing
- Full EML/MBOX email parsing wired into format router
- Attachment chain parsing and thread reconstruction
- Two-pass Office attachment parsing (`--deep` flag)
- HTML email sanitization (non-XHTML, `<style>` blocks, zero-width Unicode)
- Quoted-printable decoder and HTML sanitizer performance optimization
- Z3 contracts on email and HTML parser pure functions
- 3 AILANG-themed email sample files

### Added — OfficeDocBench v2
- 9 ECMA-376 spec-driven scoring dimensions
- Content Fidelity and Structural Quality metrics
- Pandoc + Raw OOXML benchmark adapters
- Kreuzberg v4.7.2 added as competitor (77.2% composite)
- Results: 69 files, 8 parsers, 7 metrics

### Added — MCP & Agent Tooling
- MCP stdio bridge in JS SDK
- MCP auth, billing, and estimate tools for agent self-discovery

### Added — SDKs (v0.2.0 → v0.3.0)
- `parse_file` / `parseFile` / `ParseFile` multipart upload methods
- Device auth helpers: `client.device_auth()` across Go, Python, JS
- Key persistence: auto-save/load credentials across sessions
- Integration tests for multipart upload and Unstructured compat

### Added — Website & Frontend
- GTM Phases 1-3: messaging cleanup, WASM demo, funnel, comparison table
- A2UI tab: rich document rendering with streaming animation
- Format-specific landing pages (DOCX, XLSX, PPTX, PDF, HTML)
- Dedicated pricing page with build-time price stamping
- Frontend design refresh: distinctive identity, sidebar consistency
- FirebaseUI multi-provider sign-in (email magic link, avatar, sign-out)
- `?env=test|dev|prod` support for Firebase auth and API URLs
- Privacy policy, terms of service, DPA, beta badge

### Added — Parser Improvements
- Batch mode, folder parsing, and Windows CLI for docparse
- Nested SDT element handling in DOCX parser
- Strip Wingdings/symbol font PUA characters from DOCX output
- AILANG native string builtins for email/HTML parsing performance
- HTML deep text extraction: whitespace insertion, newline collapsing
- Case-insensitive file extensions
- Large PDF optimization: upload once, reference by URI (Gemini Files API)
- PPTX large file fix (50 MB in 9.4s), hardened XLSX memory

### Changed
- 10x request limits, reframe daily as rate limit
- Boost free tier to 2,000 req/month
- Rebrand selfhost page as "Install" / "Run Locally"
- Honest speed claims: sub-second for WASM, sub-ms for CLI
- XLSX parser: use `std/map`, `scanFold`, `parseFold` from new AILANG stdlib

### Fixed
- npm publish: OIDC trusted publishing with pinned npm@11.5.0
- JS SDK multipart file upload in ESM contexts
- A2UI export, WASM binary, call pattern fixes
- Firebase auth: apiKey auth, cached key clearing, dashboard paths

---

## [0.8.2](https://github.com/sunholo-data/ailang-parse/compare/v0.8.1...v0.8.2) — 2026-03-17

### Fixed
- AILANG_REGISTRY_VALIDATOR secret in publish workflow
- Repo URLs in SDK manifests (`docparse` → `ailang-parse`)
- Use `astral-sh/setup-uv@v4` in all workflows

---

## [0.8.1](https://github.com/sunholo-data/ailang-parse/compare/v0.8.2...v0.8.1) — 2026-03-17

### Added
- AILANG package publish workflow for registry releases

---

## 0.8.0 — Platform & Ecosystem (March 2026)

- **API keys & Cloud deployment**: Terraform, Firestore, Firebase Auth
- **Agent-friendly API**: capabilities manifest, typed errors, device auth, pricing, tools
- **SDKs**: Python v0.1.3 (PyPI), JS v0.1.3 (npm), Go SDK
- **Website**: 19-page static site on GitHub Pages
- **API playground**: in-browser with Firebase auth, code gen, response panel
- **OfficeDocBench**: AILANG Parse 96.6% vs Unstructured 63.4%, Docling 63.4%, LlamaParse 53.6%
- **Gemini Files API**: upload once, reference by URI for large PDFs
- **WASM threat model**: keep open — Office parsing is costless funnel
- Design docs: [API Keys](design_docs/implemented/v0_8_0/api_keys_cloud_deployment.md) | [Agent API](design_docs/implemented/v0_8_0/agent_friendly_api.md) | [Auth](design_docs/implemented/v0_8_0/auth_security.md) | [SDKs](design_docs/implemented/v0_8_0/sdks.md) | [Website](design_docs/implemented/v0_8_0/website.md) | [Playground](design_docs/implemented/v0_8_0/api_playground.md) | [Ecosystem](design_docs/implemented/v0_8_0/ecosystem.md)

## 0.7.0 — API Server

- REST API via `ailang serve-api` with `@route` annotations
- Unstructured API drop-in compatibility (`POST /general/v0/general`)
- Auto-generated OpenAPI spec + Swagger UI, 25 smoke tests
- Cloud Run `concurrency=80` safe
- Design doc: [API Server](design_docs/implemented/v0_7_0/v0_7_0_api_server.md)

## 0.6.0 — Document Generation

- Block ADT → file output for 8 formats (HTML, DOCX, PPTX, XLSX, ODT, ODP, ODS, Markdown)
- AI-assisted generation: `--generate output.docx --prompt "Q1 sales report"`
- Cross-format conversion via `--convert` flag
- Design docs: [Generation](design_docs/implemented/v0_6_0/v0_6_0_document_generation.md) | [Features](design_docs/implemented/v0_6_0/features.md) | [Verification](design_docs/implemented/v0_6_0/verification_loop.md)

## 0.5.0 — Spec Coverage & Benchmarks

- ECMA-376 spec coverage audit — 19 gaps closed across Rounds 1-3
- OmniDocBench integration (Text ED 0.183, Table TEDS 0.871)
- Large file performance — DOCX/PPTX/XLSX within tier limits
- Design docs: [Spec Audit](design_docs/implemented/v0_5_0/spec_coverage_audit.md) | [External Benchmarks](design_docs/implemented/v0_5_0/external_benchmarks.md) | [Large File Perf](design_docs/implemented/v0_5_0/large_file_performance.md)

## 0.3.0 — Parser Coverage & Format Expansion

- 13 format parsers (DOCX, PPTX, XLSX, CSV, TSV, Markdown, HTML, EPUB, ODT, ODP, ODS, EML, MBOX)
- All parsers in pure AILANG (zero runtime dependencies)
- 53 golden benchmark files at 100% baseline
- AILANG eval module — 8 structural checks with contracts
- ODT/ODP/ODS native parsing — strategic gap, nobody else does this
- Design docs: [Format Expansion](design_docs/implemented/v0_3_0/format_expansion.md) | [Parser Coverage](design_docs/implemented/v0_3_0/v0_3_0_parser_coverage.md) | [Eval](design_docs/implemented/v0_3_0/ailang_benchmark_eval.md)

## 0.1.0 — Initial Release (March 2026)

- Deterministic Office parsing (DOCX, PPTX, XLSX)
- AI-powered PDF extraction via pluggable models
- 18 golden benchmarks at 100% baseline
- Comment extraction, track changes, headers/footers
- PDF benchmark infrastructure with multi-model support
- Competitor adapter framework (Docling, LlamaParse, Unstructured)
- Design doc: [Implementation Report](design_docs/implemented/v0_1_0/v0_1_0_implementation_report.md)
