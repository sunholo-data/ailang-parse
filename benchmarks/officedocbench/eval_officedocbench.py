#!/usr/bin/env python3
"""OfficeDocBench — the first benchmark for Office structural document parsing.

Evaluates parsers on 87 test files across 11 formats, scoring structural
feature extraction (track changes, comments, merged cells, headers/footers,
text boxes, speaker notes, images, metadata, lists, headings, tables).

Usage:
    uv run benchmarks/officedocbench/eval_officedocbench.py                # AILANG Parse (live)
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
import hashlib
import platform
import subprocess
import jsonschema
from pathlib import Path
from typing import Any

from structure_v2 import BENCHMARK_VERSION, has_extracted_content
from scoring import score_file
from report import (
    print_summary,
    print_timing,
    print_per_format,
    print_feature_heatmap,
    print_latex,
)
from datetime import datetime, timezone

# Load .env if present (for API keys like LLAMA_CLOUD_API_KEY)
_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())


# Paths
SCRIPT_DIR = Path(__file__).parent
GT_DIR = SCRIPT_DIR / "ground_truth"
GOLDEN_DIR = SCRIPT_DIR.parent / "office" / "golden"
RESULTS_DIR = SCRIPT_DIR / "results"
REPO_DIR = SCRIPT_DIR.parent.parent
TEST_DIR = REPO_DIR / "data" / "test_files"

OUTPUT_CACHE = None
REUSE_CACHE = False
ADAPTER_HASH = ""
ADAPTER_NAMES = [
    "docparse",
    "unstructured",
    "docling",
    "llamaparse",
    "markitdown",
    "kreuzberg",
    "pandoc",
    "ooxml",
    "liteparse",
]


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
    elif name == "liteparse":
        try:
            from adapters.liteparse_adapter import LiteParseAdapter

            return LiteParseAdapter()
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

    # Collect files to parse and their ground truth
    parse_jobs: list[tuple[Path, dict, Path]] = []  # (test_path, gt, gt_path)
    skip_results: list[dict] = []

    for gt_path in gt_files:
        with open(gt_path) as f:
            gt = json.load(f)

        fmt = gt["format"]
        source_file = gt["file"]

        if format_filter and fmt != format_filter:
            continue

        if fmt not in supported:
            skip_results.append(
                {
                    "file": source_file,
                    "format": fmt,
                    "status": "UNSUPPORTED",
                }
            )
            continue

        test_path = _find_test_file(source_file)
        if test_path is None:
            skip_results.append(
                {
                    "file": source_file,
                    "format": fmt,
                    "status": "MISSING",
                }
            )
            continue

        parse_jobs.append((test_path, gt, gt_path))

    started = datetime.now(timezone.utc).isoformat()
    # Batch mode is a real parser invocation, not a cache of checked-in goldens.
    batch_outputs = None
    batch_ms = 0.0
    if hasattr(adapter, "parse_batch") and not use_golden and parse_jobs:
        before = time.monotonic()
        batch_outputs = adapter.parse_batch([job[0] for job in parse_jobs])
        batch_ms = (time.monotonic() - before) * 1000 / len(parse_jobs)

    for test_path, gt, gt_path in parse_jobs:
        source_file, fmt = gt["file"], gt["format"]
        before = time.monotonic()
        try:
            expected_hash = gt.get("verification", {}).get("source_sha256")
            if (
                expected_hash
                and hashlib.sha256(test_path.read_bytes()).hexdigest() != expected_hash
            ):
                raise ValueError("fixture SHA-256 differs from verified ground truth")
            cache_path = None
            output = None
            cached_at = None
            if OUTPUT_CACHE is not None:
                fingerprint = hashlib.sha256(
                    (
                        adapter.version()
                        + ADAPTER_HASH
                        + hashlib.sha256(test_path.read_bytes()).hexdigest()
                    ).encode()
                ).hexdigest()
                cache_path = (
                    OUTPUT_CACHE
                    / adapter.name().lower().replace(" ", "_")
                    / (source_file + ".json")
                )
                if REUSE_CACHE and cache_path.exists():
                    cache = json.loads(cache_path.read_text())
                    if cache.get("fingerprint") == fingerprint:
                        output, cached_at = cache["output"], cache["parsed_at"]
            if output is None:
                if batch_outputs is not None:
                    if test_path.name not in batch_outputs:
                        raise RuntimeError(
                            "batch parser produced no output for this fixture"
                        )
                    output = batch_outputs[test_path.name]
                elif use_golden and hasattr(adapter, "parse_from_golden"):
                    output = adapter.parse_from_golden(GOLDEN_DIR / gt_path.name)
                else:
                    output = adapter.parse(test_path)
                if cache_path is not None:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(
                        json.dumps(
                            {
                                "fingerprint": fingerprint,
                                "parsed_at": datetime.now(timezone.utc).isoformat(),
                                "output": output,
                            }
                        )
                    )
            elapsed_ms = (
                batch_ms
                if batch_outputs is not None
                else (time.monotonic() - before) * 1000
            )
            jsonschema.validate(
                output,
                json.loads(
                    (SCRIPT_DIR / "schema/adapter_output.schema.json").read_text()
                ),
            )
            if not has_extracted_content(output):
                raise RuntimeError("provider returned no extracted content")
            scores = score_file(gt, output)
            results.append(
                {
                    "file": source_file,
                    "format": fmt,
                    "status": "OK",
                    **(
                        {"time_ms": round(elapsed_ms, 1)}
                        if cached_at is None and not use_golden
                        else {}
                    ),
                    "scores": scores,
                    "cached_parse_at": cached_at,
                }
            )
            print(
                f"    {source_file}: {scores['composite']:.1%}",
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:
            results.append(
                {
                    "file": source_file,
                    "format": fmt,
                    "status": "ERROR",
                    "error": str(exc)[:500],
                }
            )
            print(
                f"    {source_file}: ERROR {str(exc)[:120]}",
                file=sys.stderr,
                flush=True,
            )
    corpus_hash = hashlib.sha256(b"".join(p.read_bytes() for p in gt_files)).hexdigest()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_DIR, capture_output=True, text=True
    ).stdout.strip()
    toolchain = subprocess.run(
        ["ailang", "--version"], capture_output=True, text=True
    ).stdout.splitlines()
    return {
        "adapter": adapter.name(),
        "version": adapter.version(),
        "results": skip_results + results,
        "provenance": {
            "benchmark_version": BENCHMARK_VERSION,
            "corpus_sha256": corpus_hash,
            "scorer_sha256": hashlib.sha256(
                (SCRIPT_DIR / "scoring.py").read_bytes()
                + (SCRIPT_DIR / "structure_v2.py").read_bytes()
            ).hexdigest(),
            "adapter_sha256": ADAPTER_HASH,
            "git_commit": commit,
            "working_tree_dirty": bool(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=REPO_DIR,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            ),
            "python": platform.python_version(),
            "toolchain": toolchain[0]
            if adapter.name() == "AILANG Parse" and toolchain
            else None,
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "mode": "golden" if use_golden else "live",
            "reuse_cache": REUSE_CACHE,
            "llamaparse_premium": os.environ.get("LLAMAPARSE_PREMIUM", "").lower()
            in ("1", "true", "yes")
            if adapter.name() == "LlamaParse"
            else None,
        },
    }


def main():
    global RESULTS_DIR, OUTPUT_CACHE, REUSE_CACHE, ADAPTER_HASH
    parser = argparse.ArgumentParser(description="OfficeDocBench v2")
    parser.add_argument("--adapter", choices=ADAPTER_NAMES)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--format")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--latex", action="store_true")
    parser.add_argument(
        "--live", action="store_true", help="Live parsing (the default)"
    )
    parser.add_argument(
        "--golden",
        action="store_true",
        help="Diagnostic only; not eligible for publication",
    )
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--output-cache",
        type=Path,
        help="Save converted provider output for reproducible rescoring",
    )
    parser.add_argument(
        "--reuse-cache",
        action="store_true",
        help="Explicitly reuse matching provider/version/input/adapter output",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="Combine completed v2 adapter runs from results-dir",
    )
    args = parser.parse_args()
    RESULTS_DIR, OUTPUT_CACHE, REUSE_CACHE = (
        args.results_dir.resolve(),
        args.output_cache,
        args.reuse_cache,
    )
    gt_files = sorted(GT_DIR.glob("*.json"))
    if args.summarize:
        all_results = [
            json.loads(p.read_text())
            for p in sorted(RESULTS_DIR.glob("*/results.json"))
            if p.parent.name in ADAPTER_NAMES
        ]
        _write_summary(all_results)
        print_summary(all_results)
        return
    all_results = []
    for name in ADAPTER_NAMES if args.all else [args.adapter or "docparse"]:
        adapter = load_adapter(name)
        module = (
            SCRIPT_DIR
            / "adapters"
            / ("docparse_adapter.py" if name == "docparse" else name + "_adapter.py")
        )
        reference = (
            b"".join(
                p.read_bytes() for p in sorted((REPO_DIR / "docparse").rglob("*.ail"))
            )
            if name == "docparse"
            else b""
        )
        ADAPTER_HASH = hashlib.sha256(
            module.read_bytes()
            + (SCRIPT_DIR / "adapters/structure.py").read_bytes()
            + reference
        ).hexdigest()
        print(
            f"Evaluating {adapter.name()} {adapter.version()}",
            file=sys.stderr,
            flush=True,
        )
        try:
            result = evaluate_adapter(
                adapter, gt_files, args.format, use_golden=args.golden
            )
        except Exception as exc:
            result = {
                "adapter": adapter.name(),
                "version": adapter.version(),
                "results": [
                    {
                        "file": json.loads(p.read_text())["file"],
                        "format": json.loads(p.read_text())["format"],
                        "status": "ERROR",
                        "error": str(exc)[:500],
                    }
                    for p in gt_files
                ],
                "provenance": {
                    "benchmark_version": BENCHMARK_VERSION,
                    "mode": "live",
                    "failed": True,
                },
            }
        all_results.append(result)
        dest = RESULTS_DIR / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    if args.all and not args.format and not args.golden:
        _write_summary(all_results)
    if args.json:
        print(json.dumps(all_results, indent=2))
    elif args.latex:
        print_latex(all_results)
    else:
        print_summary(all_results)
        print_timing(all_results)
        print_per_format(all_results)
        print_feature_heatmap(all_results)
    # Errors are visible and nonzero. Unsupported formats are coverage gaps.
    if any(
        r["status"] in ("ERROR", "MISSING") for a in all_results for r in a["results"]
    ):
        sys.exit(1)


# Adapter display name → short id used by the docs/website JS
_ADAPTER_ID = {
    "DocParse": "ailang_parse",
    "AILANG Parse": "ailang_parse",
    "Unstructured": "unstructured",
    "Docling": "docling",
    "LlamaParse": "llamaparse",
    "MarkItDown": "markitdown",
    "Kreuzberg": "kreuzberg",
    "Pandoc": "pandoc",
    "Raw OOXML": "ooxml",
    "LiteParse": "liteparse",
}


def _rounded(value, digits):
    return round(value, digits) if value is not None else None


def _write_summary(all_results: list[dict]) -> None:
    """Write a compact summary.json with the headline numbers the docs site needs."""
    if not all_results or any(
        a.get("provenance", {}).get("benchmark_version") != BENCHMARK_VERSION
        for a in all_results
    ):
        raise ValueError("refusing to publish legacy or unversioned results")
    if any(
        a.get("provenance", {}).get("mode") not in ("live", "rescore")
        for a in all_results
    ):
        raise ValueError("golden-output diagnostics cannot be published")
    fingerprints = {
        a.get("provenance", {}).get("corpus_sha256")
        for a in all_results
        if not a.get("provenance", {}).get("failed")
    }
    if len(fingerprints) != 1:
        raise ValueError("refusing to combine runs from different corpus revisions")
    total_files = max((len(ar["results"]) for ar in all_results), default=0)
    adapters_summary = []
    for ar in all_results:
        ok = [r for r in ar["results"] if r["status"] == "OK"]
        n_ok = len(ok)
        n_total = len(ar["results"])
        coverage = n_ok / n_total if n_total else 0
        composite = sum(r["scores"]["composite"] for r in ok) / n_ok if ok else 0

        def _avg(key: str) -> float:
            values = [
                r["scores"][key]["score"]
                for r in ok
                if r["scores"].get(key, {}).get("applicable", True)
            ]
            return sum(values) / len(values) if values else None

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

        # Timing stats
        times = [r["time_ms"] for r in ok if "time_ms" in r]
        import statistics

        timing = {}
        if times:
            timing = {
                "median_ms": round(statistics.median(times), 1),
                "mean_ms": round(statistics.mean(times), 1),
                "min_ms": round(min(times), 1),
                "max_ms": round(max(times), 1),
                "total_ms": round(sum(times), 1),
            }

        adapters_summary.append(
            {
                "id": _ADAPTER_ID.get(
                    ar["adapter"], ar["adapter"].lower().replace(" ", "_")
                ),
                "name": ar["adapter"],
                "version": ar.get("version", ""),
                "files_ok": n_ok,
                "files_total": n_total,
                "coverage": round(coverage, 4),
                "composite": round(composite, 4),
                "adjusted": round(composite * coverage, 4),
                "feature_detection": _rounded(_avg("feature_detection"), 4),
                "structural_recall": _rounded(_avg("structural_recall"), 4),
                "structural_quality": _rounded(_avg("structural_quality"), 4),
                "content_fidelity": _rounded(_avg("content_fidelity"), 4),
                "text_jaccard": _rounded(_avg("text_jaccard"), 4),
                "element_count": _rounded(_avg("element_count"), 4),
                "metadata": _rounded(_avg("metadata"), 4),
                "timing": timing,
                "structural_fidelity": _rounded(_avg("structural_fidelity"), 4),
                "errors": sum(r["status"] == "ERROR" for r in ar["results"]),
                "provenance": ar.get("provenance", {}),
                "structural_features": {
                    kind: {
                        "score": round(
                            sum(
                                r["scores"]["structural_fidelity"]["details"][kind][
                                    "score"
                                ]
                                for r in ok
                                if kind in r["scores"]["structural_fidelity"]["details"]
                            )
                            / sum(
                                kind in r["scores"]["structural_fidelity"]["details"]
                                for r in ok
                            ),
                            4,
                        ),
                        "files": sum(
                            kind in r["scores"]["structural_fidelity"]["details"]
                            for r in ok
                        ),
                    }
                    for kind in sorted(
                        {
                            k
                            for r in ok
                            for k in r["scores"]["structural_fidelity"]["details"]
                        }
                    )
                },
                "per_format": per_format,
            }
        )

    # Sort by adjusted (coverage-aware) score descending — the leaderboard order
    adapters_summary.sort(key=lambda a: a["adjusted"], reverse=True)

    summary = {
        "schema_version": 2,
        "benchmark_version": BENCHMARK_VERSION,
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_files": total_files,
        "adapters": adapters_summary,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Wrote {summary_path}", file=sys.stderr)

    # Mirror into docs/ so the static site can fetch it without a build step.
    if RESULTS_DIR != (SCRIPT_DIR / "results").resolve():
        return
    docs_summary = REPO_DIR / "docs" / "data" / "officedocbench-summary.json"
    docs_summary.parent.mkdir(parents=True, exist_ok=True)
    with open(docs_summary, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Wrote {docs_summary.relative_to(REPO_DIR)}", file=sys.stderr)


if __name__ == "__main__":
    main()
