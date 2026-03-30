#!/usr/bin/env python3
"""DocParse adapter for OmniDocBench evaluation.

Converts page images to markdown using DocParse's AI extraction pipeline,
producing output compatible with OmniDocBench's md2md evaluation.

Usage:
    uv run benchmarks/omnidocbench/adapter.py --ai gemini-2.5-flash
    uv run benchmarks/omnidocbench/adapter.py --ai gemini-2.5-flash --demo  # Demo subset only
    uv run benchmarks/omnidocbench/adapter.py --ai ollama:granite3.2-vision
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent
OMNIDOC_DIR = Path(__file__).parent / "OmniDocBench"
DEMO_IMAGES = OMNIDOC_DIR / "demo_data" / "omnidocbench_demo" / "images"
OUTPUT_JSON = REPO_DIR / "docparse" / "data" / "output.json"


def blocks_to_markdown(blocks: list[dict]) -> str:
    """Convert DocParse JSON blocks to OmniDocBench-compatible markdown."""
    parts = []
    for b in blocks:
        btype = b.get("type", "")

        if btype == "heading":
            level = b.get("level", 1)
            text = b.get("text", "")
            parts.append(f"{'#' * level} {text}")
            parts.append("")

        elif btype == "text":
            text = b.get("text", "")
            if text.strip():
                parts.append(text)
                parts.append("")

        elif btype == "table":
            parts.append(table_to_html(b))
            parts.append("")

        elif btype == "list":
            items = b.get("items", [])
            ordered = b.get("ordered", False)
            for i, item in enumerate(items):
                if ordered:
                    parts.append(f"{i+1}. {item}")
                else:
                    parts.append(f"- {item}")
            parts.append("")

        elif btype == "section":
            # Recurse into section blocks
            sub_blocks = b.get("blocks", [])
            if sub_blocks:
                parts.append(blocks_to_markdown(sub_blocks))

    return "\n".join(parts).strip()


def table_to_html(table: dict) -> str:
    """Convert DocParse table block to HTML table (OmniDocBench format)."""
    headers = table.get("headers", [])
    rows = table.get("rows", [])

    lines = ["<table>"]

    if headers:
        lines.append("<thead>")
        lines.append("<tr>")
        for h in headers:
            text = h.get("text", h) if isinstance(h, dict) else str(h)
            lines.append(f"  <th>{text}</th>")
        lines.append("</tr>")
        lines.append("</thead>")

    if rows:
        lines.append("<tbody>")
        for row in rows:
            lines.append("<tr>")
            cells = row if isinstance(row, list) else [row]
            for cell in cells:
                text = cell.get("text", cell) if isinstance(cell, dict) else str(cell)
                lines.append(f"  <td>{text}</td>")
            lines.append("</tr>")
        lines.append("</tbody>")

    lines.append("</table>")
    return "\n".join(lines)


def run_docparse(image_path: Path, ai_model: str) -> dict | None:
    """Run DocParse on an image and return parsed JSON."""
    cmd = [
        "ailang", "run", "--entry", "main",
        "--caps", "IO,FS,Env,AI",
        "--ai", ai_model,
        "docparse/main.ail", str(image_path),
    ]

    env = os.environ.copy()
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


def main():
    parser = argparse.ArgumentParser(description="DocParse OmniDocBench adapter")
    parser.add_argument("--ai", default="gemini-2.5-flash",
                        help="AI model for extraction (default: gemini-2.5-flash)")
    parser.add_argument("--demo", action="store_true",
                        help="Use demo subset only (18 images)")
    parser.add_argument("--output-dir",
                        help="Output directory for markdown files")
    parser.add_argument("--filter-lang", default=None,
                        help="Filter by language (english, chinese)")
    args = parser.parse_args()

    # Determine image source
    if args.demo:
        image_dir = DEMO_IMAGES
    else:
        # Full dataset would go here
        image_dir = DEMO_IMAGES
        print("Note: using demo subset. Full dataset not yet downloaded.")

    if not image_dir.exists():
        print(f"Image directory not found: {image_dir}")
        print("Run: git clone https://github.com/opendatalab/OmniDocBench.git benchmarks/omnidocbench/OmniDocBench")
        return

    images = sorted(image_dir.glob("*.jpg")) + sorted(image_dir.glob("*.png"))
    if not images:
        print("No images found.")
        return

    # Output directory
    output_dir = Path(args.output_dir) if args.output_dir else (
        Path(__file__).parent / "results" / args.ai.replace(":", "_").replace("/", "_")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"DocParse OmniDocBench Adapter")
    print(f"Model: {args.ai}")
    print(f"Images: {len(images)}")
    print(f"Output: {output_dir}")
    print()

    results = []
    for img_path in images:
        stem = img_path.stem  # e.g., "docstructbench_llm-raw-scihub-o.O-j.chroma.2005.05.085.pdf_4"
        md_path = output_dir / f"{stem}.md"

        print(f"  {stem}: ", end="", flush=True)

        start = time.time()
        output = run_docparse(img_path, args.ai)
        elapsed = time.time() - start

        if output is None:
            print(f"FAILED ({elapsed:.1f}s)")
            # Write empty markdown so evaluation can still run
            md_path.write_text("")
            results.append({"file": stem, "status": "failed", "time_s": round(elapsed, 1)})
            continue

        blocks = output.get("document", {}).get("blocks", [])
        markdown = blocks_to_markdown(blocks)
        md_path.write_text(markdown)

        word_count = len(markdown.split())
        block_count = len(blocks)
        print(f"OK ({elapsed:.1f}s, {block_count} blocks, {word_count} words)")

        results.append({
            "file": stem,
            "status": "ok",
            "time_s": round(elapsed, 1),
            "blocks": block_count,
            "words": word_count,
        })

    # Summary
    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "failed"]
    print()
    print(f"Done: {len(ok)}/{len(results)} succeeded, {len(failed)} failed")
    if ok:
        avg_time = sum(r["time_s"] for r in ok) / len(ok)
        print(f"Avg time: {avg_time:.1f}s per image")

    # Save results summary
    summary_path = output_dir / "adapter_results.json"
    json.dump(results, open(summary_path, "w"), indent=2)
    print(f"Results: {summary_path}")
    print(f"\nTo evaluate, run OmniDocBench with prediction path: {output_dir}")


if __name__ == "__main__":
    main()
