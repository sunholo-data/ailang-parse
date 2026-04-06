#!/usr/bin/env python3
"""Enrich OfficeDocBench ground truth files from AILANG Parse golden outputs.

Auto-generates element_order fields by reading the golden JSON outputs
(which preserve document block ordering) and writing simplified element
sequences into the GT files.

Usage:
    uv run benchmarks/officedocbench/enrich_gt.py              # enrich all
    uv run benchmarks/officedocbench/enrich_gt.py --dry-run     # preview changes
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
GT_DIR = SCRIPT_DIR / "ground_truth"
GOLDEN_DIR = SCRIPT_DIR.parent / "office" / "golden"


def extract_element_order(golden: dict) -> list[dict]:
    """Extract an ordered element sequence from a golden output."""
    blocks = golden.get("document", {}).get("blocks", [])
    order = []
    _walk_blocks(blocks, order)
    return order


def _walk_blocks(blocks: list[dict], order: list[dict]) -> None:
    """Recursively walk golden blocks and build element order."""
    for b in blocks:
        btype = b.get("type", "")
        text = b.get("text", "")

        if btype == "heading":
            order.append({
                "type": "heading",
                "text": text[:60].strip(),
                "level": b.get("level", 1),
            })
        elif btype == "text":
            if text.strip():
                order.append({
                    "type": "text",
                    "text": text[:60].strip(),
                })
        elif btype == "table":
            # Summarize table by first header or first cell
            headers = b.get("headers", [])
            preview = " ".join(str(h) for h in headers[:3]) if headers else ""
            if not preview:
                rows = b.get("rows", [])
                if rows and isinstance(rows[0], list):
                    preview = " ".join(str(c) for c in rows[0][:3])
            order.append({
                "type": "table",
                "text": preview[:60].strip(),
            })
        elif btype == "list":
            items = b.get("items", [])
            preview = items[0] if items else ""
            order.append({
                "type": "list",
                "text": str(preview)[:60].strip(),
                "ordered": b.get("ordered", False),
            })
        elif btype == "image":
            order.append({
                "type": "image",
                "text": b.get("description", "")[:60].strip(),
            })
        elif btype == "change":
            order.append({
                "type": "change",
                "text": text[:60].strip(),
            })
        elif btype == "section":
            kind = b.get("kind", "")
            sub_blocks = b.get("blocks", [])
            if kind in ("header", "footer", "comment", "textbox", "notes"):
                # Record the section marker, then recurse
                order.append({
                    "type": kind,
                    "text": "",
                })
                _walk_blocks(sub_blocks, order)
            else:
                _walk_blocks(sub_blocks, order)


def extract_list_details(golden: dict) -> dict | None:
    """Extract list ordering and nesting details from golden output."""
    blocks = golden.get("document", {}).get("blocks", [])
    ordered_count = 0
    unordered_count = 0
    max_depth = 0
    total_lists = 0

    def _scan_lists(blocks: list[dict], depth: int = 1) -> None:
        nonlocal ordered_count, unordered_count, max_depth, total_lists
        for b in blocks:
            if b.get("type") == "list":
                total_lists += 1
                if b.get("ordered", False):
                    ordered_count += 1
                else:
                    unordered_count += 1
                max_depth = max(max_depth, depth)
            elif b.get("type") == "section":
                _scan_lists(b.get("blocks", []), depth)

    _scan_lists(blocks)
    if total_lists == 0:
        return None
    return {
        "ordered_count": ordered_count,
        "unordered_count": unordered_count,
        "max_depth": max_depth,
        "has_nested": max_depth > 1,
    }


def extract_section_breaks(golden: dict) -> dict | None:
    """Count section breaks in golden output."""
    blocks = golden.get("document", {}).get("blocks", [])
    count = 0
    for b in blocks:
        if b.get("type") == "section" and b.get("kind") == "section-break":
            count += 1
    if count == 0:
        return None
    return {"present": True, "count": count, "types": ["section_break"] * count}


def enrich_file(gt_path: Path, golden_path: Path, dry_run: bool = False) -> bool:
    """Enrich a single GT file with element_order and feature details from golden output.

    Returns True if the GT file was modified.
    """
    with open(gt_path) as f:
        gt = json.load(f)

    with open(golden_path) as f:
        golden = json.load(f)

    modified = False

    # Element order enrichment
    order = extract_element_order(golden)
    if order:
        existing = gt.get("element_order", [])
        if not existing or len(existing) < len(order):
            gt["element_order"] = order
            modified = True

    # List details enrichment
    list_details = extract_list_details(golden)
    features = gt.get("features", {})
    if list_details and isinstance(features.get("lists"), dict):
        gt_lists = features["lists"]
        if gt_lists.get("present") and gt_lists.get("ordered_count") is None:
            gt_lists.update(list_details)
            modified = True

    # Section breaks enrichment
    section_breaks = extract_section_breaks(golden)
    if section_breaks and features.get("section_breaks") is None:
        features["section_breaks"] = section_breaks
        modified = True

    if modified and not dry_run:
        with open(gt_path, "w") as f:
            json.dump(gt, f, indent=2)
            f.write("\n")

    return modified


def main():
    parser = argparse.ArgumentParser(description="Enrich GT with golden output data")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    enriched = 0
    skipped = 0

    for gt_path in sorted(GT_DIR.glob("*.json")):
        golden_path = GOLDEN_DIR / gt_path.name
        if not golden_path.exists():
            skipped += 1
            continue

        modified = enrich_file(gt_path, golden_path, dry_run=args.dry_run)
        if modified:
            enriched += 1
            prefix = "[DRY] " if args.dry_run else ""
            print(f"  {prefix}Enriched {gt_path.name}")

    print(f"\n{'Would enrich' if args.dry_run else 'Enriched'}: {enriched} files")
    print(f"Skipped (no golden): {skipped} files")


if __name__ == "__main__":
    main()
