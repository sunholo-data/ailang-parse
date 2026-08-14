# PDF write path — investigation

**Status**: INVESTIGATING (2026-08-14)
**Theme**: `--convert` can target 9 formats and none of them is `pdf`, despite PDF *read* already having a clean multi-backend design. Scope what a write-side mirror actually requires — and where it conflicts with decisions this repo already made.
**Source**: ailang message `msg_20260814_080943_46976097` from `email-parse` (`ailang messages read 46976097-433f-4a4d-89c1-593b7449e919`), filed as a feature request per the no-in-repo-workarounds convention. Concrete trigger: converting parsed `.eml` receipts to `.docx` for an accountant whose upload portal only takes PDF, requiring a manual `soffice --headless --convert-to pdf` outside docparse.
**Relationship to existing docs**: partially re-asks [`v0_21_0_quarto_integration.md`](../v0_21_0/v0_21_0_quarto_integration.md) (still unimplemented — see below) and extends it with three more backends. Also intersects [`v0_32_0_generation_surfaces.md`](../v0_32_0/v0_32_0_generation_surfaces.md) and the now-live [`CONTRACT_convert_endpoint.md`](../v0_32_0/CONTRACT_convert_endpoint.md).

## The request, as filed

Add a `--pdf-write-backend` flag mirroring the read-side `--pdf-backend pdftotext|docling|liteparse|ai` pattern, with backends:

| backend | mechanism | proposed use |
|---|---|---|
| `soffice` | shell out to `soffice --headless --convert-to pdf` | deterministic, handles docx/odt/pptx/html — what was used by hand |
| `quarto` | shell out to `quarto render --to pdf` via the existing `.qmd` path | better typography for markdown-sourced docs |
| `chromium` | headless-Chrome print-to-PDF | best fidelity for HTML-heavy sources (email receipts), respects CSS where soffice's Writer import doesn't |
| `ai` | multimodal model lays out and generates the PDF | only for `--generate` where there's no source document to render faithfully |

Default: auto-pick whichever of soffice/quarto/chromium is found on `PATH`, mirroring the read side's "deterministic first, AI only if asked" philosophy.

## What's actually true about "mirror the read-side design" today

The read side is not one pattern, it's two, and they answer different questions:

**1. `pdftotext` / `docling` / `liteparse` — `pdf_backend_external.ail` + `adapter.py`.** AILANG's `parsePdfViaBackend` shells out to `uv run --project <root> python adapter.py <backend> <path>` via the generic [`sunholo/external_backend` runner](https://github.com/sunholo/ailang-packages) (`runJson`: exec → decode JSON on stdout → typed `BackendError`). One Python dispatch script owns three backends because **all three are Python libraries** (`docling`, `liteparse`) or need `uv`-managed deps to resolve consistently. There's a real reason for the Python indirection: it's not a style choice, it's because the backends themselves are Python packages.

Two things this pattern enforces that any write-side mirror should keep:
- **Escalation only on the default.** `parsePdfWithFallback` escalates `pdftotext → docling` silently *only* when the caller took the default; an explicit `--pdf-backend X` is "a decision, not a starting point" and is never second-guessed.
- **No silent empty success.** `adapter.py`'s `_has_substance` guard treats a backend that returns only placeholder blocks (e.g. docling's `<!-- image -->`) as a hard failure, not a 0-content success. This is the same [no-fallbacks](../../../CLAUDE.md) policy stated project-wide.

