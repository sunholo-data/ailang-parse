# `POST /api/v1/convert` — the contract

**From**: `sunholo/docparse` (private, hosted API) — this is the reply the
[handoff](./HANDOFF_docparse_api_convert.md) asked for.
**Status**: LIVE on dev as of 2026-08-11 (docparse v0.16.0, `ailang_parse` 0.31.0).
**Dev base**: `https://ailang-dev-docparse-api-ejjw6zt3bq-ew.a.run.app`

Build the four SDK `convert()` methods and the `mcpConvert` hosted branch
against what follows. It is discoverable at runtime too — `GET /api/v1/capabilities`
now carries a `convert` endpoint entry with the same schema, and the endpoint is
in `/api/_meta/openapi.json`.

## Request

Same input modes as `/api/v1/parse`, plus `target`. Accepts
`application/json` or `multipart/form-data`.

| field | required | notes |
|---|---|---|
| `apiKey` | yes | `dp_` key, same gate as `/parse` |
| `target` | yes | `html md qmd docx pptx xlsx odt odp ods` |
| `filepath` | one of | multipart upload (field name **must** be `filepath`), or a `sample_id` string in JSON |
| `sourceUrl` | one of | public/signed `https://` URL, fetched server-side, per-tier size cap |
| `gcsRef` | one of | `gs://bucket/path`, Business tier only |
| `pdfBackend` | no | same semantics as `/parse` (`""`, `pdftotext`, `docling`, `liteparse`, `ai`) |

Precedence when several are supplied: `sourceUrl` > `gcsRef` > `filepath` —
identical to `/parse`.

`target` is normalised before validation: case-insensitive, a leading dot is
stripped, and `markdown` → `md`, `htm` → `html`, `quarto` → `qmd`. SDKs should
pass the bare name and let the server normalise rather than validating locally,
so a future target does not require an SDK release.

```bash
curl -X POST $BASE/api/v1/convert \
  -F 'filepath=@report.docx' -F 'target=pptx' -F 'apiKey=dp_...'

curl -X POST $BASE/api/v1/convert -H 'Content-Type: application/json' \
  -d '{"filepath":"sample_docx_formatting","target":"html","apiKey":"dp_..."}'
```

## Response

**The generated file comes back inside JSON, not as a binary body.** serve-api
response bodies are strings, so there is no route to a raw
`application/vnd.openxmlformats-...` body today. Like every `@nowrap` route
here, the body arrives wrapped as `{"result": "<stringified inner JSON>"}` —
SDKs already unwrap this for `/parse`; same handling applies.

Inner object:

```json
{
  "status": "success",
  "request_id": "req_e4573f8b6d1c2a90",
  "source_format": "zip-office",
  "source_subtype": "docx",
  "target": "pptx",
  "filename": "report.pptx",
  "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "encoding": "base64",
  "size_bytes": 6322,
  "content": "UEsDBBQ..."
}
```

| field | meaning |
|---|---|
| `source_format` | detected input **family** (`zip-office`, `zip-odf`, `csv`, `markdown`, `html`, …) |
| `source_subtype` | concrete input extension (`docx`). `source_format` alone cannot tell docx from pptx |
| `target` | the **normalised** target, echo this rather than what was sent |
| `filename` | input stem + target extension — a suggested save name, not a server path |
| `content_type` | MIME type to save the decoded bytes as |
| `encoding` | **`base64`** for `docx pptx xlsx odt odp ods`; **`utf8`** for `html md qmd` |
| `size_bytes` | decoded size; verified equal to the real payload length by our tests |
| `content` | the document, encoded per `encoding` |

### `encoding` is load-bearing

Branch on it. Do not infer it from the target and do not assume base64 — the
three text targets are returned as readable UTF-8 precisely so `curl | jq -r
.content` is useful for html/md/qmd.

```python
raw = base64.b64decode(d["content"]) if d["encoding"] == "base64" else d["content"].encode("utf-8")
```

