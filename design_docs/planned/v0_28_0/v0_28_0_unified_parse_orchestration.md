# Unified Parse Orchestration — one `parseDocument`, three thin callers

**Status**: PLANNED (2026-08-07)
**Theme**: Hoist a data-returning orchestration function into the `ailang_parse` package so the CLI, the MCP server, and the hosted API stop re-deriving format dispatch independently.
**Verdict on the originating analysis**: **valid, and understated.** The mechanism is diagnosed correctly; the blast radius is larger than reported and the line-count saving is smaller.
**Repos**: `sunholo/ailang-parse` (public, this repo) → `sunholo/docparse` (private API, consumes via registry).

---

## 1. Assessment of the originating claim

The claim was audited line by line against both repos at `ailang-parse@0.27.0`. Findings below carry file:line references so they can be re-checked.

### 1.1 Confirmed

**"`api_server.ail:467` calls `parseDocxComments`, which resolves anchors — so `anchorText` and `parentId` come through."**
Correct. [`docx_parser.ail:752-761`](docparse/services/docx_parser.ail#L752-L761) shows `parseDocxComments` walking `document.xml` for anchors before joining `comments.xml` + `commentsExtended.xml`, exactly as the spliced variant does — both funnel through `docxCommentsFromXml`. The `CommentBlock` carries `anchorText`, `anchorKind`, `anchored`, `anchorBlockIndex`, `parentId`, `resolved` ([`document.ail:56-57`](docparse/types/document.ail#L56-L57)), and all of them are serialised by [`output_formatter.ail:126-130`](docparse/services/output_formatter.ail#L126-L130). No data loss on the API path.

**"XLSX/PPTX comments come free, since those parsers emit comment blocks inline."**
Correct. [`xlsx_parser.ail:331`](docparse/services/xlsx_parser.ail#L331) calls `xlsxSheetComments` inside the per-sheet loop (threaded comments superseding the legacy compatibility copy, `parentId` preserved); [`pptx_parser.ail:214,223`](docparse/services/pptx_parser.ail#L214) emits `mkAnchoredComment` inline. `apiParseXlsx`/`apiParsePptx` are bare pass-throughs, so they inherit this.

**"The CLI splices, the API appends — same data, different ordering."**
Correct. CLI [`main.ail:314`](docparse/main.ail#L314) uses `parseDocxWithComments`; API `apiParseDocx` ends with `concat(…, comments)`. And `anchorBlockIndex` is indeed on the wire, so a client *can* reposition.

**The root-cause diagnosis — effectful printers can't be called from a server.**
Correct, and it is the whole story. Every CLI orchestrator has signature `-> () ! {IO, FS, AI, Env}` and terminates in `printBlocks` / `writeOutputs`; [`main.ail:530`](docparse/main.ail#L530) even calls `exit(1)` mid-parse on backend failure. There is no return value to reuse and no way to suppress the side effects, so the API had no option but to re-derive dispatch.

**"It belongs in the public repo, and it's a real refactor."**
Correct. The parsers already ship via `[exports]` in `ailang.toml` — including `docparse/services/pdf_annotations` (line 35) — so the API *could* call the missing merges today. Nothing is blocked on packaging; only on there being a single function that knows the right recipe.

### 1.2 Understated — this is not one gap, and not two layers

**There are three orchestration layers, not two.** [`docparse/services/mcp/tools.ail`](docparse/services/mcp/tools.ail) (493 lines) carries a third independent dispatch with its own subset of merges. It is *already* the closest thing to the proposed design — `mcpParseDocx` returns `ParsedDocument`, not `()`, and runs at `! {FS}` for the Office formats — which makes it the natural seed for the refactor rather than another victim of it.

**Ten divergences, not one.** Ordering was the only one reported; the rest are missing data:

| Merge / behaviour | CLI `main.ail` | MCP `tools.ail` | API `api_server.ail` |
|---|---|---|---|
| DOCX comments | spliced at anchor (L314) | spliced at anchor (L161) | **appended last** (L472) |
| DOCX images | ✓ (L333) | ✓ (L166) | **✗ missing** |
| DOCX header position | before body (L341) | before body (L167) | **after body** (L472) |
| PDF annotations (`/Annots`) | ✓ (L542-554) | **✗ missing** | **✗ missing** |
| PDF backend ladder | ✓ (L523) | **✗** — bare `parsePdf` (L247) | ✓ but written **twice** (L513, L543) |
| LaTeX `\input`/`\include` expansion | ✓ (L876) | **✗** — no LaTeX at all | **✗** — raw `parseLatex(content)` (L383) |
| LaTeX `.tar.gz`/arXiv bundles | ✓ (L840) | **✗** | **✗** |
| ODT headers/footers | ✓ (L1015) | ✓ (L186) | **✗ missing** |
| PPTX extracted images | ✓ opt-in (L411) | ✗ | ✗ |
| EML deep attachment recursion | ✓ (L1205) | ✗ | ✗ |

Two of these are worse than the comment-ordering issue that prompted the analysis:

- **LaTeX is materially broken on the API.** The repo's stated scientific-paper wedge is deterministic multi-file `.tex` parsing — "Vaswani, BERT, GPT-3 parse end-to-end" per `CLAUDE.md`. The API calls `parseLatex(content)` on the raw file with no `expandInputs`, so a multi-file paper returns the skeleton and drops every `\input` fragment. Silent partial output, not an error.
- **PDF annotations vanish on two of three surfaces.** The CLI comment at L544-546 says it plainly: without the `/Annots` merge "the default backend silently drops every review comment in the document." The API and MCP both drop them.

**The PDF ladder is triplicated, not duplicated.** `apiParsePdf` and `apiParsePdfResult` are near-identical 25-line bodies differing only in `Result` wrapping, and `extractPdfExternal` is a third copy with `println`/`exit` woven in. Any change to backend-selection semantics needs three edits today.

### 1.3 Overstated — the line-count saving

"Collapses ~1400 duplicated lines" does not survive measurement. The two files are 1471 and 1371 lines, but neither is mostly orchestration:

- CLI `main.ail:292-1364` (the whole `parse*Document` region) is 1073 lines, of which 196 are `println` and 288 are blank or comment → **~590 substantive lines**, and a good share of that is CLI-only concerns (convert targets, `writeOutputs`, flag plumbing).
- API duplicated dispatch is `api_server.ail:366-582` → **~216 lines**. The other ~1150 lines are auth, quota, billing, signed upload URLs, response headers, `agentCard` — none of it duplicated.
- MCP dispatch is **~120 lines**.

Realistic outcome: a shared core of ~400-500 lines replacing ~930 lines spread across three files, so **net removal in the 450-650 range**, with the API dispatch shrinking to roughly 40 lines and MCP to roughly 60. Still worth doing — the value is killing the drift class, not the line count.

### 1.4 One correction

"Making the API match is a one-line change" is true for comment ordering alone (`parseDocx` + separate comments → `parseDocxWithComments`). It is not true for parity: DOCX images, ODT headers/footers, PDF annotations, and LaTeX expansion each need their own edit, which is precisely the argument for not doing it that way.

---

## 2. Design

### 2.1 Shape

Add `docparse/services/orchestrator.ail`, exported from `ailang.toml`:

```ailang
export type ParseOptions = {
  useAI: bool,          -- AI image description + table self-healing
  pdfBackend: string,   -- "", "pdftotext", "docling", "liteparse", "ai"
  deep: bool,           -- recurse into EML attachments
  extractImages: bool,  -- PPTX/DOCX binary image extraction
  projectRoot: string   -- for Process shell-outs
}

export pure func defaultParseOptions() -> ParseOptions

export type ParseOutcome = {
  document: ParsedDocument,
  warnings: [string],   -- degradations worth surfacing (unresolved anchors, …)
  notes: [string],      -- informational (object streams unreadable, N annotations)
  aiCallsUsed: int
}

export func parseDocument(filepath: string, opts: ParseOptions)
  -> Result[ParseOutcome, AIError] ! {IO, FS, AI, Env, Net, Process, Clock}
```

Each caller then becomes thin:

- **CLI** — a printer. `parseDocument` → print `notes` as it goes → `printSummary` / `printBlocks` → `writeOutputs`. `exit(1)` moves to the CLI, where it belongs.
- **MCP** — returns `outcome.document` directly; it already speaks `ParsedDocument`.
- **API** — `apiParseByFormatResult` collapses into a `parseDocument` call plus the existing JSON/markdown/a2ui formatting. `apiParseDocx`…`apiParseOdf` all delete.

### 2.2 Two design problems to settle before coding

**Effect-row widening.** The unified signature must be the union of every format's effects, so parsing a Markdown file would nominally carry `Net` and `Process`. That is a real capability regression for embedders — an MCP server currently grants `! {FS}` only. Options, in preference order:

1. Effect polymorphism, if AILANG supports a row variable here. Check `ailang prompt` before committing to the signature — this determines whether one function suffices.
2. Split into `parseDocumentPure(filepath, opts) -> ParseOutcome ! {FS}` for the deterministic formats and `parseDocument(…)` for the full ladder, with the latter delegating. Keeps MCP at `! {FS}` and matches how `tools.ail` is already written.
3. Accept the widening and document it. Simplest, but hands every caller `Process` and `Net`.

**Progress output.** The CLI currently interleaves `Extracting headers/footers…` with the work. A data-returning core cannot print. Proposal: the core accumulates `notes`, and the CLI prints them *after* the parse rather than during. This changes CLI UX — progress lines appear as a block, not a trickle. For files under a few seconds that is invisible; for a 200-page PDF it is a regression in perceived responsiveness. Worth confirming with the user before implementing, since it is the one user-visible behaviour change in the whole refactor. (A callback parameter would preserve streaming, but re-introduces `IO` into the core signature and undoes point 1.)

### 2.3 Merge semantics to standardise

The refactor must pick one answer per row, not preserve all three. Recommended, matching current CLI behaviour because it is the most complete:

- DOCX block order: `headers ++ body-with-comments-spliced ++ footers ++ footnotes ++ endnotes ++ images`
- PDF: backend ladder, then `/Annots` annotations appended, anchored via word positions when available
- LaTeX: `.tar.gz` extraction → `\input` expansion → parse
- ODT: `body ++ headers/footers`

API consumers see comments move from the tail into the body. That is a **breaking response-shape change** for anyone who slices the block list by position — `anchorBlockIndex` becomes authoritative. Needs a CHANGELOG note and probably a minor-version gate.

### 2.4 Shipping order

The two repos are coupled through the registry, so:

1. `ailang-parse`: add `orchestrator.ail`, add to `[exports]`, migrate CLI + MCP, benchmark for regression (`--suite office` must stay at 100%).
2. Bump `ailang.toml` + `CHANGELOG.md`, tag → CI publishes. **No manual `ailang publish`.**
3. `sunholo/docparse`: bump `ailang.lock`, delete `apiParse*`, wire `parseDocument`. Expect the golden API responses to change for DOCX/ODT/LaTeX/PDF.

### 2.5 Risks

- Step 3 lands after step 2 is published, so there is a window where the API is on the old package. Non-blocking, but the parity fixes do not reach production until the API repo is redeployed.
- The Office structural benchmark covers the CLI path only. It will not catch API-side regressions; the API repo's own tests must be extended, or the drift simply reappears in the test layer.
- `apiParsePdfResult`'s typed-`AIError` behaviour (502/503 instead of 500) is API-specific and must survive — hence `Result` in the core signature rather than raising.

---

## 3. Recommendation

Proceed. The analysis is sound, the fix is the right one, and the LaTeX and PDF-annotation gaps are worth fixing on their own merits regardless of the refactor. Two caveats: budget it as ~500 lines removed rather than ~1400, and settle §2.2 (effect rows, progress output) before writing code — those two choices determine the signature, and the signature is the part that is expensive to change once three callers depend on it.

A tactical patch to `apiParseDocx` (swap to `parseDocxWithComments`, add `parseDocxImages`) is a reasonable stopgap if the API needs comment parity before this lands, but it should be labelled as such — it fixes two of ten rows.
