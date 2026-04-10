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


def run_office(json_output: bool = False, stress: bool = False):
    """Run Office structural benchmark."""
    cmd = ["uv", "run", str(REPO_DIR / "benchmarks" / "office" / "eval_office.py")]
    if stress:
        cmd.append("--stress")
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
    # Script-based adapters (legacy)
    script_adapters = {
        "unstructured": competitors_dir / "run_unstructured.py",
        "docling": competitors_dir / "run_docling.py",
        "llamaparse": competitors_dir / "run_llamaparse.py",
    }
    # OfficeDocBench-integrated adapters (run via eval_officedocbench.py --adapter)
    odbench_adapters = {"pandoc", "ooxml", "liteparse"}

    all_names = list(script_adapters.keys()) + sorted(odbench_adapters)

    if competitor and competitor in script_adapters:
        targets = {competitor: script_adapters[competitor]}
        odbench_targets: set[str] = set()
    elif competitor and competitor in odbench_adapters:
        targets = {}
        odbench_targets = {competitor}
    elif competitor:
        print(f"Unknown competitor: {competitor}")
        print(f"Available: {', '.join(all_names)}")
        return
    else:
        targets = script_adapters
        odbench_targets = odbench_adapters

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

    for name in sorted(odbench_targets):
        print(f"\n{'='*60}")
        print(f"Running {name} comparison (via OfficeDocBench)...")
        print(f"{'='*60}\n")
        cmd = [
            "uv", "run",
            str(REPO_DIR / "benchmarks" / "officedocbench" / "eval_officedocbench.py"),
            "--adapter", name,
        ]
        if json_output:
            cmd.append("--json")
        subprocess.run(cmd, cwd=str(REPO_DIR))


def main():
    parser = argparse.ArgumentParser(description="DocParse Benchmark Runner")
    parser.add_argument("--suite", choices=["office", "officedocbench", "pdf", "stress", "all"], default="office",
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

    if args.suite == "stress":
        run_office(args.json, stress=True)

    if args.suite in ("officedocbench", "all"):
        run_officedocbench(args.json)

    if args.suite in ("pdf", "all"):
        run_pdf(args.ai, args.json)


if __name__ == "__main__":
    main()
