"""PDF Extraction Benchmark — evaluates AI-powered PDF parsing accuracy.

Runs DocParse with an AI backend on test PDFs and compares extracted content
against ground truth. Unlike the Office benchmark (deterministic, instant),
this requires an AI model and produces non-deterministic results.

Metrics:
  - Heading detection: how many expected headings were found
  - Key phrase recall: what fraction of expected phrases appear in output
  - Table detection: whether expected tables were found
  - Text coverage: word-level Jaccard similarity

Usage:
    uv run benchmarks/pdf/eval_pdf.py --ai gemini-2.5-flash    # Google Cloud
    uv run benchmarks/pdf/eval_pdf.py --ai granite-docling      # Ollama (local)
    uv run benchmarks/pdf/eval_pdf.py --ai claude-haiku-4-5     # Anthropic
    uv run benchmarks/pdf/eval_pdf.py --json                    # JSON output
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

REPO_DIR = Path(__file__).parent.parent.parent
GOLDEN_DIR = Path(__file__).parent / "golden"
TEST_DIR = REPO_DIR / "data" / "test_files"
OUTPUT_JSON = REPO_DIR / "docparse" / "data" / "output.json"


def word_set(text: str) -> set[str]:
    """Extract lowercase word set from text."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def extract_all_text(blocks: list[dict]) -> str:
    """Recursively extract all text from blocks."""
    parts = []
    for b in blocks:
        btype = b.get("type", "")
        if btype in ("text", "heading"):
            parts.append(b.get("text", ""))
        elif btype == "table":
            for h in b.get("headers", []):
                if isinstance(h, str):
                    parts.append(h)
                elif isinstance(h, dict):
                    parts.append(h.get("text", ""))
            for row in b.get("rows", []):
                if isinstance(row, list):
                    for cell in row:
                        if isinstance(cell, str):
                            parts.append(cell)
                        elif isinstance(cell, dict):
                            parts.append(cell.get("text", ""))
        elif btype == "section":
            parts.append(extract_all_text(b.get("blocks", [])))
        elif btype == "list":
            for item in b.get("items", []):
                parts.append(str(item))
    return " ".join(parts)


def check_headings(blocks: list[dict], expected: list[str]) -> dict:
    """Check how many expected headings were found."""
    actual_headings = []
    for b in blocks:
        if b.get("type") == "heading":
            actual_headings.append(b.get("text", ""))

    all_text = extract_all_text(blocks).lower()

    found = 0
    for heading in expected:
        # Check exact heading blocks first, then fuzzy match in all text
        heading_lower = heading.lower()
        if any(heading_lower in ah.lower() for ah in actual_headings):
            found += 1
        elif heading_lower in all_text:
            found += 1

    return {
        "expected": len(expected),
        "found": found,
        "recall": found / len(expected) if expected else 1.0,
        "actual_headings": actual_headings,
    }


def check_key_phrases(blocks: list[dict], expected: list[str]) -> dict:
    """Check how many expected key phrases appear in extracted text."""
    all_text = extract_all_text(blocks).lower()

    found = 0
    missing = []
    for phrase in expected:
        if phrase.lower() in all_text:
            found += 1
        else:
            missing.append(phrase)

    return {
        "expected": len(expected),
        "found": found,
        "recall": found / len(expected) if expected else 1.0,
        "missing": missing,
    }


def check_tables(blocks: list[dict], expected_tables: list[dict]) -> dict:
    """Check table detection."""
    actual_tables = [b for b in blocks if b.get("type") == "table"]

    if not expected_tables:
        return {"applicable": False}

    count_match = len(actual_tables) == len(expected_tables)

    # Check if sample cells appear in table text
    all_table_text = ""
    for t in actual_tables:
        all_table_text += extract_all_text([t]).lower() + " "

    sample_found = 0
    total_samples = 0
    for et in expected_tables:
        for cell in et.get("sample_cells", []):
            total_samples += 1
            if cell.lower() in all_table_text:
                sample_found += 1

    return {
        "applicable": True,
        "count_match": count_match,
        "expected_count": len(expected_tables),
        "actual_count": len(actual_tables),
        "sample_cell_recall": sample_found / total_samples if total_samples else 1.0,
    }


def run_docparse(filepath: str, ai_model: str) -> dict | None:
    """Run docparse on a file and return parsed JSON output."""
    cmd = [
        "ailang", "run", "--entry", "main",
        "--caps", "IO,FS,Env,AI",
        "--ai", ai_model,
        "docparse/main.ail", filepath,
    ]

    env = os.environ.copy()
    # Use ADC if no explicit API key
    if not env.get("GOOGLE_API_KEY") and "gemini" in ai_model.lower():
        env["GOOGLE_API_KEY"] = ""

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(REPO_DIR), env=env,
        )
    except subprocess.TimeoutExpired:
        return None

    if not OUTPUT_JSON.exists():
        return None

    try:
        return json.loads(OUTPUT_JSON.read_text())
    except json.JSONDecodeError:
        return None


