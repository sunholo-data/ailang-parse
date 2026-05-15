"""Compare PDF parsing backends against the existing golden files.

Backends:
  - ailang-gemini : current default (Gemini 2.5 Flash via AILANG)
  - docling       : IBM Docling, local
  - markitdown    : Microsoft MarkItDown, local
  - unstructured  : Unstructured.io OSS, local
  - llamaparse    : LlamaCloud (LLAMA_CLOUD_API_KEY required)

Scoring uses the existing golden files in benchmarks/pdf/golden/:
  heading recall, key-phrase recall, time, output bytes.

Usage:
    uv run benchmarks/pdf/compare_backends.py
    uv run benchmarks/pdf/compare_backends.py --backends docling markitdown
    uv run benchmarks/pdf/compare_backends.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent
GOLDEN_DIR = Path(__file__).parent / "golden"
TEST_DIR = REPO_DIR / "data" / "test_files"
AILANG_OUT_DIR = REPO_DIR / "docparse" / "data"

PDFS = ["simple_text.pdf", "table_report.pdf", "multipage_spec.pdf"]


def score_against_golden(text: str, headings: list[str], golden: dict) -> dict:
    gt = golden["ground_truth"]
    text_lower = text.lower()
    head_lower = [h.lower() for h in headings]

    h_found = sum(
        1
        for h in gt["headings"]
        if any(h.lower() in hl for hl in head_lower) or h.lower() in text_lower
    )
    p_found = sum(1 for p in gt["key_phrases"] if p.lower() in text_lower)

    return {
        "heading_recall": round(h_found / len(gt["headings"]), 3),
        "phrase_recall": round(p_found / len(gt["key_phrases"]), 3),
        "headings_found": f"{h_found}/{len(gt['headings'])}",
        "phrases_found": f"{p_found}/{len(gt['key_phrases'])}",
        "output_chars": len(text),
    }


def extract_text_and_headings_from_ailang(blocks: list) -> tuple[str, list[str]]:
    parts, heads = [], []
    for b in blocks:
        t = b.get("type", "")
        if t == "heading":
            heads.append(b.get("text", ""))
            parts.append(b.get("text", ""))
        elif t == "text":
            parts.append(b.get("text", ""))
        elif t == "section":
            sub_text, sub_heads = extract_text_and_headings_from_ailang(b.get("blocks", []))
            parts.append(sub_text)
            heads.extend(sub_heads)
        elif t == "table":
            for row in b.get("rows", []):
                if isinstance(row, list):
                    parts.extend(str(c) for c in row)
    return " ".join(parts), heads


def headings_from_markdown(md: str) -> tuple[str, list[str]]:
    heads = []
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("#"):
            heads.append(s.lstrip("# ").strip())
    return md, heads


def run_ailang_gemini(pdf: Path) -> tuple[str, list[str], float]:
    start = time.time()
    cmd = [
        "ailang", "run", "--entry", "main", "--caps", "IO,FS,Env,AI",
        "--ai", "gemini-2.5-flash",
        "docparse/main.ail", str(pdf),
    ]
    subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_DIR), timeout=120)
    elapsed = (time.time() - start) * 1000
    out_file = AILANG_OUT_DIR / f"{pdf.name}.json"
    if not out_file.exists():
        return "", [], elapsed
    try:
        data = json.loads(out_file.read_text())
        blocks = data.get("document", {}).get("blocks", []) or data.get("blocks", [])
        text, heads = extract_text_and_headings_from_ailang(blocks)
        return text, heads, elapsed
    except Exception:
        return "", [], elapsed


def run_docling(pdf: Path) -> tuple[str, list[str], float]:
    from docling.document_converter import DocumentConverter
    start = time.time()
    result = DocumentConverter().convert(str(pdf))
    md = result.document.export_to_markdown()
    elapsed = (time.time() - start) * 1000
    text, heads = headings_from_markdown(md)
    return text, heads, elapsed


def run_markitdown(pdf: Path) -> tuple[str, list[str], float]:
    from markitdown import MarkItDown
    start = time.time()
    result = MarkItDown().convert(str(pdf))
    md = result.text_content
    elapsed = (time.time() - start) * 1000
    text, heads = headings_from_markdown(md)
    return text, heads, elapsed


def run_unstructured(pdf: Path) -> tuple[str, list[str], float]:
    from unstructured.partition.pdf import partition_pdf
    start = time.time()
    els = partition_pdf(filename=str(pdf))
    elapsed = (time.time() - start) * 1000
    parts, heads = [], []
    for e in els:
        cat = e.category if hasattr(e, "category") else type(e).__name__
        text = str(e)
        parts.append(text)
        if cat in ("Title", "Header") or cat.startswith("Heading"):
            heads.append(text)
    return " ".join(parts), heads, elapsed


def run_liteparse(pdf: Path) -> tuple[str, list[str], float]:
    from liteparse import LiteParse
    start = time.time()
    result = LiteParse().parse(str(pdf), ocr_enabled=False)
    elapsed = (time.time() - start) * 1000
    text = "\n".join(p.text for p in result.pages)
    # LiteParse returns plain text — no heading classification. Score relies on
    # text-level fallback in score_against_golden.
    return text, [], elapsed


def run_llamaparse(pdf: Path) -> tuple[str, list[str], float]:
    from llama_parse import LlamaParse
    start = time.time()
    docs = LlamaParse(result_type="markdown").load_data(str(pdf))
    md = "\n\n".join(d.text for d in docs)
    elapsed = (time.time() - start) * 1000
    text, heads = headings_from_markdown(md)
    return text, heads, elapsed


BACKENDS = {
    "ailang-gemini": (run_ailang_gemini, "GOOGLE_API_KEY"),
    "docling": (run_docling, None),
    "markitdown": (run_markitdown, None),
    "unstructured": (run_unstructured, None),
    "liteparse": (run_liteparse, None),
    "llamaparse": (run_llamaparse, "LLAMA_CLOUD_API_KEY"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", nargs="*", default=list(BACKENDS.keys()))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = []
    for pdf_name in PDFS:
        pdf_path = TEST_DIR / pdf_name
        golden = json.loads((GOLDEN_DIR / f"{pdf_name}.json").read_text())
        print(f"\n=== {pdf_name} ({pdf_path.stat().st_size}B) ===")
        for backend in args.backends:
            fn, env_key = BACKENDS[backend]
            if env_key and not os.environ.get(env_key):
                print(f"  {backend}: SKIP (no {env_key})")
                continue
            try:
                text, heads, ms = fn(pdf_path)
            except Exception as e:
                print(f"  {backend}: ERROR {type(e).__name__}: {e}")
                results.append({"file": pdf_name, "backend": backend, "error": f"{type(e).__name__}: {e}"})
                continue
            score = score_against_golden(text, heads, golden)
            score["time_ms"] = round(ms, 0)
            results.append({"file": pdf_name, "backend": backend, **score})
            print(
                f"  {backend:14s}  h={score['headings_found']:>5s}  "
                f"p={score['phrases_found']:>5s}  "
                f"{int(ms):>6d}ms  {score['output_chars']:>5d} chars"
            )

    # Summary by backend
    print("\n=== Summary (means across files) ===")
    by_backend: dict[str, list[dict]] = {}
    for r in results:
        if "error" in r:
            continue
        by_backend.setdefault(r["backend"], []).append(r)
    print(f"{'backend':16s}  h_recall  p_recall  avg_ms")
    rows = []
    for b, rs in by_backend.items():
        h = sum(r["heading_recall"] for r in rs) / len(rs)
        p = sum(r["phrase_recall"] for r in rs) / len(rs)
        ms = sum(r["time_ms"] for r in rs) / len(rs)
        rows.append((b, h, p, ms))
        print(f"{b:16s}  {h:8.2f}  {p:8.2f}  {ms:6.0f}")

    if args.json:
        print(json.dumps({"results": results, "summary": rows}, indent=2))


if __name__ == "__main__":
    main()
