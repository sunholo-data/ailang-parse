# Workbench Page

**Status**: IMPLEMENTED (v0.9.1)
**Category**: Growth / Frontend
**Priority**: P1 — bridges the gap between 30-second homepage demo and full CLI/API adoption
**Related**: [valuable_friction_onboarding.md](valuable_friction_onboarding.md), [api_playground.md](../../implemented/v0_8_0/api_playground.md), [website.md](../../implemented/v0_8_0/website.md)

> Living document. Decisions, mockups, and open questions are updated in place as the workbench evolves. Move to `implemented/` only when shipped.

## Problem

The AILANG Parse homepage hosts a single-file WASM demo (`docs/index.html` lines 1037–1112, driven by `docs/js/wasm-demo.js`). It is excellent for first-touch — drop a file, see blocks in 30 seconds, no signup — but it is a dead end for evaluation:

- **One file at a time.** No batch view, no library, no comparison across documents.
- **Read-only output.** The Original / Parsed / JSON / Markdown / A2UI panels can be inspected but not refined, filtered, exported, or chained.
- **No path to PDFs, large files, or generation** without leaving the page and learning the CLI or API.
- **No persistent surface for the friction-onboarding nudges** ([valuable_friction_onboarding.md](valuable_friction_onboarding.md)). The homepage is already crowded; the structural-insights banner, intent selector, and guided tour need somewhere to live at scale without competing with the hero.

Today's funnel jumps from "30-second homepage demo" straight to "install the CLI / sign up for the API" with no intermediate rung for the user who has *more* files to evaluate but isn't yet ready to commit to tooling.

## Principle

> **Add a power-user surface in the browser that keeps WASM-first ethos and earns its way to the CLI/API by doing real work — not by hiding features behind a paywall.**

Four supporting principles:

1. **WASM-first.** Every feature works in-browser without an account whenever possible. The hosted API is a graceful upgrade for things WASM cannot do (PDFs, large files, generation), never a paywall on things WASM already handles.
2. **One canonical engine.** Parsing always goes through the existing `docs/ailang/docparse/services/docparse_browser.ail` entry. No JavaScript reimplementation. (Project rule: single AILANG codebase.)
3. **Friction with purpose.** Borrow the structural-insights, intent-selector, and guided-tour primitives from [valuable_friction_onboarding.md](valuable_friction_onboarding.md) and surface them at moments that *teach* — never as gatekeeping.
4. **Designed, not assembled.** Use the `frontend-design` skill so the workbench has the same "Precision Instrumentation" identity as the rest of the site (Source Serif 4 + DM Sans + JetBrains Mono, emerald + DocParse blue, warm cream surfaces, top-stripe cards). No new color system; the workbench extends the existing visual language rather than competing with it.

## Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Lives at `docs/workbench.html`, a new top-level page | Shareable, linkable, can be referenced from homepage / docs / CLI `--help` |
| 2 | Auth = reuse Firebase login from the API playground | Same flow users already see on `docs/playground.html`; no BYO API key in localStorage |
| 3 | Initial API use cases: PDF/image parsing, files >20 MB, format conversion, document generation | Covers the things WASM genuinely cannot do; clear value for upgrade |
| 4 | Engine switcher is a single component | So future roadmap items (structured extraction v0.11, RAG v0.13, etc.) plug in without redesigning the UI |
| 5 | Side-by-side WASM-vs-API diff is **not** in initial scope | Listed as an Open Question for Phase 3+; cheap to add once both engines are wired |
| 6 | Visual identity: emerald = WASM/free affordances, amber = API/signed-in affordances, DocParse blue = workbench accent | Gives the engine switcher a clear at-a-glance state and reuses existing tokens |

## Layout & UX

A full-width app shell with three regions, sitting under the standard shared header (`docs/js/components.js`).

```
┌─────────────────────────────────────────────────────────────┐
│  Header (shared components.js)                              │
├──────────────┬──────────────────────────────┬───────────────┤
│              │                              │               │
│  Library     │   Active document            │   Inspector   │
│  (left rail) │   (center stage)             │   (right rail)│
│              │                              │               │
│  • file1.docx│   ┌──── tabs ────┐           │  Insights     │
│  • file2.pptx│   │ Preview      │           │  • 3 changes  │
│  • report.pdf│   │ Blocks       │           │  • 2 merged   │
│  + drop more │   │ JSON         │           │                │
│              │   │ Markdown     │           │  Actions      │
│              │   │ A2UI         │           │  • Convert →  │
│              │   │ Convert      │           │  • Download   │
│              │   └──────────────┘           │  • Open in CLI│
│              │                              │                │
│              │                              │  Engine: WASM │
│              │                              │  [⇄ try API]  │
└──────────────┴──────────────────────────────┴───────────────┘
```

### Left rail — Library

- Drag-and-drop multi-file zone. Accepts everything WASM accepts today (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, MD, CSV, EPUB, EML), plus PDFs and images via the API path.
- Per-file status chip: `parsing` / `done` / `errored` / `queued-for-API` / `needs-signin`.
- Reorder, remove, "Parse all" button.
- Persists session via `IndexedDB` so reloads don't lose work. Only file metadata + parsed output are stored — never re-uploaded blobs.
- Empty state shows the "Load demo set" affordance (5 sample files) borrowed from the friction-onboarding guided-tour primitive.

