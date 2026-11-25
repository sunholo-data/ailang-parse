# Design Doc: `sunholo/docparse_core` — the deterministic half as its own package (v0.62.0)

**Status**: Planned
**Date**: 2026-11-25
**Author**: Mark + Claude
**Target**: v0.62.0 (`[release] kind = "breaking"` for `sunholo/ailang_parse`; first release of `sunholo/docparse_core`)
**Priority**: P1
**Estimated**: 4–5 days of work, plus one upstream AILANG change (Phase 0) that blocks it
**Dependencies**: v0.61.0 `Result` generator API (branch `feat/generator-result-api`); upstream change described in Phase 0
**Requested by**: specstore 0.4.1, which builds client-letterhead `.docx` through `markdown_parser.parseMarkdown` + `docx_generator.generateDocxWithReference`

## Problem

A package that only needs Markdown → Word has to depend on all of `sunholo/ailang_parse`.

Measured on 2026-11-25 (v0.60.0):

| | What specstore uses | What it installs |
|---|---|---|
| Modules | 21 (`markdown_parser`, `docx_generator`, `docx_template` and what they import) | 102 `.ail` files in the tarball (93 under `docparse/`) |
| Lines | 8,571 | 33,133 |
| Other packages | none | `external_backend`, `gcp_auth`, `a2ui`, `logging`, `gemini_files` |
| Declared effects | `FS` | `IO, FS, AI, Env, Net, Clock, Process, Declassify` |

Size is not the problem; the five extra packages come to about 1.9k lines. **What specstore carries is
reach.** Its Cloud Run image ships code that can call Gemini, fetch GCP tokens and exec processes,
under a package whose declared ceiling includes `AI`, `Net` and `Process`. Its own effect check
passes, because the ceiling is checked against the functions it actually calls, but the image's
trust surface is the whole package. That is the opposite of what a ceiling of `IO, FS, Env, Declassify`
is meant to say.

**The deterministic half is already separable.** Computed from the import graph on 2026-11-25:

| Boundary | Modules | Effects used | Imports of other packages |
|---|---|---|---|
| A. Exactly what was asked for (types, markdown/HTML parsers, DOCX/XLSX/PPTX generators + templates) | 21 | `FS` | none |
| B. A + every generator (ODT/ODP/ODS/HTML/QMD) and `markdown_writer` | 31 | `FS` | none |
| C. B + every deterministic Office/text parser (DOCX, PPTX, XLSX, CSV, RTF, ODT, ODP, ODS, EPUB, EML, TeX, `zip_extract`, `omml`) | 46 | `FS` | none |

Every module that imports another package (`a2ui_formatter`, `direct_ai_parser`, `pdf_backend_external`,
and through them the orchestrator, MCP tools, PDF router and CLI) is outside C. Nothing in C needs to change; only its location and module names do.

## Goals

**Primary goal:** A dependent can parse and generate Office/Markdown/HTML documents by depending on a
package that has no dependencies of its own and declares `effects.max = ["FS"]`.

**Success metrics:**
- `ailang lock` in a Markdown → Word dependent resolves **1** package (today: 6). TST-DCORE-03
- The dependent's image carries no module that declares `AI`, `Net` or `Process`. TST-DCORE-03
- `sunholo/ailang_parse` behaves exactly as before: four suites unchanged, CLI output byte-identical. TST-DCORE-04, TST-DCORE-05
- The boundary is enforced by the manifest, not by review: a core module that imports another package, or uses an effect beyond `FS`, fails to compile. TST-DCORE-01, TST-DCORE-02

## Verification Log

Every load-bearing claim below was checked in-session on 2026-11-25 with AILANG v0.61.1. Scratch
packages lived in the session scratchpad; nothing here depends on them surviving.

