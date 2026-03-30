#!/usr/bin/env python3
"""Auto-generate OfficeDocBench ground truth from existing golden files.

Reads each golden output in benchmarks/office/golden/*.json, extracts
structural features programmatically, and writes ground truth JSON files
to benchmarks/officedocbench/ground_truth/.

Usage:
    uv run benchmarks/officedocbench/annotate.py              # generate all
    uv run benchmarks/officedocbench/annotate.py --file X.json # single file
    uv run benchmarks/officedocbench/annotate.py --verify      # check schema
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Add metrics to path for normalize imports
sys.path.insert(0, str(Path(__file__).parent.parent / "metrics"))
from normalize import NormalizedElement, normalize_ailang

GOLDEN_DIR = Path(__file__).parent.parent / "office" / "golden"
GT_DIR = Path(__file__).parent / "ground_truth"

# Features applicable per format.
# null = not applicable, should be omitted from scoring.
FEATURE_MATRIX = {
    "docx": {"headings", "tables", "track_changes", "comments", "headers_footers",
             "footnotes_endnotes", "text_boxes", "images", "lists", "metadata"},
    "pptx": {"headings", "tables", "speaker_notes", "text_boxes", "images", "lists", "metadata"},
    "xlsx": {"tables", "images", "metadata", "sheets"},
    "odt":  {"headings", "tables", "track_changes", "headers_footers",
             "footnotes_endnotes", "text_boxes", "images", "lists", "metadata"},
    "odp":  {"headings", "tables", "speaker_notes", "text_boxes", "images", "lists", "metadata"},
    "ods":  {"tables", "images", "metadata", "sheets"},
    "epub": {"headings", "tables", "images", "lists", "metadata"},
    "html": {"headings", "tables", "images", "lists", "metadata"},
    "csv":  {"tables"},
    "tsv":  {"tables"},
    "md":   {"headings", "tables", "images", "lists"},
}

# Source attribution for known test files
SOURCES = {
    "comments.docx": "pandoc",
    "docx-hdrftr.docx": "pandoc",
    "docx-shapes.docx": "original",
    "gutenberg_alice.epub": "project gutenberg (public domain)",
    "gutenberg_moby_dick.epub": "project gutenberg (public domain)",
    "image_vml.docx": "original",
    "lo_basic_cells.ods": "libreoffice",
    "lo_image_mimetype.odt": "libreoffice",
    "lo_listformat.odt": "libreoffice",
    "lo_merged.ods": "libreoffice",
    "lo_nested_table.odt": "libreoffice",
    "lo_table_styles.odt": "libreoffice",
    "merged_cells.docx": "original",
    "nested_sdt.docx": "original",
    "officeparser.odp": "officeparser (MIT)",
    "officeparser.ods": "officeparser (MIT)",
    "officeparser.odt": "officeparser (MIT)",
    "pandoc_basic.pptx": "pandoc",
    "pandoc_basic.xlsx": "pandoc",
    "pandoc_inline_images.docx": "pandoc",
    "pandoc_nordics.html": "pandoc",
    "pandoc_notes.docx": "pandoc",
    "pandoc_planets.html": "pandoc",
    "pandoc_planets.md": "pandoc",
    "pandoc_table_list.docx": "pandoc",
    "pandoc_tc_deletion.docx": "pandoc",
    "pandoc_tc_insertion.docx": "pandoc",
    "poi_comment.pptx": "apache poi",
    "poi_footnotes.docx": "apache poi",
    "poi_many_merges.xlsx": "apache poi",
    "poi_sampleshow.pptx": "apache poi",
    "poi_table.pptx": "apache poi",
    "poi_two_sheets.xlsx": "apache poi",
    "python_pptx_slides.pptx": "python-pptx (MIT)",
    "python_pptx_table.pptx": "python-pptx (MIT)",
    "sample.docx": "original",
    "table_header_rowspan.docx": "original",
    "tables-with-incomplete-rows.docx": "original",
    "tables.docx": "original",
    "test.csv": "original",
    "test.epub": "original",
    "test.html": "original",
    "test.md": "original",
    "test.odp": "original",
    "test.ods": "original",
    "test.odt": "original",
    "test.tsv": "original",
    "test_code.md": "original",
    "test_complex.html": "original",
    "test_quoted.csv": "original",
    "track_changes_move.docx": "original",
    "unstructured_test.pptx": "unstructured (Apache-2.0)",
    "unstructured_test.xlsx": "unstructured (Apache-2.0)",
    "xlsxwriter_chart.xlsx": "xlsxwriter (BSD-2-Clause)",
}


def _tokenize(text: str) -> list[str]:
    """Extract lowercase word tokens."""
    return re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())


def _get_format(filename: str) -> str:
    """Extract format from golden filename like 'comments.docx.json'."""
    # Remove .json suffix, then get the extension
    base = filename.removesuffix(".json")
    suffix = Path(base).suffix.lstrip(".")
    return suffix


def annotate_golden(golden_path: Path) -> dict[str, Any]:
    """Generate ground truth annotation from a golden output file."""
    with open(golden_path) as f:
        golden_json = json.load(f)

    elements = normalize_ailang(golden_json)
    doc = golden_json.get("document", {})
    blocks = doc.get("blocks", [])

    # Derive filename and format
    golden_name = golden_path.name  # e.g., comments.docx.json
    source_file = golden_name.removesuffix(".json")  # e.g., comments.docx
    fmt = _get_format(golden_name)
    applicable = FEATURE_MATRIX.get(fmt, set())

    # --- Text features (always applicable) ---
    text_elements = [e for e in elements if e.type == "text"]
    all_words = []
    for el in elements:
        all_words.extend(_tokenize(el.text))

    text_feature = {
        "paragraph_count": len(text_elements),
        "total_words": len(set(all_words)),
        "key_phrases": _extract_key_phrases(elements),
    }

    # --- Headings ---
    headings_feature = None
    if "headings" in applicable:
        heading_els = [e for e in elements if e.type == "heading"]
        by_level: dict[str, int] = {}
        for h in heading_els:
            lvl = str(h.level)
            by_level[lvl] = by_level.get(lvl, 0) + 1
        headings_feature = {
            "present": len(heading_els) > 0,
            "count": len(heading_els),
            "by_level": by_level,
        }

    # --- Tables ---
    tables_feature = None
    if "tables" in applicable:
        table_els = [e for e in elements if e.type == "table"]
        total_rows = sum(e.metadata.get("row_count", 0) for e in table_els)
        has_merges = any(e.metadata.get("has_merge_info", False) for e in table_els)
        tables_feature = {
            "present": len(table_els) > 0,
            "count": len(table_els),
            "total_rows": total_rows,
            "has_merged_cells": has_merges,
        }

    # --- Track changes ---
    track_changes_feature = None
    if "track_changes" in applicable:
        change_els = [e for e in elements if e.type == "change"]
        types: dict[str, int] = {}
        authors: set[str] = set()
        for c in change_els:
            ct = c.metadata.get("change_type", "unknown")
            types[ct] = types.get(ct, 0) + 1
            author = c.metadata.get("author", "")
            if author:
                authors.add(author)
        track_changes_feature = {
            "present": len(change_els) > 0,
            "count": len(change_els),
            "types": types,
            "authors": sorted(authors),
        }

    # --- Comments ---
    comments_feature = None
    if "comments" in applicable:
        comment_els = [e for e in elements if e.metadata.get("section") == "comment"]
        authors_set: set[str] = set()
        texts: list[str] = []
        for c in comment_els:
            texts.append(c.text)
            # Extract author from "[Author] text" pattern
            m = re.match(r"\[([^\]]+)\]", c.text)
            if m:
                authors_set.add(m.group(1))
        comments_feature = {
            "present": len(comment_els) > 0,
            "count": len(comment_els),
            "authors": sorted(authors_set),
            "texts": texts,
        }

    # --- Headers/footers ---
    headers_footers_feature = None
    if "headers_footers" in applicable:
        header_els = [e for e in elements if e.type == "header"]
        footer_els = [e for e in elements if e.type == "footer"]
        headers_footers_feature = {
            "present": len(header_els) + len(footer_els) > 0,
            "header_count": len(header_els),
            "footer_count": len(footer_els),
        }

    # --- Footnotes/endnotes ---
    footnotes_feature = None
    if "footnotes_endnotes" in applicable:
        fn_els = [e for e in elements if e.metadata.get("section") in ("footnote", "endnote", "footnotes")]
        footnotes_feature = {
            "present": len(fn_els) > 0,
            "count": len(fn_els),
        }

    # --- Speaker notes ---
    speaker_notes_feature = None
    if "speaker_notes" in applicable:
        note_els = [e for e in elements if e.metadata.get("section") == "notes"]
        speaker_notes_feature = {
            "present": len(note_els) > 0,
            "count": len(note_els),
        }

    # --- Text boxes ---
    text_boxes_feature = None
    if "text_boxes" in applicable:
        tb_els = [e for e in elements if e.metadata.get("section") == "textbox"]
        text_boxes_feature = {
            "present": len(tb_els) > 0,
            "count": len(tb_els),
        }

    # --- Images ---
    images_feature = None
    if "images" in applicable:
        img_els = [e for e in elements if e.type == "image"]
        images_feature = {
            "present": len(img_els) > 0,
            "count": len(img_els),
        }

    # --- Lists ---
    lists_feature = None
    if "lists" in applicable:
        # Count list blocks from raw JSON (before normalization flattens to list_items)
        list_block_count = _count_list_blocks(blocks)
        list_item_els = [e for e in elements if e.type == "list_item"]
        lists_feature = {
            "present": len(list_item_els) > 0,
            "count": list_block_count,
        }

    # --- Metadata ---
    metadata_feature = None
    if "metadata" in applicable:
        meta = doc.get("metadata", {})
        metadata_feature = {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "created": meta.get("created", ""),
            "modified": meta.get("modified", ""),
        }

    # --- Sheets (XLSX/ODS) ---
    sheets_feature = None
    if "sheets" in applicable:
        sheet_names = _extract_sheet_names(blocks)
        sheets_feature = {
            "present": len(sheet_names) > 0,
            "names": sheet_names,
        }

    gt = {
        "file": source_file,
        "format": fmt,
        "source": SOURCES.get(source_file, "unknown"),
        "verified": False,
        "features": {
            "text": text_feature,
            "headings": headings_feature,
            "tables": tables_feature,
            "track_changes": track_changes_feature,
            "comments": comments_feature,
            "headers_footers": headers_footers_feature,
            "footnotes_endnotes": footnotes_feature,
            "speaker_notes": speaker_notes_feature,
            "text_boxes": text_boxes_feature,
            "images": images_feature,
            "lists": lists_feature,
            "metadata": metadata_feature,
            "sheets": sheets_feature,
        },
        "full_text_words": sorted(set(all_words)),
    }

    return gt


def _extract_key_phrases(elements: list[NormalizedElement]) -> list[str]:
    """Extract representative phrases from the first few text elements."""
    phrases = []
    for el in elements:
        if el.type in ("text", "heading") and len(el.text) > 5:
            # Take first 80 chars as a key phrase
            phrase = el.text[:80].strip()
            if phrase:
                phrases.append(phrase)
            if len(phrases) >= 5:
                break
    return phrases


def _count_list_blocks(blocks: list[dict]) -> int:
    """Count List blocks in raw JSON (before normalization flattens them)."""
    count = 0
    for block in blocks:
        if block.get("type") == "list":
            count += 1
        elif block.get("type") == "section":
            count += _count_list_blocks(block.get("blocks", []))
    return count


def _extract_sheet_names(blocks: list[dict]) -> list[str]:
    """Extract sheet names from XLSX/ODS section blocks."""
    names = []
    for block in blocks:
        if block.get("type") == "section":
            kind = block.get("kind", "")
            if kind.startswith("sheet:"):
                names.append(kind.removeprefix("sheet:").strip())
            # Recurse into nested sections
            names.extend(_extract_sheet_names(block.get("blocks", [])))
    return names


def main():
    parser = argparse.ArgumentParser(description="Generate OfficeDocBench ground truth")
    parser.add_argument("--file", help="Process a single golden file")
    parser.add_argument("--verify", action="store_true", help="Validate against JSON schema")
    args = parser.parse_args()

    GT_DIR.mkdir(parents=True, exist_ok=True)

    if args.file:
        golden_files = [GOLDEN_DIR / args.file]
    else:
        golden_files = sorted(GOLDEN_DIR.glob("*.json"))

    generated = 0
    for gf in golden_files:
        if not gf.exists():
            print(f"  SKIP {gf.name} (not found)", file=sys.stderr)
            continue

        gt = annotate_golden(gf)
        out_path = GT_DIR / gf.name

        # Skip hand-verified ground truth (don't overwrite manual annotations)
        if out_path.exists():
            with open(out_path) as f:
                existing = json.load(f)
            if existing.get("verified", False):
                print(f"  SKIP {gf.name} (hand-verified, use --force to overwrite)", file=sys.stderr)
                continue

        with open(out_path, "w") as f:
            json.dump(gt, f, indent=2)
        generated += 1

        fmt = gt["format"]
        features = gt["features"]
        active = sum(1 for v in features.values() if v is not None)
        present = sum(
            1 for v in features.values()
            if isinstance(v, dict) and v.get("present", False)
        )
        print(f"  {gf.name}: {fmt} ({active} features, {present} present)", file=sys.stderr)

    print(f"\nGenerated {generated} ground truth files in {GT_DIR}", file=sys.stderr)

    if args.verify:
        _verify_schema()


def _verify_schema():
    """Validate all ground truth files against the JSON schema."""
    try:
        import jsonschema
    except ImportError:
        print("jsonschema not installed, skipping validation", file=sys.stderr)
        return

    schema_path = Path(__file__).parent / "schema" / "ground_truth.schema.json"
    with open(schema_path) as f:
        schema = json.load(f)

    errors = 0
    for gt_file in sorted(GT_DIR.glob("*.json")):
        with open(gt_file) as f:
            data = json.load(f)
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            print(f"  INVALID {gt_file.name}: {e.message}", file=sys.stderr)
            errors += 1

    if errors == 0:
        print(f"  All ground truth files valid", file=sys.stderr)
    else:
        print(f"  {errors} validation errors", file=sys.stderr)


if __name__ == "__main__":
    main()
