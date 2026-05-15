# Design Doc: SDK Ergonomics — Error Headers, GCS URIs, Block Flattening (v0.20.0)

**Status**: Planned
**Date**: 2026-05-15
**Author**: Mark + Claude
**Source**: Feedback from `multivac-system-services` after refactoring its chunker onto the `ailang-parse` Python SDK (message `msg_20260515_173649_4dbe12bd`, correlation `msg_20260515_171405_7f31981f`). Two new files in that project — `chunker/ailang_parse_client.py` (~115 LOC wrapping `DocParse` with GCS signing + retry) and `chunker/blocks_to_chunks.py` (~230 LOC flattening Block ADT into embedder chunks) — represent boilerplate that every internal Sunholo consumer (multivac chunker, aisearch, aitana, extractor) currently rewrites. This doc pulls that boilerplate into the SDK.

---

## Problem

The Python, JS, and Go SDKs solve the "talk to docparse-api" problem but stop short of three integration concerns that every downstream consumer hits:

1. **Errors lose HTTP headers.** On a non-2xx response the SDKs raise an error whose only payload is `(message, status_code)`. The headers — `X-Request-Id`, `X-AilangParse-Replayable`, `X-DocParse-Tier`, quota counters — are dropped on the floor before the exception is constructed. Consumers cannot correlate failures with `docparse-api` logs without parsing the response body, and cannot honour the server's `Replayable: true` hint when deciding whether to retry a 500. This forces every retry layer into the same conservative shape: "retry 502/503/504, never 500" — wasting retries the server explicitly said were safe to attempt.

2. **Error constructors are inconsistent.** `DocParseError` accepts kwargs (`request_id=`, `suggested_fix=`, `details=`); `AuthError` and `QuotaError` use positional arguments. Raise sites cannot pass `request_id` uniformly across error types, so downstream handlers always have to type-narrow before reading metadata.

3. **`timeout=60` is a footgun for AI parses.** All three SDKs default to a 60-second timeout. PDF parses through Gemini routinely exceed this. Every internal consumer raises it to 120s or 300s independently. The default should not be the wrong default.

4. **No first-class GCS URI parser.** Every internal Sunholo consumer holds a `gs://bucket/key` URI and needs to mint a v4 signed GET URL before calling `parse_url`. The signing dance — load credentials, get bucket+blob, `generate_signed_url(version="v4", expiration=...)` — is ~30 LOC and identical across consumers. Five projects, one function rewritten five times.

5. **Block ADT → RAG chunks is reinvented every time.** The `Block` ADT is rich (text, headings, tables, lists, images, sections, change blocks) but every embedder/RAG consumer flattens it into `[{"text": ..., "metadata": {...}}]` with the same questions: tables → row-per-chunk with header context? embed image descriptions? section_path tracking? max chars per chunk? The multivac chunker's `blocks_to_chunks.py` is 230 LOC of this; aisearch will write the same; aitana will write the same.

