# OfficeDocBench v2

OfficeDocBench evaluates document parsers on **87 files across 11 formats**. It measures structural fidelity as well as text extraction. The corpus retains the original 69 cases and adds 18 Office regression fixtures. `corpus.json` declares the exact case set; extra files downloaded by CI never silently change the public comparison. Results from v1 use different scoring and must not be compared directly with v2 percentages.

## What changed

The reference adapter now preserves comment anchors and sheet attribution, logical table cells, formulas, colours on empty cells, list depth, inline formatting, bookmarks, breaks, and slide/notes relationships. Competitor adapters map the same evidence when their output exposes it. They never reopen the input document to fill in features missing from a provider's response. Raw OOXML is explicitly a local reference parser, not an external product.

There are **61 Office cases with source-derived structural assertions**. `build_structure_truth.py` reads the original DOCX/PPTX/XLSX XML, independently of AILANG output, and records the source SHA-256. It checks exact cell coordinates and merge anchors, sheet/slide order, notes attribution, comment targets, list levels, run formatting, formulas, colours, links, bookmarks, and section breaks where the input supplies those features.

`audit_legacy_truth.py` independently audits selected legacy fields in six cases against source HTML/XML. This replaces historical HTML parse-error expectations, nonexistent footnote bodies, fragmented list counts, empty SDT text expectations, and an extra image count. Each `legacy_verification.fields` array records the precise audit scope and its source hash; the other legacy fields remain unaudited. Both oracles have CI checks.

Assertions are selective, not an exhaustive claim about every Office feature. For example, stored numbers are not treated as display-formatted text, theme/tint colours are not yet fully annotated here, and spreadsheet row-coordinate assertions stop at row 100 to avoid conflating original rows with parsers' collapsed large gaps. Image detection remains a count metric; lossless image bytes and document generation are covered by separate regression suites.

One added fixture, `challenge_threaded_comments.xlsx`, is labeled `input_profile: recovery`: it deliberately lacks workbook relationships. Its failures test recovery from a minimal package and should not be described as failures on a fully formed standard workbook. Other known minimal-file failures remain visible by filename in the results.

The legacy `challenge_footnotes.docx` is also labeled as recovery input: it references notes but contains no note-body parts. Parsers cannot recover note text that is absent. AILANG warning blocks remain in adapter diagnostics and do not count as source prose or source reading-order elements. Image blocks do contribute reading-order evidence.

## Scoring

The seven original dimensions keep their relative weights: feature detection (15%), structural recall (20%), structural quality (15%), content fidelity (15%), text Jaccard (10%), element count (15%), and metadata (10%).

The eighth dimension, **structural fidelity**, uses the source-derived assertions. On annotated legacy cases, it receives 25% of the score and the seven legacy dimensions share 75%. The 18 added cases test only independently derived assertions, so their score is structural fidelity alone. Cases without new assertions retain the legacy weights. Metric aggregates omit explicitly inapplicable dimensions.

Structural assertions compare identity and position, not just word presence. Reading/container order uses a sequence alignment that penalizes missing, additional, or reordered entries. Other assertions require their declared properties to agree; missing evidence scores zero. Styled phrases can match within a coalesced run. Formula comparisons ignore the optional leading `=` used in spreadsheet display notation; missing or changed expressions still lose credit. An actual paragraph containing the target words does not establish a comment-to-target relationship.

The legacy scorer also now checks real reading order, actual comment anchors, and ordered sheet names. It no longer reconstructs document order by concatenating feature buckets. Corrected an inconsistent legacy list count in `challenge_real_world.docx` (six list groups).

**Composite** is the mean over successfully parsed cases. **Coverage** is successful parses divided by all 87 cases. **Coverage-adjusted score** is composite times coverage; failed and unsupported cases contribute zero. Always publish coverage and error counts alongside scores. Per-feature structural results expose which new capabilities actually survive extraction.

## Run

```bash
# Reference parser, live by default
uv run benchmarks/officedocbench/eval_officedocbench.py

# Tests include saved pre-fix outputs and deliberately corrupted structures
uv run python -m unittest discover -s benchmarks/officedocbench/tests -v
python3 benchmarks/officedocbench/build_structure_truth.py --check
uv run python benchmarks/officedocbench/audit_legacy_truth.py --check

# Install the local comparison providers; install native pandoc separately
uv sync --extra competitors
uv run benchmarks/officedocbench/eval_officedocbench.py --all \
  --output-cache /tmp/officedocbench-output

# One provider, or one format
uv run benchmarks/officedocbench/eval_officedocbench.py --adapter docling
uv run benchmarks/officedocbench/eval_officedocbench.py --adapter pandoc --format docx

# Explicit reuse of matching converted output, not a hidden fallback
uv run benchmarks/officedocbench/eval_officedocbench.py --all \
  --output-cache /tmp/officedocbench-output --reuse-cache

# Rescore an identifiable live parse after a scoring/annotation correction
# This preserves its original parser/adapter revision and parse timestamps.
uv run benchmarks/officedocbench/rescore.py \
  --results-dir benchmarks/officedocbench/results \
  --output-cache /tmp/officedocbench-output
uv run benchmarks/officedocbench/eval_officedocbench.py --summarize
```

