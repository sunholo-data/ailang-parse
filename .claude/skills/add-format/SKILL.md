---
name: add-format
description: End-to-end checklist for adding a new input or output format to AILANG Parse (docparse). Use when the user says 'add support for X format', 'wire up a new parser', 'add .foo format', 'add a parser for .bar', 'support .baz files', 'ship format X', 'can we parse .qux', 'new format rollout', or mentions a file extension that isn't yet supported (e.g. 'what about RTF', 'add Jupyter notebooks'). Covers parser code, ailang.toml exports, WASM demo, vendor-wasm-packages.sh, homepage, workbench, all format-list surfaces across the docs site, SDK READMEs, release tag, registry publish, and the ailang messages send docparse downstream notification. Use even when only part of this is requested — the skill tells you which surfaces you'd otherwise miss.
---

# Add a new format to AILANG Parse

## When to Use

Invoke this skill any time a new input or output format is being added to AILANG Parse — no matter how the request is phrased. The cost of forgetting a surface (Pages deploys failing silently, registry out of sync with docs, SDK READMEs stale) is far higher than the cost of running through the checklist. Also use it when the user asks "what's left?" mid-rollout, to audit which surfaces are still missing.

## Quick Start

1. Confirm scope with user (see [Before you start](#before-you-start)).
2. Work through phases 1→7 in order. Do not batch phases 3+ before phases 1–2 type-check and smoke-test cleanly.
3. Use the [Files checklist](#files-checklist-use-this-to-audit-a-pr) at the end as the final PR audit.

## Workflow

Adding a format hits ~20 distinct files across parser code, WASM bundle, docs, SDKs, release manifests, and deployment messaging. Skipping any one of them breaks something silently — the LaTeX/v0.15.0 rollout missed the vendor script and two Pages deploys failed before anyone noticed. Work through this list in order; do not batch steps 6-8 before 1-5 are green.

## Before you start

Confirm with the user:
1. **Extension(s)** — e.g. `.tex`, `.latex`, `.ltx`
2. **Parser strategy** — deterministic (XML/text → Block ADT) or AI-assisted (PDF/image)?
3. **Archive wrapper?** — some formats ship as `.tar.gz`/`.zip` bundles. If yes, flag which archive tooling is missing (see `std/tar`/`std/gzip` blocker tracked as ailang-core#156).
4. **Will the WASM demo support it?** — pure parser with no FS/AI effect = yes. FS-dependent (like multi-file `\input` resolution) = server-side only, WASM gets a single-file subset.

Set a working variable — `$FMT` in examples below is the lowercase short name (`tex`, `epub`, etc.).

---

## Phase 1 — Parser (AILANG source)

1. **Write the parser** → `docparse/services/${FMT}_parser.ail`
   - Export a **pure** entry point: `export pure func parse${Fmt}(content: string) -> [Block]`
   - Match block ADT variants from `docparse/types/document.ail`; don't add new variants unless absolutely necessary.
   - Follow the foldl + reverse pattern from `markdown_parser.ail` — see [feedback_ailang_string_perf.md](/Users/mark/.claude/projects/-Users-mark-dev-sunholo-ailang-parse/memory/feedback_ailang_string_perf.md) — never `concat(xs, [x])` in foldl.

2. **If the format needs FS (multi-file resolution, archive extraction)**:
   - Write a separate helper: `docparse/services/${FMT}_input_resolver.ail` (or `_extract.ail`)
   - Keep effects minimal: `! {FS}` only where unavoidable.
   - The pure `parse${Fmt}` must still work without FS for the WASM path.

3. **Register the format** → `docparse/services/format_router.ail`
   - Add the extension(s) to the detection table.

4. **Wire the CLI dispatcher** → `docparse/main.ail`
   - Add the case that calls your parser + passes blocks to `output_formatter`.

5. **Type-check + smoke test**:
   ```bash
   ailang check docparse/
   ./bin/docparse data/test_files/<sample>.$FMT
   ```

## Phase 2 — Package (ailang.toml)

6. **Add to `[exports]` modules list** in `ailang.toml` — including the input_resolver helper if you made one. **Missing this means consumers of the installed package silently lack the format.**

7. **Bump the package version** in `ailang.toml` (e.g. `0.9.3 → 0.10.0`). Follow the release checklist at [feedback_release_checklist.md](/Users/mark/.claude/projects/-Users-mark-dev-sunholo-ailang-parse/memory/feedback_release_checklist.md) for all version files to sync.

8. **Bump the AILANG constraint if needed** — `ailang = ">=X.Y.Z"` — to match whatever stdlib features your parser uses.

9. **Regenerate the lock**:
   ```bash
   ailang lock
   ```

10. **Sync `pyproject.toml`** (root) — it tracks the AILANG package version for release parity.

## Phase 3 — WASM demo (the trap that bit us last time)

11. **Add the browser wrapper** → `docparse/services/docparse_browser.ail`
    - Import your pure parser: `import docparse/services/${FMT}_parser (parse${Fmt})`
    - Export a content wrapper:
      ```
      export pure func parse${Fmt}Content(content: string) -> string {
        encode(ja(blocksToJson(parse${Fmt}(content))))
      }
      ```
    - **Do NOT use FS effect here** — WASM can't do FS. Multi-file resolution stays server-side.

12. **Mirror sources into `docs/ailang/`**:
    ```bash
    cp docparse/services/${FMT}_parser.ail docs/ailang/docparse/services/
    cp docparse/services/docparse_browser.ail docs/ailang/docparse/services/
    ```

13. **⚠️ Add to vendor script** → `docs/scripts/vendor-wasm-packages.sh`
    - Append `"services/${FMT}_parser.ail"` to the `MODULES=(…)` array.
    - **This is the step everyone forgets.** CI runs `docs/scripts/check-wasm-bindings.py` before deploying Pages — if `MODULES_TO_LOAD` and this script disagree, deploy fails and the live homepage silently stays on the previous commit.

14. **Wire the demo JS** → `docs/js/wasm-demo.js`
    - Add to `MODULES_TO_LOAD` array:
      `{ name: 'docparse/services/${FMT}_parser', path: 'docparse/services/${FMT}_parser.ail' }`
    - Add extension(s) to **both** `textFormats` arrays (two copies, lines ~391 and ~2040).
    - Route in `parseTextFile`:
      ```js
      } else if (ext === '${FMT}' || ext === 'otheralias') {
        r = engine.call('parse${Fmt}Content', content);
      }
      ```

15. **Verify bindings locally**:
    ```bash
    python3 docs/scripts/check-wasm-bindings.py
    ```
    Must say "✓ All WASM binding checks passed" before you push.

## Phase 4 — Homepage and workbench

16. **Create a sample asset** → `docs/assets/sample_${FMT}.${FMT}` (or whatever extension)
    - ~100 lines, self-contained, exercises every feature the landing page pitches.
    - Verify with `./bin/docparse docs/assets/sample_${FMT}.${FMT}` and check the block output is rich.

17. **Homepage** → `docs/index.html`
    - Add extension to `<input type="file" accept="…">`.
    - Add `<span>${FMT_UPPER}</span>` to the format ticker.
    - Add `<button class="dp-demo-btn" data-file="assets/sample_${FMT}.${FMT}" title="…">${Label}</button>` to the samples row.
    - If homepage has a format grid card section, add a card linking to `docs/${FMT}-parsing.html`.

18. **Workbench** → `docs/workbench.html`
    - Add extension to `accept=".…"`.
    - Add sample path to `DEMO_SET` array.

19. **Shared data** → `docs/js/site-data.js`
    - Add to `formats.input` array.
    - Bump `formats.input_count`.

## Phase 5 — Documentation surfaces

20. **Landing page** → `docs/${FMT}-parsing.html` — use the `/landing-page` skill.

21. **Docs hub** → `docs/docs.html` — add a card under Document Formats grid linking to the landing page.

22. **Benchmarks** → `docs/benchmarks.html` — add a section if there's a relevant benchmark suite.

23. **Format-list consistency** (doc-only, but ~6 files):
    - `docs/api.html` — supported-formats list in quickstart / reference
    - `docs/claude-code.html` — "N Input Formats" section
    - `docs/integrations.html` — deterministic formats list
    - `docs/migrate-from-unstructured.html` — format list (usually 2 occurrences — use replace_all)
    - `docs/privacy.html` — deterministic-format parsing paragraph
    - `README.md` — "Parsing (N formats)" line
    - `CLAUDE.md` — project-purpose paragraph

24. **SDK READMEs** (doc-only, no version bump — SDK code is format-agnostic):
    - `sdks/python/README.md` — "Parse N formats" line + any format lists
    - `sdks/go/README.md`
    - `sdks/js/README.md`
    - `sdks/r/README.md`

## Phase 6 — Release

25. **Run full checks**:
    ```bash
    ailang check docparse/                          # type-check
    ./bin/docparse --test                            # inline tests
    python3 docs/scripts/check-wasm-bindings.py      # WASM bindings
    uv run benchmarks/run_benchmarks.py --suite office   # no regressions
    ```

26. **Commit and push**. Prefer one commit per phase (parser / package / wasm / docs / release-bump) over a single mega-commit.

27. **Tag the release**:
    ```bash
    git tag v$NEW_VERSION && git push origin v$NEW_VERSION
    ```
    Fires [publish-ailang.yml](.github/workflows/publish-ailang.yml). Watch with `gh run list --workflow=publish-ailang.yml --limit 1` — prior runs take ~6-7 min.

28. **Watch the Pages deploy**:
    ```bash
    gh run list --workflow=pages.yml --limit 2
    ```
    If it shows failure within ~20s, it's the bindings check — you missed step 13 or something equivalent.

29. **Verify the registry has the new version**:
    ```bash
    ailang install sunholo/ailang_parse@$NEW_VERSION --dry-run
    ```

## Phase 7 — Downstream notification

30. **Message the API deployment repo**:
    ```bash
    ailang messages send docparse "sunholo/ailang_parse v$NEW_VERSION available — adds .${FMT} parsing. Pull and rebuild when ready. No API/route changes. …" \
      --from ailang-parse \
      --title "ailang_parse v$NEW_VERSION incoming — .${FMT} support"
    ```
    Include: new modules, Block ADT impact (almost always "no changes"), known caveats (archive support, FS requirements), benchmark numbers if relevant.

## What we learned from LaTeX (v0.15.0)

- The vendor script (step 13) is the most-missed surface. Pages deploys fail silently and the homepage serves a stale build — users see a missing button and think the feature is broken.
- "Format-list consistency" across the site (step 23) requires a thorough pass; the user caught multiple misses with "we need to be more thorough in adding the format updates around the website".
- Never ship a JS fallback that fakes parsing when the AILANG path isn't wired (see [feedback_no_fallbacks.md](/Users/mark/.claude/projects/-Users-mark-dev-sunholo-ailang-parse/memory/feedback_no_fallbacks.md)). Either wire the real thing or remove the sample button until you do.
- SDKs are format-agnostic — don't bump SDK versions for format additions unless SDK code actually changed.
- `0.10.0 ≠ `bug fix — if you're adding a format, it's a feature release. Pick the version accordingly.

## Files checklist (use this to audit a PR)

Parser code:
- [ ] `docparse/services/${FMT}_parser.ail`
- [ ] `docparse/services/${FMT}_input_resolver.ail` *(if multi-file/archive)*
- [ ] `docparse/services/format_router.ail`
- [ ] `docparse/main.ail`
- [ ] `docparse/services/mcp/tools.ail` — add an `mcpFormatEntry` to `mcpFormats()`.
      **This is how agents discover the format exists.** Set the feature flags
      (tables / track_changes / comments / images) from what the parser actually
      produces on a real file, not from intent — md and html both sat advertising
      `images: false` long after they surfaced images.

Verification (all three, not just the office suite):
- [ ] `bash benchmarks/generate_golden.sh` — new file gets a golden
- [ ] `uv run benchmarks/run_benchmarks.py --suite office` — must be 100%
- [ ] `uv run benchmarks/roundtrip_check.py` — parse → md → parse
- [ ] `uv run benchmarks/verify_generated.py` — if the format is also an OUTPUT

Package:
- [ ] `ailang.toml` (exports + version + ailang constraint)
- [ ] `ailang.lock`
- [ ] `pyproject.toml`

WASM:
- [ ] `docparse/services/docparse_browser.ail` (+ mirror to `docs/ailang/`)
- [ ] `docs/ailang/docparse/services/${FMT}_parser.ail`
- [ ] `docs/scripts/vendor-wasm-packages.sh` — the module MUST be in `MODULES`.
      The registry validator type-checks the WHOLE checkout, so a vendored copy
      nothing refreshes goes stale against the canonical tree and fails the
      publish (v0.33.0 died exactly this way). The script now fails on any
      orphan, and `check-wasm-bindings.py` fails on any vendored module the demo
      does not load — the two together pin the set from both sides.
- [ ] `docs/js/wasm-demo.js` (MODULES_TO_LOAD + both textFormats + parseTextFile route)

UI:
- [ ] `docs/assets/sample_${FMT}.${FMT}`
- [ ] `docs/index.html` (accept, ticker, button, grid card)
- [ ] `docs/workbench.html` (accept, DEMO_SET)
- [ ] `docs/js/site-data.js`

Docs:
- [ ] `docs/${FMT}-parsing.html`
- [ ] `docs/docs.html`
- [ ] `docs/benchmarks.html` *(if applicable)*
- [ ] `docs/api.html`
- [ ] `docs/claude-code.html`
- [ ] `docs/integrations.html`
- [ ] `docs/migrate-from-unstructured.html`
- [ ] `docs/privacy.html`
- [ ] `README.md`
- [ ] `CLAUDE.md`

SDK READMEs:
- [ ] `sdks/python/README.md`
- [ ] `sdks/go/README.md`
- [ ] `sdks/js/README.md`
- [ ] `sdks/r/README.md`

Release:
- [ ] `git tag` pushed
- [ ] `gh run view` — publish-ailang succeeded
- [ ] `gh run view` — pages deploy succeeded
- [ ] `ailang install … --dry-run` — registry has new version
- [ ] `ailang messages send docparse …` — deployment repo notified