| # | Claim | How verified | Result |
|---|---|---|---|
| V1 | Boundaries A/B/C import no other package and use only `FS` | Python walk of every `import` line under `docparse/`, plus each module's `! {…}` annotations | Confirmed (table above) |
| V2 | ~~A dependent must import `pkg/sunholo/ailang_parse/services/...`, not the `docparse/...` names in `[exports]`~~ | Scratch package with a path dep on this checkout ran `parseMarkdown` + `generateDocxResult` through `pkg/`. **Re-checked 2026-11-25:** `import docparse/services/markdown_parser` from the same dependent also resolves, on both v0.61.1 and dev, by design: bare imports resolve via the module_prefix map (ailang `c59f8f916`). | **Refuted** as "must". Both forms resolve. `pkg/` is the unambiguous one, because the loader lets several dependencies share a prefix and tries each. `AGENT.md` corrected |
| V3 | Depending on `ailang_parse` pulls all five transitive packages | `ailang lock` in that scratch dependent | Confirmed: listed all five |
| V4 | Two packages cannot share a `module_prefix` | `ailang/docs/docs/reference/errors/mod013.md` (MOD013) | Confirmed: core needs its own prefix |
| V5 | An ADT built in package X can be passed to functions of package Y that depend on X | Scratch `core` → `mid` → `app`: `core.mkDoc` passed to `mid.shout`; ADT `Shape` built with core's `Sq` passed through `mid`'s alias | Confirmed |
| V6 | A wrapper module can forward functions and alias types | `mid/doc`: `export pure func mkDoc(...) = coreMk(...)`, `export type Shape2 = Shape` | Confirmed |
| V7 | A wrapper module **cannot** re-export ADT constructors | `import pkg/scratch/mid/doc (Sq)` | **Confirmed negative**: `IMP010: symbol 'Sq' not exported by 'pkg/scratch/mid/doc'` |
| V8 | `ailang publish` rewrites `path` deps to registry versions, and needs the target published first | `ailang/docs/docs/guides/package-publishing.md` §"How publish handles path deps"; dry run printed `Rewrote dep scratch/core: path "packages/core" → registry 0.0.1` | Confirmed |
| V9 | A package nested in a subdirectory is swept into the outer package | Outer package with core at `packages/core/`: `compile: ✓ 3 files` and `MOD010 … packages/core/core/doc`, tarball 685 bytes; same outer package with core outside: `compile: ✓ 2 files`, 560 bytes | **Confirmed**: nesting leaks core into every `ailang_parse` publish |
| V10 | Known dependents that import `types/document` constructors | grep across `~/dev/sunholo-data` | `docparse` (hosted API): `docparse_api/services/api_server.ail:41` imports 11 constructors (`TextBlock`, `HeadingBlock`, `TableBlock`, ...), `docparse_api/main.ail:10` more; `email-parse/packages/eparse` also depends on `ailang_parse` |
| V11 | The browser build already loads a vendored package module by its `pkg/` name | `docs/js/wasm-demo.js:67`: `{ name: 'pkg/sunholo/a2ui/components', ... }` | Confirmed: precedent for core in the browser |
| V12 | `ailang publish` bundles every `*.ail` under the package root | `RELEASING.md` §"What ships in the package"; V9 | Confirmed |
| V13 | How many modules satisfy "closure uses only `FS` and imports no other package" | Same import/effect walk as V1, applied to all 93 modules | 69 do; all 46 of C among them; the 24 that do not are `main`, `orchestrator`, `mcp/{tools,auth,account,estimate}`, `direct_ai_parser`, `pdf_ai_pages`, `pdf_backend_external`, `pdf_pages_tool`, `layout_ai`, `ai_generator`, `a2ui_formatter`, `docparse_browser`, `docparse_generate`, `document_render`, `docx_audit`, `eval`, `console_report`, `tex_input_resolver`, `tex_archive_extract`, `redact/{core,source,egress}` |

## High-Impact Decisions

| Decision | Why High Impact | Chosen By | Deadline | Change Cost |
|---|---|---|---|---|
| D1. Which boundary (A, B or C) | Sets which import paths break for dependents, and the rule every future module is sorted by | human | design | high |
| D2. Where core's source lives | V9: nesting it in this repo leaks it into `ailang_parse` today. Decides whether Phase 0 is an upstream blocker or the dev loop spans two repos | human | design | high |
| D3. Compatibility for existing dependents: forwarding shims or a clean break | V7: constructors cannot be forwarded, so `types/document` breaks either way; shims only soften the function-only modules | human | design | med |
| D4. Core's `module_prefix` and directory name | Every core import line in every dependent carries it, permanently | human | design | high |
| D5. Release ordering: core published first, three dependents migrated in the same window | A half-published pair leaves `ailang_parse` unresolvable (V8) | agent | compile | low |

### Design Freeze

