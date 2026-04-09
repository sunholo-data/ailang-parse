# Valuable Friction Onboarding

**Status**: Planned (v0.9.0)
**Category**: Growth / Go-to-Market
**Priority**: P1 — directly impacts conversion from evaluation to adoption

## Problem

AILANG Parse onboarding is optimized for minimum time-to-first-parse. The browser demo has zero friction (drag-and-drop, instant results, no signup). The SDK takes 3 steps and ~2 minutes. This is good for getting people in, but bad for retention.

**The core issue:** Users parse a file, get raw JSON blocks, and have no idea they just got something competitors cannot produce. The "aha moment" — realizing track changes, merged cells, and comments were preserved — is left entirely to chance.

Most users never discover the structural features that are the entire reason to use AILANG Parse over Unstructured, Docling, or LlamaParse.

## Principle

> "Cut annoying friction that doesn't add value, but ADD friction that helps users understand why the product is for them."
>
> — Adding steps to onboarding flows consistently improved conversion at Mercury, MasterClass, Calm, and Anthropic. The key is the friction must teach users what makes the product theirs.

## Current Onboarding Paths

| Path | Time-to-First-Parse | Friction | Problem |
|------|---------------------|----------|---------|
| Browser demo | 30 seconds | Zero | No interpretation of output — raw JSON |
| SDK (pip/npm/go) | ~2 minutes | Low (device auth) | `ParseResult` has no highlights |
| CLI | ~1 minute | Low | `printSummary` shows counts, not value |
| MCP | ~2 minutes | Low (2-line config) | Tool responses don't educate agents |

## Design: Add Valuable Friction

### 1. Structural Insights Banner (Browser Demo)

After every parse in the browser demo, display a banner between the info bar and output tabs that highlights what AILANG Parse found that competitors miss.

**Implementation:** Add `computeStructuralInsights(blocks)` function in `docs/js/wasm-demo.js` that inspects parsed blocks for:

| Block pattern | Insight message |
|---------------|----------------|
| `type === 'change'` | "N track changes preserved (author + date). 0/5 competitors extract these." |
| Table cells with `colSpan > 1` or `merged === true` | "N merged cells with colspan/rowspan. Competitors flatten to plain text." |
| `kind === 'comment'` sections | "N comments with author + position. Competitors strip these entirely." |
| `kind === 'header'` or `kind === 'footer'` | "Headers/footers extracted per-section. Competitors ignore these." |
| Parse time < 1000ms | "Parsed in Xms. No AI needed — deterministic XML extraction." |

Display using existing `.dp-callout` styling from `docs/css/components.css`, with competitive comparison context.

**Files:**
- `docs/js/wasm-demo.js` — add `computeStructuralInsights(blocks)`, call from `showOutput()` (~line 763)
- `docs/index.html` — add `<div id="structural-insights">` element (~line 1072)

**Effort:** Small (1-2 hours)

### 2. Guided Sample Tour

Replace the flat row of 13 sample buttons with a 3-step guided sequence that teaches the core value proposition in ~10 seconds:

**Step 1: "Track Changes"**
→ Parse `track_changes_move.docx`
→ Banner: "3 track changes found with authors and dates. 0/5 competitors extract these."

**Step 2: "Merged Cells"**
→ Parse `challenge_merged_cells.xlsx`
→ Banner: "4 merged cells with colspan/rowspan. Competitors flatten these."

**Step 3: "Your File"**
→ Dropzone activates with CTA: "Now try your own file. See what structure you've been losing."

The full sample list remains accessible via a "Show all samples" toggle for power users.

**Files:**
- `docs/js/wasm-demo.js` — add guided tour state machine
- `docs/index.html` — restructure sample buttons area

**Effort:** Medium (3-4 hours)

### 3. Intent Selector — "What Matters to You?"

Add three clickable cards above the demo section:

| Card | Auto-loads | Emphasizes |
|------|-----------|------------|
| "Contracts & legal docs" | `track_changes_move.docx` | Track changes, author attribution, comments |
| "Spreadsheet data extraction" | `challenge_merged_cells.xlsx` | Merged cells, structure preservation |
| "Fast bulk document parsing" | `challenge_formatting.docx` | Speed (Xms), no AI needed, per-document pricing |

Selection sets a `userIntent` variable that personalizes:
- Which sample loads first
- Which structural insights are emphasized in the banner
- Which CTA appears after parsing (e.g., "API for contract review pipelines" vs "CLI for batch processing")

**Files:**
- `docs/index.html` — add intent selector UI above demo
- `docs/js/wasm-demo.js` — handle intent selection, personalize output

**Effort:** Medium (3-4 hours)

### 4. CLI "Only AILANG Parse" Summary

Extend `printSummary` in `docparse/services/output_formatter.ail` to add a structural advantage section after the existing block counts:

```
=== Document Summary ===
Format:   docx
Blocks:   24
Headings: 3
Tables:   2
Images:   1
Sections: 4
Changes:  3

=== Only AILANG Parse ===
Track changes: 3 (with author + date attribution)
Merged cells:  2 (colspan/rowspan preserved)
Comments:      1 (with position and author)
Headers:       2 (per-section, not flattened)
Parse time:    12ms (deterministic, no AI)
→ These features are lost when converting to PDF first.
========================
```

**File:** `docparse/services/output_formatter.ail` — extend `printSummary` (~line 171)

