# `ParseOutcome` non-throwing variant

**Status**: PLANNED (2026-04-08)
**Source**: Aitana Labs Python SDK feedback (2026-04-09), item #7
**Target version**: v0.10.0 SDK

## Goal

> "We wrap every `client.parse_file(...)` call in a try/except and translate exceptions into our own `ParseOutcome` type that the rest of the pipeline expects. It would be nicer if the SDK gave us that shape directly so we don't have to remember which exception class maps to which error code."

A non-throwing variant of `parse_file` that returns a tagged-union result instead of raising exceptions. The existing throwing API stays unchanged — `parse_file_checked` (or similar) is purely additive.

## Background

Aitana's `ParseOutcome` looks roughly like this (paraphrased from their feedback):

```python
@dataclass
class ParseOutcome:
    ok: bool
    blocks: list[Block] = field(default_factory=list)
    text: str = ""
    error_code: Literal[
        "auth", "quota", "not_found", "unsupported_format",
        "network", "server", "unknown",
    ] | None = None
    error_message: str = ""
```

Their pipeline branches on `outcome.error_code` to decide whether to retry, surface to the user, or skip the file. Try/except is more verbose for this kind of dispatch.

Today the SDK throws:

- `AuthError` (subclass of `DocParseError`, status 401)
- `QuotaError` (status 429)
- `DocParseError` (everything else)

Mapping HTTP status / exception class → `error_code` is straightforward but easy to get wrong if every consumer rolls their own.

## Design

### Python

```python
from ailang_parse import DocParse, ParseOutcome

client = DocParse()
outcome = client.parse_file_checked("report.docx")
if outcome.ok:
    process(outcome.blocks)
else:
    log.warning("parse failed: %s (%s)", outcome.error_code, outcome.error_message)
```

```python
@dataclass
class ParseOutcome:
    ok: bool
    result: ParseResult | None = None
    error_code: ErrorCode | None = None
    error_message: str = ""
    status_code: int = 0  # underlying HTTP status if applicable
```

`ErrorCode` is a `Literal` (or `StrEnum`):

```python
ErrorCode = Literal[
    "auth",                # 401, AuthError
    "quota",               # 429, QuotaError
    "not_found",           # 404
    "unsupported_format",  # 415 / specific server error message
    "network",             # ConnectionError, TimeoutError
    "server",              # 5xx
    "unknown",             # everything else
]
```

`parse_file_checked` is a thin wrapper:

```python
def parse_file_checked(self, filepath, output_format="blocks") -> ParseOutcome:
    try:
        result = self.parse_file(filepath, output_format)
        return ParseOutcome(ok=True, result=result)
    except AuthError as e:
        return ParseOutcome(ok=False, error_code="auth", error_message=str(e), status_code=401)
    except QuotaError as e:
        return ParseOutcome(ok=False, error_code="quota", error_message=str(e), status_code=429)
    except DocParseError as e:
        code = _classify_docparse_error(e)
        return ParseOutcome(ok=False, error_code=code, error_message=str(e), status_code=e.status_code)
    except (requests.ConnectionError, requests.Timeout) as e:
        return ParseOutcome(ok=False, error_code="network", error_message=str(e))
```

`parse_checked` mirrors this for the (no-upload) `parse` call.

### JS

A discriminated union plays nicely with TypeScript narrowing:

```ts
type ParseOutcome =
  | { ok: true; result: ParseResult }
  | { ok: false; errorCode: ErrorCode; errorMessage: string; statusCode?: number };

const outcome = await client.parseFileChecked("report.docx");
if (outcome.ok) {
  console.log(outcome.result.blocks);
} else {
  console.warn(outcome.errorCode);
}
```

### Go

`(result, error)` is already the idiomatic outcome. **No new type.** Document the mapping from `error` shapes to logical codes:

```go
res, err := client.ParseFile(ctx, "report.docx")
switch {
case errors.Is(err, docparse.ErrAuth):
    // auth
case errors.Is(err, docparse.ErrQuota):
    // quota
case err != nil:
    var dpe *docparse.DocParseError
    if errors.As(err, &dpe) && dpe.StatusCode >= 500 {
        // server
    }
}
```

If demand emerges we can add a helper `func ClassifyError(err error) ErrorCode` that returns the same `string` codes used in Python/JS — purely additive, callable from any error site.

### R

R does not have native pattern-matching but we can return an S3 list with a `class` slot:

```r
outcome <- client$parse_file_checked("report.docx")
if (outcome$ok) {
  process(outcome$result)
} else if (identical(outcome$error_code, "auth")) {
  reauth()
}
```

`outcome` is `class = c("ailang_parse_outcome_ok", "ailang_parse_outcome")` or `c("ailang_parse_outcome_err", "ailang_parse_outcome")` so users can dispatch via `inherits()` if they prefer.

## Open questions

1. **Naming**. `parse_file_checked` is the working name. Other candidates: `try_parse_file`, `parse_file_safe`, `parse_file_or_err`. Final choice should match Python's idiomatic style — Python tends to prefer explicit `_checked` suffix over Go-style `Try` prefix.
2. **Should `ErrorCode` be an `enum.StrEnum` or `Literal`?** `StrEnum` (Python 3.11+) gives nicer introspection but raises the minimum Python version. We currently support 3.9+. Prefer `Literal` for now.
3. **`unsupported_format` detection**. The server doesn't currently return a stable error code for "format not supported" — it returns a 400 with a free-text message. We'd either need to (a) string-match the message, which is brittle, or (b) ask the AILANG side to add a stable error envelope. Option (b) is cleaner; track separately.
4. **Should `parse` (the non-upload variant) also get a `_checked` twin?** Yes, for consistency. Same shape, same mapping.

## Out of scope

- Changing the existing throwing API in any way.
- Removing exception classes — they remain the canonical raise targets and `ParseOutcome` is built on top of them.
- Server-side error code standardization (separate AILANG-side work).
- Retry policy (separate doc — `v0_10_0_retry_policy.md`).
