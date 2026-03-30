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
        except Exception as e:
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
    parser.add_argument("--adapter", help="Evaluate a single adapter (docparse, unstructured, docling, llamaparse, markitdown)")
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
        adapter_names = ["docparse", "unstructured", "docling", "llamaparse", "markitdown"]
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

    if args.json:
        print(json.dumps(all_results, indent=2))
    elif args.latex:
        print_latex(all_results)
    else:
        print_summary(all_results)
        print_per_format(all_results)
        print_feature_heatmap(all_results)


if __name__ == "__main__":
    main()