**Effort:** Small (1 hour)

### 5. MCP Response Education

#### 5a. `mcpFormats` — Add `competitive_advantage` field

```json
{
  "formats": [...],
  "competitive_advantage": {
    "track_changes": "Full extraction with author, date, original/revised text. 0/5 other parsers tested extract this.",
    "merged_cells": "colspan/rowspan preserved as typed metadata. Others flatten to individual cells.",
    "comments": "Author, date, position, and reply threads. Others strip entirely.",
    "speed": "Office formats: <100ms (deterministic XML). Others: 2-5 seconds (ML reconstruction).",
    "pricing": "Per-document, not per-page. 100-page PDF = 1 request."
  }
}
```

Agents that read this understand what to highlight to users and can make informed parser recommendations.

#### 5b. `mcpParse` — Add `structural_notes` to output

```json
{
  "document": { ... },
  "structural_notes": [
    "3 ChangeBlocks extracted with author attribution — most parsers drop track changes entirely",
    "Table at block[7] has 2 merged cells (colspan:2) — preserved as typed metadata",
    "2 comments extracted with author and position metadata"
  ]
}
```

**Files:**
- `docparse/services/mcp_tools.ail` — modify `mcpFormats` and `mcpParse` output
- `docparse/services/output_formatter.ail` — add `structuralNotesToJson(blocks)` function

**Effort:** Medium (2-3 hours)

### 6. SDK First-Parse Highlights

Add `highlights` property to Python `ParseResult` that computes structural insights from blocks:

```python
@property
def highlights(self) -> List[str]:
    """What AILANG Parse extracted that competitors typically miss."""
    highlights = []
    changes = [b for b in self.blocks if b.type == 'change']
    if changes:
        highlights.append(f"{len(changes)} track changes with author/date (0/5 competitors extract these)")
    # ... merged cells, comments, headers/footers, parse time
    return highlights
```

On first parse, print to stderr (suppressible via `DOCPARSE_QUIET=1`):

```
AILANG Parse found 5 features competitors miss:
  - 3 track changes with author/date
  - 2 merged cells with colspan
  - 1 comment with author metadata
  - Parsed in 42ms (no AI needed)
```

**Files:**
- `sdks/python/ailang_parse/types.py` — add `highlights` property to `ParseResult`
- `sdks/python/ailang_parse/client.py` — add first-run stderr output

**Effort:** Small (1-2 hours)

## Design: Cut Annoying Friction

These remove irritation that adds no value:

| Friction | Fix | File | Effort |
|----------|-----|------|--------|
| CLI `--help` is a dead end | Add doc links to `usage()` output | `bin/docparse` | 15 min |
| No quota warnings before hitting limits | Add `X-Quota-Remaining` header to API responses; SDK reads and warns at 90% | Server + SDKs | 2 hours |
| MCP config errors silently fail | Validate connection on startup, print diagnostic to stderr | `sdks/js/` | 1 hour |
| No onboarding email after device auth | Trigger welcome email: "Here's what you got that others miss" | Server-side | 2 hours |
| Competitor annotation in Parsed view | Badge "Only AILANG Parse" next to change/merged-cell blocks | `docs/js/wasm-demo.js` | 1 hour |

## Implementation Phases

### Phase 1: Quick Wins (1 day)
- **Structural insights banner** (Item 1) — highest impact, teaches value on every parse
- **CLI printSummary enhancement** (Item 4) — developer-facing, immediate
- **CLI --help links** — 15 minutes, removes a dead end
- **mcpFormats competitive_advantage** (Item 5a) — educates agents immediately

### Phase 2: Guided Experience (1-2 days)
- **Guided sample tour** (Item 2) — replaces random samples with educational sequence
- **mcpParse structural notes** (Item 5b) — teaches agents per-parse
- **SDK highlights property** (Item 6) — developer first-run experience
- **Intent selector** (Item 3) — personalizes the demo

### Phase 3: Polish (1 day)
- Quota warnings via `X-Quota-Remaining`
- MCP config error diagnostics
- Onboarding email after device auth
- Competitor annotation badges in Parsed view

## Success Metrics

| Metric | Current | Target | How to measure |
|--------|---------|--------|----------------|
| Users who parse >1 file in browser demo | Unknown | +50% | Analytics event on 2nd parse |
| Users who try "Your file" after guided tour | N/A | 40% | Analytics event on dropzone after tour |
| SDK users who discover highlights | 0% | 80% | stderr output fires on first parse |
| Time from first parse to "I understand the differentiator" | Minutes (if ever) | 10 seconds | Qualitative (user interviews) |

## Mobile Compatibility

All browser changes must work at 768px breakpoint per existing project requirements. The structural insights banner, guided tour, and intent selector must be fully responsive.

## Verification

1. **Browser demo**: Parse `track_changes_move.docx` → verify insights banner shows change count + competitor comparison
2. **CLI**: `./bin/docparse data/test_files/track_changes_move.docx` → verify "Only AILANG Parse" section
3. **MCP**: Call `mcpFormats` → verify `competitive_advantage` field present
4. **SDK**: `python -c "from ailang_parse import DocParse; r = DocParse().parse('sample.docx'); print(r.highlights)"` → verify highlights list
5. **Mobile**: Resize browser to 768px → verify all new UI elements are usable
