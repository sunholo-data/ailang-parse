# Async DocParse SDK

**Status**: PLANNED (2026-04-08)
**Source**: Aitana Labs Python SDK feedback (2026-04-09), item #3
**Target version**: v0.10.0 SDK

## Goal

Aitana Labs runs the AILANG Parse SDK inside a FastAPI / Cloud Run service that takes uploaded files, partitions them, and fans out to a downstream pipeline. Their feedback:

> "We're running on `asyncio` end-to-end. Today we have to wrap every `client.parse_file(...)` call in `run_in_executor` to keep the event loop responsive. An `AsyncDocParse(api_key=...)` mirroring the sync class would let us drop the executor and use the SDK natively."

The Python SDK is currently sync-only (uses `requests`). JS is already promise-based. Go is sync but the standard concurrency primitives (`context.Context`, goroutines) make wrapping unnecessary. R has no widespread async story.

## Background

`ailang_parse.DocParse` builds on `requests.Session`, which is blocking. Every `parse`, `parse_file`, `keys.list`, `device_auth` call holds the calling thread. When invoked from inside an `async def` FastAPI handler, this blocks the event loop and starves other in-flight requests, hence Aitana's `run_in_executor` workaround.

## Design

### Python — `AsyncDocParse` class (httpx)

A sibling class `ailang_parse.AsyncDocParse` mirrors `DocParse` 1:1 but uses `httpx.AsyncClient` under the hood. Same constructor signature, same methods, all returning awaitables:

```python
from ailang_parse import AsyncDocParse

async with AsyncDocParse(api_key="dp_...") as client:
    result = await client.parse_file("report.docx")
    print(result.blocks)
```

- All sync methods get an `async def` twin: `parse`, `parse_file`, `health`, `formats`, `device_auth`, `key_info`, plus `keys.list / revoke / rotate / usage`.
- The error hierarchy (`DocParseError`, `AuthError`, `QuotaError`) is shared — no separate async-only exceptions.
- Implement `__aenter__` / `__aexit__` so the underlying `httpx.AsyncClient` can be cleanly closed.
- The unwrap logic (`_unwrap`, `_is_auth_error_message`, `_raise_envelope_error`, `_build_parse_result`) is already a static helper on `DocParse` — `AsyncDocParse` reuses it directly to keep behaviour identical.
- `device_auth` is the trickiest method: the sync implementation uses `time.sleep(interval)` inside a poll loop. The async version uses `await asyncio.sleep(interval)` and `httpx.AsyncClient.post`.

### JS / TS

Already async (uses `fetch`). No work needed — the sync/async distinction does not exist here.

### Go

`(*Client).Parse(ctx, ...)` already takes a `context.Context`, so any caller can run it inside an errgroup or goroutine. Adding a separate `AsyncClient` would be redundant and idiomatically wrong. **No change.**

### R

R does not have a widely-adopted async story (the `future` package exists but is non-standard). **Skip for v0.10.0.** Revisit if user demand emerges.

## Open questions

1. **Optional install vs base install?** `httpx` is pure-Python and already a transitive dep of many Python projects, so the cost of bundling it is small. Two options:
   - Make it a hard dep — `pip install ailang-parse` always brings it in.
   - Make it optional — `pip install ailang-parse[async]` opts in.

   Recommendation: hard dep. The size cost is ~600KB and it eliminates the "I imported `AsyncDocParse` and got an `ImportError`" footgun.

2. **Connection pooling between sync and async clients.** If a caller mixes both, should they share a transport? Probably not — it complicates the lifecycle (`__aexit__` would have to know about the sync session). Recommend keeping them fully independent.

3. **`device_auth` interactivity.** The sync version prints a verification URL and optionally calls `webbrowser.open`. The async version should do the same; `webbrowser.open` is non-blocking enough that it does not need its own awaitable wrapper.

## Out of scope

- Rewriting the sync client. Both must coexist; existing callers must not break.
- Streaming responses. The current API returns whole-document JSON; streaming would require an API-level change.
- Other languages (JS already async; Go context-driven; R no demand).
