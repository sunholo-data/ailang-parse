#!/usr/bin/env python3
"""DocParse Benchmark: AILANG DocParse vs IBM Docling.

Compares structural extraction on Office files (DOCX, PPTX, XLSX) and PDF.
Docling uses AI models (DocLayNet, TableFormer) for layout analysis.
DocParse uses deterministic XML parsing for Office + pluggable AI for PDF.

Install: uv pip install docling
Usage:
    uv run benchmarks/competitors/run_docling.py
    uv run benchmarks/competitors/run_docling.py --format docx
    uv run benchmarks/competitors/run_docling.py --files sample.docx
"""

from __future__ import annotations

import argparse
import json
import os
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

OFFICE_EXTS = {".docx", ".pptx", ".xlsx"}
PDF_EXTS = {".pdf"}


def normalize_docling(doc_result) -> list[NormalizedElement]:
    """Normalize Docling DoclingDocument to common schema."""
    elements = []

    # Export to dict and walk the structure
    try:
        doc_dict = doc_result.document.export_to_dict()
    except Exception:
        # Fallback: use markdown and split into text elements
        md = doc_result.document.export_to_markdown()
        for line in md.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                text = line.lstrip("# ").strip()
                elements.append(NormalizedElement(
                    type="heading", text=text, level=level,
                    metadata={"source_type": "DoclingHeading"},
                ))
            else:
                elements.append(NormalizedElement(
                    type="text", text=line, level=0,
                    metadata={"source_type": "DoclingText"},
                ))
        return elements

    # Walk Docling's structured output
    for item in doc_dict.get("main-text", doc_dict.get("body", [])):
        item_type = item.get("type", "")
        text = item.get("text", "")

        if item_type in ("title", "section-header"):
            level = item.get("level", 1)
            elements.append(NormalizedElement(
                type="heading", text=text, level=level,
                metadata={"source_type": f"Docling:{item_type}"},
            ))
        elif item_type == "table":
            # Docling exports tables as HTML or structured data
            table_text = text or item.get("data", "")
            elements.append(NormalizedElement(
                type="table", text=str(table_text), level=0,
                metadata={
                    "source_type": "Docling:table",
                    "has_merge_info": False,
                },
            ))
        elif item_type in ("list-item", "list"):
            elements.append(NormalizedElement(
                type="list_item", text=text, level=0,
                metadata={"source_type": f"Docling:{item_type}"},
            ))
        elif item_type == "picture":
            elements.append(NormalizedElement(
                type="image", text=text, level=0,
                metadata={"source_type": "Docling:picture"},
            ))
        else:
            if text.strip():
                elements.append(NormalizedElement(
                    type="text", text=text, level=0,
                    metadata={"source_type": f"Docling:{item_type or 'paragraph'}"},
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


def run_docling(filepath: Path) -> tuple[list[NormalizedElement], float]:
    """Run Docling and return normalized elements + time."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        print("ERROR: docling not installed. Run: uv pip install docling")
        return [], 0.0

    start = time.time()
    converter = DocumentConverter()
    result = converter.convert(str(filepath))
    elapsed = (time.time() - start) * 1000

    return normalize_docling(result), elapsed


def compare_elements(
    ailang_els: list[NormalizedElement],
    docling_els: list[NormalizedElement],
) -> dict[str, Any]:
    """Compare two element lists on key metrics."""
    def count_by_type(els):
        counts = {}
        for e in els:
            counts[e.type] = counts.get(e.type, 0) + 1
        return counts

    def all_text(els):
        return " ".join(e.text for e in els if e.text)

    ailang_counts = count_by_type(ailang_els)
    docling_counts = count_by_type(docling_els)

    # Text coverage (word-level Jaccard)
    import re
    ailang_words = set(re.findall(r"[a-z0-9]+", all_text(ailang_els).lower()))
    docling_words = set(re.findall(r"[a-z0-9]+", all_text(docling_els).lower()))
    union = ailang_words | docling_words
    jaccard = len(ailang_words & docling_words) / len(union) if union else 1.0

    # Feature detection
    ailang_features = {
        "tables": ailang_counts.get("table", 0),
        "headings": ailang_counts.get("heading", 0),
        "images": ailang_counts.get("image", 0),
        "changes": ailang_counts.get("change", 0),
        "comments": sum(1 for e in ailang_els if e.metadata.get("section") == "comment"),
        "headers_footers": sum(1 for e in ailang_els if e.type in ("header", "footer")),
    }
    docling_features = {
        "tables": docling_counts.get("table", 0),
        "headings": docling_counts.get("heading", 0),
        "images": docling_counts.get("image", 0),
        "changes": 0,  # Docling doesn't extract track changes
        "comments": 0,  # Docling doesn't extract comments
        "headers_footers": 0,  # Docling doesn't extract headers/footers
    }

    return {
        "text_jaccard": round(jaccard, 3),
        "ailang_elements": len(ailang_els),
        "docling_elements": len(docling_els),
        "ailang_features": ailang_features,
        "docling_features": docling_features,
    }


def main():
    parser = argparse.ArgumentParser(description="DocParse vs Docling benchmark")
    parser.add_argument("--format", choices=["docx", "pptx", "xlsx", "pdf", "all"],
                        default="all", help="File format to test")
    parser.add_argument("--files", nargs="*", help="Specific files to test")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # Discover files
    if args.files:
        files = [TEST_DIR / f for f in args.files]
    else:
        exts = OFFICE_EXTS | PDF_EXTS if args.format == "all" else {f".{args.format}"}
        files = sorted(f for f in TEST_DIR.iterdir() if f.suffix.lower() in exts)

    if not files:
        print("No test files found.")
        return

    print(f"DocParse vs Docling — {len(files)} files")
    print()

    results = []
    for filepath in files:
        fname = filepath.name
        print(f"  {fname}: ", end="", flush=True)

        ailang_els, ailang_ms = run_ailang(filepath)
        docling_els, docling_ms = run_docling(filepath)

        comparison = compare_elements(ailang_els, docling_els)

        result = {
            "file": fname,
            "ailang_time_ms": round(ailang_ms, 1),
            "docling_time_ms": round(docling_ms, 1),
            **comparison,
        }
        results.append(result)
        print(f"Jaccard={comparison['text_jaccard']:.2f} "
              f"(AILANG: {ailang_ms:.0f}ms/{len(ailang_els)} els, "
              f"Docling: {docling_ms:.0f}ms/{len(docling_els)} els)")

    if args.json:
        print(json.dumps(results, indent=2))
        return

    # Summary
    print()
    print("# DocParse vs Docling Comparison")
    print()
    print("| File | Jaccard | AILANG Time | Docling Time | AILANG Els | Docling Els |")
    print("|------|---------|-------------|--------------|------------|-------------|")
    for r in results:
        print(f"| {r['file']} | {r['text_jaccard']:.2f} | {r['ailang_time_ms']:.0f}ms | "
              f"{r['docling_time_ms']:.0f}ms | {r['ailang_elements']} | {r['docling_elements']} |")

    # Feature gap analysis
    print()
    print("## Structural Feature Gap")
    print()
    print("| Feature | DocParse | Docling |")
    print("|---------|----------|---------|")
    features_seen = set()
    for r in results:
        for feat in r["ailang_features"]:
            if feat not in features_seen and (
                r["ailang_features"][feat] > 0 or r["docling_features"].get(feat, 0) > 0
            ):
                features_seen.add(feat)
                a_total = sum(res["ailang_features"].get(feat, 0) for res in results)
                d_total = sum(res["docling_features"].get(feat, 0) for res in results)
                winner = "DocParse" if a_total > d_total else "Docling" if d_total > a_total else "Tie"
                print(f"| {feat} | {a_total} | {d_total} | {winner} |")


if __name__ == "__main__":
    main()
