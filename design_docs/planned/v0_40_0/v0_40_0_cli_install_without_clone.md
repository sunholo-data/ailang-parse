# `docparse` installable without a git clone

**Status**: PLANNED (2026-09-04)
**Priority**: P0
**Target**: v0.40.0
**Estimated**: 2 days (Phase 1–2), +1 day (Phase 3)
**Source**: while adding local-CLI guidance to `sunholo-data/docparse-skill`
(commit `7457398`), every documented route to the local CLI turned out to
require `git clone`. The skill now has to tell users "if you won't clone, the
local CLI is unavailable to you" — which pushes exactly the confidential-document
cases onto the hosted API, the one workload the local CLI exists to serve.

## Scope

Make the local `docparse` CLI installable with one command on a machine that has
never cloned this repo, and close the latent bug underneath it: the published
registry package ships parser source that **cannot run its own PDF backends**,
because the Python adapter is not in the tarball.

In scope:

1. The registry package carries the CLI wrapper, the PDF adapter and a minimal
   backend `pyproject.toml` (via `assets/`).
2. A `curl | sh` installer that materialises a runnable prefix from the
   published package.
3. PDF backend deps become a normal opt-in extra rather than
   "`uv pip install` into the clone's venv".
4. A CI job that installs **from the published artifact** on a clean runner.

Out of scope, deliberately:

- Replacing the clone for *contributors*. `git clone` stays the dev workflow;
  this is about consumers.
- A single self-contained binary. `docparse` orchestrates the `ailang` runtime,
  which is a separate Go binary with its own installer; merging them is a
  different project.
- Vendoring poppler. `pdftotext` stays a system dependency we detect and report.
- Homebrew tap and published container image — real, but Phase 5 (see
  "Deferred"), and neither is on the critical path once the one-liner exists.

## Verified current state

Every row checked against the working tree at `v0.39.4` and the live registry on
2026-09-04. Nothing here is taken from documentation.

| # | Claim | Evidence |
|---|---|---|
| V1 | The wrapper structurally requires the source tree on disk | `bin/docparse` resolves symlinks to `SCRIPT_DIR`, sets `PROJECT_DIR="$(dirname "$SCRIPT_DIR")"` and `MAIN_AIL="docparse/main.ail"`, then `ailang run … "$PROJECT_DIR/$MAIN_AIL"` |
| V2 | The publish file set is `ailang.toml`, `*.ail`, `AGENT.md`, `assets/**` — nothing else | `ailang/internal/pkg/tarball.go:58-66`, the `switch` in `CreateTarball`; mirrored in `publish_validator.go:144` |
| V3 | So the published tarball has **no** `bin/docparse`, **no** `docparse/services/pdf_backends/adapter.py`, **no** `pyproject.toml` | `tar tzf package.tar.gz` → 85 entries, all `.ail` plus `AGENT.md`/`ailang.toml`; `ls ~/.ailang/cache/registry/sunholo/ailang_parse/0.39.4/` → `AGENT.md ailang.toml docparse docs scripts` |
| V4 | **`assets/**` is already an escape hatch, and executable-ish payloads under it are a tested case** | `tarball.go:19` `const AssetsDir = "assets"`; `tarball_test.go:247-248` builds `assets/scripts/bin/run.sh` and asserts it round-trips |
| V5 | **The published source is genuinely runnable** — the only gap is tooling, not code | copied the cached `0.39.4` to a temp dir, ran `ailang lock` (resolved external_backend/gcp_auth/http_helpers/gemini_files/logging), then `ailang run --entry main --caps IO,FS,Env docparse/main.ail comments.docx` → parsed, comments and section breaks intact, `.json` + `.md` written |
| V6 | Running from the cache **without** `ailang lock` fails | `module loading error: … failed to resolve package import "pkg/sunholo/external_backend/runner": package "sunholo/external_backend" not found in ailang.lock` (`ailang.lock` is excluded from the tarball) |
| V7 | Tarball entries lose the executable bit | `tarball.go:88` hardcodes `Mode: 0644` in the `tar.Header`; there is no mode plumbing |
| V8 | The package tarball is fetchable over plain HTTP at a documented base URL | `internal/pkg/registry.go:100` → `%s/packages/%s/%s/%s/package.tar.gz`; `ailang install --help` documents `$AILANG_REGISTRY` (default `https://storage.googleapis.com/ailang-registry`). `curl -sL …/packages/sunholo/ailang_parse/0.39.4/package.tar.gz` → 200, 393 771 bytes |
| V9 | The GitHub tag archive also works, but is 62x larger | `curl -sIL …/archive/refs/tags/v0.39.4.tar.gz` → 200; full download 24 516 841 bytes vs 393 771 for the package |
| V10 | Docker is not a shortcut: no image is published, and the Dockerfile's caps forbid the PDF/AI paths anyway | `gh api /orgs/sunholo-data/packages?package_type=container` → no container packages; `Dockerfile:32` `ENTRYPOINT ["ailang","run","--entry","main","--caps","IO,FS,Env","docparse/main.ail"]` — no `Process`, no `AI` |
| V11 | Releases are SDK-only; there is no binary release | `gh release list` → `sdk-v0.13.1`, `sdk-v0.13.0`, … only |
| V12 | The SDKs cannot substitute — they are hosted-API clients | `sdks/python/ailang_parse/client.py:94` `base_url: str = DEFAULT_BASE_URL`; `:211` `url = self.base_url + "/api/v1/parse"`. No parser code in any SDK |
| V13 | `docling`/`liteparse` are not in the default dependency group | `pyproject.toml` `[project] dependencies = ["fpdf2>=2.8"]`; both live in `[project.optional-dependencies] competitors`, alongside `unstructured`, `llama-parse`, `markitdown`, `kreuzberg` |
| V14 | uv is pointed at the **repo root** project, so today the only route drags in the whole benchmark stack | `pdf_backend_external.ail:45-47` `backendProject(projectRoot)`; `uv sync --extra competitors --dry-run` resolves the full competitor set |
| V16 | **The current `PROJECT_DIR` resolution breaks under the proposed layout** — it is `dirname(SCRIPT_DIR)` *after* full symlink resolution, so a real wrapper at `assets/bin/docparse` would compute `PROJECT_DIR=<repo>/assets` and never find `docparse/main.ail` | `bin/docparse:11-19`: the `while [ -L "$SOURCE" ]` loop resolves to the real file, then `SCRIPT_DIR="$(dirname "$SOURCE")"`, `PROJECT_DIR="$(dirname "$SCRIPT_DIR")"`, `MAIN_AIL="docparse/main.ail"`. Phase 1 must fix this first — see below |
| V17 | The proposed root-discovery replacement resolves all four layouts and fails cleanly on none | prototyped and run 2026-09-04: `repo/bin/docparse` (symlink → `assets/bin/`) → `repo`; `repo/assets/bin/docparse` direct → `repo`; `prefix/bin/docparse` → `prefix`; `~/.local/bin/docparse` → `prefix/bin/docparse` → `prefix`; orphaned copy → `ERR: no root above …`, exit 1 |
| V15 | Missing `docling` breaks the **default** backend, not just the opt-in one | `pdf_backend_external.ail:112-125` `parsePdfWithFallback` escalates `pdftotext → docling` on an empty text layer; the failure surfaces as `no text layer (pdftotext: …) and OCR found nothing (docling: …)`, which reads as a bad PDF |

