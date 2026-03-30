#!/usr/bin/env python3
"""Run OmniDocBench evaluation on DocParse output.

Prerequisites:
    1. Run adapter.py first to generate markdown predictions
    2. OmniDocBench repo cloned in benchmarks/omnidocbench/OmniDocBench/

Usage:
    # Generate predictions first
    uv run benchmarks/omnidocbench/adapter.py --ai gemini-2.5-flash --demo

    # Then evaluate
    uv run benchmarks/omnidocbench/run_omnidocbench.py --model gemini-2.5-flash --demo
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OMNIDOC_DIR = Path(__file__).parent / "OmniDocBench"
RESULTS_BASE = Path(__file__).parent / "results"


def main():
    parser = argparse.ArgumentParser(description="Run OmniDocBench evaluation")
    parser.add_argument("--model", default="gemini-2.5-flash",
                        help="Model name (must match adapter output dir)")
    parser.add_argument("--demo", action="store_true",
                        help="Use demo config (18 images)")
    args = parser.parse_args()

    model_dir_name = args.model.replace(":", "_").replace("/", "_")
    pred_dir = RESULTS_BASE / model_dir_name

    if not pred_dir.exists() or not list(pred_dir.glob("*.md")):
        print(f"No predictions found at {pred_dir}")
        print(f"Run adapter first: uv run benchmarks/omnidocbench/adapter.py --ai {args.model} --demo")
        return

    md_count = len(list(pred_dir.glob("*.md")))
    print(f"OmniDocBench Evaluation")
    print(f"Model: {args.model}")
    print(f"Predictions: {md_count} markdown files in {pred_dir}")
    print()

    # Create a config pointing to our predictions
    config = {
        "end2end_eval": {
            "metrics": {
                "text_block": {"metric": ["Edit_dist"]},
                "table": {"metric": ["TEDS", "Edit_dist"]},
                "reading_order": {"metric": ["Edit_dist"]},
            },
            "dataset": {
                "dataset_name": "md2md_dataset",
                "ground_truth": {
                    "data_path": str(OMNIDOC_DIR / "demo_data" / "omnidocbench_demo" / "mds"),
                    "page_info": str(OMNIDOC_DIR / "demo_data" / "omnidocbench_demo" / "OmniDocBench_demo.json"),
                },
                "prediction": {
                    "data_path": str(pred_dir),
                },
                "match_method": "quick_match",
            },
        }
    }

    if not args.demo:
        config["end2end_eval"]["dataset"]["filter"] = {"language": "english"}

    # Write temp config
    config_path = pred_dir / "eval_config.yaml"
    import yaml
    yaml.dump(config, open(config_path, "w"), default_flow_style=False)

    print(f"Config: {config_path}")
    print(f"Running OmniDocBench evaluation...")
    print()

    # Run evaluation
    cmd = [
        sys.executable, str(OMNIDOC_DIR / "pdf_validation.py"),
        "--config", str(config_path),
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300,
        cwd=str(OMNIDOC_DIR),
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # Check for results
    result_dir = OMNIDOC_DIR / "result"
    if result_dir.exists():
        print(f"\nResults in: {result_dir}")
        for f in sorted(result_dir.glob("*.json")):
            print(f"  {f.name}")
            try:
                data = json.loads(f.read_text())
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, (int, float)):
                            print(f"    {k}: {v:.3f}" if isinstance(v, float) else f"    {k}: {v}")
            except (json.JSONDecodeError, ValueError):
                pass


if __name__ == "__main__":
    main()