**2. Local binaries via `std/process.exec` directly — the *undelivered* `v0.21.0` design.** [`v0_21_0_quarto_integration.md`](../v0_21_0/v0_21_0_quarto_integration.md) already specs a `quarto_render.ail` module that calls `quarto render <qmd> --to <fmt> --output <path>` straight through `std/process.exec`, no Python involved, because `quarto` is a compiled binary with a CLI, not a library. **This module does not exist yet** — `find docparse -iname '*quarto*'` returns nothing, there's no `--via` flag in `main.ail`, and `writeOutputs`'s convert dispatch (`main.ail:365-407`) still only handles `html docx pptx xlsx odt odp ods md qmd`, falling through to `println("Unsupported conversion format: ...")` for anything else, including `pdf`. The CLI help text (`bin/docparse` "Conversion & generation" section) already tells users to work around this by hand: `docparse in.docx --convert out.qmd`, then `quarto render out.qmd --to pdf` — exactly the two-step the feature request is complaining about.

So: **`soffice` and `chromium` are genuinely new backend classes** (compiled binaries, direct `std/process.exec`, no Python). **`quarto` is not new work, it's a nearly-four-month-old unshipped design.** That should reorder the priority: ship the doc that already exists before speccing three more.

## Backend-by-backend assessment

### `quarto` — low risk, mostly spec'd
Exactly what `v0_21_0` designed: `quarto_render.ail` (`! {Process, FS}`), `isAllowedFormat` allowlist, `NotInstalled`/`RenderFailed`/`UnsupportedFmt` error variants, `--via quarto` flag. Constraint that doc already states: **only from a `.qmd` source.** A non-QMD input (`.docx`, `.eml`) must first go through `generateQmd(doc)` — already shipped, used by the `--convert out.qmd` path — before `quarto render` ever runs. That two-stage shape (generate QMD → render) should stay explicit in the module, not hidden behind a single flag that looks like a one-step DOCX→PDF conversion; the intermediate `.qmd` (and its `_files/` assets dir) is a real, sometimes-useful artifact and Quarto's own convention is to leave it, not clean it up.

### `soffice` — new, but narrow and well-precedented elsewhere
`soffice --headless --convert-to pdf --outdir <dir> <input>` is a single binary invocation with no Python step — same shape as the *proposed* `quarto_render.ail`, not the `pdftotext`/`docling` shape. A sibling module (`soffice_render.ail`) following the exact structure of `quarto_render.ail` (`NotInstalled` / `ConversionFailed` / effect surface `! {Process, FS}`) is the natural fit. Unlike Quarto, `soffice` can take `docx`/`odt`/`pptx`/`ods`/`odp`/`html` directly — no intermediate generation step, so it's actually the more direct answer to "just give me a PDF" for anything that isn't markdown-sourced.

Caveat worth stating up front rather than discovering in a bug report: LibreOffice's headless conversion is known to vary output slightly by installed version/fonts (this is why `benchmarks/office/golden/` doesn't compare rendered pixels for anything). A PDF-output golden check can assert "valid PDF, non-zero pages, opens in `pdftotext`" — not byte-identical output. Contrast with the DOCX/PPTX/etc. generators, whose goldens *are* structurally exact because AILANG owns every byte of XML; `soffice`-produced PDFs are the first write-side output this repo doesn't fully control.