**V3 + V5 together are the whole design.** We publish a package that is
source-complete and tool-incomplete. The fix is not new infrastructure; it is
putting three files in `assets/` and writing an installer that assembles them.

## Problem statement

There is no way to obtain the local CLI other than cloning a 24 MB repo. That is
a poor experience for any consumer, but it is a *blocking* one for the case the
CLI is for: someone with material that must not be uploaded, who now has to
choose between "clone a repo you have never heard of" and "upload the
confidential document to the hosted API". Many will pick the upload.

Three routes look like they should work and all dead-end (V3, V10, V12), so the
failure is also expensive to diagnose: an agent or user reasonably spends time
on `ailang install`, then Docker, then pip, before concluding none of them
produce a CLI.

Secondary, and worse in kind: **the published package is broken for PDF today**
(V3). Any consumer importing `docparse/services/pdf_backend_external` from the
registry gets a module whose `adapterPath` points at a file the tarball does not
contain. It fails at the `Process` boundary rather than at import, so nothing
catches it — no test installs from the published artifact (see Phase 4).

## Goals

**Primary**: a user with neither the repo nor prior AILANG experience gets a
working `docparse` in one command, and a working PDF path in two.

**Success metrics**

1. `curl -fsSL https://www.sunholo.com/ailang-parse/install.sh | sh` on a clean
   machine yields a `docparse` on `PATH` that parses a DOCX. No `git` required.
2. Installed payload ≤ 1 MB (package is 394 KB today) — not the 24 MB repo (V9).
3. `docparse --install-backends` gets `docling`/`liteparse` working without
   pulling `unstructured`/`llama-parse`/`markitdown`/`kreuzberg` (V13, V14).
4. CI installs from the **published** artifact and parses a DOCX and a
   text-layer PDF — so V3-class regressions fail the build instead of shipping.
5. The published package can run its own PDF backends. (Fixes the latent bug.)

## Solution design

### Phase 1 — make the package self-contained (P0, ~0.5 day)

Add an `assets/` tree, which `CreateTarball` bundles verbatim (V4):

