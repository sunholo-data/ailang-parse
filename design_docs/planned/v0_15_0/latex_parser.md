# LaTeX / arXiv Source Parser

**Target release:** v0.15.0 (post v0.14.0 competitive-gap work)
**Status:** Planned — this doc supersedes the out-of-scope dismissal in
[v0_14_0_competitive_gaps.md §Out of scope](../v0_14_0/v0_14_0_competitive_gaps.md#out-of-scope-deferred).
**Recommendation:** **Ship.** This is the single highest-leverage parser
addition on the roadmap — not because LaTeX is a common file format, but
because arXiv is a strategic wedge into scientific-document RAG that no
competitor can match without rebuilding their stack.

---

## 1. Strategic case

### The one-line pitch

**We parse the source. Every competitor OCRs the rendering.**

That sentence is AILANG Parse's entire value proposition compressed into
seven words, and arXiv is the corpus where it's most obviously, most
defensibly true.

### Why the earlier dismissal was wrong

The v0.14.0 competitive-gaps audit listed `.tex` under "Out of scope":

> "Docling owns this niche; building a real TeX parser is a multi-week
> project for a small audience."

That assessment answered the wrong question. It asked *"is LaTeX a file
format users drop on our CLI?"* — and the answer is reasonably "not many."
Most people don't email each other `.tex` files.

The right question is *"is LaTeX a corpus format for a buyer segment we
want?"* — and the answer there is very different. The buyer segment is
**scientific-document RAG**, and the corpus is **arXiv + bioRxiv +
OpenReview + conference proceedings + institutional repositories**, which
collectively hold tens of millions of documents where:

1. The authoritative source is `.tex`, not PDF.
2. Every commercial parser in the space is PDF-OCR-bound.
3. Equations, tables, citations, and cross-references — the exact
   structures that matter most to downstream RAG — are precisely what
   OCR loses.

### Corpus scale

- arXiv: ~2M papers, ~89% ship LaTeX source, official bulk access
  ([info.arxiv.org/help/bulk_data](https://info.arxiv.org/help/bulk_data/index.html))
- bioRxiv / medRxiv: hundreds of thousands, increasingly LaTeX
- OpenReview: ML conferences, virtually all LaTeX-source-available
- Institutional repositories (MIT DSpace, CERN, etc.)
- Overleaf export bundles from enterprise customers

That's not a "small audience." It's the entire scientific literature of
the 21st century, and AI-for-research is one of the most-funded
application segments of the current LLM cycle (Elicit, Consensus,
Perplexity, Scite, Semantic Scholar, FutureHouse, plus every pharma and
quant research copilot built in-house).

### The competitive moat

| Parser       | arXiv paper input | Equation fidelity       | Citation structure      |
|--------------|------------------|--------------------------|--------------------------|
| Docling      | PDF only         | OCR-best-effort (lossy) | Flattened text          |
| MarkItDown   | PDF only         | OCR-best-effort (lossy) | Flattened text          |
| LlamaParse   | PDF only         | AI-best-effort (lossy)  | AI-best-effort          |
| Unstructured | PDF only         | OCR-best-effort (lossy) | Flattened text          |
| Pandoc       | `.tex` → md      | Converts to MathML/unicode (lossy for LLMs) | Partial resolution |
| **AILANG**   | **`.tex` source**| **Raw LaTeX preserved** | **Structured `\bibitem`** |

None of the OCR-bound competitors can fix this without rebuilding their
pipeline around structural parsing — which is precisely the core
architectural bet AILANG Parse already made. **We ship this for free
because we're already the deterministic-first parser.**

### Fit with existing story

The project's stated philosophy
([.claude/rules/benchmarks.md](../../../.claude/rules/benchmarks.md)):

> "The real differentiator is deterministic structural parsing that
> competitors miss entirely. For PDFs, we delegate to whatever AI model
> the user plugs in — we don't try to beat specialized OCR."

arXiv papers are the purest possible expression of that thesis. The
author already wrote structured source; OCR'ing the rendered PDF is
information-destructive on purpose. Our win here is *definitional*, not
marginal.

---

## 2. Scope boundaries

Full LaTeX is Turing-complete via macro expansion. Supporting the
general case is a research project, not an engineering task. We target a
specific, defensible subset: **the arXiv-paper subset** — what real
submitted papers actually contain, with aggressive falls-through for
anything exotic.

### In scope

| LaTeX construct | Mapping |
|---|---|
| `\documentclass`, `\usepackage` | Ignored (metadata only) |
| `\title`, `\author`, `\date`, `\affiliation` | `DocMetadata` + `SectionBlock(kind: "frontmatter")` |
| `\begin{abstract}...\end{abstract}` | `SectionBlock(kind: "abstract")` |
| `\section`, `\subsection`, `\subsubsection`, `\paragraph` | `HeadingBlock` (level 1-4) |
| Paragraph text | `TextBlock(style: "paragraph")` |
| `\textbf`, `\emph`, `\textit`, `\texttt`, `\underline` | Inline style markers in `TextBlock.text` |
| `$...$`, `\(...\)` | `TextBlock(style: "equation-inline")`, raw LaTeX |
| `$$...$$`, `\[...\]` | `TextBlock(style: "equation-display")`, raw LaTeX |
| `equation`, `align`, `gather`, `multline`, `eqnarray` envs | `TextBlock(style: "equation-display")`, raw LaTeX including env wrapper |
| `itemize`, `enumerate`, `description` | `ListBlock` |
| `tabular`, `tabularx`, `tabu`, `longtable` | `TableBlock` |
| `figure`, `table` floats + `\caption` | `ImageBlock`/`TableBlock` with caption text |
| `\includegraphics{path}` | `ImageBlock(data: path)` (path-only; resolution deferred) |
| `\cite{key}`, `\citep{key}`, `\citet{key}` | Inline marker `[cite:key]` in `TextBlock.text` |
| `\ref{label}`, `\label{x}` | Inline marker `[ref:label]` in `TextBlock.text` |
| `\footnote{text}` | Inline marker + `SectionBlock(kind: "footnote")` |
| `thebibliography` env + `\bibitem{key}` | `SectionBlock(kind: "bibliography")` containing `TextBlock` per entry |
| `.bbl` sibling file | Same as above (arXiv bundles usually include this) |
| Comments (`%`) | Stripped |
| `\input{file}`, `\include{file}` | Resolved relative to main file if tar.gz bundle provided; otherwise inline marker |

### Explicitly out of scope

| Construct | Why out |
|---|---|
| Arbitrary `\newcommand`/`\def` expansion | Macro expansion is Turing-complete. We'll trivially inline single-arg textual macros; anything else passes through verbatim. |
| TikZ / PGF diagrams | Preserve raw source inside `TextBlock(style: "tikz-source")`; no rendering. |
| `\expandafter`, `\csname`, category-code hackery | Never. |
| Beamer slides | Distinct format with distinct semantics; if demanded, separate parser. |
| Custom document classes with exotic sectioning | Best-effort fallback to heading detection by `\@startsection` pattern; document limits clearly. |
| BibTeX style resolution (`.bib` → formatted citation) | Prefer `.bbl` which has this pre-baked. If only `.bib` is present, emit raw entries. |
| Live compilation fidelity | We are not a TeX engine. We extract content. |
| `.tex` *output* (generator) | Users who want TeX output go via [qmd_generator.ail](../../../docparse/services/qmd_generator.ail) → Quarto/Pandoc. |

### The equation decision (important, and slightly counterintuitive)

**We preserve equations as raw LaTeX strings. We do not convert to
MathML, to Unicode, to KaTeX, or to anything else.**

This looks like a limitation and is actually a feature:

1. **LLMs prefer LaTeX.** GPT-4/Claude/Gemini were trained on arXiv-heavy
   corpora; they read LaTeX math natively and fluently. Converting to
   MathML actively degrades downstream RAG quality.
2. **Conversion is lossy.** `\begin{align}` with cross-line alignment
   points cannot round-trip through Unicode.
3. **Rendering is orthogonal.** Downstream consumers that need visual
   rendering (Jupyter, Quarto, web) already handle raw LaTeX natively.

This differentiates us from Pandoc, which aggressively normalizes to
MathML by default and loses semantic information that RAG actually
consumes.

---

## 3. Block ADT mapping

From [docparse/types/document.ail](../../../docparse/types/document.ail):

```
Block = TextBlock | TableBlock | ImageBlock | AudioBlock | VideoBlock
      | ListBlock | HeadingBlock | SectionBlock | ChangeBlock
```

**No new Block variants are needed.** This is important — adding
variants would break every existing generator and downstream consumer.

Mapping:

- **TextBlock** with new conventional `style` values: `"paragraph"`,
  `"equation-inline"`, `"equation-display"`, `"tikz-source"`,
  `"citation"`, `"abstract"`
- **HeadingBlock** — direct (levels 1-4 from `\section` → `\paragraph`)
- **ListBlock** — direct (`ordered` flag from `itemize` vs `enumerate`)
- **TableBlock** — direct; `tabular` column spec → cell structure
- **ImageBlock** — direct; `\includegraphics` path → `data`, caption → `description`
- **SectionBlock** — used for `kind: "frontmatter" | "abstract" | "bibliography" | "footnote" | "appendix"`
- **AudioBlock / VideoBlock / ChangeBlock** — unused (LaTeX has no equivalents)

Consumers (HTML generator, QMD generator, SDK wrappers) already match
exhaustively on these variants and will render LaTeX papers with zero
additional changes beyond the new `style` values being human-readable.

---

## 4. Implementation approach

### Parser structure

Follow the [markdown_parser.ail](../../../docparse/services/markdown_parser.ail)
pattern:

- Pure AILANG, no shelling out (enforced by
  [the "single AILANG codebase" rule](../../../../.claude/projects/-Users-mark-dev-sunholo-ailang-parse/memory/feedback_single_codebase.md))
- `foldl` over tokenized input with a parse-state record
- Contracts on every public function
- Size estimate: **400-600 lines**, in line with html_parser (479 lines)

Pipeline:

```
.tex source string
  └→ tokenize      → [Token]  (command, text, math-delim, group-open/close, newline, comment)
  └→ expand-trivial-macros
  └→ env-stack     → [BlockEvent]  (push-section, push-list, push-table, emit-text, emit-equation, ...)
  └→ emit-blocks   → [Block]
  └→ resolve-refs  → [Block]  (cite/ref keys resolved against bibliography)
  └→ ParsedDocument
```

### Files to add

```
docparse/services/tex_parser.ail            (new, ~500 lines)
docparse/services/tex_tokenizer.ail         (new, ~200 lines — optional split)
docparse/services/bibtex_parser.ail         (new, ~150 lines — .bbl / thebibliography)
benchmarks/arxivbench/                      (new directory)
  ├── adapters/
  │   ├── docparse_adapter.py
  │   ├── docling_adapter.py
  │   ├── llamaparse_adapter.py
  │   ├── markitdown_adapter.py
  │   └── pandoc_adapter.py
  ├── corpus/                                (50 arXiv papers: .tex + .pdf pairs)
  ├── eval_arxivbench.py
  └── report.py
data/test_files/arxiv_sample.tex            (representative fixture)
```

### Files to modify

- [docparse/services/format_router.ail:66-82](../../../docparse/services/format_router.ail#L66-L82)
  — add `tex` → `"latex"` case in `detectFormat`
- [docparse/main.ail:133-147](../../../docparse/main.ail#L133-L147)
  — add dispatcher to `tex_parser.parse`
- [docparse/main.ail:219-258](../../../docparse/main.ail#L219-L258)
  — no generator changes (deferred; no `.tex` output in v0.15.0)
- SDK wrappers (Python/JS/Go) — no changes needed (they pass through blocks)

### Archive handling (iteration 2)

arXiv source arrives as `.tar.gz`. [zip_extract.ail](../../../docparse/services/zip_extract.ail)
handles `.zip` (used for DOCX/PPTX); `.tar.gz` is adjacent work. Ship
order:

- **v0.15.0-beta:** raw `.tex` file input only. Users extract tar.gz
  themselves.
- **v0.15.0 GA:** `.tar.gz` bundle support — auto-detect main `.tex`
  (heuristics: `\documentclass` presence + filename matches title), walk
  `\input`/`\include`, resolve `\includegraphics` against bundled images.

---

## 5. Benchmark plan: arxivbench

This is the half of the release that sells the story. Clone the shape of
[benchmarks/officedocbench/](../../../benchmarks/officedocbench/) which
is already wired into the website via
[bench-data.js](../../../docs/js/bench-data.js).

### Corpus

50 arXiv papers, stratified:

- 15 ML (with many equations, many citations, some tables)
- 10 physics (equation-heavy, SI tables, figure-heavy)
- 10 math (theorem environments, proof environments, reference-heavy)
- 10 CS systems (pseudocode, algorithm envs, tables)
- 5 edge cases (book-length theses, multi-file bundles, TikZ-heavy)

Each entry has:
- Original `.tex` (or tar.gz bundle)
- Original `.pdf` as rendered by arXiv
- Hand-curated golden extraction (key equations, citation keys, table
  structures, section hierarchy) — this is the expensive part, budget
  2-3 engineer-days

### Scoring dimensions

| Dimension | What we measure |
|---|---|
| Section hierarchy | Exact-match on heading text + level sequence |
| Equation preservation | Set-equality of equation source strings vs golden |
| Table structure | Row/col count + cell text similarity |
| Citation resolution | Fraction of `\cite` keys correctly paired to `\bibitem` |
| Figure-caption pairing | Fraction of figures with correct caption attached |
| Bibliography completeness | Number of entries extracted / golden count |
| Text fidelity (non-math) | Jaccard similarity on body paragraphs |

### Baselines

- **AILANG deterministic** (this work) on `.tex`
- **Docling** on `.pdf`
- **LlamaParse** on `.pdf`
- **MarkItDown** on `.pdf`
- **Unstructured** on `.pdf`
- **Pandoc** on `.tex` — the honest ceiling for existing source-based tooling

### Expected story

Projected outcomes (calibrated to OfficeDocBench gaps):

- AILANG on equation preservation: ~95%+
- OCR baselines on equation preservation: 20-50%
- AILANG on citation resolution: ~90%+
- OCR baselines on citation resolution: ~0% (citations flatten to text)
- AILANG vs Pandoc on section/block structure: approximate tie
- AILANG vs Pandoc on equation-as-LaTeX preservation: AILANG wins (Pandoc normalizes)

The chart writes itself. This becomes the v0.15.0 launch post.

---

## 6. Risks and open questions

### Risks we've identified

**R1. Macro expansion burden.** If a large fraction of arXiv papers use
non-trivial `\newcommand` (e.g., redefining sectioning, custom theorem
environments via `amsthm`), trivial inlining isn't enough.

- *Mitigation:* sample 20 random arXiv papers from different fields and
  catalogue macro usage before implementation starts. Budget 2 eng-days
  for this study.
- *Kill criterion:* if >40% of papers have macros that materially affect
  block extraction and can't be handled by trivial inlining, reassess
  scope (may need to ship with documented "arXiv-clean" subset only).

**R2. Bibliography format variance.** `.bbl` is easier than `.bib`;
`natbib`/`biblatex`/plain-bibtex have different `\bibitem` formats.

- *Mitigation:* support the three most common bbl styles; `.bib` source
  support is optional v0.15.1+.

**R3. Multi-file papers with complex `\input` graphs.** Book-length
theses and some conference papers split across many files.

- *Mitigation:* DFS from main file with cycle detection; cap at 50
  files; log warnings on unresolved paths.

**R4. TikZ-heavy papers look empty.** If we skip TikZ, figure count
drops and the paper looks under-extracted.

- *Mitigation:* emit `ImageBlock(mime: "application/x-tikz", description:
  "<TikZ diagram>", data: raw-source)`. Downstream consumers can render
  via MathJax/TikZJax or skip.

**R5. Corpus construction dominates timeline.** Hand-curating golden
extractions for 50 papers is the bottleneck, not parser code.

- *Mitigation:* start corpus work in parallel with parser spec. Consider
  using an AI-assisted first pass for golden creation, then human
  verification.

### Open questions requiring answer before implementation

- **Q1.** Do we support `\input` resolution in v0.15.0 or defer to
  v0.15.1? *Proposal: defer; ship single-file only at GA.*
- **Q2.** Do we expose raw LaTeX equation strings in the SDK wrappers
  with any special handling (e.g., a `render_equation()` helper)? *Proposal:
  no — keep SDK format-agnostic, let users handle.*
- **Q3.** Do we accept `.latex` extension too? *Proposal: yes, plus
  `.ltx`.*
- **Q4.** Is there a demand signal beyond strategic reasoning? *Action:
  check [ailang-feedback](../../../../.claude/projects/-Users-mark-dev-sunholo-ailang-parse/memory/MEMORY.md)
  inbox and any GitHub issues mentioning LaTeX/arXiv before sequencing.*

---

## 7. Sequencing and deliverable

### Ordering within the release

1. 20-paper macro-usage survey (validates scope) — 2 days
2. `tex_tokenizer.ail` + `tex_parser.ail` core — 4-5 days
3. `bibtex_parser.ail` + citation resolution — 2 days
4. Register in format_router + main.ail + one integration test — 0.5 day
5. arxivbench corpus + golden extractions — 3-4 days (parallel with 2)
6. arxivbench adapters + eval script — 2 days
7. Run baselines, generate report, write launch post — 2 days

**Estimated total:** 2-3 engineer-weeks to GA, front-loaded with the
corpus work that de-risks everything else.

### Dependencies

- **v0.14.0 must ship first** (RTF, Jupyter, `.msg`, comment threads,
  chart data). This is the competitive-gap release and shouldn't be
  reordered behind a strategic bet.
- **No new AILANG compiler features required.** Existing string
  manipulation + foldl + records + match is sufficient. (Verified
  against existing parsers.)

### Release posture

Position v0.15.0 as **"the scientific paper release."** Launch post
should lead with the deterministic-vs-OCR chart on equations and
citations, not with a feature list.

---

## 8. Recommendation

**Ship, as v0.15.0 headline feature.**

Rationale (compressed):

- Uniquely leverages the project's existing architectural bet
- Zero new Block ADT surface, zero new compiler features
- 2-3 engineer-weeks is cheap for a release headline
- Corpus of literal millions of documents, growing monthly
- Buyer segment (scientific RAG) is actively funded and expanding
- Competitive moat is structural, not a feature race

The v0.14.0 audit dismissed this because it asked "who emails `.tex`
files?" — which is the wrong question. The right question is "whose
entire industry runs on a corpus that's LaTeX-native and currently served
badly?" — and that answer is scientific research, which is large,
valuable, and underserved.

This is the parser that makes the deterministic-first story concrete
in a way no Office-format parser ever will.
