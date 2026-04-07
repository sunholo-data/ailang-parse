---
name: benchmark
description: Run OfficeDocBench evaluation and refresh benchmark scores across the AILANG Parse website. Use when the user says 'run benchmarks', 'rerun the benchmark', 'refresh benchmark numbers', 'update bench scores', 'regenerate summary.json', mentions OfficeDocBench, asks to evaluate parsers, asks why scores are out of sync on the docs, or after any change to docparse/services/*.ail or benchmarks/officedocbench/scoring.py — even if they don't explicitly say 'benchmark'. Also use after editing any AILANG parser to verify no regression.
---

# Benchmark

Run OfficeDocBench, regenerate `summary.json` (the single source of truth for benchmark numbers across the website), and verify the docs site stays in sync.

## Why this skill exists

OfficeDocBench scores live in **one place**: `benchmarks/officedocbench/results/summary.json`. From there they propagate to the static site via `docs/data/officedocbench-summary.json` (a mirror) and the `data-bench` injector at `docs/js/bench-data.js`. If you re-run the benchmark without using this skill, you risk:

- Forgetting to regenerate the summary mirror in `docs/`
- Forgetting that JSON-LD / SEO copy on a handful of pages **cannot** use `data-bench` and must be hand-edited if the AILANG Parse composite changes
- Not catching score regressions before committing

This skill bundles all of those steps so they happen together.

## Three modes

| When | Use script | What it does |
|---|---|---|
| Changed parser code, want to re-verify everything | `scripts/full.sh` | Full eval across all 8 adapters (~1 minute), regenerates summary, syncs docs |
| Changed parser code, only care about AILANG Parse | `scripts/quick.sh` | docparse-only eval (~10 sec), regenerates summary, syncs docs |
| Just want to refresh `summary.json` from existing per-adapter results without re-parsing | `scripts/refresh-summary.sh` | Re-aggregates the existing `results/<adapter>/results.json` files into a fresh `summary.json` + mirror |

After any of these, the script automatically:

1. Diffs the new AILANG Parse composite score against the previous run
2. If the composite changed, prints a checklist of static-copy files that need manual updates (since they can't use `data-bench`)
3. Reports the headline numbers so you can sanity-check before committing

## Quick start

```bash
# Standard: re-run all adapters and refresh the site
.claude/skills/benchmark/scripts/full.sh

# Fast iteration: only re-run AILANG Parse
.claude/skills/benchmark/scripts/quick.sh

# Just regenerate summary.json from existing results (no parsing)
.claude/skills/benchmark/scripts/refresh-summary.sh
```

## When to use this skill

- The user explicitly asks to run/refresh/update benchmarks
- The user asks "are the docs scores still right?" or "is the website in sync?"
- After editing **any** file under `docparse/services/*.ail` (parser code) — to verify no regression
- After editing `benchmarks/officedocbench/scoring.py` or `enrich_gt.py`
- After adding a new test file under `data/test_files/` or new ground truth under `benchmarks/officedocbench/ground_truth/`
- Before tagging a release

Do **not** use this skill for:
- One-off questions about what a specific score means (just read `summary.json`)
- Adding a new adapter (that's a code change to `eval_officedocbench.py`)

## How the data flows

```
docparse/services/*.ail
        ↓ (parser changes)
benchmarks/officedocbench/eval_officedocbench.py --all
        ↓
benchmarks/officedocbench/results/<adapter>/results.json   ← per-adapter detail
        ↓ (_write_summary aggregates)
benchmarks/officedocbench/results/summary.json             ← canonical headline numbers
        ↓ (mirrored in same script)
docs/data/officedocbench-summary.json                      ← static-site fetchable
        ↓ (fetched at page load)
docs/js/bench-data.js → resolves data-bench="<adapter>.<field>" attrs
        ↓
docs/index.html, benchmarks.html, why.html, vs-pdf-conversion.html,
docs/migrate-from-unstructured.html, pricing.html             ← all auto-update
```

Pages **not** wired to `data-bench` (they need literal text for SEO/JSON-LD):
`docs/docx-parsing.html`, `docs/pptx-parsing.html`, `docs/xlsx-parsing.html`,
`docs/tables.html`, `docs/integrations.html`. The skill prints a reminder
to update these by hand whenever the AILANG Parse composite score changes.

## Available scripts

### `scripts/full.sh`
Full benchmark across all 8 adapters. Run after any non-trivial parser change. Takes ~1 minute. Requires the competitor adapters to be installed (`uv pip install -e '.[competitors]'`) — script warns if missing.

### `scripts/quick.sh`
docparse-only run. Use during fast iteration when you only care about whether AILANG Parse regressed. Other adapters in `summary.json` are left at their previous values, so the site still shows a consistent snapshot.

### `scripts/refresh-summary.sh`
Re-aggregates existing per-adapter `results.json` files into a fresh `summary.json` + docs mirror. Useful if you tweaked the summary writer in `eval_officedocbench.py` but the underlying scores haven't changed.

All three scripts call `scripts/_postcheck.sh` at the end to:
1. Print the current AILANG Parse composite + adjusted + coverage
2. Compare against the previous run (saved as `.previous-summary.json`)
3. If composite changed, list the static-copy files that need a manual sweep

## After running

The scripts will tell you what (if anything) needs manual attention. Common follow-ups:

- **No score change** → nothing to do, you're done
- **Composite changed within ±0.5%** → likely just rounding from a re-parse; commit the updated summary
- **Composite changed by more than 0.5%** → investigate (regression or improvement?), then update the static-copy SEO pages listed by the post-check, commit everything together
- **Coverage dropped** → a parser is now failing on files it used to handle. Check `results/docparse/results.json` for files with `status: ERROR`

## Resources

See [`resources/reference.md`](resources/reference.md) for the full data path reference (every `data-bench` field and where it appears on the site).

## Notes

- Always run from the repo root (`/Users/mark/dev/sunholo/ailang-parse`)
- The scripts use `uv` per the project rule — never `pip` or `python` directly
- `summary.json` and the docs mirror should both be committed; they're the contract between the benchmark and the website
