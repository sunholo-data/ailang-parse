#!/usr/bin/env python3
"""OfficeDocBench — the first benchmark for Office structural document parsing.

Evaluates parsers on 54 test files across 10 formats, scoring structural
feature extraction (track changes, comments, merged cells, headers/footers,
text boxes, speaker notes, images, metadata, lists, headings, tables).

Usage:
    uv run benchmarks/officedocbench/eval_officedocbench.py                # AILANG Parse only (from golden)
    uv run benchmarks/officedocbench/eval_officedocbench.py --live         # AILANG Parse (re-parse files)
    uv run benchmarks/officedocbench/eval_officedocbench.py --all          # All installed adapters
    uv run benchmarks/officedocbench/eval_officedocbench.py --adapter X    # Single competitor
    uv run benchmarks/officedocbench/eval_officedocbench.py --format docx  # Single format
    uv run benchmarks/officedocbench/eval_officedocbench.py --json         # JSON output
    uv run benchmarks/officedocbench/eval_officedocbench.py --latex        # LaTeX table
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Load .env if present (for API keys like LLAMA_CLOUD_API_KEY)
_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

from scoring import score_file
from report import print_summary, print_per_format, print_feature_heatmap, print_latex
from datetime import datetime, timezone

# Paths
SCRIPT_DIR = Path(__file__).parent
GT_DIR = SCRIPT_DIR / "ground_truth"
GOLDEN_DIR = SCRIPT_DIR.parent / "office" / "golden"
RESULTS_DIR = SCRIPT_DIR / "results"
REPO_DIR = SCRIPT_DIR.parent.parent
TEST_DIR = REPO_DIR / "data" / "test_files"


def _find_test_file(source_file: str) -> Path | None:
    """Find a test file in TEST_DIR or its subdirectories (e.g., challenge/)."""
    direct = TEST_DIR / source_file
    if direct.exists():
        return direct
    # Check subdirectories (challenge/, etc.)
    for subdir in TEST_DIR.iterdir():
        if subdir.is_dir():
            candidate = subdir / source_file
            if candidate.exists():
                return candidate
    return None


def load_adapter(name: str):
    """Load an adapter by name. Returns instance or None if unavailable."""
    if name == "docparse":
        from adapters.docparse_adapter import DocParseAdapter
        return DocParseAdapter()
    elif name == "unstructured":
        try:
            from adapters.unstructured_adapter import UnstructuredAdapter
            return UnstructuredAdapter()
        except Exception:
            return None
    elif name == "docling":
        try:
            from adapters.docling_adapter import DoclingAdapter
            return DoclingAdapter()
        except Exception:
            return None
    elif name == "llamaparse":
        try:
            from adapters.llamaparse_adapter import LlamaParseAdapter
            return LlamaParseAdapter()
        except Exception:
            return None
    elif name == "markitdown":
        try:
            from adapters.markitdown_adapter import MarkItDownAdapter
            return MarkItDownAdapter()
        except Exception:
            return None
    elif name == "kreuzberg":
        try:
            from adapters.kreuzberg_adapter import KreuzbergAdapter
            return KreuzbergAdapter()
        except Exception:
            return None
    elif name == "pandoc":
        try:
            from adapters.pandoc_adapter import PandocAdapter
            return PandocAdapter()
        except Exception:
            return None
    elif name == "ooxml":
        try:
            from adapters.ooxml_adapter import OOXMLAdapter
            return OOXMLAdapter()
        except Exception:
            return None
    return None


def evaluate_adapter(
    adapter,
    gt_files: list[Path],
    format_filter: str | None = None,
    use_golden: bool = True,
) -> dict[str, Any]:
    """Run evaluation for a single adapter across all ground truth files."""
    results = []
    supported = adapter.supported_formats()

    for gt_path in gt_files:
        with open(gt_path) as f:
            gt = json.load(f)

        fmt = gt["format"]
        source_file = gt["file"]

        # Apply format filter
        if format_filter and fmt != format_filter:
            continue

        # Skip if adapter doesn't support this format
        if fmt not in supported:
            results.append({
                "file": source_file,
                "format": fmt,
                "status": "UNSUPPORTED",
            })
            continue

        # Get adapter output
        try:
            start = time.time()
            if use_golden and hasattr(adapter, "parse_from_golden"):
                golden_path = GOLDEN_DIR / gt_path.name
                if golden_path.exists():
                    output = adapter.parse_from_golden(golden_path)
                else:
                    # No golden file (e.g., challenge files) — parse live
                    test_path = _find_test_file(source_file)
                    if test_path is None:
                        results.append({
                            "file": source_file,
                            "format": fmt,
                            "status": "MISSING",
                        })
                        continue
                    output = adapter.parse(test_path)
            else:
                test_path = _find_test_file(source_file)
                if test_path is None:
                    results.append({
                        "file": source_file,
                        "format": fmt,
                        "status": "MISSING",
                    })
                    continue
                output = adapter.parse(test_path)
            elapsed_ms = round((time.time() - start) * 1000, 1)
        except BaseException as e:
            # BaseException (not Exception) so a pyo3_runtime.PanicException
            # from a Rust-backed adapter (e.g. kreuzberg's comrak panic on
            # certain EPUBs) records as a per-file ERROR instead of crashing
            # the entire benchmark run. KeyboardInterrupt still re-raises.
            if isinstance(e, KeyboardInterrupt):
                raise
            results.append({
                "file": source_file,
                "format": fmt,
                "status": "ERROR",
                "error": str(e)[:200],
            })
            continue

        # Score
        scores = score_file(gt, output)

        results.append({
            "file": source_file,
            "format": fmt,
            "status": "OK",
            "time_ms": elapsed_ms,
            "scores": scores,
        })

    return {
        "adapter": adapter.name(),
        "version": adapter.version(),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="OfficeDocBench Evaluation")
    parser.add_argument("--adapter", help="Evaluate a single adapter (docparse, unstructured, docling, llamaparse, markitdown, kreuzberg, pandoc, ooxml)")
    parser.add_argument("--all", action="store_true", help="Evaluate all installed adapters")
    parser.add_argument("--format", help="Filter by format (docx, pptx, xlsx, etc.)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--latex", action="store_true", help="LaTeX table output")
    parser.add_argument("--live", action="store_true", help="Re-parse files instead of using golden outputs")
    args = parser.parse_args()

    # Load ground truth files
    gt_files = sorted(GT_DIR.glob("*.json"))
    if not gt_files:
        print("No ground truth files found. Run annotate.py first.", file=sys.stderr)
        sys.exit(1)

    # Determine which adapters to evaluate
    adapter_names = []
    if args.adapter:
        adapter_names = [args.adapter]
    elif args.all:
        adapter_names = ["docparse", "unstructured", "docling", "llamaparse", "markitdown", "kreuzberg", "pandoc", "ooxml"]
    else:
        adapter_names = ["docparse"]

    all_results = []
    for name in adapter_names:
        adapter = load_adapter(name)
        if adapter is None:
            print(f"  SKIP {name} (not installed)", file=sys.stderr)
            continue

        print(f"  Evaluating {adapter.name()} v{adapter.version()}...", file=sys.stderr)
        use_golden = not args.live and name == "docparse"
        result = evaluate_adapter(adapter, gt_files, args.format, use_golden=use_golden)
        all_results.append(result)

        # Save results
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result_dir = RESULTS_DIR / name
        result_dir.mkdir(parents=True, exist_ok=True)
        with open(result_dir / "results.json", "w") as f:
            json.dump(result, f, indent=2)

    # Write summary.json — single source of truth for headline numbers used by docs.
    # Only refresh when running --all or a single adapter wouldn't give a complete picture.
    if args.all and not args.format:
        _write_summary(all_results)

    if args.json:
        print(json.dumps(all_results, indent=2))
    elif args.latex:
        print_latex(all_results)
    else:
        print_summary(all_results)
        print_per_format(all_results)
        print_feature_heatmap(all_results)


# Adapter display name → short id used by the docs/website JS
_ADAPTER_ID = {
    "DocParse": "ailang_parse",
    "Unstructured": "unstructured",
    "Docling": "docling",
    "LlamaParse": "llamaparse",
    "MarkItDown": "markitdown",
    "Kreuzberg": "kreuzberg",
    "Pandoc": "pandoc",
    "Raw OOXML": "ooxml",
}


def _write_summary(all_results: list[dict]) -> None:
    """Write a compact summary.json with the headline numbers the docs site needs."""
    total_files = max((len(ar["results"]) for ar in all_results), default=0)
    adapters_summary = []
    for ar in all_results:
        ok = [r for r in ar["results"] if r["status"] == "OK"]
        n_ok = len(ok)
        n_total = len(ar["results"])
        coverage = n_ok / n_total if n_total else 0
        composite = sum(r["scores"]["composite"] for r in ok) / n_ok if ok else 0

        def _avg(key: str) -> float:
            return sum(r["scores"].get(key, {}).get("score", 0) for r in ok) / n_ok if ok else 0

        # Per-format composite
        by_fmt: dict[str, list[float]] = {}
        for r in ok:
            by_fmt.setdefault(r["format"], []).append(r["scores"]["composite"])
        per_format = {
            fmt: {
                "composite": round(sum(scores) / len(scores), 4),
                "files": len(scores),
            }
            for fmt, scores in sorted(by_fmt.items())
        }

        adapters_summary.append({
            "id": _ADAPTER_ID.get(ar["adapter"], ar["adapter"].lower().replace(" ", "_")),
            "name": ar["adapter"],
            "version": ar.get("version", ""),
            "files_ok": n_ok,
            "files_total": n_total,
            "coverage": round(coverage, 4),
            "composite": round(composite, 4),
            "adjusted": round(composite * coverage, 4),
            "feature_detection": round(_avg("feature_detection"), 4),
            "structural_recall": round(_avg("structural_recall"), 4),
            "structural_quality": round(_avg("structural_quality"), 4),
            "content_fidelity": round(_avg("content_fidelity"), 4),
            "text_jaccard": round(_avg("text_jaccard"), 4),
            "element_count": round(_avg("element_count"), 4),
            "metadata": round(_avg("metadata"), 4),
            "per_format": per_format,
        })

    # Sort by adjusted (coverage-aware) score descending — the leaderboard order
    adapters_summary.sort(key=lambda a: a["adjusted"], reverse=True)

    summary = {
        "schema_version": 1,
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_files": total_files,
        "adapters": adapters_summary,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Wrote {summary_path.relative_to(REPO_DIR)}", file=sys.stderr)

    # Mirror into docs/ so the static site can fetch it without a build step.
    docs_summary = REPO_DIR / "docs" / "data" / "officedocbench-summary.json"
    docs_summary.parent.mkdir(parents=True, exist_ok=True)
    with open(docs_summary, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Wrote {docs_summary.relative_to(REPO_DIR)}", file=sys.stderr)


if __name__ == "__main__":
    main()
