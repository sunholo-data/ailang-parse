# Sprint Plan — M-CLI-INSTALL (`docparse` installable without a git clone)

**Sprint JSON**: `.ailang/state/sprints/sprint_M-CLI-INSTALL.json`
**Design doc**: [`v0_40_0_cli_install_without_clone.md`](v0_40_0_cli_install_without_clone.md)
**GitHub**: #41 · **Target**: v0.40.0 · **Mode**: sequential · **Created**: 2026-09-04

Strictly sequential. M1 is a prerequisite for M2 (V16: the current
`PROJECT_DIR=dirname(SCRIPT_DIR)` breaks the moment the real wrapper moves into
`assets/bin/`), and M3 cannot be exercised end-to-end until M2 has put the files
in the tarball. M5 is the gate that makes the whole thing hold.

**Chicken-and-egg, handled in M3**: the installer fetches the *published*
package, which will not contain `assets/` until v0.40.0 ships. So the installer
takes a `--tarball PATH` escape hatch, used by the local test and by the CI job
on pre-release commits; the published-URL path is exercised by the tag job.

## M1 — Wrapper root discovery (prerequisite)

| Step | Detail | Files |
|---|---|---|
| 1.1 | Replace `PROJECT_DIR="$(dirname "$SCRIPT_DIR")"` with a walk up from `SCRIPT_DIR` for `docparse/main.ail`, bounded by `!= "/"`, with a named error naming the reinstall command | `bin/docparse` |
| 1.2 | Same change in the Windows wrapper if it hardcodes the parent | `bin/docparse.cmd` |
| 1.3 | Verify all four call shapes resolve (repo `bin/` symlink, repo direct, installed prefix, `~/.local/bin` chain) and the orphaned copy exits 1 | scratch harness |
| 1.4 | Checkpoint: `./bin/docparse --check`, `--test` | — |

**Done when**: `--check`/`--test` pass unchanged, and a wrapper copied to a
directory with no `docparse/main.ail` above it fails with the named error rather
than an opaque `ailang` failure.

## M2 — `assets/` carries the CLI

| Step | Detail | Files |
|---|---|---|
| 2.1 | `git mv bin/docparse assets/bin/docparse`; `ln -s ../assets/bin/docparse bin/docparse` | `assets/bin/docparse`, `bin/docparse` |
| 2.2 | `git mv docparse/services/pdf_backends/adapter.py assets/pdf_backends/adapter.py`; symlink back so `adapterPath` keeps resolving | `assets/pdf_backends/adapter.py` + symlink |
| 2.3 | `assets/backends-pyproject.toml` — only `docling` + `liteparse` under an optional `backends` extra | new |
| 2.4 | Confirm `filepath.Walk` skips the symlinks (they match no include rule) and reads the real files under `assets/` | `ailang publish --dry-run` |
| 2.5 | Checkpoint: dry-run tarball **grows** vs the 393 771-byte v0.39.4 baseline; `--check`, `--test` still pass through the symlink | — |

**Done when**: `ailang publish --dry-run` reports a larger tarball and the repo
still behaves identically for contributors.

## M3 — `scripts/install.sh`

| Step | Detail | Files |
|---|---|---|
| 3.1 | Arg parsing: `--version`, `--prefix`, `--tarball`, `--uninstall`, `--help`. Defaults: latest, `~/.local/share/ailang-parse` | `scripts/install.sh` |
| 3.2 | `ailang` preflight — install via the official script if absent, then re-check; hard-fail with the URL if still missing | " |
| 3.3 | Resolve version from `$AILANG_REGISTRY/index.json` (`.packages[] | select(.name=="sunholo/ailang_parse") | .latest`), no `jq` dependency | " |
| 3.4 | Fetch `$AILANG_REGISTRY/packages/sunholo/ailang_parse/<ver>/package.tar.gz`; verify sha256 against `metadata.json`; `--tarball` skips fetch+verify | " |
| 3.5 | Unpack to `PREFIX/<ver>/`; materialise layout: `assets/bin/docparse` → `bin/docparse` (+`chmod +x`, V7), `assets/pdf_backends/*` → `docparse/services/pdf_backends/`, `assets/backends-pyproject.toml` → `pyproject.toml` | " |
| 3.6 | `ailang lock` once in the prefix; explicit error if offline (V6) | " |
| 3.7 | Symlink `~/.local/bin/docparse`; warn if that dir is not on `PATH` | " |
| 3.8 | Preflight report: `pdftotext`, `uv`, ADC — print the exact fix command for each missing one; never auto-install, never fail the install | " |
| 3.9 | `--uninstall`: remove prefix + symlink, leave nothing | " |
| 3.10 | Local test: build a tarball from the working tree, install with `--tarball`, parse a DOCX from a directory that is not the repo | scratch |

**Done when**: `install.sh --tarball <local> --prefix <tmp>` yields a `docparse`
that parses a DOCX, re-running is a no-op, and `--uninstall` leaves no files.

## M4 — Backends as a lean extra

| Step | Detail | Files |
|---|---|---|
| 4.1 | `--install-backends`: `uv sync --project "$PROJECT_DIR" --extra backends`; require `uv`, name the install command if absent | `assets/bin/docparse` |
| 4.2 | Make the V15 dead end actionable: the `no text layer … and OCR found nothing` error names `docparse --install-backends` | `docparse/services/pdf_backend_external.ail` |
| 4.3 | Checkpoint: `--check`, `--test`, `--prove` (error-string change only; no logic touched) | — |

**Done when**: in an installed prefix, `--install-backends` then a text-layer
PDF parse succeeds with no `unstructured`/`llama-parse` in the environment.

## M5 — Install-from-published CI + docs

| Step | Detail | Files |
|---|---|---|
| 5.1 | `.github/workflows/install-smoke.yml`: clean runner, **no repo checkout for the install step**, run the installer, parse a DOCX, assert non-empty JSON | new |
| 5.2 | Second job: `apt-get install poppler-utils`, `--install-backends`, parse a text-layer PDF (exercises the adapter — the file missing from today's tarball) | " |
| 5.3 | Negative test: delete `assets/bin/docparse` from the tarball and assert the install fails. This is the regression gate for the root cause | " |
| 5.4 | README: one-liner first, clone demoted to the contributor path | `README.md` |
| 5.5 | RELEASING.md: `assets/` contents ship; the smoke job gates the tag | `RELEASING.md` |
| 5.6 | CHANGELOG Unreleased entry | `CHANGELOG.md` |
| 5.7 | Sprint JSON `passes` → true | — |

**Done when**: the smoke workflow is green on a branch push using `--tarball`,
and deleting `assets/bin/docparse` turns it red.

## Estimates

| Milestone | Impl | Test/CI | Notes |
|---|---|---|---|
| M1 | ~15 | harness | prerequisite, tiny but load-bearing |
| M2 | ~15 | — | mostly `git mv` + symlinks |
| M3 | ~200 | ~40 | the bulk |
| M4 | ~30 | — | + 3-line error text |
| M5 | ~50 | ~60 | CI yaml + docs |
| **Total** | **~310** | **~100** | ~2 days at recent velocity (6 213 insertions / 32 commits over 14 days) |

**Risk**: low-medium. No `.ail` logic changes (M4.2 is an error string). The
sharp edges are all verified: mode 0644 (V7), lock needs network (V6), root
discovery (V16/V17).

## Out of scope

Homebrew tap, container image, upstream `Mode` plumbing in `CreateTarball`.
Windows beyond keeping `bin/docparse.cmd` working for clone users.