- [ ] **D1 boundary.** Recommendation: **C**, stated as a product rule: *core is every reader and writer of a non-PDF format, plus the helpers they import.* A or B draw a line through the parsers that no rule explains, and the next request ("parse DOCX without the AI stack") reopens this. Note what the rule is **not**: "FS-only with no other package" is the constraint the core manifest enforces, but 69 of the 93 modules satisfy it (V13). The 23 beyond C (PDF post-processing `pdf_router`/`pdf_furniture`/`pdf_pages`/`pdf_annotations`, `chunker`, `output_formatter`, `unstructured_compat`, `format_router`, `samples`, `tools`, `mcp/request`, `redact/policy`, and the `browser_*` glue) serve the PDF, API and browser surfaces and stay in `ailang_parse` by choice, not by necessity.
- [ ] **D2 location.** Recommendation: **`packages/docparse_core/` in this repo, blocked on Phase 0** (an upstream change that makes a nested `ailang.toml` a package boundary for compile and tarball). Core's tests are this repo's four suites and goldens; moving the source to another repo would mean every parser fix spans two PRs and CI clones a sibling. If Phase 0 is refused, the fallback is a separate `sunholo-data/ailang-parse-core` repo with `ailang-parse` CI checking it out at a pinned ref.
- [ ] **D3 compatibility.** Recommendation: **clean break, no shims.** Shims would cover 46 modules of forwarding boilerplate, would still not cover the constructors every serious dependent imports (V7, V10), and would need their own deprecation release. The migration is one mechanical rewrite per dependent (Example 2), and there are three known dependents, all ours.
- [ ] **D4 prefix.** Recommendation: package `sunholo/docparse_core`, `module_prefix = "docparse_core"`, source under `packages/docparse_core/docparse_core/{types,services}/`. Dependents import `pkg/sunholo/docparse_core/services/docx_generator`.

## Solution Design

### Overview

Move the boundary-C modules, unchanged except for their `module` lines and the imports between them,
into a second package. `ailang_parse` keeps the AI, PDF, MCP, orchestration, redaction and CLI code
and depends on `docparse_core`. The core manifest has no `[dependencies]` and `effects.max = ["FS"]`,
so the boundary holds itself: an import of another package fails to resolve, and a new effect fails
the ceiling check.

```
sunholo/docparse_core   effects.max = [FS], no dependencies
  types/document, markdown_*, html_parser/layout, csv/rtf/eml/epub/tex parsers,
  docx/pptx/xlsx/odt/odp/ods parsers, zip_extract, omml, xml_helpers, colour,
  image_*, odf_*, every generator + template, markdown_writer
        ▲
        │ depends on
sunholo/ailang_parse    effects.max = [IO, FS, AI, Env, Net, Clock, Process, Declassify]
  orchestrator, format_router, direct_ai_parser, pdf_*, layout_ai, a2ui_formatter,
  mcp/*, tools, eval, redact/*, chunker, output_formatter, unstructured_compat,
  docx_audit, document_render, tex_input_resolver, tex_archive_extract, browser_*, main
  + external_backend, gcp_auth, a2ui, logging, gemini_files
```

### Implementation Plan

