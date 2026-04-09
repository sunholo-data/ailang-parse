# Configurable retry policy

**Status**: PLANNED (2026-04-08)
**Source**: Aitana Labs Python SDK feedback (2026-04-09), item #9
**Target version**: v0.10.0 SDK

## Goal

> "Cloud Run sometimes blips a 503 on us during cold start. We have to wrap every SDK call in our own retry loop with exponential backoff. The SDK could expose a `retry_policy=` argument and bake this in — with sensible defaults so it Just Works."

A first-class, opt-in retry policy that handles transient failures (network errors, 5xx responses) without callers needing to roll their own backoff loop.

## Background

The current SDK does no retries. Every transient blip (TCP reset, Cloud Run cold-start 503, intermittent DNS failure) propagates to the caller as an exception. This is correct behaviour for non-idempotent state-changing endpoints (`/auth/device/poll`, `/keys/revoke`, `/keys/rotate`) but unhelpful for read-mostly endpoints (`/parse`, `/health`, `/formats`).

Aitana's pattern is the canonical "retry on 5xx + network error with exponential backoff", which is well-understood and small enough to ship in-SDK.

## Design

### The shared shape

```python
from ailang_parse import DocParse, RetryPolicy

policy = RetryPolicy(
    max_attempts=3,
    backoff_base=1.0,        # seconds
    backoff_factor=2.0,      # exponential
    jitter=0.2,              # ±20% random jitter
    retry_on_status=[500, 502, 503, 504],
    retry_on_network_errors=True,
    respect_retry_after=True,  # honour Retry-After header on 429/503
)

client = DocParse(api_key="dp_...", retry_policy=policy)
```

`RetryPolicy.default()` returns a sensible default:

- `max_attempts=3`
- `backoff_base=1.0`, `backoff_factor=2.0` (1s, 2s, 4s)
- `jitter=0.2`
- Retries 5xx + network errors only — never 4xx (including auth failures), never on non-idempotent endpoints.

`RetryPolicy.none()` disables retries entirely (current behaviour).

### Critical design constraints

1. **Never retry non-idempotent endpoints.** Hard-coded list of paths that opt out of retries:
   - `/api/v1/auth/device` (issuing a new device code)
   - `/api/v1/auth/device/poll` (consumes the device code; retrying could double-charge user code lookups)
   - `/api/v1/keys/revoke`
   - `/api/v1/keys/rotate`

   The retry layer checks the request's path before considering a retry.

2. **Never retry 4xx.** A 401 means bad credentials — retrying won't fix it. Same for 400, 404, 415. Auth/quota errors propagate immediately.

3. **Respect `Retry-After`.** Servers return this on 429 and (sometimes) 503. The retry layer parses both delta-seconds and HTTP-date forms and waits at least that long before the next attempt.

4. **Add jitter.** Pure exponential backoff causes thundering-herd on shared upstream failures. Multiplicative jitter (`delay *= random(1-jitter, 1+jitter)`) is enough.

5. **Cap total wait.** A `max_total_wait_seconds` ceiling prevents pathological cases (e.g. server returns `Retry-After: 86400`). Default: 60 seconds.

### Per-SDK implementation

#### Python

`requests` ships with `urllib3.util.Retry`, mountable via `HTTPAdapter`. The `RetryPolicy` dataclass translates into a `Retry` instance and gets installed on `self._session` in `DocParse.__init__`. The non-idempotent endpoint allow-list is enforced by mounting *two* adapters — one with retries on `https://host/api/v1/parse` etc., and one with `Retry(total=0)` on `https://host/api/v1/auth/device/poll`. `urllib3.util.Retry` already handles `Retry-After`.

#### JS

No built-in retry helper for `fetch`. Hand-rolled wrapper around the `_call` / `parse` / `parseFile` methods that catches transient errors and retries with backoff. The wrapper checks the request URL against the non-idempotent allow-list before scheduling a retry.

#### Go

Use `github.com/hashicorp/go-retryablehttp` (small, well-tested) or hand-rolled. The `RetryPolicy` becomes an `http.RoundTripper` wrapping the existing `*http.Client`. Same allow-list check.

#### R

Hand-rolled. `httr2` already has `req_retry()`, which takes a backoff function and a retry-status filter. The `RetryPolicy` translates directly into `httr2::req_retry(req, max_tries=..., backoff=..., is_transient=...)`. Apply only to non-state-changing requests.

### Per-call override

```python
# Override the client default for a single call
result = client.parse_file("huge.pdf", retry_policy=RetryPolicy(max_attempts=10))
```

This is more flexible than client-only config but adds API surface. **Recommendation**: ship client-level config first; add per-call override only if requested.

## Open questions

1. **Should retries respect `context.Context` (Go) / `signal: AbortSignal` (JS) / `timeout=` (Python httpx)?** Yes — a cancelled context should abort the retry loop immediately. This is automatic for `urllib3.Retry` and `go-retryablehttp` but needs explicit handling in hand-rolled implementations.
2. **Per-call override or client-level only?** Client-level is simpler. Per-call is more flexible but adds API surface. Recommend client-level only for v0.10.0.
3. **Logging.** Should retries emit a log line ("retrying after 503, attempt 2/3 in 1.4s")? Useful for debugging, noisy in production. Probably gated behind a `verbose=True` flag on `RetryPolicy`.
4. **How does retry interact with `ParseOutcome`?** If retries are exhausted and the final attempt still fails, the outcome's `error_code` reflects the *final* error. The retry count is not surfaced — should it be? (Probably not for v0.10.0; track only if asked.)
5. **Idempotency keys.** RFC 9457-style idempotency keys would let us safely retry currently-non-idempotent endpoints. Requires server-side support — out of scope for this change but worth a follow-up.

## Out of scope

- Circuit breakers (open/closed/half-open state machine).
- Request hedging (firing two parallel requests and taking the first response).
- Server-side idempotency keys.
- Per-call retry overrides (defer to user feedback).
