"""DocParse Structural Benchmark — regression testing across all formats.

Evaluates DocParse output against golden expected outputs on structural
features: track changes, comments, headers/footers, merged cells, text boxes,
speaker notes, images, tables, and text content.

Covers: DOCX, PPTX, XLSX, ODT, ODP, ODS, EPUB, HTML, CSV, Markdown.

No API calls needed. Runs entirely locally, instantly.

Usage:
    uv run benchmarks/office/eval_office.py                  # full report
    uv run benchmarks/office/eval_office.py --json           # JSON output
    uv run benchmarks/office/eval_office.py --file tables.docx  # single file
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

# Add parent to path for metrics imports
sys.path.insert(0, str(Path(__file__).parent.parent / "metrics"))
from normalize import NormalizedElement, normalize_ailang


REPO_DIR = Path(__file__).parent.parent.parent
GOLDEN_DIR = Path(__file__).parent / "golden"
TEST_DIR = REPO_DIR / "data" / "test_files"
OUTPUT_DIR = REPO_DIR / "docparse" / "data"


# --- Feature checks ---

def check_tables(golden_els: list[NormalizedElement], actual_els: list[NormalizedElement]) -> dict:
    """Check table extraction: count, headers, cell content."""
    golden_tables = [e for e in golden_els if e.type == "table"]
    actual_tables = [e for e in actual_els if e.type == "table"]

    if not golden_tables:
        return {"applicable": False}

    # Table count match
    count_match = len(actual_tables) == len(golden_tables)

    # Check merged cell detection
    golden_merges = sum(1 for t in golden_tables if t.metadata.get("has_merge_info"))
    actual_merges = sum(1 for t in actual_tables if t.metadata.get("has_merge_info"))

    # Cell text Jaccard
    golden_words = set()
    for t in golden_tables:
        golden_words |= set(t.text.lower().split())
    actual_words = set()
    for t in actual_tables:
        actual_words |= set(t.text.lower().split())

    intersection = golden_words & actual_words
    union = golden_words | actual_words
    jaccard = len(intersection) / len(union) if union else 1.0

    return {
        "applicable": True,
        "table_count_match": count_match,
        "golden_tables": len(golden_tables),
        "actual_tables": len(actual_tables),
        "golden_merged": golden_merges,
        "actual_merged": actual_merges,
        "merge_match": golden_merges == actual_merges,
        "cell_text_jaccard": round(jaccard, 4),
    }


def check_track_changes(golden_els: list[NormalizedElement], actual_els: list[NormalizedElement]) -> dict:
    """Check track change extraction: types, authors, text."""
    golden_changes = [e for e in golden_els if e.type == "change"]
    actual_changes = [e for e in actual_els if e.type == "change"]

    if not golden_changes:
        return {"applicable": False}

    # Count by type
    golden_types = {}
    for c in golden_changes:
        ct = c.metadata.get("change_type", "unknown")
        golden_types[ct] = golden_types.get(ct, 0) + 1
    actual_types = {}
    for c in actual_changes:
        ct = c.metadata.get("change_type", "unknown")
        actual_types[ct] = actual_types.get(ct, 0) + 1

    # Author extraction
    golden_authors = set(c.metadata.get("author", "") for c in golden_changes if c.metadata.get("author"))
    actual_authors = set(c.metadata.get("author", "") for c in actual_changes if c.metadata.get("author"))

    return {
        "applicable": True,
        "count_match": len(actual_changes) == len(golden_changes),
        "golden_count": len(golden_changes),
        "actual_count": len(actual_changes),
        "golden_types": golden_types,
        "actual_types": actual_types,
        "types_match": golden_types == actual_types,
        "golden_authors": sorted(golden_authors),
        "actual_authors": sorted(actual_authors),
        "authors_match": golden_authors == actual_authors,
    }


def check_comments(golden_els: list[NormalizedElement], actual_els: list[NormalizedElement]) -> dict:
    """Check comment extraction."""
    # Comments appear as section elements with kind="comment" in AILANG
    golden_comments = [e for e in golden_els if e.metadata.get("section") == "comment"]
    actual_comments = [e for e in actual_els if e.metadata.get("section") == "comment"]

    if not golden_comments:
        return {"applicable": False}

    return {
        "applicable": True,
        "count_match": len(actual_comments) == len(golden_comments),
        "golden_count": len(golden_comments),
        "actual_count": len(actual_comments),
    }


def check_headers_footers(golden_els: list[NormalizedElement], actual_els: list[NormalizedElement]) -> dict:
    """Check header/footer extraction."""
    golden_hf = [e for e in golden_els if e.type in ("header", "footer")]
    actual_hf = [e for e in actual_els if e.type in ("header", "footer")]

    if not golden_hf:
        return {"applicable": False}

    golden_headers = [e for e in golden_hf if e.type == "header"]
    golden_footers = [e for e in golden_hf if e.type == "footer"]
    actual_headers = [e for e in actual_hf if e.type == "header"]
    actual_footers = [e for e in actual_hf if e.type == "footer"]

    return {
        "applicable": True,
        "golden_headers": len(golden_headers),
        "golden_footers": len(golden_footers),
        "actual_headers": len(actual_headers),
        "actual_footers": len(actual_footers),
        "header_match": len(actual_headers) == len(golden_headers),
        "footer_match": len(actual_footers) == len(golden_footers),
    }


def check_text_boxes(golden_els: list[NormalizedElement], actual_els: list[NormalizedElement]) -> dict:
    """Check text box / shape content extraction."""
    golden_tb = [e for e in golden_els if e.metadata.get("section") == "textbox"]
    actual_tb = [e for e in actual_els if e.metadata.get("section") == "textbox"]

    if not golden_tb:
        return {"applicable": False}

    return {
        "applicable": True,
        "golden_count": len(golden_tb),
        "actual_count": len(actual_tb),
        "count_match": len(actual_tb) == len(golden_tb),
    }


def check_images(golden_els: list[NormalizedElement], actual_els: list[NormalizedElement]) -> dict:
    """Check image extraction."""
    golden_imgs = [e for e in golden_els if e.type == "image"]
    actual_imgs = [e for e in actual_els if e.type == "image"]

    if not golden_imgs:
        return {"applicable": False}

    return {
        "applicable": True,
        "golden_count": len(golden_imgs),
        "actual_count": len(actual_imgs),
        "count_match": len(actual_imgs) == len(golden_imgs),
    }


def check_metadata(golden_json: dict, actual_json: dict) -> dict:
    """Check document metadata extraction."""
    golden_meta = golden_json.get("document", {}).get("metadata", {})
    actual_meta = actual_json.get("document", {}).get("metadata", {})

    checks = {}
    for field in ["title", "author", "created", "modified"]:
        golden_val = golden_meta.get(field, "")
        actual_val = actual_meta.get(field, "")
        checks[field] = {
            "match": golden_val == actual_val,
            "golden": golden_val,
            "actual": actual_val,
        }

    return checks


def check_text_jaccard(golden_els: list[NormalizedElement], actual_els: list[NormalizedElement]) -> dict:
    """Overall text content Jaccard similarity."""
    import re

    def tokenize(elements):
        words = set()
        for el in elements:
            words |= set(re.findall(r"\b[a-zA-Z0-9]+\b", el.text.lower()))
        return words

    golden_words = tokenize(golden_els)
    actual_words = tokenize(actual_els)

    intersection = golden_words & actual_words
    union = golden_words | actual_words
    jaccard = len(intersection) / len(union) if union else 1.0

    return {
        "jaccard": round(jaccard, 4),
        "golden_words": len(golden_words),
        "actual_words": len(actual_words),
        "shared": len(intersection),
    }


# --- Main evaluation ---

def evaluate_file(test_file: Path, golden_file: Path) -> dict:
    """Run DocParse on a test file and compare against golden output."""
    fname = test_file.name

    # Load golden
    with open(golden_file) as f:
        golden_json = json.load(f)
    golden_els = normalize_ailang(golden_json)

    # Run DocParse
    start = time.time()
    try:
        result = subprocess.run(
            ["ailang", "run", "--entry", "main", "--caps", "IO,FS,Env",
             "--max-recursion-depth", "50000",
             "docparse/main.ail", str(test_file)],
            capture_output=True, text=True, cwd=str(REPO_DIR),
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return {"file": fname, "status": "SKIP", "error": "timeout (120s)", "time_ms": elapsed_ms}
    elapsed_ms = round((time.time() - start) * 1000, 1)

    # Check if the parser succeeded
    if result.returncode != 0:
        return {"file": fname, "status": "FAIL", "error": f"parse error (exit {result.returncode})", "time_ms": elapsed_ms}

    # Load actual output (filename-based: sample.docx → sample.docx.json)
    output_json = OUTPUT_DIR / f"{fname}.json"
    if not output_json.exists():
        return {"file": fname, "status": "FAIL", "error": f"no {fname}.json", "time_ms": elapsed_ms}

    with open(output_json) as f:
        actual_json = json.load(f)
    actual_els = normalize_ailang(actual_json)

    # Run all checks
    checks = {
        "tables": check_tables(golden_els, actual_els),
        "track_changes": check_track_changes(golden_els, actual_els),
        "comments": check_comments(golden_els, actual_els),
        "headers_footers": check_headers_footers(golden_els, actual_els),
        "text_boxes": check_text_boxes(golden_els, actual_els),
        "images": check_images(golden_els, actual_els),
        "text_similarity": check_text_jaccard(golden_els, actual_els),
        "metadata": check_metadata(golden_json, actual_json),
    }

    # Compute overall score (applicable checks that pass)
    applicable = 0
    passed = 0
    for name, check in checks.items():
        if name == "text_similarity":
            applicable += 1
            if check["jaccard"] >= 0.95:
                passed += 1
        elif name == "metadata":
            for field, result in check.items():
                if result.get("golden"):  # only count fields that have golden values
                    applicable += 1
                    if result["match"]:
                        passed += 1
        elif isinstance(check, dict) and check.get("applicable"):
            applicable += 1
            # Check passes if primary match is True
            match_keys = [k for k in check if k.endswith("_match")]
            if match_keys and all(check[k] for k in match_keys):
                passed += 1

    score = passed / applicable if applicable else 1.0

    return {
        "file": fname,
        "status": "OK",
        "time_ms": elapsed_ms,
        "golden_elements": len(golden_els),
        "actual_elements": len(actual_els),
        "element_count_match": len(actual_els) == len(golden_els),
        "checks": checks,
        "applicable_checks": applicable,
        "passed_checks": passed,
        "score": round(score, 4),
    }


def print_report(results: list[dict]) -> None:
    """Print a markdown-style report."""
    print("\n# DocParse Structural Benchmark\n")
    print(f"| File | Score | Time | Elements | Tables | Changes | Comments | Hdr/Ftr | TextBox | Jaccard |")
    print(f"|------|-------|------|----------|--------|---------|----------|---------|---------|---------|")

    total_score = 0
    total_files = 0

    for r in results:
        if r["status"] != "OK":
            print(f"| {r['file']} | FAIL | {r.get('time_ms', 0)}ms | — | — | — | — | — | — | — |")
            continue

        total_files += 1
        total_score += r["score"]

        c = r["checks"]

        def cell(check, key="count_match"):
            if not check.get("applicable"):
                return "—"
            return "PASS" if check.get(key, True) else "FAIL"

        tables = cell(c["tables"], "table_count_match")
        if c["tables"].get("applicable") and c["tables"].get("merge_match") is False:
            tables = "MERGE"

        changes = cell(c["track_changes"])
        comments = cell(c["comments"])
        hdrftr = cell(c["headers_footers"], "header_match")
        textbox = cell(c["text_boxes"])
        jaccard = f"{c['text_similarity']['jaccard']:.2f}"

        score_pct = f"{r['score']:.0%}"
        print(f"| {r['file']} | {score_pct} | {r['time_ms']}ms | {r['actual_elements']} | {tables} | {changes} | {comments} | {hdrftr} | {textbox} | {jaccard} |")

    mean_score = total_score / total_files if total_files else 0
    print(f"\n**Mean score: {mean_score:.1%}** across {total_files} files\n")


def main():
    parser = argparse.ArgumentParser(description="DocParse Structural Benchmark")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--file", help="Evaluate a single file")
    args = parser.parse_args()

    os.chdir(REPO_DIR)

    # Collect test files
    if args.file:
        test_files = [TEST_DIR / args.file]
    else:
        test_files = sorted(
            p for p in TEST_DIR.iterdir()
            if p.suffix in (".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods", ".epub", ".html", ".csv", ".tsv", ".md")
        )

    results = []
    for tf in test_files:
        golden = GOLDEN_DIR / f"{tf.name}.json"
        if not golden.exists():
            print(f"  SKIP {tf.name} (no golden output)", file=sys.stderr)
            continue
        result = evaluate_file(tf, golden)
        if not args.json:
            status = f"{result['score']:.0%}" if result["status"] == "OK" else "FAIL"
            print(f"  {tf.name}: {status}", file=sys.stderr)
        results.append(result)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)


if __name__ == "__main__":
    main()
