#!/usr/bin/env python3
"""DocParse Benchmark Runner.

Usage:
    uv run benchmarks/run_benchmarks.py --suite office          # Structural regression (no API, instant)
    uv run benchmarks/run_benchmarks.py --suite officedocbench   # OfficeDocBench formal benchmark
    uv run benchmarks/run_benchmarks.py --suite pdf              # PDF extraction (needs AI)
    uv run benchmarks/run_benchmarks.py --suite all              # Everything
    uv run benchmarks/run_benchmarks.py --competitors            # Compare to competitors
    uv run benchmarks/run_benchmarks.py --json                   # JSON output
"""

import argparse
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent


def run_office(json_output: bool = False):
    """Run Office structural benchmark."""
    cmd = ["uv", "run", str(REPO_DIR / "benchmarks" / "office" / "eval_office.py")]
    if json_output:
        cmd.append("--json")
    subprocess.run(cmd, cwd=str(REPO_DIR))


def run_pdf(ai_backend: str = "gemini", json_output: bool = False):
    """Run PDF benchmark (requires AI backend)."""
    eval_script = REPO_DIR / "benchmarks" / "pdf" / "eval_pdf.py"
    if not eval_script.exists():
        print("PDF benchmark not yet implemented. Run --suite office first.")
        return
    cmd = ["uv", "run", str(eval_script), "--ai", ai_backend]
    if json_output:
        cmd.append("--json")
    subprocess.run(cmd, cwd=str(REPO_DIR))


def run_officedocbench(json_output: bool = False):
    """Run OfficeDocBench formal benchmark."""
    cmd = ["uv", "run", str(REPO_DIR / "benchmarks" / "officedocbench" / "eval_officedocbench.py")]
    if json_output:
        cmd.append("--json")
    subprocess.run(cmd, cwd=str(REPO_DIR))


def run_competitors(competitor: str | None = None, json_output: bool = False):
    """Run competitor comparison."""
    competitors_dir = REPO_DIR / "benchmarks" / "competitors"
    adapters = {
        "unstructured": competitors_dir / "run_unstructured.py",
        "docling": competitors_dir / "run_docling.py",
        "llamaparse": competitors_dir / "run_llamaparse.py",
    }

    if competitor and competitor in adapters:
        targets = {competitor: adapters[competitor]}
    elif competitor:
        print(f"Unknown competitor: {competitor}")
        print(f"Available: {', '.join(adapters.keys())}")
        return
    else:
        targets = adapters

    for name, script in targets.items():
        if not script.exists():
            print(f"  {name}: adapter not found at {script}")
            continue
        print(f"\n{'='*60}")
        print(f"Running {name} comparison...")
        print(f"{'='*60}\n")
        cmd = ["uv", "run", str(script)]
        if json_output:
            cmd.append("--json")
        subprocess.run(cmd, cwd=str(REPO_DIR))


def main():
    parser = argparse.ArgumentParser(description="DocParse Benchmark Runner")
    parser.add_argument("--suite", choices=["office", "officedocbench", "pdf", "all"], default="office",
                        help="Benchmark suite to run (default: office)")
    parser.add_argument("--ai", default="gemini",
                        help="AI backend for PDF benchmark (default: gemini)")
    parser.add_argument("--competitors", nargs="?", const="all", default=None,
                        help="Run competitor comparison (optionally specify: unstructured, docling, llamaparse)")
    parser.add_argument("--json", action="store_true",
                        help="JSON output")
    args = parser.parse_args()

    if args.competitors is not None:
        comp = None if args.competitors == "all" else args.competitors
        run_competitors(comp, args.json)
        return

    if args.suite in ("office", "all"):
        run_office(args.json)

    if args.suite in ("officedocbench", "all"):
        run_officedocbench(args.json)

    if args.suite in ("pdf", "all"):
        run_pdf(args.ai, args.json)


if __name__ == "__main__":
    main()