### Center — Active document

Reuses the existing tab structure from `wasm-demo.js` (Preview / Blocks / JSON / Markdown / A2UI), expanded:

- **Preview** — same as today, file-type-aware preview.
- **Blocks** — filterable by type (heading / table / change / comment / image / paragraph / section). Click a block to scroll the preview.
- **JSON** — search bar with live highlight; copy + download `.json`.
- **Markdown** — copy + download `.md`.
- **A2UI** — same vendored component rendering as today.
- **Convert** *(new)* — pick a target format from a dropdown, calls `POST /api/v1/convert` for formats WASM cannot generate cleanly. Shows the target file as a download once ready.

### Right rail — Inspector

- **Structural Insights panel** — the friction-onboarding banner content (track changes, merged cells, comments, headers/footers, parse time) but persistent and per-document, not a one-shot toast. Always present, always educates.
- **Actions**:
  - Download as… (current tab's format)
  - Copy CLI command for *this exact file* — `./bin/docparse <filename>` plus suggested flags
  - Copy SDK snippet (Python / JS / Go selector)
  - Send to API (re-parse via hosted API for comparison or to unlock features)
- **Engine indicator** — `WASM` (emerald) by default, `API` (amber) when toggled. One-click switch triggers Firebase login if needed. When `API` is active, a quota strip appears below.

### Top of page — Intent Selector (above app shell)

Optional row of cards from the friction-onboarding doc:

- "Contracts & legal" → emphasizes track changes, comments, author attribution
- "Spreadsheets" → emphasizes merged cells, formulas, structure preservation
- "Bulk parsing" → emphasizes speed, no-AI, per-document pricing
- "PDFs & scans" → emphasizes the API path, AI model selection

The selection persists per session and personalizes which insights are highlighted in the right rail and which sample files load with "Load demo set".

## WASM ⇄ API boundary

| Scenario | Engine | Why |
|---|---|---|
| Office formats < 20 MB | WASM | Free, instant, private |
| HTML / MD / CSV / EML | WASM | Same |
| PDF / PNG / JPG | API (Firebase login) | Needs Gemini, and we don't ship API keys to browsers |
| File > 20 MB | API | Browser memory ceiling; API tier limit |
| Format conversion (`→ DOCX`, `→ PPTX`, `→ Quarto`) | API `/api/v1/convert` | Generation pipeline lives server-side |
| Document generation from prompt | API `/api/v1/generate` | Same |
| **Future**: structured extraction (v0.11) | API | Roadmap hook |
| **Future**: RAG chunking / embeddings (v0.13) | API or WASM | Roadmap hook — engine switcher absorbs new modes |

The engine switcher is a single component so future roadmap items plug in without redesigning the UI.

## Friction nudges in the workbench

Cross-references [valuable_friction_onboarding.md](valuable_friction_onboarding.md) and explicitly partitions which nudges live where:

| Nudge | Homepage demo | Workbench |
|---|---|---|
| Structural insights banner | One-shot below output | Persistent right-rail per doc |
| Guided sample tour | 3-step intro | "Load demo set" button (loads 5 sample files at once) |
| Intent selector | Above demo | Above app shell, persists per session |
| "Open in CLI" / "Open in SDK" copy | n/a | Per-file action button with exact command |
| Quota warnings (when API engine on) | n/a | Inspector quota strip at 80% / 95% |
| Per-block "Only AILANG Parse" badges | n/a | Inline annotation in Blocks tab on `change`, merged-cell, and comment blocks |

## Visual design direction

To be filled in with mockups generated via the `frontend-design` skill in a follow-up turn. Constraints captured up front so the mockups land in the right ballpark:

- **Tokens only from `docs/css/design-system.css`.** No new colors, no new font stacks.
- **Three-region shell collapses to single column at 768 px.** Mobile compatibility is a hard project rule. On mobile the Library and Inspector become bottom-sheet drawers triggered from a sticky bottom toolbar.
- **Component vocabulary already in the site:** top-stripe cards, dashed dropzones, dark code blocks, monospace badges, staggered fadeInUp animations.
- **Engine identity:**
  - `--dp-blue` (#2563eb) — workbench accent (active tab, focus rings, primary CTAs)
  - emerald (#00b37a) — "WASM / free / instant" affordances
  - amber (#d97706) — "API / signed in / quota'd" affordances
- **Animations:** reuse staggered fadeInUp and scroll-reveal patterns from `homepage-v2.css`. Do not invent new ones.

## Implementation Phases

### Phase 0: Design & mockups *(this milestone)*
- This design doc (✅ on first write)
- Frontend mockups via `frontend-design` skill — full layout + key states (empty, parsing, signed-out, signed-in, mobile)

### Phase 1: Shell + Library + WASM reuse
- `docs/workbench.html` shell with three-region layout
- `docs/js/workbench.js` controller
- Refactor `docs/js/wasm-demo.js` to extract reusable parse helpers (`parseFile(file) → blocks`) into a module-scoped export so the workbench imports without duplicating WASM init or AILANG module loading
- Multi-file library with IndexedDB session persistence
- Active document tabs (Preview / Blocks / JSON / Markdown / A2UI), reusing existing rendering logic

### Phase 2: Inspector & friction nudges
- Structural Insights panel (per-doc, persistent)
- Action buttons: Download, Copy CLI command, Copy SDK snippet
- Per-block "Only AILANG Parse" badges in the Blocks tab
- Filterable Blocks view, JSON search, Markdown copy/download

### Phase 3: API engine + Firebase auth
- Engine switcher component
- Firebase login wired from existing playground patterns
- API endpoints: `POST /api/v1/parse`, `POST /api/v1/convert`, `POST /api/v1/generate`
- Quota strip with 80% / 95% warnings (consumes `X-Quota-Remaining` header — see friction doc Phase 3)
- PDF / image / >20MB routing to API path

### Phase 4: Polish
- Intent selector at top of page
- "Load demo set" guided sample tour
- Mobile pass — drawers, bottom toolbar, gestures
- Analytics instrumentation (see Open Questions #4)

## Open Questions

These live here and are answered as the workbench evolves.

1. **Session export** — Should parsed results be exportable as a single zip ("workbench session export") so users can share with colleagues or support? Cheap to add if all output formats already exist client-side.
2. **WASM vs API diff view** — Side-by-side comparison of the same file parsed both ways. Trust-building ("see, the API gives you the same answer for Office formats") and useful for debugging. Cheap once both engines are wired in Phase 3.
3. **Nav placement** — New top-level "Workbench" entry, or nested under a "Try it" submenu? Top-level is more discoverable but adds nav weight.
4. **Analytics** — Which interactions instrument the friction hypotheses from [valuable_friction_onboarding.md](valuable_friction_onboarding.md)? Minimum viable: parse count per session, engine switches, CLI/SDK snippet copies, API conversion attribution.
5. **Installer detection for "Open in CLI"** — Should the copy button check whether the user already has `docparse` installed (e.g. via a custom URL scheme handshake) or is the raw copy command good enough? Probably good enough to start.
6. **Anonymous API access** — Should we allow N free API calls without Firebase login (rate-limited by IP / browser fingerprint) so PDF parsing isn't fully gated? Trades off conversion friction against abuse risk; defer to Phase 3 implementation.

## Success Metrics

| Metric | Current | Target | How to measure |
|---|---|---|---|
| Workbench visitors who parse > 3 files | N/A | 40% | Analytics event on 4th parse |
| % of workbench sessions that switch engine to API at least once | N/A | 15% | Engine switcher click event |
| % who copy a CLI/SDK snippet | N/A | 25% | Click event on action button |
| Bounce rate on workbench vs homepage demo | TBD | Lower | Comparative analytics |
| API key conversions attributed to workbench vs cold signup | N/A | 2x cold | Funnel attribution via UTM / referrer |

## Mobile Compatibility

All workbench changes must work at the 768 px breakpoint per existing project requirements (see `MEMORY.md`: "Mobile compatibility required"). Specifically:

- Three-region shell collapses to single column
- Library becomes a bottom-sheet drawer with the file count badge in a sticky toolbar
- Inspector becomes a second bottom-sheet drawer
- Tab strip in the center remains horizontally scrollable
- All action buttons are reachable without horizontal scroll

## Verification

Once implemented, verify end-to-end:

1. Open `docs/workbench.html` locally → empty state shows "Load demo set" and dropzone
2. Drop `data/test_files/sample.docx`, `sample.pptx`, `sample.xlsx` → all three parse via WASM, library shows them with `done` chips
3. Click each library item → center tabs update, right-rail insights update per document
4. Click "Convert" tab → pick HTML → file downloads
5. Drop `data/test_files/sample.pdf` → status `needs-signin`, prompt shows Firebase login
6. Sign in → engine indicator flips to amber `API`, PDF parses, quota strip appears
7. Click "Copy CLI command" → exact `./bin/docparse <filename>` command in clipboard
8. Click "Copy SDK snippet" → Python / JS / Go selector, copies appropriate import + parse call
9. Resize browser to 768 px → three-region shell collapses to single column with bottom drawers
10. Reload page → IndexedDB restores library
11. All existing homepage demo tests still pass (workbench is additive — no regression in `wasm-demo.js`)

## Critical files (for the eventual implementation)

- **NEW**: `docs/workbench.html` — page shell
- **NEW**: `docs/js/workbench.js` — controller
- **NEW**: `docs/css/workbench.css` — three-region shell layout only; everything else from `design-system.css`
- **EDIT**: `docs/js/wasm-demo.js` — extract reusable parse helpers (`parseFile(file) → blocks`) into module scope so workbench can import without duplicating WASM init
- **EDIT**: `docs/js/components.js` — add Workbench to nav
- **EDIT**: `docs/js/site-data.js` — register page
- **REUSE**: `sdks/js/src/client.ts` — TypeScript API client; the workbench can call its REST endpoints directly via `fetch` to keep the page dependency-light, mirroring shapes from this client
