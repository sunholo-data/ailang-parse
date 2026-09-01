# `ailang_parse_version` on `/health` and `/capabilities`

**Status**: PLANNED (2026-09-01)
**Source**: step 2 of [`HANDOFF_docparse_redeploy.md`](../../implemented/v0_40_0/HANDOFF_docparse_redeploy.md),
claims A6 and A7 of [`v0_40_0_convert_reference_doc_api.md`](../../implemented/v0_40_0/v0_40_0_convert_reference_doc_api.md).
Carved out when the rest of that work shipped, so the one open item does not
disappear into an implemented doc.
**Lands in**: the private `sunholo/docparse` repo (both endpoints are served
from there). Nothing to build in this repo.

## The complaint, which was a real defect and not a misreading

The `aitana-platform` reporter could not determine which parser version was
serving their requests, and said so. Four version series are in play:

| series | example | what it is |
|---|---|---|
| hosted service | `0.9.0` | `sunholo/docparse`, the deployment repo. `/api/v1/health.version` |
| SDK | `0.12.0` | PyPI `ailang-parse`, npm `@ailang/parse`, Go `ailang-parse-go`, CRAN `ailangparse` — all four move together |
| **AILANG module / registry package** | `0.39.3` | `sunholo/ailang_parse`, this repo. **The one that carries every parser and generator fix** |
| AILANG runtime | `v0.34.0` | the compiler running it. `/api/v1/health.ailang_commit` |

`/health` exposes the first and the last — the two *least* useful for
answering "is the fix I need live?". The one series that carries parser fixes
is invisible from the outside, so the only way to answer that question today
is to read a Cloud Build log or ask us.

It cost the reporter a detour once, and it cost a second one on 2026-09-01: a
probe of prod read `ailang_commit: v0.34.0` and recorded the deployed *package*
as "still six minors short of 0.39.2", because `v0.34.0` is ambiguous between
two series that both have a v0.34.0. The deployed package was in fact 0.39.2.
A version field nobody can misread would have prevented both.

## The change

Add `ailang_parse_version` to:

1. `GET /api/v1/health` — beside `ailang_commit`, which should keep its name so
   nothing breaks, even though `ailang_runtime_version` would have been the
   clearer one. Consider adding the clearer alias alongside it.
2. the `GET /api/v1/capabilities` payload — the reporter checked capabilities
   first, and an agent doing discovery has no reason to also fetch `/health`.

## Where the value comes from

Do **not** hardcode it. A constant that must be bumped by hand is a constant
that will report last release's number, which is worse than reporting nothing:
it converts "I can't tell" into "I was told, wrongly".

`ailang.lock` is copied into the image next to `ailang.toml` and already pins
the resolved version, so read it at startup:

```json
{"packages": [{"name": "sunholo/ailang_parse", "version": "0.39.3", ...}]}
```

Read once at boot rather than per request — it is FS work on a hot path
otherwise, and the value cannot change while the process lives.

## Definition of done

- `/api/v1/health` and `/api/v1/capabilities` both report
  `ailang_parse_version` matching `ailang.lock` on dev, test and prod.
- The value tracks a dependency bump with no source edit: bump the pin,
  redeploy, and the endpoint reports the new number.
- A caller can answer "is parser fix X live?" from one unauthenticated GET.
