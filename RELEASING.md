# Releasing — pending work, blocked on GitHub Actions

**Written 2026-08-06.** Three releases are built, committed and validated but
**not tagged**, because GitHub Actions was in `major_outage` for the whole
session. Nothing here needs code changes; it needs Actions to come back.

## Current state

- Working tree clean, `main` pushed.
- `ailang.toml` and `pyproject.toml` both at **0.27.0**.
- CHANGELOG has all three sections (v0.25.0, v0.26.0, v0.27.0).
- `./bin/docparse --check`: 35 modules clean.
- `ailang publish --dry-run --allow-dotted-tool-names`: passes, 43 exports
  including `docparse/services/chunker`, tarball builds.

15 commits since `v0.22.2`, spanning three logical releases:

| version | what |
|---------|------|
| v0.25.0 | PDF annotation anchoring — highlights report the text they cover; also fixed the default backend dropping every annotation, an off-by-one page number, and an over-broad `/ObjStm` bail-out |
| v0.26.0 | Email attachments — PDF extraction with automatic OCR fallback (`pdftotext` → `docling`), plus a guard against docling's `<!-- image -->` false success |
| v0.27.0 | Document chunking (`docparse/services/chunker`) — four deterministic strategies |

## When Actions is healthy

Do **not** run `ailang publish` by hand — tag-triggered CI does it, and a manual
run races the workflow and turns the release red.

```bash
# 1. Confirm CI is green on main first
gh run list --workflow=ci.yml --branch=main --limit 1

# 2. Tag each release at the commit where its version was current.
#    Tags can point at specific commits, so the sequence still works even
#    though the tree has since moved on to 0.27.0.
git tag v0.25.0 ad68b73    # effects fix; ailang.toml was 0.25.0 here
git tag v0.26.0 8bfd458    # --deep CLI routing fix; ailang.toml was 0.26.0
git tag v0.27.0 HEAD       # chunker

git push origin v0.25.0 v0.26.0 v0.27.0
```

Each tag fires `publish-ailang.yml`, which re-runs `./bin/docparse --check`
before uploading. Watch them land before moving on.

### If a tag fails validation

The publish workflow builds AILANG from the **dev branch**, which moves. A green
CI run does not guarantee a green publish an hour later. Re-run the failed job
rather than retagging.

## Immediately after publishing

`email-parse` currently depends on this repo by **path**, which works locally
and breaks for anyone else:

```toml
# email-parse/ailang.toml
"sunholo/ailang_parse" = { path = "../ailang-parse" }   # ← change this
"sunholo/ailang_parse" = { version = "0.27.0" }         # ← to this
```

Then `ailang lock` in `email-parse` and commit. Until that swap happens, M7
attachment chunking only builds on this machine.

## Known-failing things that are NOT release blockers

- **4 contract-verification errors** (`emlGetAttachment*` in `main.ail`,
  `emptyParseState`/`flushList` in `markdown_parser.ail`) — pre-existing, in
  code untouched by these releases.
- **16 stale golden files** (12 `.eml`, 2 `.epub`, 2 image-related `.docx`) —
  drift that predates this work. Deliberately reverted rather than absorbed, so
  the diffs stay attributable. Worth a separate pass.
- **Open upstream issues** filed during this work, none blocking:
  - [ailang#607](https://github.com/sunholo-data/ailang/issues/607) — `exit()`
    inside batch mode panics the whole run
  - [ailang#609](https://github.com/sunholo-data/ailang/issues/609) —
    `std/bytes` has `fromInts` but no `toInts`, blocking Latin-1 → UTF-8
    transcoding of RFC 2047 headers
  - [ailang#610](https://github.com/sunholo-data/ailang/issues/610) — retaining
    values from `mapE` over query rows costs ~49x a range loop

## What ships in the package

`ailang publish` bundles `ailang.toml`, every `*.ail`, `AGENT.md`, and
**everything under `assets/`** — nothing else. The CLI wrapper
(`assets/bin/docparse`), the PDF adapter (`assets/pdf_backends/adapter.py`) and
`assets/backends-pyproject.toml` are real files there, with symlinks at their
historical paths for the clone workflow.

If you move any of those back out of `assets/`, they silently vanish from every
published version — which is exactly what happened to `bin/docparse` and the PDF
adapter up to v0.39.4. The `install-smoke` workflow is the gate: it installs
from the tarball with no checkout and fails if `assets/bin/docparse` is missing.
Do not disable it to get a release out.
