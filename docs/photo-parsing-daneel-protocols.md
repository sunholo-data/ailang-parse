# Photo Parsing (Screenshots) via AILANG Parse — and how Daneel + Sunholo services fit

Status: proposal / design note. No code changed by this document.
Raised by: maintainer request 2026-10-02 ("Can you parse photos? … consider how
Daneel and Sunholo services could help this situation. Protocols between?
Permissions?")

## 1. Can AILANG Parse parse photos today? Yes.

The capability already exists end to end; nothing new needs to be built to
parse a single screenshot:

- **Routing** (`docparse/services/format_router.ail`): `detectFormat` maps
  `png`, `jpg`, `jpeg`, `gif`, `bmp`, `webp`, `tiff` → `"image"`, and
  `needsAI("image") = true`. Content sniffing (`sniffByBase64Prefix`) also
  recognises PNG (`iVBORw0KGgo`), JPEG (`/9j/`), GIF, WEBP even when the file
  has no or a wrong extension — which is exactly what happens when a signed
  URL is fetched to a mangled temp name.
- **Two AI paths** (`docparse/services/direct_ai_parser.ail`):
  - `parseImage(filepath, mime)` — vision description of the photo ("what it
    shows, visible text, key data, visual structure"). Returns a single
    `ImageBlock` with the base64 and the description.
  - `parseDocumentImage(filepath, mime)` — structured extraction into the
    standard Block schema (headings, text, tables, lists), with a
    reading-first prompt: if the image is a chart/graph it names the chart
    type, axes/units and the trend (rises/falls/peaks) before extracting
    literal labels; screenshots of documents are extracted like a page;
    formulas come back in LaTeX.
- **Images inside documents** (`docparse/services/layout_ai.ail`):
  `describeImages(baseDir, blocks)` sends every embedded/linked image through
  a real multimodal request (`mode=multimodal` — not base64-in-prompt),
  fail-soft per image, with warnings surfaced rather than swallowed.
- **How to run it**: `./bin/docparse screenshot.png --ai gemini-2.5-flash`
  (needs `GOOGLE_API_KEY`), or hosted via the MCP `mcpParse` tool — `png` and
  `jpg` are already listed in `mcpFormats` as hosted-parseable inputs.

"Or image model?" — there is no separate image pipeline to choose. Parsing is
done by a vision-capable LLM through AILANG's `AI` effect
(`mode=multimodal` requests with inline base64 or a `fileUri`), so any model
AILANG supports with vision (Gemini by default, Claude, GPT, local Ollama)
works, and the prompt is the only thing that changes per strategy.

**Caveat on "see these screenshots"**: the request that raised this arrived
with no attachments, and the CI lane this was written on has no network, so no
photo was actually parsed while writing this. The capability claim above is
verified from the package source, not re-executed end to end.

## 2. Where Daneel fits — the gap is capability routing, not parsing

Daneel runs under an AILANG policy lane that grants a narrow effect set
(typically `IO, FS, Env`, sometimes `Process` for git). The `docparse` shim is
deliberately built for that world: `[bin] docparse` carries `caps =
"IO,FS,Env"` — **no `AI`, no `Net`** — so the AI-required image path is
unreachable from a plain agent lane. That is a feature, not a bug: "this
machine never sends files to Gemini" is enforced by the capability set, not by
prompt discipline. The consequence for the photo question is simple:

> Daneel cannot parse a photo locally even though the code exists locally.
> Photo parsing for agents must go through a route where the AI call happens
> under a service's credentials, not the agent's.

Three routes, in preference order for an agent like Daneel:

### Route A — hosted MCP (recommended default for agents)

1. `mcpFormats` — discovery. The manifest lists image inputs and, since the
   runtime block, reports what is *actually provisioned* on this deployment
   (`ai_generation: provisioned|unconfigured`, backend presence as
   `true|false|unknown`), so the agent trusts state rather than aspiration.
2. `mcpAuth` / `mcpAuthPoll` — RFC 8628 device authorization. The human
   opens the verification URL, sees a code (e.g. `ABCD-1234`), approves.
   Scope is currently `"parse"`. The agent never types a credential; the
   human is the consent gate.
3. `mcpParse` with `DOCPARSE_MODE=hosted` — POSTs to
   `/api/v1/parse` at `docparse.ailang.sunholo.com`. Auth is
   `Authorization: Bearer` / `X-API-Key` (preferred: the key never enters
   model context) or the `apiKey` field. Errors come back as one JSON shape
   (`error` / `message` / `retryable` / `suggested_fix`) so the agent can
   distinguish "retry" from "give up".
4. The AI call runs server-side under Sunholo's provider key; Daneel never
   holds one. Tier quotas bound cost (Free: 50 AI parses/month, 10 MB/file;
   Pro: 500, 25 MB; Business: 2,000, 50 MB).

### Route B — local with an explicit AI grant

`bin/docparse photo.png --ai gemini-2.5-flash` with `--caps AI` (or the AI
cap added to a policy) and a key. This is the right route only when a human
has decided this specific machine/agent may talk to a model provider
directly — it is a deliberate, auditable capability widening, the same
judgement call as the `docparse-pdf` shim carrying `Process`.

### Route C — hybrid (the natural steady state)

Deterministic formats (docx/pptx/xlsx/csv/md/html/…) parse locally with no AI
and no network; only `needsAI(format) = true` inputs — photos, PDFs, audio,
video — escalate to Route A. `format_router.needsAI` is already the exact
predicate an orchestrator needs to make that decision, and
`mcpFormats.input_formats[].ai_required` exposes it to the agent.

## 3. Protocols between Daneel and Sunholo services

What already exists and works:

- **MCP tool surface** (7 tools, each with an `@route` HTTP mapping):
  `mcpParse`, `mcpConvert`, `mcpFormats`, `mcpEstimate`, `mcpAuth`,
  `mcpAuthPoll`, `mcpAccount`. An agent can discover, estimate cost, parse,
  and convert without bespoke glue.
- **Error contract**: every orchestrator failure renders as
  `{error, message, retryable}` with the AIError's own code and retryable
  flag — clients can loop on `retryable: true` and stop on `false`.
- **Capability honesty**: `mcpFormats.service` + `runtime` blocks distinguish
  "the package supports this" from "this deployment can do this right now".

Gaps this request exposes (proposals, not implemented here):

1. **Byte transport for hosted image parsing.** `mcpParse` hosted mode takes a
   `filepath` / `sample_id`; `/api/v1/convert` additionally accepts
   `sourceUrl` and `gcsRef`. A phone screenshot that lives in a chat has
   neither a URL nor a bucket unless someone puts it there. Options:
   - a direct-bytes endpoint (multipart or raw body) on `/api/v1/parse`; or
   - a signed-URL upload flow (POST metadata → get a one-shot upload URL →
     parse by reference), which keeps large binaries off the parse API and
     reuses the GCS path `gemini_files` already knows.
   For Daneel specifically, the signed-URL variant is better: the agent's
   lane grants `Net`, and uploading to a short-lived, scope-limited URL is a
   much narrower grant than general GCS write.
2. **Image upload parity with PDF.** `parsePdf` uploads files over
   500 KB base64 once via `prepareUpload` → `gemini_files.uploadFile` and
   references them by `fileUri`; `parseDocumentImage` / `parseImage` do not —
   a 2 MB screenshot (~2.7 MB base64) is inlined in every request. Porting
   `prepareUpload`/`sourceKv` to the image functions is a small, contained
   change (effect rows widen to `{Clock, FS, AI, Net, Env}` on those two
   functions and their callers must allow it) with an immediate cost/latency
   win for phone photos.
3. **Finer device-auth scopes.** Scope is `"parse"` today. Splitting into
   `parse:deterministic` (free, no AI) and `parse:ai` (metered) would let a
   human pre-approve an agent for the cheap class while keeping the
   expensive/PII-sensitive class behind a per-use decision — which matches
   how the capability lanes already split `docparse` from `docparse-pdf`.

## 4. Permissions

- **Consent**: photos are the most privacy-sensitive input class this package
  handles (screenshots contain mail, tokens, personal data). RFC 8628 device
  auth is exactly the right gate: a human sees *that* an agent wants parse
  access and approves it, per agent, with a revocable key. Do not hand agents
  long-lived provider keys to get around it.
- **Data-flow labelling (AILANG IFC angle)**: a screenshot arriving from a
  user is untrusted data — conceptually `string<screenshot>`. The hosted
  parse sink is where the label is laundered, and the declassifier should be
  explicit and auditable (the device-flow approval). Local lanes should keep
  the label: an agent with only local caps physically cannot exfiltrate the
  photo, which is stronger than any policy sentence.
- **Budgets**: local runs are bounded by the AI capability budget
  (`AI @limit=30` per document, already in `bin/docparse`); hosted runs by
  tier quotas (`ai_parses_month`, `max_file_mb`). Both directions have a
  ceiling; keep it that way when adding the byte-transport endpoint.
- **Precedent for "never upload" policies**: Mark/Daneel's PDF policy routes
  PDFs to the local, non-AI `docparse-pdf` backend. If the same rule ever
  applies to photos, there is currently *no* local non-AI image path (no OCR
  backend like `pdftotext` for images). Worth a decision now, not later:
  either declare "images are always AI", or add a `tesseract`-style local
  backend tier to `pdf_backend_external`'s pattern. Declaring is free;
  deferring the decision is how a policy violation gets discovered in
  production.

## 5. Recommended next steps (in order)

1. **Answer the user now** (no code): yes — `./bin/docparse photo.png --ai
   gemini-2.5-flash` locally with a key, or hosted via MCP `mcpParse` for
   agents. For Daneel specifically: Route A, behind device auth.
2. **Signed-URL (or direct-bytes) upload on the hosted parse API** so an
   agent can hand over a screenshot without a pre-existing URL/bucket.
3. **Port `prepareUpload` to the image parsers** for >500 KB inputs.
4. **Split device-auth scopes** `parse:deterministic` / `parse:ai`.
5. **Decide and document** whether photos have a "never leave the machine"
   tier (local OCR) or are always AI — one paragraph in `AGENT.md` is enough
   if the answer is "always AI".