6. **Retry policy is reinvented every time.** Constructor takes no retry config. Every consumer wraps `DocParse` in its own retry loop (~40 LOC) with the same shape — exponential backoff over a fixed set of statuses. (Depends on #1: a "respect Replayable" retry needs the header on the exception first.)

The first three are bugs masquerading as opinions; the last three are features the SDK is mature enough to take on.

---

## Non-Goals

- **Async clients.** All three SDKs are sync. Async is its own design discussion (FastAPI consumers want it, gRPC consumers don't care). Out of scope here.
- **An "SDK plugin" registry.** GCS/S3/Azure URI handling lands as a bounded set of optional extras — not a generic protocol-handler interface. We add what consumers actually use.
- **A pluggable chunking algorithm DSL.** `flatten()` ships with a fixed policy struct + escape-hatch callbacks. No expression language, no YAML config.
- **Retries with circuit breakers / token buckets.** A simple exponential-backoff + Replayable-aware retry covers the observed need. Anything fancier is a wrapper concern.
- **Cross-SDK feature parity in this release.** Python ships first because that's where the feedback came from and where the highest-LOC internal consumers live. JS + Go track in v0.21.0.

---

## Part 1: Errors carry HTTP metadata

### Current shape

```python
# client.py:96-101 (parse), 143-148 (parse_file) — identical
if resp.status_code == 401:
    raise AuthError("Invalid or missing API key", 401)
if resp.status_code == 429:
    raise QuotaError("Quota exceeded")
if resp.status_code >= 400:
    raise DocParseError(f"API error: {resp.status_code} {resp.text}", resp.status_code)
```

The `ResponseMeta.from_headers` machinery already exists ([types.py:178-212](sdks/python/ailang_parse/types.py#L178-L212)). It is only consulted on the success path. On error, the same headers are discarded.

### Target shape

A single helper that raises the right exception type from the response, populating headers regardless of status:

```python
def _raise_for_response(resp: requests.Response) -> None:
    if resp.status_code < 400:
        return
    meta = ResponseMeta.from_headers(dict(resp.headers))
    body = _try_json(resp)
    msg = body.get("error", resp.text) if isinstance(body, dict) else resp.text
    details = body if isinstance(body, dict) else None
    suggested = body.get("suggestedFix", "") if isinstance(body, dict) else ""

    if resp.status_code == 401:
        raise AuthError(msg or "Invalid or missing API key",
                        status_code=401, request_id=meta.request_id,
                        suggested_fix=suggested, details=details)
    if resp.status_code == 429:
        raise QuotaError(msg or "Quota exceeded",
                         tier=meta.tier, request_id=meta.request_id,
                         details=details)
    raise DocParseError(f"API error: {resp.status_code} {msg}",
                        status_code=resp.status_code,
                        request_id=meta.request_id,
                        suggested_fix=suggested,
                        details=details,
                        replayable=meta.replayable)
```

Call sites collapse to `_raise_for_response(resp)`.

### Part 1a: Align `AuthError` / `QuotaError` constructors with `DocParseError`

```python
class AuthError(DocParseError):
    def __init__(self, message: str = "Invalid or missing API key", **kwargs):
        kwargs.setdefault("status_code", 401)
        super().__init__(message, **kwargs)

class QuotaError(DocParseError):
    def __init__(self, message: str = "Quota exceeded", *,
                 tier: str = "", used: int = 0, limit: int = 0, **kwargs):
        kwargs.setdefault("status_code", 429)
        super().__init__(message, **kwargs)
        self.tier, self.used, self.limit = tier, used, limit
```

`DocParseError` gains a `replayable: bool = False` field to carry the header through. Both attribute access (`err.request_id`, `err.replayable`, `err.tier`) and `__dict__` survive intact, so existing `except` blocks that only read `status_code` are unaffected.

### Compatibility

- Existing positional `AuthError("msg", 401)` calls keep working because `AuthError.__init__` accepts a positional `message` and falls back to a default `status_code`.
- `DocParseError.__init__` already accepts kwargs — no signature change.
- New attributes (`request_id`, `replayable`, `details`, `suggested_fix`) are additive; absence is `""` / `False` / `None`, same as today.

---

## Part 2: Default timeout 120s; document the AI case

Change [client.py:49](sdks/python/ailang_parse/client.py#L49) from `timeout: int = 60` to `timeout: int = 120`. Mirror in [sdks/js/src/client.ts:38](sdks/js/src/client.ts#L38) (`60000` → `120000`) and [sdks/go/client.go:162](sdks/go/client.go#L162) (`60 * time.Second` → `120 * time.Second`).

Add to each SDK's `parse_url` / `parse_file` docstring:

> AI-backed formats (PDF, images) routinely exceed the default 120s timeout
> on large documents. Set `timeout=300` (or higher) on the client for those
> workloads.

This is a behaviour change. Note it in `CHANGELOG.md` under "Breaking — minor": code that explicitly relied on a 60s upper bound (rare — usually the symptom of a missing retry budget elsewhere) needs to set `timeout=60` explicitly.

---

## Part 3: `parse_gs_uri(gs_uri, *, ttl=900)` — optional GCS extra

### Shape

```python
from ailang_parse import DocParse
client = DocParse()  # parse_gs_uri uses Application Default Credentials by default
result = client.parse_gs_uri("gs://my-bucket/path/to/doc.pdf", ttl=900,
                              output_format="markdown+metadata")
```

Internally:

```python
def parse_gs_uri(self, gs_uri: str, *, ttl: int = 900,
                 output_format: str = "blocks",
                 credentials: Optional["google.auth.credentials.Credentials"] = None
                 ) -> ParseResult:
    """Sign a gs:// URI and parse the document via the API.

    Requires the optional `google-cloud-storage` extra:
        pip install ailang-parse[gcs]
    """
    try:
        from google.cloud import storage
    except ImportError as e:
        raise ImportError(
            "parse_gs_uri requires the 'gcs' extra: "
            "pip install ailang-parse[gcs]"
        ) from e

    bucket, blob_name = _parse_gs_uri(gs_uri)  # "gs://b/k" -> ("b", "k")
    sc = storage.Client(credentials=credentials)
    blob = sc.bucket(bucket).blob(blob_name)
    signed = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=ttl),
        method="GET",
    )
    return self.parse_url(signed, output_format=output_format)
```

### Packaging

`pyproject.toml` gains:

```toml
[project.optional-dependencies]
gcs = ["google-cloud-storage>=2.0,<4"]
s3 = ["boto3>=1.28,<2"]   # parse_s3_uri lands behind same extra; ship in v0.20.0 or v0.20.1
```

No new runtime dep for users who don't install the extra. Importing `parse_gs_uri` works without the extra; *calling* it raises `ImportError` with a clear fix message.

### Auth resolution

Default to ADC (`storage.Client()`). Accept an explicit `credentials=` for callers (like multivac) that already hold a credential object. This matches how `google-cloud-aiplatform` exposes auth.

### Why this is the right call

Every internal consumer signs URIs the same way. The 30 LOC of signing logic is identical across multivac chunker, aisearch ingestion, aitana doc-import, and (eventually) extractor. Pulling it into the SDK once removes one boilerplate file from each project. The optional extra means non-GCS users carry no `google-cloud-storage` weight.

`parse_s3_uri(s3_uri, *, ttl=900)` follows the same pattern behind a `[s3]` extra. Ship together if the AWS code is ready; otherwise land GCS in v0.20.0 and S3 in v0.20.1.

---

## Part 4: `ParseResult.flatten(policy)` — Block ADT → RAG chunks

This is the meatiest change in the doc. The Block ADT is rich; every embedder consumer flattens it. We ship one canonical flatten with composable callback escape hatches.

### Target API

```python
from ailang_parse import FlattenPolicy

chunks = result.flatten(FlattenPolicy(
    max_chunk_chars=4000,
    embed_images=True,        # ImageBlock -> chunk using .description
    embed_changes=True,       # ChangeBlock -> chunk with author metadata
    on_table="row",           # "row" | "whole" | callable(block) -> List[Chunk]
    section_path=True,        # tag each chunk with its heading ancestry
))
# chunks: List[Chunk]
# Chunk: {"text": str, "metadata": {block_type, section_path, table_id?, change_author?, ...}}
```

### Why a dataclass policy, not kwargs

The policy will grow. We've already identified 6 knobs from multivac alone; aisearch will add more (`include_headers_as_chunks`, `merge_adjacent_text`). A dataclass keeps the API stable as knobs land; kwargs on `flatten()` would force a breaking change every time.

### Why callbacks, not a config DSL

`on_table` is the proof case. "Row per chunk" handles 80%. "Whole table" handles another 15%. The remaining 5% (table with merged header cells that need flattening, table where caption matters) is consumer-specific and not worth encoding as a policy enum. Accept `Callable[[Block], List[Chunk]]` as an override and stop.

### Shape of `Chunk`

```python
@dataclass
class Chunk:
    text: str
    metadata: ChunkMetadata

@dataclass
class ChunkMetadata:
    block_type: str          # "text" | "heading" | "table_row" | "image" | "change" | ...
    section_path: List[str]  # e.g., ["Introduction", "Background"]
    block_index: int         # position in the original .blocks list (for round-tripping)
    table_id: Optional[str] = None      # set on table_row chunks
    row_index: Optional[int] = None     # set on table_row chunks
    change_author: Optional[str] = None # set on change chunks
    image_mime: Optional[str] = None    # set on image chunks
```

The `metadata` shape is intentionally JSON-friendly: every consumer feeds it straight into Vertex/Pinecone/Chroma metadata fields without re-mapping.

### Default policy

```python
DEFAULT_FLATTEN_POLICY = FlattenPolicy(
    max_chunk_chars=2000,
    embed_images=False,        # safer default — images often have no description
    embed_changes=False,       # most RAG ingestion ignores tracked changes
    on_table="row",
    section_path=True,
)
```

`result.flatten()` (no arg) uses these defaults. The multivac chunker's policy ships as a recipe in the docs.

### Scope

Python only in v0.20.0. JS + Go track in v0.21.0 once the API has burned in with one real consumer (multivac).

---

## Part 5: `RetryPolicy` on the constructor

### Shape

```python
from ailang_parse import DocParse, RetryPolicy

client = DocParse(
    retry=RetryPolicy(
        max_retries=3,
        retryable_statuses={502, 503, 504},
        respect_replayable=True,   # also retries 5xx when X-AilangParse-Replayable: true
        backoff_base=2.0,
        backoff_max=30.0,
    ),
)
```

Default: `RetryPolicy(max_retries=0)` — opt-in. Existing callers see no behaviour change.

### Why opt-in

Auto-retry without explicit consent is the wrong default for an SDK. Idempotency assumptions vary by endpoint (POST `/api/v1/parse` *is* idempotent server-side, but a wrapper may have other reasons not to retry). Users who want retries say so; users who don't aren't surprised.

### Implementation note

Lands *after* Part 1. `respect_replayable=True` reads `err.replayable` on the raised exception, which only exists once Part 1 is merged. Until then, only the status-set path is meaningful.

---

## Cross-SDK parity

| Part | Python (v0.20.0) | JS (v0.20.0 / v0.21.0) | Go (v0.20.0 / v0.21.0) |
|------|------------------|-------------------------|--------------------------|
| 1. Errors carry headers | v0.20.0 | v0.20.0 | v0.20.0 |
| 1a. Constructor parity  | v0.20.0 | n/a (TS shape already aligned) | v0.20.0 |
| 2. Timeout default 120s | v0.20.0 | v0.20.0 | v0.20.0 |
| 3. `parse_gs_uri` extra | v0.20.0 | v0.21.0 | v0.21.0 |
| 4. `flatten(policy)`    | v0.20.0 | v0.21.0 | v0.21.0 |
| 5. `RetryPolicy`        | v0.20.0 | v0.21.0 | v0.21.0 |

Parts 1, 1a, and 2 ship to all three SDKs in v0.20.0 — they are bugs, and the fixes are small. Parts 3–5 ship Python-first because Python is where the high-LOC internal consumers live; JS and Go follow once the API has settled.

---

## Risks and migration

- **Error attribute access on old code paths.** Code that catches `DocParseError` and reads only `status_code` is unaffected. Code that uses `repr()` on the exception will see new fields — cosmetic only.
- **Timeout bump breaks a tight-deadline use case.** Mitigation: changelog note, `timeout=60` is still settable explicitly.
- **`flatten()` API drift.** The risk is shipping a `FlattenPolicy` we later regret. Mitigation: keep the policy small in v0.20.0 (the six fields above), grow it from real consumer requests, document that callbacks are the escape hatch.
- **`google-cloud-storage` as an optional dep.** Risk is users running `pip install ailang-parse` and being surprised `parse_gs_uri` raises. Mitigation: the `ImportError` message names the exact extra to install; the README documents the extras matrix.

---

## Acceptance criteria

- [ ] `DocParseError.request_id` populated on every non-2xx response in Python SDK
- [ ] `AuthError("msg", 401)` (positional) still works; `AuthError(message="msg", request_id="r")` (kwargs) also works
- [ ] Python SDK default timeout is 120s; JS + Go match
- [ ] `pip install ailang-parse` works without `google-cloud-storage`; `pip install ailang-parse[gcs]` enables `parse_gs_uri`
- [ ] `result.flatten()` returns `List[Chunk]` for at least: TextBlock, HeadingBlock, TableBlock (row mode), ListBlock, SectionBlock (recursive with section_path), ChangeBlock (when enabled), ImageBlock (when enabled)
- [ ] `DocParse(retry=RetryPolicy(max_retries=3))` retries on 502/503/504; `respect_replayable=True` also retries 500 when header is set
- [ ] CHANGELOG entry covers timeout default change as "Breaking — minor"
- [ ] One multivac-equivalent example in `sdks/python/examples/` showing GCS-URI → flatten → embed flow under 30 LOC
- [ ] Reply to `msg_20260515_173649_4dbe12bd` with link to merged design doc

---

## References

- Feedback message: `msg_20260515_173649_4dbe12bd` (multivac-system-services → docparse)
- Correlation context: `msg_20260515_171405_7f31981f` (multivac doc-pipeline migration)
- Current Python SDK: [sdks/python/ailang_parse/client.py](sdks/python/ailang_parse/client.py), [types.py](sdks/python/ailang_parse/types.py)
- Current JS SDK: [sdks/js/src/client.ts](sdks/js/src/client.ts)
- Current Go SDK: [sdks/go/client.go](sdks/go/client.go)
- Consumer code shape (referenced but not in this repo): `multivac-system-services/chunker/ailang_parse_client.py`, `multivac-system-services/chunker/blocks_to_chunks.py`
