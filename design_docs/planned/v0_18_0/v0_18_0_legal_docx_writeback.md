# Design Doc: Legal-Grade DOCX Write-Back (v0.18.0)

**Status**: Planned
**Date**: 2026-05-03
**Author**: Mark + Claude
**Source**: Gap analysis vs [willchen96/mike](https://github.com/willchen96/mike) (OSS AI Legal Platform). AILANG already beats Mike on DOCX *parsing* (tracked changes, comments, headers/footers, equations, field codes); the gap is on the *write* side. Closing it makes ailang-parse the natural backend for legal-AI workflows (contract drafting, redlining, due-diligence matrices).

**Repo split (which bits land where):**

| Component | Repo | Doc |
|---|---|---|
| Read-side redline renderer (Part 0) | **ailang-parse** | this doc |
| `docx/` writer module (Part 1) | **ailang-parse** | this doc |
| Tracked-changes write-back (Part 2) | **ailang-parse** | this doc |
| `docparse legal` reference CLI (Part 3) | **ailang-parse** | this doc |
| `std/ai.step` / `runTools` tool-loop (upstream) | **ailang stdlib** | [ailang/design_docs/planned/v0_17_0/m-ai-tool-loop.md](https://github.com/sunholo-data/ailang/blob/dev/design_docs/planned/v0_17_0/m-ai-tool-loop.md) |
| `sunholo/legal-prompts` (CP checklist, credit/SHA summaries) | **ailang-packages** (new) | follow-up |
| `sunholo/legal-tools` (`extractMatrix`, citation helpers) | **ailang-packages** (new) | follow-up |
| `sunholo/audit` (capability-trace, doc-touch enumeration) | **ailang-packages** (new) | follow-up |

This doc covers only the **ailang-parse** parts. The stdlib AI tool-loop primitive is a hard dependency for Part 3 — it must ship in ailang first.

---

## Problem

`ailang-parse` is read-biased. We can extract everything OOXML carries, but we cannot:

1. **Present** existing tracked changes and comment bubbles to an LLM as inline markers (`{++ins++}` / `{--del--}` / `{>>comment<<}`) so the model can reason about what a lawyer has already proposed — rather than silently collapsing `<w:ins>`/`<w:del>` into accepted view.
2. **Author** a structured DOCX programmatically with stable heading hierarchy, auto-numbering, tables, page breaks, and signature blocks — the building blocks of a contract or legal memo.
3. **Edit** an existing DOCX as **tracked changes** (`<w:ins>` / `<w:del>` runs) so a reviewer sees Accept/Reject in Word, not opaque substitutions.

(A fourth gap — multi-turn AI tool dispatch — exists in the language stdlib, not in parse. It is scoped in the ailang-side doc above and is a hard dependency for Part 3 of this doc.)

Gap 1 was identified from [jamietso/mike-redline](https://github.com/jamietso/mike-redline), a fork of Mike that adds inline-marker rendering to feed redlines to the LLM. The fork implements this in TypeScript (~80 LOC rewrite of `extractDocxBodyText`). Since `docparse` already extracts tracked changes and comments as structured blocks, the AILANG equivalent is mostly a thin renderer, not new parsing.

Without closing all three gaps, AILANG users building "Mike-class" legal tooling have to drop down to TypeScript (JSZip + `fast-xml-parser` + provider SDK), defeating the point of using AILANG. With them, AILANG becomes a strictly more capable substrate: same outbound surface, plus deterministic effects, schema-enforced JSON, and `docparse`'s richer inbound extraction.

---

## Non-Goals

- A full Word feature surface. We target the operative ~10% (paragraphs, headings 1-6, ordered/unordered lists, tables with merged cells, page breaks, sections, basic run formatting, tracked changes). No SmartArt, no charts, no embedded objects, no comments-write (read-only stays read-only in v0.18.0 — comments-write deferred to v0.19.0).
- A frontend. Mike's React UI (Accept/Reject cards, doc viewer, tabular grid) is out of scope. Consumers build their own UI.
- Streaming/SSE wire format. Consumers' problem.
- Real-time collaborative editing. Single-author write-back only.
- Stdlib changes. We compose `std/zip` + `std/xml` (already shipped) plus the upstream `std/ai.step` (planned v0.17.0); we do not add a new stdlib module. DOCX is a domain format, not a language primitive.
- Cross-reference renumbering intelligence (`see Section 5` updates). Pushed to the prompt layer or a future `docx/refs.ail` follow-up.
- Legal prompt content. Lives in `ailang-packages/sunholo/legal-prompts`, not here.
- PDF colour-based redline detection. PDFs carry no tracked-change semantics; detecting redlines by text-span colour (red/blue/green) via PyMuPDF is fragile and outside the deterministic-parsing scope of this project. PDF inputs go to the AI backend, which sees the raw text and can reason about content without inline markers.

---

## Part 0: Read-side redline renderer (`docparse/docx/redline_render.ail`)

*Derived from [jamietso/mike-redline](https://github.com/jamietso/mike-redline) — specifically the `extractDocxBodyText` rewrite in `backend/src/lib/docxTrackedChanges.ts` (~80 LOC diff) and the observation that feeding an LLM inline markers rather than the accepted view is what lets it reason about what a lawyer has already redlined.*

The write-side (Parts 1–2) makes AILANG a redlining *producer*. This part makes it a redlining *reader*: turning a received `.docx` with existing tracked changes and comment bubbles into an LLM-ready string so the model can interpret what is proposed and why — rather than silently collapsing `<w:ins>`/`<w:del>` into accepted view.

`docparse` already extracts tracked changes and comments as structured blocks. This part adds a thin renderer that re-emits the body text with inline markers.

### Marker format

```
{++inserted text++}
{--deleted text--}
{>>by AUTHOR: comment text<<}
```

This matches the mike-redline convention exactly, so system prompts written for that stack are portable. Downstream callers include the markers in the user/system message; the LLM is instructed that `{++…++}` is the proposed new text, `{--…--}` is what it replaces, and `{>>…<<}` is a reviewer annotation.

### API

```ailang
module docparse/docx/redline_render

import std/result (Result, Ok, Err)

-- Render the body text of a .docx with tracked-change markers preserved.
-- Paragraphs are joined by "\n". The output is intended for LLM consumption;
-- the accepted-view flattenParagraph path used by the edit matcher is
-- separate and must not be conflated with this.
export func renderRedlines(input: bytes) -> Result[string, string]

-- Convenience: parse via docparse then render. Avoids double-zip-open.
export func renderRedlinesFromPath(path: string) -> Result[string, string] ! {FS}
```

### Rendering rules

1. Normal `<w:r>` runs — emit `w:t` text as-is.
2. `<w:ins>` wrappers — collect inner `w:t` text, wrap `{++…++}`.
3. `<w:del>` wrappers — collect inner `w:delText` (not `w:t`), wrap `{--…--}`.
4. `<w:commentRangeStart w:id="N">` — look up ID in `word/comments.xml`, emit `{>>by AUTHOR: text<<}` at the insertion point. Comments loaded once per document; malformed `comments.xml` silently skipped.
5. Text inside headers, footers, footnotes, text boxes — omitted (same scope limit as the write-side matcher in Part 2).
6. Paragraphs separated by `\n`; tables rendered as existing `docparse` table blocks with markers applied per-cell.

### Open question: comment positional anchors

The current `docparse` comment extractor pulls comment bodies as standalone blocks but may not preserve their `w:id` tied to body-text position. If it does, rule 4 is pure rendering. If not, a small parser tweak is needed to thread the anchor ID through the `CommentBlock` variant. **Verify before starting** with `./bin/docparse data/test_files/` on a `.docx` with comments and check whether comment block order mirrors their body-text anchoring.

### CLI flag

```bash
./bin/docparse contract.docx --redlines
# emits marked-up body text to stdout
```

### Effort

~0.5–1 day if comment anchors are already threaded through; ~1.5 days if the parser needs a tweak first.

---

## Part 1: Structured DOCX writer (`docparse/docx/`)

A new ailang-parse module — `docx/` — that builds an OOXML `.docx` from a structured AILANG value. Sits on top of `std/zip` and `std/xml` (no new builtins required); pure where possible, requires `FS` only at the final write.

### Why a parse-repo module, not stdlib

DOCX is a domain format the way `std/json` is not. Stdlib should stay narrow. The OOXML expertise, golden corpus, and `--convert` pipeline already live in ailang-parse — co-locate the writer there. The `_xml_*` and `_zip_*` builtins it depends on are already in the ailang stdlib; nothing new is needed upstream.

### API shape

Mirrors Mike's `generate_docx` tool schema almost exactly so the tool wrapping is one-to-one:

```ailang
module docparse/docx

import std/result (Result, Ok, Err)
import std/option (Option, Some, None)

-- A document is a list of sections. Each section may carry an optional
-- heading + level, prose content, an optional table, and a pageBreak flag.
type Section = {
  heading:    Option[string],
  level:      Option[int],          -- 1..6, ignored if heading is None
  content:    Option[string],       -- paragraphs separated by "\n\n"
  table:      Option[Table],
  pageBreak:  bool,                 -- start this section on a new page
  numbered:   bool                  -- false suppresses auto-numbering (preambles/recitals)
}

type Table = {
  headers: list[string],
  rows:    list[list[string]],
  widths:  Option[list[int]]        -- twentieths of a point; equal width if None
}

type DocOptions = {
  title:           string,
  landscape:       bool,
  signature_block: Option[SignatureBlock]
}

type SignatureBlock = {
  parties: list[string]             -- one signature panel per party
}

-- Build the .docx into a byte buffer (pure, no FS).
export func build(opts: DocOptions, sections: list[Section])
  -> Result[bytes, string]

-- Convenience: build + write to disk.
export func write(opts: DocOptions, sections: list[Section], path: string)
  -> Result[(), string] ! {FS}
```

### Numbering rules (legal-drafting hygiene)

These match Mike's prompt-side rules, but enforced by the *generator* so the LLM cannot violate them:

- All numbering starts at 1 at every level. Never 0, never `1.0`, never `0.1`.
- Heading levels never skip (H1 → H2 → H3, not H1 → H3). The builder errors if a `level` jump > 1 is detected.
- The heading text must NOT contain its own number prefix. `"1. Introduction"` is rejected; pass `"Introduction"`. The generator applies the number from the OOXML numbering definition.
- Sections with `numbered: false` are emitted as plain paragraphs (use for preambles, recitals, "WHEREAS" blocks). Numbering resumes at the next `numbered: true` section, continuing the previous count.
- Signature blocks are always unnumbered, on their own page (`pageBreak: true` is forced), with a per-party panel: party name, then "By:", "Name:", "Title:", "Date:" lines.

### Effort

~1.5 weeks. The OOXML surface for the operative 10% is small; the work is mostly schema design, numbering definitions (`word/numbering.xml`), and table cell merging.

---

## Part 2: Tracked-changes write-back (`docparse/docx/track.ail`)

The crown jewel — and the one Mike spent the most engineering on. We do it once, properly, in AILANG.

### API

```ailang
type Edit = {
  find:           string,           -- exact substring to replace
  replace:        string,           -- "" = pure deletion
  context_before: string,           -- ~40 chars preceding `find`
  context_after:  string,           -- ~40 chars following `find`
  reason:         Option[string]    -- annotation, surfaced in revision metadata
}

type TrackedChange = {
  id:              int,             -- w:id value, stable across the doc
  kind:            string,          -- "ins" | "del" | "replace"
  text:            string,
  paragraph_index: int,
  reason:          Option[string]
}

type TrackResult = {
  bytes:   bytes,
  changes: list[TrackedChange]      -- one per applied edit, with assigned IDs
}

-- Apply edits as <w:ins>/<w:del> tracked changes. Returns the new docx
-- bytes and the list of changes (with their assigned w:id values) so
-- callers can render Accept/Reject UI.
export func trackEdits(input: bytes, edits: list[Edit])
  -> Result[TrackResult, string]

-- Resolve a single tracked change by id: "accept" collapses w:ins/removes
-- w:del; "reject" reverses it. Returns the new docx bytes.
export func resolveChange(input: bytes, id: int, action: string)
  -> Result[bytes, string]
```

### Behavioural requirements (non-obvious, lifted from Mike's hard-won implementation)

These are the things you only learn by shipping a tracked-changes engine. Calling them out explicitly so the implementer doesn't re-discover them:

1. **Only `<w:p><w:r><w:t>` is in scope.** Headers, footers, footnotes, comments, text boxes, drawings — all left alone. Edits that resolve to text inside those raise `error: edit lands outside body text`.
2. **Pre-existing tracked changes use "accepted view".** When matching `find`, treat existing `<w:ins>` runs as normal text and ignore `<w:del>` wrappers. If a new edit's range lands inside a pre-existing `<w:ins>`, drop the old wrapper (silently accepting that prior insertion) before emitting the new change.
3. **Anchoring uses `context_before`/`context_after`.** A bare `find` is ambiguous in any document longer than a page. Match `context_before + find + context_after` with whitespace-collapse tolerance. Error if 0 or >1 matches.
4. **Whitespace tolerance.** OOXML splits runs on every formatting change, so "Section 4.2" may be `<w:r>Section </w:r><w:r>4.2</w:r>`. The matcher operates on concatenated visible text and maps back to run boundaries.
5. **Backslash-path zip entries.** Some legacy Word/Windows zips store entries as `word\document.xml` not `word/document.xml`. The `std/zip` accessor must transparently fall back. `docparse` already handles this on read; the writer must too.
6. **Stable `w:id`s.** IDs are assigned in document order, starting from `max(existing_id) + 1`. Returned in `TrackedChange.id` so a UI can map Accept/Reject buttons back to specific changes.
7. **Author/date metadata.** Every emitted `<w:ins>` and `<w:del>` carries `w:author="AILANG"` and `w:date=<ISO-8601 now>`. Caller can override via a future `TrackOptions` record (deferred).
8. **Bracket integrity.** When `replace=""` deletes a `[`, the matching `]` must also be deleted (and vice versa). Mike enforces this prose-side via the prompt; we enforce it in the engine and return an error if an edit would leave an unmatched bracket — opt-out via `Edit.allow_unbalanced: bool` (deferred).
9. **Cross-reference renumbering is OUT of scope.** Mike pushes "if you renumber Section 5, find every `see Section 5` and update it" onto the LLM. We don't try to be smarter than the model on that — `trackEdits` does what it's told. Cross-ref intelligence is a future `docx/refs.ail` analyzer.

### Test corpus

Ship a `tests/golden/docx_writeback/` corpus with:
- Empty doc + 1 insertion
- Doc with pre-existing tracked changes + new edit on top
- Backslash-pathed zip
- Edit that lands across a run boundary (`Section </w:r><w:r>4.2`)
- Edit with ambiguous `find` (must error)
- Bracket-unbalanced edit (must error)
- Round-trip: parse with `docparse` → edit → parse again → assert tracked-change blocks present

### Effort

~2.5 weeks. Mike's [docxTrackedChanges.ts](https://github.com/willchen96/mike/blob/main/backend/src/lib/docxTrackedChanges.ts) is ~1k LOC of fiddly XML surgery. We get to start from a clean spec, but the OOXML behaviors above are mandatory.

---

## Part 3: Reference legal-AI workflow (`docparse legal`)

To prove the writer + tracked-changes primitives compose with the upstream `std/ai.step` tool-loop, ship a reference workflow as part of the `docparse` CLI:

```bash
docparse legal review credit_agreement.docx \
  --workflow cp_checklist \
  --ai gemini-3.1-pro-preview \
  --out checklist.docx
```

What it does end-to-end:
1. `docparse` parses the input DOCX (existing capability).
2. Builds messages including the parsed body text with `[Page N]` markers.
3. Loads the chosen built-in workflow prompt (port of Mike's three: `cp_checklist`, `credit_summary`, `sha_summary`).
4. Calls **upstream** `std/ai.runTools` (planned v0.17.0) with `[generate_docx, edit_document, read_document, find_in_document]` registered, dispatched to `docparse/docx` + parsed content.
5. Writes the resulting `.docx` (with citations preserved as Word footnotes referencing the `[Page N]` anchor).

This is **not** a Mike clone — it's a CLI proof. A full app composes this with `ailang-packages/sunholo/legal-prompts`, frontend, persistence, and auth.

### Built-in workflow prompts

For the CLI proof we inline the three prompts (CP checklist, credit summary, SHA summary), attributed to Mike (AGPL-3.0). For production use, consumers should depend on the dedicated `sunholo/legal-prompts` package so prompts can be versioned and extended without `docparse` PRs.

### Hard dependency

This part **cannot ship until `std/ai.step` lands in ailang stdlib** (planned v0.17.0). If that slips, Parts 1 and 2 still ship; Part 3 follows in v0.18.x or v0.19.0.

### Effort

~3-4 days once the upstream dependency is available. Pure composition.

---

## Out-of-scope follow-ups (sketch)

These are deliberately deferred — call them out so reviewers know we've thought about them:

- **`docx/refs.ail`** — cross-reference graph (`see Section 4.2` ↔ `Section 4.2`) so renumbering can propagate updates automatically. Removes the burden Mike currently puts on the LLM.
- **Comments-write** — emit `<w:comment>` annotations from AILANG. Pairs with the read-side already in `docparse`.
- **`pptx/` and `xlsx/` writers** — same pattern as `docx/`. PPTX is more involved (slide layouts, masters); XLSX is mostly cells + formulas.
- **`sunholo/legal-tools` package** — typed `extractMatrix(docs, columns) -> Matrix[Cell]` with per-column format schemas (`yes_no`, `date`, `monetary_amount`, `[[USD]]`, `[[tag]]`). Trivial composition of `runTools` + `callJson` once primitives stabilize.
- **`sunholo/audit` package** — capability-trace recording, doc-touch enumeration. AILANG's effect-capability model is a natural fit for "prove this workflow only touched these doc IDs." General-purpose, not legal-specific.

---

## Acceptance criteria

- [ ] `docx.renderRedlines` on a `.docx` with tracked changes emits `{++…++}` / `{--…--}` markers matching all `<w:ins>`/`<w:del>` runs; comment bubbles appear inline as `{>>by AUTHOR: text<<}`.
- [ ] `--redlines` flag on the CLI produces correct markers for a real redlined contract.
- [ ] `docx.build` produces a valid `.docx` that opens cleanly in Word, LibreOffice, and Google Docs across the test corpus.
- [ ] `docx.trackEdits` round-trips through Word: edits appear as Accept/Reject changes; accepting them in Word reproduces the expected text; the tracked-change view in `docparse` round-trip identifies all emitted changes by `w:id`.
- [ ] All 9 behavioral requirements in Part 2 have a passing golden test.
- [ ] Numbering rules from Part 1 are enforced by the builder (test: passing `"1. Introduction"` as heading text returns an error).
- [ ] Bracket integrity check from Part 2.8 fires on a deliberately unbalanced edit.
- [ ] (gated on upstream) `docparse legal review --workflow credit_summary` on a real credit agreement produces a 21-section summary `.docx` with citations.

## Total effort (ailang-parse only)

| Part | Estimate |
|------|----------|
| 0. Read-side redline renderer | 0.5–1.5 days |
| 1. `docx/` writer | 1.5 weeks |
| 2. Tracked-changes write-back | 2.5 weeks |
| 3. Reference `docparse legal` workflow | 3-4 days (gated on ailang v0.17.0) |
| **Total (parse repo)** | **~4.5–5 weeks** |

Plus ~1 week upstream in ailang stdlib for the AI tool-loop primitive. See the linked sprint plan.

Part 0 ships independently and can be merged ahead of Parts 1–2.
