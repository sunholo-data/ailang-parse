#!/usr/bin/env python3
"""DocParse Benchmark: AILANG DocParse vs Microsoft MarkItDown.

Compares text extraction and structural feature detection on Office files.
MarkItDown converts documents to flat Markdown — no track changes, comments,
headers/footers, merged-cell detection, or metadata extraction.

Install: uv pip install markitdown[all]
Usage:
    uv run benchmarks/competitors/run_markitdown.py
    uv run benchmarks/competitors/run_markitdown.py --format docx
    uv run benchmarks/competitors/run_markitdown.py --files sample.docx
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Add metrics to path
sys.path.insert(0, str(Path(__file__).parent.parent / "metrics"))
from normalize import NormalizedElement, normalize_ailang

REPO_DIR = Path(__file__).parent.parent.parent
TEST_DIR = REPO_DIR / "data" / "test_files"
AILANG_OUTPUT = REPO_DIR / "docparse" / "data" / "output.json"
RESULTS_DIR = Path(__file__).parent / "results"

SUPPORTED_EXTS = {".docx", ".pptx", ".xlsx", ".html", ".csv", ".epub"}


def normalize_markitdown(text: str) -> list[NormalizedElement]:
    """Normalize MarkItDown markdown output to common schema."""
    elements = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            heading_text = line.lstrip("# ").strip()
            if heading_text:
                elements.append(NormalizedElement(
                    type="heading", text=heading_text, level=level,
                    metadata={"source_type": "MarkItDown:heading"},
                ))
        elif line.startswith("|") and "|" in line[1:]:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if cells and not all(set(c) <= {"-", ":", " "} for c in cells):
                elements.append(NormalizedElement(
                    type="table", text=" ".join(cells), level=0,
                    metadata={"source_type": "MarkItDown:table"},
                ))
        elif re.match(r"^[-*+]\s+", line):
            elements.append(NormalizedElement(
                type="list_item", text=re.sub(r"^[-*+]\s+", "", line), level=0,
                metadata={"source_type": "MarkItDown:list"},
            ))
        elif re.match(r"^\d+\.\s+", line):
            elements.append(NormalizedElement(
                type="list_item", text=re.sub(r"^\d+\.\s+", "", line), level=0,
                metadata={"source_type": "MarkItDown:ordered_list"},
            ))
        elif re.match(r"!\[.*\]\(.*\)", line):
            elements.append(NormalizedElement(
                type="image", text=line, level=0,
                metadata={"source_type": "MarkItDown:image"},
            ))
        else:
            elements.append(NormalizedElement(
                type="text", text=line, level=0,
                metadata={"source_type": "MarkItDown:text"},
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


def run_markitdown(filepath: Path) -> tuple[list[NormalizedElement], float]:
    """Run MarkItDown and return normalized elements + time."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        print("ERROR: markitdown not installed. Run: uv pip install markitdown[all]")
        return [], 0.0

    start = time.time()
    md = MarkItDown()
    result = md.convert(str(filepath))
    elapsed = (time.time() - start) * 1000

    return normalize_markitdown(result.text_content or ""), elapsed


def compare_elements(
    ailang_els: list[NormalizedElement],
    mit_els: list[NormalizedElement],
) -> dict[str, Any]:
    """Compare two element lists on key metrics."""
    def all_text(els):
        return " ".join(e.text for e in els if e.text)

    ailang_words = set(re.findall(r"[a-z0-9]+", all_text(ailang_els).lower()))
    mit_words = set(re.findall(r"[a-z0-9]+", all_text(mit_els).lower()))
    union = ailang_words | mit_words
    jaccard = len(ailang_words & mit_words) / len(union) if union else 1.0

    def count_by_type(els):
        counts = {}
        for e in els:
            counts[e.type] = counts.get(e.type, 0) + 1
        return counts

    ailang_counts = count_by_type(ailang_els)
    mit_counts = count_by_type(mit_els)

    ailang_features = {
        "tables": ailang_counts.get("table", 0),
        "headings": ailang_counts.get("heading", 0),
        "images": ailang_counts.get("image", 0),
        "changes": ailang_counts.get("change", 0),
        "comments": sum(1 for e in ailang_els if e.metadata.get("section") == "comment"),
        "headers_footers": sum(1 for e in ailang_els if e.type in ("header", "footer")),
    }
    mit_features = {
        "tables": mit_counts.get("table", 0),
        "headings": mit_counts.get("heading", 0),
        "images": mit_counts.get("image", 0),
        "changes": 0,
        "comments": 0,
        "headers_footers": 0,
    }

    return {
        "text_jaccard": round(jaccard, 3),
        "ailang_elements": len(ailang_els),
        "markitdown_elements": len(mit_els),
        "ailang_features": ailang_features,
        "markitdown_features": mit_features,
    }


def main():
    parser = argparse.ArgumentParser(description="DocParse vs MarkItDown benchmark")
    parser.add_argument("--format", choices=["docx", "pptx", "xlsx", "html", "csv", "epub", "all"],
                        default="all", help="File format to test")
    parser.add_argument("--files", nargs="*", help="Specific files to test")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.files:
        files = [TEST_DIR / f for f in args.files]
    else:
        exts = SUPPORTED_EXTS if args.format == "all" else {f".{args.format}"}
        files = sorted(f for f in TEST_DIR.iterdir() if f.suffix.lower() in exts)

    if not files:
        print("No test files found.")
        return

    print(f"DocParse vs MarkItDown — {len(files)} files")
    print()

    results = []
    for filepath in files:
        fname = filepath.name
        print(f"  {fname}: ", end="", flush=True)

        ailang_els, ailang_ms = run_ailang(filepath)
        mit_els, mit_ms = run_markitdown(filepath)

        comparison = compare_elements(ailang_els, mit_els)

        result = {
            "file": fname,
            "ailang_time_ms": round(ailang_ms, 1),
            "markitdown_time_ms": round(mit_ms, 1),
            **comparison,
        }
        results.append(result)
        print(f"Jaccard={comparison['text_jaccard']:.2f} "
              f"(AILANG: {ailang_ms:.0f}ms/{len(ailang_els)} els, "
              f"MarkItDown: {mit_ms:.0f}ms/{len(mit_els)} els)")

    if args.json:
        print(json.dumps(results, indent=2))
        return

    # Summary table
    print()
    print("# DocParse vs MarkItDown Comparison")
    print()
    print("| File | Jaccard | AILANG Time | MIT Time | AILANG Els | MIT Els |")
    print("|------|---------|-------------|----------|------------|---------|")
    for r in results:
        print(f"| {r['file']} | {r['text_jaccard']:.2f} | {r['ailang_time_ms']:.0f}ms | "
              f"{r['markitdown_time_ms']:.0f}ms | {r['ailang_elements']} | {r['markitdown_elements']} |")

    # Feature gap analysis
    print()
    print("## Structural Feature Gap")
    print()
    print("| Feature | DocParse | MarkItDown |")
    print("|---------|----------|------------|")
    features_seen = set()
    for r in results:
        for feat in r["ailang_features"]:
            if feat not in features_seen and (
                r["ailang_features"][feat] > 0 or r["markitdown_features"].get(feat, 0) > 0
            ):
                features_seen.add(feat)
                a_total = sum(res["ailang_features"].get(feat, 0) for res in results)
                m_total = sum(res["markitdown_features"].get(feat, 0) for res in results)
                winner = "DocParse" if a_total > m_total else "MarkItDown" if m_total > a_total else "Tie"
                print(f"| {feat} | {a_total} | {m_total} | {winner} |")


if __name__ == "__main__":
    main()
