# OfficeDocBench results

`summary.json` is the canonical v2 comparison and is mirrored byte-for-byte to `docs/data/officedocbench-summary.json`. `<adapter>/results.json` contains every per-file score, error/unsupported status, and parse/scoring provenance. `environment.txt` pins the Python comparison environment; native tool versions are recorded in adapter results.

The summary includes composite, coverage-adjusted score, coverage, error count, eight metric aggregates, per-format scores, and per-feature structural fidelity. An unavailable or failing provider is not replaced with old results. The CLI's nonzero exit code does not discard its error report.

Rebuild the comparison with `eval_officedocbench.py --all --output-cache DIR`. Recombine independently run adapters with `--summarize`; all must use the same v2 corpus. Only the canonical results directory updates the website mirror. See the parent README for explicit cache reuse and rescoring.

`v1/` preserves the two differing historical summaries and their original dates. Their scores use a different protocol and are not directly comparable to v2.
