# arxivbench

Structural fidelity benchmark for LaTeX / arXiv paper parsers.

**Thesis:** parsing the `.tex` source is categorically better than OCR-ing
the rendered `.pdf` for equations, tables, citations, and cross-references.
This benchmark quantifies how much better.

## How it works

1. **Truth** is extracted directly from the `.tex` source by counting
   structural markers (`\section`, `\begin{equation}`, `\cite`,
   `\bibitem`, `\begin{tabular}`, `\begin{figure}`, `\begin{itemize}`,
   theorem-like envs, …). The source is authoritative — if it contains
   42 equations, a correct parser emits 42 equation blocks. See
   [truth_extractor.py](truth_extractor.py).

2. **Adapters** run each tool on its preferred input and convert its
   output into the same structural count schema.

   - `ailang` — AILANG Parse on `.tex` (deterministic)
   - `pandoc` — Pandoc on `.tex` (honest source-based ceiling)
   - `docling` / `llamaparse` / `markitdown` / `unstructured` — on `.pdf`
     (what the rest of the market does). Wrappers reuse the adapters
     already shipped in [officedocbench/adapters/](../officedocbench/adapters/).
   - `liteparse` — on `.pdf` (reference light-weight OCR)

3. **Scoring.** Per dimension, `score = min(observed, truth) / truth`.
   Aggregated per adapter as the mean across papers where `truth > 0`.

### What these scores actually measure

**Structural preservation, not raw text capture.** A PDF-OCR parser
scoring 0% on `equations_display` is not failing to read the equation —
it is failing to emit it as a structurally distinct, re-renderable
block. The rendered equation text is typically still present in the
adapter output, often as mangled unicode (`E = mc2` with subscripts
lost, or `∫ x dx` glyph-stitched). What's gone is the `$…$` source,
the equation number, and the cross-reference linkage.

Same for `bibliography_entries`: OCR adapters dump the reference list
as paragraphs. The text of each entry is there, but there's no typed
record per entry with a backlinkable citation key. Downstream RAG
cannot build a citation graph from that.

This distinction matters because "the words are there" is the bar for
full-text search, while "the structure is there" is the bar for
scientific RAG, citation graph construction, equation search, and
reference resolution. arxivbench measures the second bar; the first
bar is OmniDocBench territory.

The counts are deliberately strict (`\bibitem`, `$…$`, `\cite{…}` etc.
as exact markers) to avoid false-positives from flat text. An adapter
that emits 42 bibliography entries as plain paragraphs scores 0 — it
did not do the work of separating them.

## Scoring dimensions

| Dimension | What it measures |
|---|---|
| `sections` | `\chapter`/`\section`/`\subsection`/… coverage |
| `equations_display` | `$$…$$`, `\[…\]`, `equation`/`align`/`gather`/`eqnarray` envs |
| `equations_inline` | `$…$` (single-line math) |
| `tables` | `tabular`/`tabularx` envs |
| `figures` | `\begin{figure}` envs |
| `citation_calls` | `\cite`/`\citep`/`\citet` calls (keys comma-split) |
| `bibliography_entries` | `\bibitem` entries |
| `lists` | `itemize`/`enumerate`/`description` envs |
| `theorems` | `theorem`/`thm`/`lemma`/`cor`/`prop`/…  envs |

## Corpus

The corpus lives at [`data/test_files/arxiv/`](../../data/test_files/arxiv/).
Each directory is one paper; the main `.tex` file is auto-selected
(preferring `main.tex` / `<dirname>.tex` / single-file directories).

Current scope: **multi-file LaTeX supported** as of v0.15.0 —
`\input`/`\include` directives are resolved depth-first with cycle
detection (see [tex_input_resolver.ail](../../docparse/services/tex_input_resolver.ail)).
Plain TeX (harvmac-style, `\chap`/`\sec`) remains out of scope by
design — see [design_docs/planned/v0_15_0/latex_parser.md](../../design_docs/planned/v0_15_0/latex_parser.md).
arXiv `.tar.gz` bundle handling is deferred to v0.15.1, blocked on
upstream [ailang-core#156](https://github.com/sunholo-data/ailang/issues/156).

## Usage

```bash
# AILANG only (default, fast)
bash benchmarks/arxivbench/run_benchmark.sh

# AILANG + Pandoc source-based ceiling
bash benchmarks/arxivbench/run_benchmark.sh --adapter ailang --adapter pandoc

# Everything installed (requires: uv pip install docling markitdown llama-parse unstructured)
bash benchmarks/arxivbench/run_benchmark.sh --all

# One paper in detail
bash benchmarks/arxivbench/run_benchmark.sh --all --paper perelman_ricci

# JSON output for downstream tooling
uv run benchmarks/arxivbench/eval_arxivbench.py --all --json > results.json
```

Latest JSON is always written to [`results/latest.json`](results/).

## What a good result looks like

| Dimension | AILANG (`.tex`) target | Pandoc (`.tex`) | Docling/LlamaParse (`.pdf`) |
|---|---|---|---|
| sections | ≥95% | ~100% | ~50–70% |
| equations_display | ≥90% | ≥90% | ≤30% (OCR mangles) |
| equations_inline | ≥80% | ≥80% | ~0% (no math spans) |
| citation_calls | ≥90% | ≥90% | ~0% (citations flattened) |
| bibliography_entries | ≥90% | ≥90% | 0–30% (if refs page OCR'd) |
| papers parsed | 100% | 60–80% (fragile on real arXiv) | 100% |

The interesting columns are `equations_*`, `citation_calls`, and
`bibliography_entries` — that's where PDF-OCR baselines structurally
cannot compete with source-based parsing.

## Limitations

- **Count-based, not content-based.** A parser emitting 42 random
  equations scores equally with one emitting the 42 right ones.
  Content fidelity is a separate follow-up (use a hand-curated golden
  subset).
- **Truth counts assume standard LaTeX.** Papers using custom macros
  for sectioning (harvmac `\chap`, phyzzx, amsthm redefinitions) show
  as "0 sections" in truth and are treated correctly as out-of-scope.
- **PDF rendering may differ from source.** Some papers' PDFs are
  pre-compiled with resolved macros, so OCR tools sometimes look
  better than they would on raw rendering. We live with this — it's
  the baseline they'd hit in production anyway.