def evaluate_file(pdf_name: str, ai_model: str) -> dict:
    """Evaluate a single PDF file."""
    golden_path = GOLDEN_DIR / f"{pdf_name}.json"
    if not golden_path.exists():
        return {"file": pdf_name, "error": "no golden file"}

    golden = json.loads(golden_path.read_text())
    gt = golden.get("ground_truth", {})

    filepath = str(TEST_DIR / pdf_name)
    if not Path(filepath).exists():
        return {"file": pdf_name, "error": "test file missing"}

    start = time.time()
    output = run_docparse(filepath, ai_model)
    elapsed_ms = (time.time() - start) * 1000

    if output is None:
        return {"file": pdf_name, "error": "parse failed", "time_ms": elapsed_ms}

    blocks = output.get("document", {}).get("blocks", [])
    all_text = extract_all_text(blocks)

    # Evaluate
    heading_result = check_headings(blocks, gt.get("headings", []))
    phrase_result = check_key_phrases(blocks, gt.get("key_phrases", []))
    table_result = check_tables(blocks, gt.get("tables", []))

    # Overall score: weighted average
    scores = [heading_result["recall"], phrase_result["recall"]]
    if table_result.get("applicable"):
        table_score = (
            (1.0 if table_result["count_match"] else 0.5) * 0.5
            + table_result["sample_cell_recall"] * 0.5
        )
        scores.append(table_score)

    overall = sum(scores) / len(scores) if scores else 0.0

    return {
        "file": pdf_name,
        "model": ai_model,
        "time_ms": round(elapsed_ms, 1),
        "overall_score": round(overall, 3),
        "headings": heading_result,
        "key_phrases": phrase_result,
        "tables": table_result,
        "block_count": len(blocks),
        "word_count": len(all_text.split()),
    }


def main():
    parser = argparse.ArgumentParser(description="PDF extraction benchmark")
    parser.add_argument("--ai", default="gemini-2.5-flash",
                        help="AI model to use (default: gemini-2.5-flash)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--file", help="Run single file only")
    args = parser.parse_args()

    # Discover test PDFs with golden files
    if args.file:
        pdf_files = [args.file]
    else:
        pdf_files = sorted(
            p.stem.replace(".pdf", "") + ".pdf"
            for p in GOLDEN_DIR.glob("*.pdf.json")
        )

    if not pdf_files:
        print("No PDF test files with golden outputs found.")
        print("Run: uv run benchmarks/pdf/generate_test_pdfs.py")
        return

    print(f"PDF Benchmark — model: {args.ai}")
    print(f"Files: {len(pdf_files)}")
    print()

    results = []
    for pdf in pdf_files:
        print(f"  {pdf}: ", end="", flush=True)
        r = evaluate_file(pdf, args.ai)
        if "error" in r:
            print(f"ERROR ({r['error']})")
        else:
            score_pct = f"{r['overall_score']*100:.0f}%"
            print(f"{score_pct} ({r['time_ms']:.0f}ms)")
        results.append(r)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    # Summary table
    print()
    print("# DocParse PDF Extraction Benchmark")
    print()
    print(f"Model: `{args.ai}`")
    print()
    print("| File | Score | Time | Blocks | Headings | Phrases | Tables |")
    print("|------|-------|------|--------|----------|---------|--------|")

    for r in results:
        if "error" in r:
            print(f"| {r['file']} | ERROR | — | — | — | — | — |")
            continue

        score = f"{r['overall_score']*100:.0f}%"
        time_s = f"{r['time_ms']:.0f}ms"
        blocks = str(r["block_count"])
        headings = f"{r['headings']['found']}/{r['headings']['expected']}"
        phrases = f"{r['key_phrases']['found']}/{r['key_phrases']['expected']}"
        tables = "—"
        if r["tables"].get("applicable"):
            tr = r["tables"]
            tables = f"{tr['actual_count']}/{tr['expected_count']}"

        print(f"| {r['file']} | {score} | {time_s} | {blocks} | {headings} | {phrases} | {tables} |")

    # Mean score
    scored = [r for r in results if "error" not in r]
    if scored:
        mean = sum(r["overall_score"] for r in scored) / len(scored)
        print(f"\n**Mean score: {mean*100:.1f}%** across {len(scored)} files (model: {args.ai})")


if __name__ == "__main__":
    main()
