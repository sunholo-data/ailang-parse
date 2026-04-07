# cran-comments.md

## Test environments

* local: macOS 14, R 4.2.1 — 0 errors, 0 warnings, 0 notes
* (TBD: win-builder, R-hub, GitHub Actions matrix before submission)

## R CMD check results

0 errors | 0 warnings | 0 notes

## Notes for CRAN reviewers

This is a new submission.

The package is an HTTP client + MCP stdio bridge for the AILANG Parse
document parsing API at https://docparse.ailang.sunholo.com . It is
feature-equivalent to the Python (`ailang-parse`), JavaScript
(`@ailang/parse`) and Go (`github.com/sunholo-data/ailang-parse-go`) SDKs
shipped from the same repository.

* All examples that touch the network or require credentials are wrapped
  in `\dontrun{}`.
* Tests do not access the network. Live API tests are gated by
  `Sys.getenv("DOCPARSE_API_KEY")` via `skip_if()`.
* The credential helpers write to a tempdir during testing (the test
  `withr::with_envvar`s `XDG_CONFIG_HOME` / `APPDATA` to a `tempfile()`),
  never to the real user config directory.
* No external system dependencies beyond the declared CRAN packages
  (`httr2`, `jsonlite`, `R6`, `curl`).