### `chromium` — plausible, adds the heaviest new external dependency
`chromium --headless --disable-gpu --print-to-pdf=<out> <input.html>` is likewise a direct binary call. Best fit for the motivating case (HTML-heavy `.eml` receipts, where CSS layout fidelity matters and `soffice`'s Writer HTML import is known to be lossy). But it only takes HTML as input — anything else needs `generateHtml(doc)` first (already shipped), same two-stage shape as the Quarto path. It's also the only one of the three with no existing precedent anywhere in this codebase (no module shells to a browser today), and it's the largest binary to expect on `PATH` (~300MB+), which matters more once you consider where this needs to run — see below.

### `ai` — not a fourth backend, a different feature
The other three all take an existing document (parsed Blocks or a rendered intermediate) and deterministically rasterize it. AI "laying out and generating the PDF" has no such deterministic anchor — it's `--generate --prompt`'s problem, not `--convert`'s. AILANG models don't emit raw PDF bytes; realistically this means "AI generates HTML or QMD content, then a deterministic backend (chromium/quarto) renders it" — i.e. it's not a fourth peer backend, it's the existing `--generate` path gaining a PDF *output* format once one of the above two renderers exists. Folding it into a `--pdf-write-backend ai` flag as a sibling of `soffice`/`quarto`/`chromium` overstates what it is; scope it as "PDF becomes a valid `--generate` target once a renderer backend ships," not as backend #4.

## Where "auto-pick whichever is on PATH" breaks the project's own precedent

The read side *does* auto-escalate on the default (`pdftotext → docling`) — but only between two backends of the same trust tier producing structurally comparable output. The `v0.21.0` doc explicitly rejected the equivalent move for engines that differ qualitatively:

> "Why a flag, not auto-detection: the user knows which engine they want. Magic that flips between local generators and an external binary based on heuristics is the kind of thing that bites in CI."

`soffice`, `quarto`, and `chromium` are exactly that kind of qualitative difference — different typography, different CSS handling, different output for the same input. Whichever happens to be installed on a given laptop or CI runner silently changes the PDF a user gets. That's a worse version of the wall-clock WASM budget bug already reported upstream (ailang-core #662): behavior that depends on what's on the machine, invisible until someone compares two runs.

If a default is wanted at all, it should be **keyed to source format** (soffice for docx/odt/pptx-native sources, chromium for HTML-heavy sources, quarto for markdown/qmd-sourced docs — which is literally the reasoning the feature request itself gives for each backend) rather than "first one found on PATH." That ties the default to fidelity, not environment. Either way, this needs an explicit decision, not an inherited assumption from the request as filed.

## The hosted API tension this doc surfaces

`POST /api/v1/convert` is **live** (dev, `docparse` v0.16.0 / `ailang_parse` 0.31.0 — see [`CONTRACT_convert_endpoint.md`](../v0_32_0/CONTRACT_convert_endpoint.md)) and deliberately supports only `html md qmd docx pptx xlsx odt odp ods` — no `pdf`. That contract's generators are pure AILANG compute; nothing it currently does shells out to an external binary. Adding `pdf` to that endpoint means one of:

1. **Bundle soffice/chromium/quarto into the API's Cloud Run image.** This is the exact move `v0_21_0_quarto_integration.md` already rejected for Quarto specifically — "adding a Quarto binary to the API Docker image (~500MB with TinyTeX) doesn't make sense when there's a dedicated, battle-tested [multivac Quarto Cloud Run] service already running." `soffice` (LibreOffice + fonts) and `chromium` are comparably heavy. The current image is light enough that cold start is already ~47s per the CONTRACT doc; three multi-hundred-MB binaries would push that further, on every one of the three multivac environments (dev/test/prod, `europe-west1` — see the `sunholo/docparse` deploy topology).
2. **Proxy to a separate microservice**, following the precedent that already exists for Quarto at multivac (used by aitana). Real option, but it's new infrastructure work in a different repo (`sunholo/docparse`, private), not a docparse/`ailang_parse` change — bigger scope than this doc should claim.
3. **Ship PDF write as CLI/registry-only for v1**, matching how the CONTRACT doc already scoped `/convert` to exclude it. `mcpConvert`'s *local* (non-hosted) branch and the registry package both already run wherever the user's binaries are, so CLI users get soffice/quarto/chromium support with no image-size question at all.

Recommendation embedded in this doc: **(3) first.** It's the only option with no cross-repo dependency, and it's consistent with the CONTRACT doc's own current scope. Extending the hosted `/convert` endpoint to `pdf` is a separate decision for `sunholo/docparse`, to make once there's a real backend to point at.

## WASM: not a phase-2 gap, a hard no

[`v0_32_0_generation_surfaces.md`](../v0_32_0/v0_32_0_generation_surfaces.md) shows browser DOCX generation works today by keeping every generator step pure and letting JS do the one unavoidable effectful step (zipping). That trick has no equivalent here: `soffice`, `quarto`, and `chromium` are OS processes, categorically unreachable from a WASM sandbox. There's no "second lazily-fetched bundle" fix, no future unlock — PDF write cannot become a WASM demo capability under any of the three deterministic backends. Worth stating explicitly so nobody spends time routing `pdf` into `wasm-demo.js` or `MODULES_TO_LOAD` expecting it to eventually work; the `add-format` skill's whole WASM phase (3) is N/A for this feature and should be marked so up front if this is scaffolded from that checklist.

## Effects and capabilities

No new capability *class* — `Process` is already load-bearing for the PDF read path (`bin/docparse` already sets `NEEDS_PROCESS=true` for any `.pdf` input regardless of backend) and for the unshipped Quarto design. A write-side module follows the same `! {Process, FS}` shape as `quarto_render.ail`'s existing sketch. `--process-timeout` (default 30s) needs the same bump the Quarto doc already flags for TinyTeX-class renders — `soffice` cold-starts its own process pool on first invocation and can be slow the first time in a session.

## Non-goals (proposed, for whichever doc supersedes this one)

- No bundling/vendoring of soffice, quarto, or chromium binaries. User- or CI-installed, exactly like the Quarto policy already states.
- No hosted `/api/v1/convert` support in v1 (see above) — CLI and registry package only.
- No WASM/browser path, ever, for the reason above.
- No `ai` as a peer backend flag — it rides on `--generate` once a renderer exists, not on `--pdf-write-backend`.
- No silent cross-engine fallback (soffice fails → try chromium) without telling the user which engine actually ran — same "no silent 1-byte success" standard the read side already holds itself to.

## Suggested phasing (not committed — this doc is investigation, not a plan)

| Phase | Deliverable | Why this order |
|---|---|---|
| 1 | Ship the *existing* `v0.21.0` Quarto design as written (`quarto_render.ail`, `--via quarto`, QMD-sourced PDF/EPUB/RevealJS) | Already fully spec'd, zero new design risk, closes the exact two-step workaround the CLI help text documents today |
| 2 | `soffice_render.ail`, same shape as phase 1's module, direct docx/odt/pptx/html → PDF, `--via soffice` | Narrowest new backend; answers the motivating `.eml → .docx → PDF` case without going through QMD |
| 3 | Golden/verification strategy for non-byte-exact PDF output (`pdftotext`-based content assertions, not structural diff) | Needed before either phase 1 or 2 can get CI coverage the way `benchmarks/office/golden/` covers everything else |
| 4 | `chromium_render.ail` (HTML → PDF) | Heaviest new dependency, best fidelity for the HTML-heavy case; do after 1–2 prove out the module shape and CI story |
| 5 | Hosted-API decision (option 2 or 3 above) | Cross-repo, needs its own doc in `sunholo/docparse` once there's a backend to point at |
| — | `ai` as a `--generate` output target | Depends on 1 or 4 existing first (AI produces the intermediate, not the PDF) |

## Open questions

1. **Default backend when no `--via`/`--pdf-write-backend` is given at all** — error asking the user to pick, or format-keyed default (soffice for office-native, chromium for HTML, quarto for qmd)? This doc argues against "whichever is on PATH first"; it doesn't resolve what replaces it.
2. **Golden strategy for phase 3** — what's the actual assertion? Non-zero page count via `pdfinfo` (already used server-side in `adapter.py`) plus a text-content Jaccard against the source, skipped in CI when the backend binary is absent (same guard shape as `quartoAvailable()`)?
3. **Does `soffice`'s HTML import degrade badly enough on real `.eml` receipts to matter**, or was that specific to the one receipt that prompted this request? Worth a quick empirical check before ranking chromium's priority — it's the heaviest new dependency and its value depends on how bad soffice actually is on that input class.
4. Is there a scheduling target version for phase 1+2, or does this stay `unscheduled/` until prioritized? (Filed here rather than under a `vX_Y_Z/` folder since no version has been committed to it yet.)