**Phase 0 — Upstream: nested `ailang.toml` is a package boundary** (blocker for D2's recommendation)
- [ ] File with ailang-core: when a subdirectory contains its own `ailang.toml`, the outer package's compile, quality report and tarball must skip it. Repro is V9: two files in, three compiled, 560 → 685-byte tarball.
- [ ] Until it lands, do not merge Phases 1–4. If it is refused, switch D2 to the separate-repo fallback before starting.

**Phase 1 — Create core in place** (~1 day)
- [ ] `git mv` the boundary-C modules to `packages/docparse_core/docparse_core/...`; rewrite their `module` lines and inter-core imports `docparse/` → `docparse_core/`.
- [ ] `packages/docparse_core/ailang.toml`: `module_prefix = "docparse_core"`, `[exports]` = every moved module, no `[dependencies]`, `effects.max = ["FS"]`, `[bin]` none. Own `AGENT.md` (the "Using it from another AILANG package" section moves here) and `CHANGELOG.md`.
- [ ] Prefix the internal helpers that the move puts next to same-named helpers in another module (the known module-scoping collision in `.claude/rules/ailang-coding.md`).
- [ ] `ailang check` core standalone: TST-DCORE-01, TST-DCORE-02.

**Phase 2 — Point `ailang_parse` at core** (~1 day)
- [ ] Root `ailang.toml`: add `"sunholo/docparse_core" = { path = "packages/docparse_core" }`; remove moved modules from `[exports]`.
- [ ] Rewrite `import docparse/<moved>` → `import pkg/sunholo/docparse_core/<moved>` across `docparse/`, `scripts/`, `benchmarks/*.ail`, `tests/`. Mechanical; one script, checked in under `scripts/` so the dependents can reuse it.
- [ ] `./bin/docparse --check`, `--test`, `--prove`; the four suites; CLI byte-identity: TST-DCORE-04, TST-DCORE-05, TST-DCORE-10.

**Phase 3 — Browser, CI, release** (~1–1.5 days)
- [ ] `docs/scripts/vendor-wasm-packages.sh`: copy core modules to `docs/ailang/pkg/sunholo/docparse_core/`, following the `a2ui` precedent (V11); `docs/js/wasm-demo.js`: register them under their `pkg/` names. Its orphan guard and `check-wasm-bindings.py` pin the set: TST-DCORE-08.
- [ ] CI: a core-only job (check + `--prove` + `publish --dry-run`); the Floor Check job covers both manifests.
- [ ] `publish-ailang.yml`: publish core, then `ailang_parse`. A core version that is already published is skipped, not a failure; `RELEASING.md` states the order.
- [ ] `install-smoke.yml`: install `ailang_parse` from its tarball and confirm `docparse` still runs (TST-DCORE-07); install `docparse_core` alone in a Markdown → Word dependent (TST-DCORE-03).
- [ ] Publish dry-run proves `ailang_parse`'s tarball holds no core module: TST-DCORE-06.

**Phase 4 — Dependents** (~1 day, same release window)
- [ ] `sunholo-data/docparse` (hosted API), `email-parse/packages/eparse`, specstore: run the rewrite script, bump pins, type-check: TST-DCORE-09.
- [ ] `ailang messages send` to each, plus the registry's `upgrade-available` notice.

### Files to Modify/Create

**New files:**
- `packages/docparse_core/ailang.toml` (~70 lines) — core manifest, `effects.max = ["FS"]`, no dependencies
- `packages/docparse_core/AGENT.md` (~80 lines) — library usage guide, moved from root `AGENT.md`
- `packages/docparse_core/CHANGELOG.md` — first entry
- `scripts/migrate-to-docparse-core.sh` (~40 lines) — the import rewrite, used here and by dependents

**Moved files (46, `git mv`, `module` line + inter-core imports only):**
- `docparse/types/document.ail` → `packages/docparse_core/docparse_core/types/document.ail`
- `docparse/services/*.ail` (the 45 boundary-C services) → `packages/docparse_core/docparse_core/services/`

**Modified files:**
- `ailang.toml` — add the dependency, shrink `[exports]`, `[release] kind = "breaking"`
- `docparse/main.ail`, `docparse/services/{orchestrator,format_router,tools,output_formatter,chunker,unstructured_compat,a2ui_formatter,...}.ail`, `docparse/services/mcp/*.ail` — import rewrites only
- `scripts/verify_document_quality.ail`, `benchmarks/**/*.ail` — import rewrites
- `docs/scripts/vendor-wasm-packages.sh`, `docs/js/wasm-demo.js` — core under `pkg/sunholo/docparse_core/`
- `.github/workflows/{ci,publish-ailang,install-smoke}.yml` — core job, publish order, core install smoke
- `AGENT.md`, `README.md`, `RELEASING.md`, `CLAUDE.md` (project structure) — two packages
- `.claude/skills/add-format/SKILL.md` — a new deterministic format goes in core

## Examples

### Example 1: specstore after the split

```toml
[dependencies]
"sunholo/docparse_core" = "0.62.0"     # was: "sunholo/ailang_parse" = "0.60.0"
```

```ailang
import pkg/sunholo/docparse_core/services/markdown_parser (parseMarkdown, parseMarkdownMeta)
import pkg/sunholo/docparse_core/services/docx_generator (generateDocxWithReferenceResult)
```

`ailang lock` resolves one package. The function names and `Result` contract are the ones v0.61.0 ships.

### Example 2: the migration for an existing dependent

```bash
# For every module that moved, swap the package segment; nothing else changes.
scripts/migrate-to-docparse-core.sh path/to/dependent
#   pkg/sunholo/ailang_parse/types/document        -> pkg/sunholo/docparse_core/types/document
#   pkg/sunholo/ailang_parse/services/docx_generator -> pkg/sunholo/docparse_core/services/docx_generator
#   pkg/sunholo/ailang_parse/services/orchestrator   (unchanged: stays in ailang_parse)
```

A dependent that uses both halves (the hosted API) depends on both packages; per V5 the
`ParsedDocument` it gets from `ailang_parse`'s orchestrator is the same type core's generators take.

## Success Criteria

- [ ] Core type-checks and proves on its own with `effects.max = ["FS"]` and no dependencies — TST-DCORE-01
- [ ] The manifest rejects a core module that imports another package — TST-DCORE-02
- [ ] A Markdown → Word dependent of core alone locks to one package and produces a letterhead DOCX — TST-DCORE-03
- [ ] Office suite 100%, round-trip / verify_generated / failure_check 0 failures, goldens untouched — TST-DCORE-04
- [ ] CLI output byte-identical across the conversion matrix — TST-DCORE-05
- [ ] `ailang_parse`'s published tarball holds no core module — TST-DCORE-06
- [ ] Installed `docparse` shim still runs — TST-DCORE-07
- [ ] Browser demo parses and generates as before — TST-DCORE-08
- [ ] Hosted API, eparse and specstore type-check after the rewrite — TST-DCORE-09
- [ ] A `ParsedDocument` from core flows through `ailang_parse` functions — TST-DCORE-10
- [ ] Docs: both `AGENT.md`s, README, RELEASING, CLAUDE.md project structure, add-format skill

## Testing Strategy

| ID | Level | Given / When / Then |
|----|-------|---------------------|
| TST-DCORE-01 | integration | Given `packages/docparse_core` alone, when `ailang check` and `ailang verify` run there, then both pass with `effects.max = ["FS"]` and an empty `[dependencies]` |
| TST-DCORE-02 | integration | *(negative control)* Given a core module with an added `import pkg/sunholo/logging/...`, when core is checked, then it **fails**. Proves the boundary is enforced, not merely currently true |
| TST-DCORE-03 | e2e | Given a scratch dependent whose only dependency is `docparse_core` and whose ceiling is `IO, FS, Env, Declassify`, when it locks and converts Markdown with `data/test_files/docx-hdrftr.docx` as reference, then the lock lists exactly one package and the result is `Ok("Generated DOCX: ... reference doc applied ...")` |
| TST-DCORE-04 | e2e | *(regression surface)* Given the v0.61.0 goldens, when the four suites run, then office is 100.0% and the other three report 0 failures, with no golden regenerated |
| TST-DCORE-05 | e2e | *(regression surface)* Given the conversion matrix (DOCX/PPTX/XLSX/ODT/ODP/ODS from Markdown; bad reference; unwritable path), when run before and after, then stdout and exit codes are byte-identical modulo output path |
| TST-DCORE-06 | e2e | Given the root package, when `ailang publish --dry-run` runs, then its compile count equals the root's own module count, with no `MOD010` naming `packages/docparse_core` |
| TST-DCORE-07 | e2e | *(regression surface)* Given the `ailang_parse` tarball installed with no checkout, when `docparse sample.docx` runs, then it exits 0 and writes the same JSON as from a clone |
| TST-DCORE-08 | e2e | *(regression surface)* Given the refreshed WASM mirror, when `vendor-wasm-packages.sh` and `check-wasm-bindings.py` run, then neither reports orphans or missing bindings, and the demo parses `sample.docx` |
| TST-DCORE-09 | integration | Given each known dependent after `migrate-to-docparse-core.sh`, when it type-checks against the new pins, then it passes with no further edits |
| TST-DCORE-10 | integration | Given a `ParsedDocument` built by core's `parseMarkdown`, when passed to `ailang_parse`'s `renderMarkdown`/orchestrator output path, then it type-checks and renders (V5 at full scale) |

## Deferred Decisions

- Moving any of the 23 extra eligible modules (V13), e.g. `output_formatter` (JSON output) or `chunker`, into core later. Each satisfies the manifest constraint, so it is an additive, non-breaking follow-up when a dependent asks. Agent may decide case by case; `format_router` stays out because `needsAI` is a routing decision for the AI half.
- `docx_audit` (`Env`, `IO`), `document_render` (`Process`), `tex_input_resolver`/`tex_archive_extract` (`IO`) cannot go in core without widening its ceiling. They stay out; `tex_parser` is in C and does not import them (V1).
- Version numbering of core: start at `0.62.0` to track `ailang_parse`, or `0.1.0`. Agent may choose; tracking is recommended so "which core goes with which parse" needs no table.
- Layout of the rewrite script (sed vs AILANG program). Agent may choose.

## Non-Goals

- No API changes beyond the `module` lines and import paths. The `Result` API ships in v0.61.0, separately.
- No forwarding shims (D3). If D3 is decided the other way, shims are an additive follow-up.
- No split of the Python/JS/Go SDKs; they call the CLI or hosted API, not AILANG modules.
- ~~Not fixing the `[exports]` vs import-path mismatch (V2) in AILANG~~. There is no mismatch to fix: V2 was refuted, and both spellings resolve. `ailang pkg docs` now prints the unambiguous `pkg/` import line (ailang M-PKG-PARALLEL-AGENTS M6).

## Timeline

- **Phase 0**: upstream; elapsed time depends on ailang-core. Nothing below merges before it, or before D2 switches to the fallback.
- **Day 1**: Phase 1 (move, manifest, standalone check).
- **Day 2**: Phase 2 (rewrite imports, all suites, byte-identity).
- **Days 3–4**: Phase 3 (browser, CI, publish order, install smoke).
- **Day 5**: Phase 4 (three dependents, notices), release.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Phase 0 refused or slow | High | Fallback repo layout is already designed (D2); decide before Day 1, not mid-sprint |
| Module-scoping collision surfaces after the move (same-named private helpers now in different packages) | Medium | Known AILANG bug: prefix helpers per module in Phase 1; TST-DCORE-04/05 catch any behavioural change |
| Core published, `ailang_parse` publish fails: a dangling core version | Low | Harmless (core has no dependents yet); re-run the `ailang_parse` job, do not retag (RELEASING.md) |
| A dependent pinned to `ailang_parse` 0.60/0.61 upgrades without migrating | Medium | `kind = "breaking"`, registry upgrade notice, rewrite script; three known dependents migrated in the same window |
| Browser demo silently loads a stale core copy | Medium | Vendor script's orphan guard + `check-wasm-bindings.py` already pin the set; extend both to the `pkg/` path (TST-DCORE-08) |

## Axiom Compliance

| Axiom | Score | Justification |
|-------|-------|---------------|
| A1: Determinism | 0 | No behaviour change; the package boundary coincides with the determinism boundary |
| A2: Replayability | 0 | No impact |
| A3: Effect Legibility | +1 | A dependent's dependency now declares `FS`, not eight effects; the declared ceiling matches what can run |
| A4: Explicit Authority | +1 | Least authority: Markdown → Word no longer ships AI/Net/Process-capable code |
| A5: Bounded Verification | +1 | Core's proofs and checks run on 46 modules with no external packages |
| A6: Safe Concurrency | 0 | No impact |
| A7: Machines First | 0 | Import paths change once; the rule (deterministic ⇒ core) is mechanical for agents adding formats |
| A8: Minimal Syntax | 0 | No syntax |
| A9: Cost Visibility | 0 | No impact |
| A10: Composability | +1 | Other packages compose with the deterministic parsers/generators without the AI stack |
| A11: Structured Failure | 0 | (The `Result` API that serves this axiom ships separately in v0.61.0) |
| A12: System Boundary | +1 | The package boundary is enforced by the manifest (TST-DCORE-02) rather than by convention |

**Net score: +5.** No hard violations: A1, A3, A4, A7 are none negative.

## Quorum

Triggers 1 (design-freeze items D1–D4) and 4 (load-bearing premises about AILANG's package system,
V4/V7/V8/V9, which lives in another repo) fire. **Not yet run.**

## Related Documents

- `design_docs/implemented/v0_40_0/v0_40_0_convert_reference_doc_api.md` — the reference-doc path specstore relies on
- `design_docs/implemented/v0_39_0/v0_39_0_reference_doc_followups.md`
- `design_docs/implemented/v0_29_0/v0_29_0_docx_generation_fidelity.md`

## References

- AILANG package guide: `ailang/docs/docs/guides/packages.md` (module prefix, exports, effect ceilings)
- Publishing guide: `ailang/docs/docs/guides/package-publishing.md` (path-dep rewrite)
- MOD013: `ailang/docs/docs/reference/errors/mod013.md`
- [Design Axioms](/docs/references/axioms)

## Future Work

- If AILANG gains constructor re-export, forwarding shims for `types/document` become possible and D3 could be revisited for external dependents.
- A further `docparse_pdf` split (PDF router + local backends, `Process` but no `AI`) for users who want local-only PDF parsing without Gemini code.