```
assets/
  bin/docparse                 # the real wrapper (see note on drift)
  pdf_backends/adapter.py      # the real adapter
  backends-pyproject.toml      # minimal: docling + liteparse only
```

**Avoiding a second copy that drifts.** `assets/` holds the *real* files;
the historical locations become symlinks (`bin/docparse` →
`../assets/bin/docparse`, `docparse/services/pdf_backends/adapter.py` →
`../../../assets/pdf_backends/adapter.py`). `CreateTarball` uses
`filepath.Walk` + `os.ReadFile`, so the symlink at the old path does not match
any include rule and is skipped, while the real file under `assets/` is read
normally — one copy on disk, one copy in the tarball, and the existing dev
workflow (`bin/docparse`, `--check`, `--test`) keeps working unchanged.

**Prerequisite: root discovery, not `dirname` (V16).** The wrapper currently
assumes the script sits exactly one level under the project root, which is false
for both `assets/bin/docparse` and any future layout. Replace the fixed
`dirname` with a walk up from `SCRIPT_DIR` looking for the thing that actually
defines the root:

```bash
PROJECT_DIR="$SCRIPT_DIR"
while [ ! -f "$PROJECT_DIR/docparse/main.ail" ] && [ "$PROJECT_DIR" != "/" ]; do
  PROJECT_DIR="$(dirname "$PROJECT_DIR")"
done
[ -f "$PROJECT_DIR/docparse/main.ail" ] || {
  echo "docparse: cannot locate docparse/main.ail above $SCRIPT_DIR" >&2
  echo "  reinstall: curl -fsSL https://www.sunholo.com/ailang-parse/install.sh | sh" >&2
  exit 1
}
```

This is what makes both layouts work from one file: from `<repo>/assets/bin` it
walks past `assets/` to the repo root; from `PREFIX/bin` it stops at `PREFIX`.
It also turns today's silent misresolution into a named error. Prototyped
against all four call shapes before writing this (V17). Do this first — without
it, the rest of Phase 1 ships a wrapper that cannot find its own source.

**No `.ail` change.** `adapterPath(projectRoot)` keeps returning
`${projectRoot}/docparse/services/pdf_backends/adapter.py` (V1 layout); the
installer is responsible for materialising that path (Phase 2). This keeps the
change out of the type-checked surface and off the `--prove` gate.

### Phase 2 — the installer (P0, ~1 day)

`scripts/install.sh`, published at `https://www.sunholo.com/ailang-parse/install.sh`.

```
1. ailang present?            → else run the official installer, re-check
2. resolve version            → $AILANG_REGISTRY/index.json → .latest  (V8)
                                (or --version X.Y.Z)
3. curl the package tarball   → $AILANG_REGISTRY/packages/sunholo/ailang_parse/
                                <ver>/package.tar.gz                    (V8)
4. verify sha256              → against .../metadata.json               (V8)
5. unpack to PREFIX           → ~/.local/share/ailang-parse/<ver>/
6. materialise the layout     → assets/bin/docparse        → PREFIX/bin/docparse
                                assets/pdf_backends/*.py   → PREFIX/docparse/
                                                              services/pdf_backends/
                                assets/backends-pyproject.toml → PREFIX/pyproject.toml
   chmod +x PREFIX/bin/docparse                                          (V7)
7. ailang lock                → in PREFIX, once                          (V5, V6)
8. symlink                    → ~/.local/bin/docparse → PREFIX/bin/docparse
9. preflight report           → pdftotext? uv? ADC? Print what is missing
                                and the exact command to fix each. Do not
                                fail the install; do not silently proceed.
```

Properties that matter:

- **Version-pinned and side-by-side.** `PREFIX/<version>/` means an upgrade is a
  new directory and a moved symlink; downgrade is moving it back. `--prefix`
  and `--version` override; re-running is idempotent.
- **Fetches over documented contracts only.** `$AILANG_REGISTRY` and the
  `packages/<vendor>/<name>/<version>/` layout are public (V8). The installer
  must **not** read `~/.ailang/cache/registry/` — that is AILANG's internal
  cache (`registry.go:190`), not an interface.
- **Step 7 needs network.** `ailang lock` resolves five transitive packages
  (V5). Offline install is unsupported in this phase; say so in the error.
- **Step 9 reports rather than installs.** Silently `brew install`ing poppler on
  someone's machine is not our call.

`--uninstall` removes the prefix and the symlink.

### Phase 3 — PDF backends as a normal extra (P1, ~1 day)

`assets/backends-pyproject.toml` declares only what the adapter imports:

```toml
[project]
name = "docparse-backends"
version = "0.0.0"
requires-python = ">=3.11"

[project.optional-dependencies]
backends = ["docling", "liteparse"]
```