A reasonable SDK shape is `convert(...) -> bytes` (decode internally, always
hand the caller bytes) with the metadata alongside. That keeps `encoding` an
implementation detail of the SDK rather than of every user's code.

## Errors

Typed error envelope, same shape as `/parse`
(`{"error": {"code", "message", "retryable", "suggested_fix", "details"}, "request_id"}`).

`UNSUPPORTED_TARGET_FORMAT` · `INVALID_API_KEY` · `QUOTA_EXCEEDED` ·
`INPUT_NOT_FOUND` · `FORMAT_NOT_AVAILABLE` · `CONVERSION_FAILED` ·
`TIER_UPGRADE_REQUIRED` · `INVALID_GCS_REF` · `FORBIDDEN` ·
`GCS_DOWNLOAD_FAILED` · `INVALID_SOURCE_URL` · `SOURCE_FETCH_FAILED` ·
`FILE_TOO_LARGE`

A bad target is `UNSUPPORTED_TARGET_FORMAT` with the supported list in
`details.supported`, rejected before any fetch, parse or quota burn — never a
500. `CONVERSION_FAILED` (HTTP 500, `retryable: true`) is the only path that
means the generator itself failed.

## Response headers

`X-Request-Id` · `X-AilangParse-Format` · `X-AilangParse-Target` ·
`X-AilangParse-Encoding` · `X-DocParse-Tier` · `X-DocParse-Quota-Remaining-{Day,Month,Ai}`

## Metering — answering the open question

**One request per conversion**, on the same counters and the same key gate as
`/parse`. Output size does not affect the charge. The AI sub-quota is consumed
only when the **source** format needs AI (pdf, images); generation itself is
pure compute.

Of the three candidates in [`v0_32_0_generation_surfaces.md`](./v0_32_0_generation_surfaces.md)
this is "per generated document", chosen because it is the only one that can be
changed later: per-byte or allowance pricing can be layered onto a per-document
counter, but cannot be reconstructed from a counter that was never recorded.
`size_bytes` is logged per request, so the data to evaluate per-byte pricing is
accumulating from day one whether or not we adopt it.

AI generation (`--generate --prompt`) is deliberately **not** on this endpoint —
different cost profile, cannot share this price or rate limit.

## `mcpConvert`

The hosted branch should POST the above and return the decoded bytes, instead of
gating local work behind a key. Everything it needs is in the response:
`filename` for the save name, `content_type` for the MIME type, `encoding` to
decode.

## Two things for your side

1. **ODF `mimetype` is DEFLATED where OASIS ODF 1.2 part 3 §3.3 requires STORED.**
   Present in odt/odp/ods from the CLI too, so it is not a hosted-API artifact.
   `std/zip.createArchive` takes no compression method, so no generator can
   currently satisfy it — it needs an ailang-core change first. LibreOffice,
   python-docx/pptx and openpyxl all accept the files regardless, so this is a
   conformance gap rather than a breakage; strict ODF validators and `file(1)`
   magic sniffing will complain. Our suite warns rather than fails on it.

2. **`ailang_parse` 0.31.0 is a breaking change for record literals.**
   `TextBlock`/`HeadingBlock` gained `runs`, `ListBlock` gained `itemRuns`, so
   any consumer constructing those literals directly fails to type-check on
   upgrade. `mkText`/`mkHeading`/`mkList` are the fix and the package already
   documents them as preferred — worth saying so in the release notes, since the
   type error points at the literal rather than at the constructor.

## Verification standard met

`tests/test_convert_api.sh` in the docparse repo drives the endpoint over HTTP
for all nine targets and opens every artifact with the library that actually
reads it: 105 checks covering ZIP integrity, XML well-formedness of every part,
python-docx run assertions (bold/italic/underline survive the round trip),
python-pptx, openpyxl, and ODF package conformance, plus an opt-in LibreOffice
headless pass that opens all six container formats. `tests/test_e2e_dev.sh`
section 8 repeats a subset against the live deployment on every deploy.

Warm conversion latency on dev is ~0.2s; cold start ~47s.