LlamaParse needs `LLAMA_CLOUD_API_KEY`; inject it into the process from your secret manager. Standard non-premium mode is the default. `LLAMAPARSE_PREMIUM=1` is a different, more expensive run configuration and is recorded in provenance. Local adapters need their native dependencies, including Node.js/LibreOffice for LiteParse and Pandoc for the Pandoc adapter and some Unstructured formats.

`--golden` is diagnostic only and cannot produce a published summary. `--results-dir` supports isolated runs; only the canonical results directory mirrors a summary into `docs/data/officedocbench-summary.json`. `--summarize` rejects incompatible corpus revisions, filtered/incomplete case sets, duplicate cases, legacy results, and golden diagnostics.

## Reproducibility and failures

Each adapter result records its installed version, adapter hash, corpus/scorer hashes, source commit, toolchain, run timestamps, and configuration. Converted-output caches are keyed by provider version, adapter revision, and input bytes. Cached reads are not reported as fresh parsing latency. A rescore has its own timestamp and revision and retains the original parse provenance. Its separately hashed portable normalizer may use evidence already present in cached output, such as worksheet headings; it never reads the source to fill a provider gap.

Provider errors and unsupported formats are explicit. An empty response is an error except for source-verified blank documents and slide decks. Failed runs overwrite their own result with the failure; they never substitute a historical score. The command exits nonzero on parse or missing-fixture errors while retaining the complete report. A comparison may therefore be publishable with documented provider failures even when the command exits nonzero.

The current comparison environment is pinned in `results/environment.txt`. Raw converted-output caches are local artifacts and are not committed. v1 repository and website summaries are retained separately in `results/v1/` because those summaries previously disagreed.

Ground truth must be checked against the input source, not regenerated to make the reference parser pass. Run the oracle with no `--check` to rebuild source assertions, inspect the diff, and run the corruption tests. Legacy `annotate.py`/`enrich_gt.py` are v1 annotation utilities, not the v2 maintenance path.

## License

Benchmark annotations: CC-BY-4.0. Evaluation code: Apache-2.0. Source files retain their original licenses; see `benchmarks/SOURCES.md`.

## Recorded comparison (2026-10-23)

The reference is the **PR #114 candidate**, labeled `0.52.2+pr114`, and includes
the unreleased DOCX hyperlink fix. `DOCPARSE_BENCHMARK_LABEL=pr114` records that
label; the exact source revision and toolchain remain in provenance. Competitor
outputs retain their original live parse timestamps and are rescored against
the same audited expectations without new API requests. Do not attribute this
candidate's score to the unchanged v0.52.2 release.

| Provider | Version | Parsed | Composite | Coverage-adjusted | Errors |
|---|---|---:|---:|---:|---:|
| AILANG Parse | 0.52.2+pr114 | 87/87 | 97.3% | 97.3% | 0 |
| Kreuzberg | 4.10.4 | 82/87 | 68.2% | 64.3% | 5 |
| Docling | 2.142.1 | 83/87 | 64.9% | 61.9% | 3 |
| LlamaParse (standard) | 0.6.94 | 83/87 | 61.8% | 59.0% | 4 |
| Unstructured | 0.27.34 | 76/87 | 58.7% | 51.3% | 5 |
| Raw OOXML | 2.0.0-stdlib | 60/87 | 70.3% | 48.5% | 1 |
| MarkItDown | 0.1.5 | 69/87 | 58.4% | 46.3% | 2 |
| Pandoc | 3.12.1 | 49/87 | 63.1% | 35.6% | 1 |
| LiteParse | 2.17.0 | 70/87 | 35.9% | 28.9% | 6 |

LlamaParse uses the legacy `llama-parse` 0.6.94 client in standard non-premium mode. The original provider job responses were retrieved to audit and repair the mappings; no new parsing requests were needed for that remap. Its EPUB and minimal ODS/ODT conversion failures are retained. Other model tiers require separate configured runs.
