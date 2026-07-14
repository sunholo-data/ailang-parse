"""DocParse Gap Analysis — measures known parser limitations.

Unlike eval_office.py (regression tests against golden outputs), this script
explicitly tests features we know we're MISSING and reports coverage gaps.

Each check produces a score from 0.0 (complete gap) to 1.0 (fully handled).
This gives us an honest measure of spec coverage to improve against.

Usage:
    uv run benchmarks/office/eval_gaps.py              # full gap report
    uv run benchmarks/office/eval_gaps.py --json        # JSON output
    uv run benchmarks/office/eval_gaps.py --verbose     # detailed per-check output
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

REPO_DIR = Path(__file__).parent.parent.parent
CHALLENGE_DIR = REPO_DIR / "data" / "test_files" / "challenge"
OUTPUT_DIR = REPO_DIR / "docparse" / "data"


def parse_file(filepath: Path) -> dict | None:
    """Run DocParse on a file and return the JSON output."""
    result = subprocess.run(
        ["ailang", "run", "--entry", "main", "--caps", "IO,FS,Env",
         "--max-recursion-depth", "50000",
         "docparse/main.ail", str(filepath)],
        capture_output=True, text=True, cwd=str(REPO_DIR),
        timeout=120,
    )
    if result.returncode != 0:
        return None

    output_json = OUTPUT_DIR / f"{filepath.name}.json"
    if not output_json.exists():
        return None

    with open(output_json) as f:
        return json.load(f)


def get_blocks(output: dict) -> list[dict]:
    """Extract blocks from DocParse output."""
    return output.get("document", {}).get("blocks", [])


def flatten_blocks(blocks: list[dict]) -> list[dict]:
    """Recursively flatten section blocks."""
    result = []
    for b in blocks:
        if b.get("type") == "section":
            result.extend(flatten_blocks(b.get("blocks", [])))
        else:
            result.append(b)
    return result


# --- Gap checks ---

def check_custom_heading_styles(output: dict) -> dict:
    """Does the parser detect custom heading styles?

    File: challenge_styles.docx
    Expected: ChapterTitle→h1, SectionHeader→h2, Subsection→h3, Title→h1, Subtitle→h2
    Gap: Only hardcoded "Heading1"-"Heading6" recognized.
    Spec: §17.7 (Styles)
    """
    blocks = flatten_blocks(get_blocks(output))

    expected_headings = {
        "Annual Report 2025": 1,          # ChapterTitle (based on Heading 1)
        "Financial Overview": 2,           # SectionHeader (based on Heading 2)
        "Revenue Breakdown": 3,            # Subsection (based on Heading 3)
        "Operational Highlights": 2,       # SectionHeader
        "Engineering": 3,                  # Subsection
        "Appendix: Supplementary Data": 1, # Title style
        "Detailed financial tables": 2,    # Subtitle style
    }

    detected = 0
    total = len(expected_headings)

    for text, expected_level in expected_headings.items():
        for b in blocks:
            if b.get("text", "").strip() == text:
                if b.get("type") == "heading":
                    detected += 1
                break

    return {
        "name": "Custom Heading Styles",
        "spec_ref": "§17.7",
        "file": "challenge_styles.docx",
        "score": detected / total if total else 0,
        "detected": detected,
        "total": total,
        "detail": f"{detected}/{total} custom styles detected as headings",
    }


def check_list_detection(output: dict) -> dict:
    """Does the parser detect list-style paragraphs as ListBlocks?

    File: challenge_numbering.docx
    Expected: ListNumber/ListBullet styles → ListBlock with correct type and level.
    Gap: Paragraphs with list styles appear as TextBlock, not ListBlock.
    Spec: §17.9 (Numbering)
    """
    blocks = flatten_blocks(get_blocks(output))

    # Expected list item texts from the challenge file (23 items)
    expected_texts = [
        "Introduction", "Background", "Objectives", "Primary objective",
        "Secondary objective", "Methodology", "Data collection", "Survey design",
        "Sample size calculation", "Recruitment strategy", "Analysis approach",
        "Results", "Discussion", "Limitations", "Future work",
        "Must have features", "User authentication", "Data export",
        "CSV format", "JSON format", "Nice to have features",
        "Dark mode", "Keyboard shortcuts",
    ]

    # Collect all text from ListBlocks
    list_item_texts = []
    for b in blocks:
        if b.get("type") == "list":
            list_item_texts.extend(b.get("items", []))

    # Count expected texts found in list items
    found = sum(1 for text in expected_texts if any(text in item for item in list_item_texts))
    total = len(expected_texts)

    return {
        "name": "List Style Detection",
        "spec_ref": "§17.9",
        "file": "challenge_numbering.docx",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} list-style paragraphs detected as ListBlock",
    }


def check_run_formatting(output: dict) -> dict:
    """Does the parser preserve bold/italic/underline formatting?

    File: challenge_formatting.docx
    Expected: Formatting annotations on runs (bold gene names, italic book titles).
    Gap: All w:rPr content stripped.
    Spec: §17.3.2 (Run Properties)
    """
    blocks = flatten_blocks(get_blocks(output))

    # Check if any block has formatting metadata or markdown markers
    has_formatting = False
    for b in blocks:
        text = b.get("text", "")
        if b.get("formatting") or b.get("runs") or "**" in text:
            has_formatting = True
            break

    # The text should at least be there
    all_text = " ".join(b.get("text", "") for b in blocks)
    has_brca1 = "BRCA1" in all_text
    has_books = "Emperor of All Maladies" in all_text
    text_preserved = has_brca1 and has_books

    return {
        "name": "Run Formatting (bold/italic)",
        "spec_ref": "§17.3.2",
        "file": "challenge_formatting.docx",
        "score": 0.5 if text_preserved and not has_formatting else (1.0 if has_formatting else 0.0),
        "text_preserved": text_preserved,
        "formatting_preserved": has_formatting,
        "detail": f"Text: {'yes' if text_preserved else 'no'}, Formatting: {'yes' if has_formatting else 'no'}",
    }


def check_field_text(output: dict) -> dict:
    """Does the parser extract display text from field codes?

    File: challenge_fields.docx
    Expected: Field result text visible (date, page count, filename).
    Gap: w:fldSimple content completely invisible.
    Spec: §17.16 (Fields and Hyperlinks)
    """
    blocks = flatten_blocks(get_blocks(output))
    all_text = " ".join(b.get("text", "") for b in blocks)

    field_texts = {
        "March 28, 2026": "DATE field",
        "3": "NUMPAGES field",
        "challenge_fields.docx": "FILENAME field",
    }

    detected = 0
    total = len(field_texts)
    details = []

    for text, field_name in field_texts.items():
        if text in all_text:
            detected += 1
            details.append(f"  {field_name}: found")
        else:
            details.append(f"  {field_name}: MISSING")

    return {
        "name": "Field Code Display Text",
        "spec_ref": "§17.16",
        "file": "challenge_fields.docx",
        "score": detected / total if total else 0,
        "detected": detected,
        "total": total,
        "detail": f"{detected}/{total} field values extracted",
        "details": details,
    }


def check_hyperlink_urls(output: dict) -> dict:
    """Does the parser preserve hyperlink URL targets?

    File: challenge_hyperlinks.docx
    Expected: Both link text and URL preserved.
    Gap: w:hyperlink text extracted but r:id → URL not resolved.
    Spec: §17.16.22
    """
    blocks = flatten_blocks(get_blocks(output))
    all_text = " ".join(b.get("text", "") for b in blocks)

    # Check for link text (should be there)
    link_texts = ["Sunholo Homepage", "DocParse Docs", "GitHub Issues", "ECMA-376 Standard"]
    texts_found = sum(1 for t in link_texts if t in all_text)

    # Check for URLs in any form (text, metadata, links field)
    urls = ["sunholo.com", "github.com", "ecma-international.org"]
    urls_found = 0
    full_output = json.dumps(output)
    for url in urls:
        if url in full_output:
            urls_found += 1

    return {
        "name": "Hyperlink URL Targets",
        "spec_ref": "§17.16.22",
        "file": "challenge_hyperlinks.docx",
        "score": urls_found / len(urls) if urls else 0,
        "texts_found": f"{texts_found}/{len(link_texts)}",
        "urls_found": f"{urls_found}/{len(urls)}",
        "detail": f"Link text: {texts_found}/{len(link_texts)}, URLs: {urls_found}/{len(urls)}",
    }


def check_equation_text(output: dict) -> dict:
    """Does the parser extract text from Office Math equations?

    File: challenge_equations.docx
    Expected: At least the text content of m:oMath elements.
    Gap: m:oMath content completely lost.
    Spec: §22.1 (Math)
    """
    blocks = flatten_blocks(get_blocks(output))
    all_text = " ".join(b.get("text", "") for b in blocks)

    # Four equations, each testing a distinct OMML construct rendered as linear
    # math. Fragment presence alone is not enough — the STRUCTURE must render
    # (superscript ^(), fraction (num)/(den), subscript _()), which is what the
    # answer-key use case depends on.
    detected = 0
    total = 4

    # 1. Superscript (m:sSup): E = mc²  ->  E=mc^(2)
    if "mc^(2)" in all_text:
        detected += 1
    # 2. Pre-flattened display equation (m:oMathPara): quadratic formula
    if "(-b" in all_text and "2a" in all_text:
        detected += 1
    # 3. Fraction (m:f/m:num/m:den): U = (168 W)/(1,40 A)
    if "(168 W)/(1,40 A)" in all_text:
        detected += 1
    # 4. Subscript (m:sSub/m:e/m:sub): E_kin  ->  E_(kin)
    if "E_(kin)" in all_text:
        detected += 1

    return {
        "name": "Equation Text Extraction",
        "spec_ref": "§22.1",
        "file": "challenge_equations.docx",
        "score": detected / total if total else 0,
        "detected": detected,
        "total": total,
        "detail": f"{detected}/{total} equations rendered as linear math",
    }


def check_xlsx_merged_cells(output: dict) -> dict:
    """Does the parser handle XLSX merged cell regions?

    File: challenge_merged_cells.xlsx
    Expected: Correct column count, merged cell metadata.
    Gap: <mergeCells> element not parsed.
    Spec: §18.3.1.55
    """
    blocks = flatten_blocks(get_blocks(output))
    tables = [b for b in blocks if b.get("type") == "table"]

    if not tables:
        return {
            "name": "XLSX Merged Cells",
            "spec_ref": "§18.3.1.55",
            "file": "challenge_merged_cells.xlsx",
            "score": 0,
            "detail": "No tables found",
        }

    # First table (Sales Report) should have 4 columns
    first_table = tables[0]
    headers = first_table.get("headers", [])
    rows = first_table.get("rows", [])

    # Check column count
    expected_cols = 4
    actual_cols = len(headers) if headers else (len(rows[0]) if rows else 0)
    col_correct = actual_cols == expected_cols

    # Check for merge metadata
    has_merges = False
    all_cells = headers + [cell for row in rows for cell in (row if isinstance(row, list) else [])]
    for cell in all_cells:
        if isinstance(cell, dict):
            if cell.get("colSpan", 1) > 1 or cell.get("rowSpan", 1) > 1 or cell.get("merged", False):
                has_merges = True
                break

    score = 0.0
    if col_correct:
        score += 0.5
    if has_merges:
        score += 0.5

    return {
        "name": "XLSX Merged Cells",
        "spec_ref": "§18.3.1.55",
        "file": "challenge_merged_cells.xlsx",
        "score": score,
        "expected_cols": expected_cols,
        "actual_cols": actual_cols,
        "col_correct": col_correct,
        "has_merge_info": has_merges,
        "detail": f"Cols: {actual_cols}/{expected_cols}, Merges: {'yes' if has_merges else 'no'}",
    }


# --- Round 2 gap checks ---

def check_pptx_speaker_notes(output: dict) -> dict:
    """Does the parser extract speaker notes from PPTX?

    File: challenge_speaker_notes.pptx
    Expected: Notes text included in output alongside slide content.
    Gap: ppt/notesSlides/ never read.
    Spec: §19.3 (Notes Slide)
    """
    blocks = flatten_blocks(get_blocks(output))
    all_text = " ".join(b.get("text", "") for b in blocks)
    full_output = json.dumps(output)

    # The challenge file has notes on 2 slides
    expected_notes = [
        "greet the audience warmly",
        "Spend 5 minutes on this slide",
    ]

    found = sum(1 for note in expected_notes if note in full_output)
    total = len(expected_notes)

    return {
        "name": "PPTX Speaker Notes",
        "spec_ref": "§19.3",
        "file": "challenge_speaker_notes.pptx",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} speaker notes extracted",
    }


def check_xlsx_hyperlinks(output: dict) -> dict:
    """Does the parser extract hyperlink URLs from XLSX?

    File: challenge_hyperlinks.xlsx
    Expected: Cell text + hyperlink URLs preserved.
    Gap: <hyperlinks> element and sheet rels not read.
    Spec: §18.3 (Hyperlinks)
    """
    full_output = json.dumps(output)

    urls = ["google.com", "github.com", "sunholo.com"]
    urls_found = sum(1 for url in urls if url in full_output)
    total = len(urls)

    return {
        "name": "XLSX Hyperlinks",
        "spec_ref": "§18.3",
        "file": "challenge_hyperlinks.xlsx",
        "score": urls_found / total if total else 0,
        "detected": urls_found,
        "total": total,
        "detail": f"{urls_found}/{total} hyperlink URLs extracted",
    }


def check_xlsx_number_formats(output: dict) -> dict:
    """Does the parser format numbers (dates, percentages, currency)?

    File: challenge_number_formats.xlsx
    Expected: Dates as yyyy-mm-dd, percentages as N%, currency with $.
    Gap: Raw numeric values only (dates as serial numbers).
    Spec: §18.8.30 (Number Formats)
    """
    blocks = flatten_blocks(get_blocks(output))
    full_output = json.dumps(output)

    checks = {
        "2026-03-15": "Date formatting",
        "85.6%": "Percentage formatting",
        "$1,234.56": "Currency formatting",
    }

    # Also check that raw serial numbers are NOT present
    raw_serial = "46096" in full_output  # serial for 2026-03-15

    found = sum(1 for text in checks if text in full_output)
    total = len(checks)

    return {
        "name": "XLSX Number Formats",
        "spec_ref": "§18.8.30",
        "file": "challenge_number_formats.xlsx",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "has_raw_serial": raw_serial,
        "detail": f"{found}/{total} formatted values (raw serial: {'yes' if raw_serial else 'no'})",
    }


def check_xlsx_comments(output: dict) -> dict:
    """Does the parser extract cell comments/notes?

    File: challenge_comments.xlsx
    Expected: Comment text and author preserved.
    Gap: xl/comments*.xml never read.
    Spec: §18.7 (Comments)
    """
    full_output = json.dumps(output)

    expected = [
        "Q1 revenue",
        "Exceeds target",
        "Under budget",
    ]

    found = sum(1 for text in expected if text in full_output)
    total = len(expected)

    return {
        "name": "XLSX Comments",
        "spec_ref": "§18.7",
        "file": "challenge_comments.xlsx",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} cell comments extracted",
    }


def check_docx_page_breaks(output: dict) -> dict:
    """Does the parser detect page breaks and section breaks?

    File: challenge_page_breaks.docx
    Expected: Page breaks indicated in output, section breaks preserved.
    Gap: w:br type=page and w:sectPr completely ignored.
    Spec: §17.6 (Section Properties)
    """
    blocks = flatten_blocks(get_blocks(output))
    full_output = json.dumps(output)

    # Check that content from all 3 chapters is present
    chapters = ["Chapter 1", "Chapter 2", "Chapter 3"]
    chapters_found = sum(1 for ch in chapters if ch in full_output)

    # Check for page break indication in any form
    has_break_marker = any(
        "page-break" in full_output.lower()
        or "page_break" in full_output.lower()
        or "pagebreak" in full_output.lower()
        or b.get("style", "") == "page-break"
        for b in blocks
    )

    # Check for section break indication (search full JSON since flatten_blocks
    # recurses into section blocks and loses empty section-break markers)
    has_section_break = "section-break" in full_output

    score = 0.0
    if chapters_found == 3:
        score += 0.34  # Content preserved
    if has_break_marker:
        score += 0.33  # Page break detected
    if has_section_break:
        score += 0.33  # Section break detected

    return {
        "name": "DOCX Page/Section Breaks",
        "spec_ref": "§17.6",
        "file": "challenge_page_breaks.docx",
        "score": score,
        "chapters_found": chapters_found,
        "has_break_marker": has_break_marker,
        "has_section_break": has_section_break,
        "detail": f"Chapters: {chapters_found}/3, Breaks: {'yes' if has_break_marker else 'no'}, Sections: {'yes' if has_section_break else 'no'}",
    }


def check_pptx_text_formatting(output: dict) -> dict:
    """Does the parser preserve bold/italic in PPTX text?

    File: challenge_pptx_formatting.pptx
    Expected: Bold/italic markers preserved (like DOCX run formatting).
    Gap: DrawingML run properties (a:rPr) not checked.
    Spec: §21.1 (DrawingML Text)
    """
    blocks = flatten_blocks(get_blocks(output))
    all_text = " ".join(b.get("text", "") for b in blocks)
    full_output = json.dumps(output)

    # Check text content is there
    has_bold_text = "bold text" in all_text.lower()
    has_italic_text = "italic text" in all_text.lower()

    # Check for formatting markers
    has_markers = "**" in full_output or "*italic" in full_output

    score = 0.0
    if has_bold_text and has_italic_text:
        score += 0.5  # Text preserved
    if has_markers:
        score += 0.5  # Formatting preserved

    return {
        "name": "PPTX Text Formatting",
        "spec_ref": "§21.1",
        "file": "challenge_pptx_formatting.pptx",
        "score": score,
        "text_preserved": has_bold_text and has_italic_text,
        "formatting_preserved": has_markers,
        "detail": f"Text: {'yes' if has_bold_text and has_italic_text else 'no'}, Formatting: {'yes' if has_markers else 'no'}",
    }


def check_xlsx_formula_fallback(output: dict) -> dict:
    """Does the parser show formula text when cached value is missing?

    File: challenge_formula_cached.xlsx
    Expected: When <v> is empty but <f> has a formula, show the formula text.
    Gap: Cells with formulas but no cached value appear empty.
    Spec: §18.3 (Cell)
    """
    blocks = flatten_blocks(get_blocks(output))
    full_output = json.dumps(output)

    # openpyxl writes formulas without cached values.
    # A good parser should show the formula text (e.g. "=B2+C2") as fallback.
    formulas = ["=B2+C2", "=D2/2", "=B3+C3", "=B2-B3", "=SUM(B2:C2)", "=B6-B7"]
    found = sum(1 for f in formulas if f in full_output)
    total = len(formulas)

    return {
        "name": "XLSX Formula Text Fallback",
        "spec_ref": "§18.3",
        "file": "challenge_formula_cached.xlsx",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} formula texts shown as fallback",
    }


def check_docx_comment_ranges(output: dict) -> dict:
    """Does the parser associate comments with the text they annotate?

    File: challenge_comment_ranges.docx
    Expected: Comment blocks include the annotated text range alongside comment text.
    Gap: Comments show "[Author] text" but not which text they annotate.
    Spec: §17.13.1 (Comment Range)
    """
    full_output = json.dumps(output)

    # The annotated text must appear INSIDE the comment block itself,
    # not just in a separate paragraph. This tests that w:commentRangeStart/End
    # are tracked and the annotated text is included in the comment output.
    # Expected format: something like '[Author @ "annotated text"] comment text'
    # or comment block containing both pieces linked together.
    comment_with_range = [
        ("deadline is March 15", "deadline seems too tight"),
        ("budget allocation", "increase by 15%"),
        ("technical specification", "Missing API section"),
    ]

    # Find comment section blocks and check they contain annotated text
    blocks = get_blocks(output)
    comment_blocks = []
    for b in blocks:
        if b.get("type") == "section" and b.get("kind") == "comment":
            comment_blocks.append(json.dumps(b))

    found = 0
    total = len(comment_with_range)
    for annotated, comment in comment_with_range:
        # The annotated text must be in the SAME comment block as the comment text
        for cb in comment_blocks:
            if annotated in cb and comment in cb:
                found += 1
                break

    return {
        "name": "DOCX Comment Ranges",
        "spec_ref": "§17.13.1",
        "file": "challenge_comment_ranges.docx",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} comments linked to annotated text ranges",
    }


def check_docx_bookmarks(output: dict) -> dict:
    """Does the parser extract bookmark definitions?

    File: challenge_bookmarks.docx
    Expected: Bookmark names appear as structured annotations (not just in paragraph text).
    Gap: w:bookmarkStart elements silently ignored.
    Spec: §17.13.6 (Bookmarks)
    """
    blocks = get_blocks(output)

    # Bookmark names must appear as structured metadata on blocks,
    # NOT just as coincidental text in paragraphs. We check that
    # blocks containing bookmarked text have a "bookmark" or "bookmarks"
    # field, or that a bookmark section/annotation exists.
    bookmarks = ["introduction_section", "data_collection", "key_findings"]

    # Exclude the cross-reference paragraphs that mention bookmark names as plain text
    # Check for bookmark metadata in block attributes
    found = 0
    total = len(bookmarks)

    for b in blocks:
        # Check for bookmark field on the block itself
        block_bookmarks = b.get("bookmarks", [])
        if isinstance(block_bookmarks, str):
            block_bookmarks = [block_bookmarks]
        for bm in bookmarks:
            if bm in block_bookmarks:
                found += 1

    # Also check for section blocks of kind "bookmark"
    for b in blocks:
        if b.get("type") == "section" and b.get("kind") == "bookmark":
            block_str = json.dumps(b)
            for bm in bookmarks:
                if bm in block_str:
                    found += 1

    # Cap at total
    found = min(found, total)

    return {
        "name": "DOCX Bookmarks",
        "spec_ref": "§17.13.6",
        "file": "challenge_bookmarks.docx",
        "score": found / total if total else 0,
        "detected": found,
        "total": total,
        "detail": f"{found}/{total} bookmark definitions extracted as metadata",
    }


def check_title_subtitle(output: dict) -> dict:
    """Does the parser detect Title/Subtitle as headings?

    File: challenge_real_world.docx
    Expected: Title→heading, Subtitle→heading.
    Gap: Only "Heading1"-"Heading6" style names recognized.
    Spec: §17.7
    """
    blocks = flatten_blocks(get_blocks(output))

    title_texts = {
        "Quarterly Performance Review": ("Title", "heading"),
        "Engineering Division — Q1 2026": ("Subtitle", "heading"),
    }

    detected = 0
    total = len(title_texts)

    for text, (style, expected_type) in title_texts.items():
        for b in blocks:
            if b.get("text", "").strip() == text:
                if b.get("type") == expected_type:
                    detected += 1
                break

    return {
        "name": "Title/Subtitle as Headings",
        "spec_ref": "§17.7",
        "file": "challenge_real_world.docx",
        "score": detected / total if total else 0,
        "detected": detected,
        "total": total,
        "detail": f"{detected}/{total} title/subtitle styles detected as headings",
    }


# --- Main ---

def run_gap_analysis(verbose: bool = False) -> list[dict]:
    """Run all gap checks and return results."""
    # Map files to their checks
    file_checks = {
        # Round 1 (all at 100%)
        "challenge_styles.docx": [check_custom_heading_styles],
        "challenge_numbering.docx": [check_list_detection],
        "challenge_formatting.docx": [check_run_formatting],
        "challenge_fields.docx": [check_field_text],
        "challenge_hyperlinks.docx": [check_hyperlink_urls],
        "challenge_equations.docx": [check_equation_text],
        "challenge_merged_cells.xlsx": [check_xlsx_merged_cells],
        "challenge_real_world.docx": [check_title_subtitle],
        # Round 2 (new gaps)
        "challenge_speaker_notes.pptx": [check_pptx_speaker_notes],
        "challenge_hyperlinks.xlsx": [check_xlsx_hyperlinks],
        "challenge_number_formats.xlsx": [check_xlsx_number_formats],
        "challenge_comments.xlsx": [check_xlsx_comments],
        "challenge_page_breaks.docx": [check_docx_page_breaks],
        "challenge_pptx_formatting.pptx": [check_pptx_text_formatting],
        # Round 3 (new gaps)
        "challenge_formula_cached.xlsx": [check_xlsx_formula_fallback],
        "challenge_comment_ranges.docx": [check_docx_comment_ranges],
        "challenge_bookmarks.docx": [check_docx_bookmarks],
    }

    results = []

    for filename, checks in file_checks.items():
        filepath = CHALLENGE_DIR / filename
        if not filepath.exists():
            print(f"  SKIP {filename} (not found)", file=sys.stderr)
            continue

        print(f"  Parsing {filename}...", file=sys.stderr)
        output = parse_file(filepath)
        if output is None:
            print(f"  FAIL {filename} (parse error)", file=sys.stderr)
            continue

        for check_fn in checks:
            result = check_fn(output)
            results.append(result)
            if verbose:
                print(f"    {result['name']}: {result['score']:.0%} — {result['detail']}", file=sys.stderr)

    return results


def print_report(results: list[dict]) -> None:
    """Print gap analysis report."""
    print("\n# DocParse Gap Analysis — Known Parser Limitations\n")
    print("| Check | Spec | File | Score | Detail |")
    print("|-------|------|------|-------|--------|")

    total_score = 0
    total_checks = 0

    for r in results:
        total_checks += 1
        total_score += r["score"]
        score_pct = f"{r['score']:.0%}"
        score_emoji = "PASS" if r["score"] >= 0.8 else ("PARTIAL" if r["score"] > 0 else "GAP")
        print(f"| {r['name']} | {r['spec_ref']} | {r['file']} | {score_pct} ({score_emoji}) | {r['detail']} |")

    mean_score = total_score / total_checks if total_checks else 0
    print(f"\n**Gap coverage score: {mean_score:.0%}** ({total_checks} checks)\n")
    print("Checks scoring 0% represent complete gaps in parser coverage.")
    print("Improving these requires reading the corresponding ECMA-376 spec sections")
    print("and implementing the missing XML element handlers in the AILANG parsers.\n")

    # Priority list
    gaps = [r for r in results if r["score"] < 0.8]
    if gaps:
        gaps.sort(key=lambda r: r["score"])
        print("## Priority Fixes (by gap severity)\n")
        for i, r in enumerate(gaps, 1):
            print(f"{i}. **{r['name']}** ({r['spec_ref']}) — {r['score']:.0%} — {r['detail']}")
        print()


def main():
    parser = argparse.ArgumentParser(description="DocParse Gap Analysis")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose per-check output")
    args = parser.parse_args()

    os.chdir(REPO_DIR)

    results = run_gap_analysis(verbose=args.verbose)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)


if __name__ == "__main__":
    main()
