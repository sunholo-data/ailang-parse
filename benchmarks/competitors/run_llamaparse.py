#!/usr/bin/env python3
"""DocParse Benchmark: AILANG DocParse vs LlamaParse.

LlamaParse is LlamaIndex's cloud-based document parsing API.
Requires LLAMA_CLOUD_API_KEY environment variable.

Install: uv pip install llama-parse
Usage:
    LLAMA_CLOUD_API_KEY=xxx uv run benchmarks/competitors/run_llamaparse.py
    LLAMA_CLOUD_API_KEY=xxx uv run benchmarks/competitors/run_llamaparse.py --format docx
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "metrics"))
from normalize import NormalizedElement, normalize_ailang

REPO_DIR = Path(__file__).parent.parent.parent
TEST_DIR = REPO_DIR / "data" / "test_files"
AILANG_OUTPUT = REPO_DIR / "docparse" / "data" / "output.json"

OFFICE_EXTS = {".docx", ".pptx", ".xlsx"}
PDF_EXTS = {".pdf"}


def normalize_llamaparse(documents: list) -> list[NormalizedElement]:
    """Normalize LlamaParse output to common schema."""
    elements = []
    for doc in documents:
        text = doc.text if hasattr(doc, "text") else str(doc)
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                heading_text = line.lstrip("# ").strip()
                elements.append(NormalizedElement(
                    type="heading", text=heading_text, level=level,
                    metadata={"source_type": "LlamaParse:heading"},
                ))
            elif line.startswith("|") and "|" in line[1:]:
                # Markdown table row
                cells = [c.strip() for c in line.split("|") if c.strip() and c.strip() != "---"]
                if cells and not all(set(c) <= {"-", ":"} for c in cells):
                    elements.append(NormalizedElement(
                        type="table", text=" ".join(cells), level=0,
                        metadata={"source_type": "LlamaParse:table_row"},
                    ))
            elif line.startswith("- ") or line.startswith("* "):
                elements.append(NormalizedElement(
                    type="list_item", text=line[2:], level=0,
                    metadata={"source_type": "LlamaParse:list"},
                ))
            else:
                elements.append(NormalizedElement(
                    type="text", text=line, level=0,
                    metadata={"source_type": "LlamaParse:text"},
                ))
    return elements


def run_ailang(filepath: Path) -> tuple[list[NormalizedElement], float]:
    """Run AILANG DocParse and return normalized elements + time."""
    start = time.time()
    cmd = [
        "ailang", "run", "--entry", "main", "--caps", "IO,FS,Env",
        "docparse/main.ail", str(filepath),
    ]
    subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_DIR), timeout=60)
    elapsed = (time.time() - start) * 1000

    if not AILANG_OUTPUT.exists():
        return [], elapsed

    try:
        data = json.loads(AILANG_OUTPUT.read_text())
        return normalize_ailang(data), elapsed
    except (json.JSONDecodeError, KeyError):
        return [], elapsed


def run_llamaparse(filepath: Path) -> tuple[list[NormalizedElement], float]:
    """Run LlamaParse and return normalized elements + time."""
    api_key = os.environ.get("LLAMA_CLOUD_API_KEY")
    if not api_key:
        print("ERROR: Set LLAMA_CLOUD_API_KEY environment variable")
        return [], 0.0

    try:
        from llama_parse import LlamaParse
    except ImportError:
        print("ERROR: llama-parse not installed. Run: uv pip install llama-parse")
        return [], 0.0

    start = time.time()
    parser = LlamaParse(api_key=api_key, result_type="markdown")
    documents = parser.load_data(str(filepath))
    elapsed = (time.time() - start) * 1000

    return normalize_llamaparse(documents), elapsed


def main():
    parser = argparse.ArgumentParser(description="DocParse vs LlamaParse benchmark")
    parser.add_argument("--format", choices=["docx", "pptx", "xlsx", "pdf", "all"],
                        default="all", help="File format to test")
    parser.add_argument("--files", nargs="*", help="Specific files to test")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if not os.environ.get("LLAMA_CLOUD_API_KEY"):
        print("Set LLAMA_CLOUD_API_KEY to run this benchmark.")
        print("Get a key at: https://cloud.llamaindex.ai/")
        return

    if args.files:
        files = [TEST_DIR / f for f in args.files]
    else:
        exts = OFFICE_EXTS | PDF_EXTS if args.format == "all" else {f".{args.format}"}
        files = sorted(f for f in TEST_DIR.iterdir() if f.suffix.lower() in exts)

    if not files:
        print("No test files found.")
        return

    print(f"DocParse vs LlamaParse — {len(files)} files")
    print()

    results = []
    for filepath in files:
        fname = filepath.name
        print(f"  {fname}: ", end="", flush=True)

        ailang_els, ailang_ms = run_ailang(filepath)
        llama_els, llama_ms = run_llamaparse(filepath)

        # Text Jaccard
        ailang_words = set(re.findall(r"[a-z0-9]+",
            " ".join(e.text for e in ailang_els).lower()))
        llama_words = set(re.findall(r"[a-z0-9]+",
            " ".join(e.text for e in llama_els).lower()))
        union = ailang_words | llama_words
        jaccard = len(ailang_words & llama_words) / len(union) if union else 1.0

        result = {
            "file": fname,
            "text_jaccard": round(jaccard, 3),
            "ailang_time_ms": round(ailang_ms, 1),
            "llamaparse_time_ms": round(llama_ms, 1),
            "ailang_elements": len(ailang_els),
            "llamaparse_elements": len(llama_els),
        }
        results.append(result)
        print(f"Jaccard={jaccard:.2f} "
              f"(AILANG: {ailang_ms:.0f}ms/{len(ailang_els)} els, "
              f"LlamaParse: {llama_ms:.0f}ms/{len(llama_els)} els)")

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print()
    print("# DocParse vs LlamaParse Comparison")
    print()
    print("| File | Jaccard | AILANG Time | LlamaParse Time | AILANG Els | LlamaParse Els |")
    print("|------|---------|-------------|-----------------|------------|----------------|")
    for r in results:
        print(f"| {r['file']} | {r['text_jaccard']:.2f} | {r['ailang_time_ms']:.0f}ms | "
              f"{r['llamaparse_time_ms']:.0f}ms | {r['ailang_elements']} | {r['llamaparse_elements']} |")

    scored = [r for r in results if r["text_jaccard"] > 0]
    if scored:
        mean_j = sum(r["text_jaccard"] for r in scored) / len(scored)
        print(f"\n**Mean Jaccard: {mean_j:.3f}** across {len(scored)} files")


if __name__ == "__main__":
    main()