Add `docparse --install-backends`, which runs
`uv sync --project "$PROJECT_DIR" --extra backends`. Because
`backendProject(projectRoot)` already points uv at `$PROJECT_DIR` (V14), an
installed prefix resolves to this minimal project while a clone continues to
resolve to the repo's benchmark `pyproject.toml`. Both work; only the installed
path gets the lean dependency set.

Given V15, `--install-backends` should also be what the
`no text layer … and OCR found nothing` error tells the user to run. That error
is currently a dead end that reads as a corrupt PDF.

### Phase 4 — install-from-published CI (P0, part of the above)

A job that does **not** check out the repo for the install step:

```yaml
- run: curl -fsSL <installer> | sh
- run: docparse --version && docparse fixtures/sample.docx --output-dir /tmp/o
- run: test -s /tmp/o/sample.docx.json
- run: sudo apt-get install -y poppler-utils && docparse --install-backends
- run: docparse fixtures/text-layer.pdf --output-dir /tmp/o   # exercises the adapter
```

This is the gate that would have caught V3. Today nothing installs from the
published artifact, so "publish silently omitted a file" is invisible until a
user hits it. Run it on the release tag, after `publish-ailang.yml`.

### Deferred (P2, not this doc)

- **Homebrew tap** — best macOS UX, but a formula wrapping the same installer;
  cheap to add once Phase 2 exists.
- **Container image** — needs its caps widened to `IO,FS,Env,Process,AI` and
  poppler + backends baked in (V10). Useful for CI consumers, not for the
  confidential-laptop case that motivates this doc.
- **Getting `Mode` plumbed through `CreateTarball`** in AILANG core (V7), which
  would let `assets/bin/docparse` ship executable and remove the `chmod` step.
  Worth an upstream issue; the `chmod` is a one-line workaround, so it does not
  block.

## Files to modify

- `assets/bin/docparse` — moved from `bin/docparse` (823 lines), + root discovery (~10 lines, V16), + `--install-backends` (~25 lines)
- `assets/pdf_backends/adapter.py` — moved from `docparse/services/pdf_backends/adapter.py`, unchanged
- `assets/backends-pyproject.toml` — new, ~10 lines
- `bin/docparse`, `docparse/services/pdf_backends/adapter.py` — become symlinks
- `scripts/install.sh` — new, ~180 lines
- `.github/workflows/install-smoke.yml` — new, ~40 lines
- `README.md` — install section: one-liner first, clone as the contributor path
- `RELEASING.md` — note that `assets/` contents ship, and the smoke job gates the tag
- `docparse/services/pdf_backend_external.ail` — error text for V15 only (~3 lines); no logic change

## Success criteria

- [ ] Clean container, no `git`: one-liner installs and `docparse sample.docx` writes valid JSON
- [ ] `tar tzf package.tar.gz | grep -c assets/` ≥ 3 on the published artifact
- [ ] `docparse --install-backends` then `docparse text-layer.pdf` succeeds without `unstructured` in the env
- [ ] A scanned PDF with backends absent errors with an actionable message naming `--install-backends` (V15)
- [ ] Install smoke job green on the release tag; deliberately deleting `assets/bin/docparse` turns it red
- [ ] Installed payload < 1 MB
- [ ] Re-running the installer is a no-op; `--uninstall` leaves no files
- [ ] `./bin/docparse --check` and `--test` still pass through the symlink (this is the V16 regression test — it fails today under the new layout)
- [ ] `docparse` invoked via a symlink *chain* (`~/.local/bin/docparse` → `PREFIX/bin/docparse`) resolves the root correctly

## Risks

| Risk | Mitigation |
|---|---|
| Executable bit stripped (V7) | `chmod +x` in the installer; smoke job would fail loudly if missed |
| `ailang lock` needs network mid-install (V6) | Documented; explicit error, not a hang. Offline install deferred |
| Root discovery loop walks to `/` on a broken install | Bounded by the `!= "/"` guard and a named error (V16), not an infinite loop or a confusing `ailang` failure |
| Symlink handling differs on Windows | Installer is `sh`; Windows users keep the clone + `bin/docparse.cmd`. Note it in the README |
| Registry URL shape is technically AILANG-internal | It is documented in `ailang install --help` via `$AILANG_REGISTRY` (V8); pin the layout in the installer and let the smoke job catch a change |
| `assets/` grows into a dumping ground | Only these three files; the rule is "things the CLI needs at runtime that are not `.ail`" |

## Related documents

- [`v0_40_0_parser_version_discoverability.md`](v0_40_0_parser_version_discoverability.md)
  — `ailang_parse_version` on `/health`; same "which build am I actually running"
  question, from the hosted side.
- `sunholo-data/docparse-skill` `plugins/ailang-parse/skills/ailang-parse/resources/local-cli.md`
  — the consumer-facing doc that currently has to say "if you won't clone, the
  local CLI is unavailable to you". Phases 1–3 are what let that paragraph be
  deleted.
