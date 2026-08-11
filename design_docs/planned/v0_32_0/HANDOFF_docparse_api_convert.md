# HANDOFF → `sunholo/docparse` — add `/api/v1/convert`

**Audience**: the agent working in the private `sunholo/docparse` repo (hosted API).
**From**: `sunholo/ailang-parse` @ v0.31.0, published and live on the registry.
**Companion**: [`v0_32_0_generation_surfaces.md`](./v0_32_0_generation_surfaces.md) — strategy, pricing and the browser-WASM route. Read that for *why*; this doc is *what to build*.

## What you are adding and why it is small

The hosted API exposes `/parse`, `/estimate`, `/samples`, `/pricing`,
`/auth/device` — and no conversion. Meanwhile this package generates **nine
formats** with renderer-verified fidelity, and none of it is reachable from the
API or from any of the four SDKs.

**You are not writing document logic.** Every generator already exists in the
registry package you consume. This is an endpoint, a recipe call, and metering.

## Dependency

```toml
sunholo/ailang_parse = "0.31.0"   # published, live
```

Confirm with `ailang search ailang_parse`. Take **0.31.0 specifically**: 0.30.0
hangs on DOCX/XLSX/HTML → PPTX and → ODP (an infinite recursion in two
generators), so any convert endpoint built on it has six dead paths.

## The call you need

Conversion is already a single orchestrator recipe. Parse to blocks, then hand
the blocks to a generator:

```ailang
import docparse/services/orchestrator (parseDocument, ParseOptions, defaultParseOptions)
import docparse/services/docx_generator (generateDocx)
import docparse/services/html_generator (generateHtml)
import docparse/services/pptx_generator (generatePptx)
import docparse/services/xlsx_generator (generateXlsx)
import docparse/services/odt_generator  (generateOdt)
import docparse/services/odp_generator  (generateOdp)
import docparse/services/ods_generator  (generateOds)
import docparse/services/qmd_generator  (generateQmd)
```

Generator signature is uniform — `(doc: ParsedDocument, outputPath: string) ->
string ! {FS}` — except `generateQmd(doc) -> string`, which is pure and returns
the markdown directly rather than writing a file.

Targets: `html docx pptx xlsx odt odp ods md qmd`.

The CLI's `--convert` path in `docparse/main.ail` is the reference
implementation; mirror its target dispatch rather than inventing one.

## Three things that will bite you

**1. Generators write to a path, not a buffer.** `std/zip.createArchive` is
`! {FS}` and takes an output path — there is no in-memory variant (ailang-core
#644). On Cloud Run, generate into a temp path and stream the file back, then
unlink. Do not try to hold it in memory; that route needs a change to the
generators, described in the companion doc.

**2. Effects tier.** `parseDocument` is the full ladder (`Process` for the PDF
backend). If the endpoint should not shell out, use `parseDocumentPure`
(`! {FS}`) and refuse the formats it refuses — it returns `Err` for pdf/latex/
image/audio/video **rather than** parsing them partially. That refusal is
deliberate; do not paper over it with a fallback.

**3. Deterministic vs AI conversion are different cost profiles.** Office → Office
is pure compute. `--generate --prompt` burns model tokens. They must not share a
price or a rate limit. Scope this endpoint to deterministic conversion only.

## Metering

`/parse` bills per document / per page. Conversion does not fit per-page: a
three-block input can emit a forty-page document. The companion doc lists three
candidate models; **the choice is not made yet** — check before you wire a
meter, because it determines whether you count input pages, output bytes, or
documents.

Whatever you choose, key-gate it exactly as `/parse` is gated.

## Also in your court

`mcpConvert` currently demands an API key in hosted mode and then does the
conversion **locally** — the key gates work running on the user's own machine,
because there is no server-side conversion to call. Once `/api/v1/convert`
exists, its hosted branch should call your endpoint. The AILANG-side change is
ours; the endpoint contract is yours. Tell us the request/response shape and we
will wire it.

## Definition of done

- `POST /api/v1/convert` — document (upload / URL / `gs://`, matching `/parse`'s
  input modes) plus target format, returns the generated file.
- Rejects unsupported target formats with a clear error, not a 500.
- Key-gated and metered like `/parse`.
- Renderer-level verification, not "it returned 200": a generated DOCX must open
  in Word/LibreOffice and pass `python-docx` run assertions. That is the bar this
  repo holds itself to (`benchmarks/verify_generated.py`), and parse-side checks
  are structurally unable to catch generator defects — an orphaned `styles.xml`
  survived months here for exactly that reason.
- Tell us the contract so the four SDKs and `mcpConvert` can follow.

## What we are doing on our side

Tracked in the companion doc:

1. SDK `convert()` methods in Python/JS/Go/R, once you publish the contract.
2. `mcpConvert` hosted branch calling your endpoint.
3. A hidden lab page measuring whether browser-side generation is viable —
   bundle delta, generation time, fidelity. That route is **not** blocked on
   #644 as previously recorded: the generators' part-builders are already pure,
   so JS can do the zipping.
