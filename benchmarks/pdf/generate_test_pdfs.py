"""Generate test PDF files with known content for benchmarking.

Creates PDFs with deterministic content so we can verify AI extraction accuracy.
Each PDF has a corresponding ground truth JSON file.

Usage:
    uv run benchmarks/pdf/generate_test_pdfs.py
"""

from __future__ import annotations

import json
from pathlib import Path

from fpdf import FPDF


OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "test_files"
GOLDEN_DIR = Path(__file__).parent / "golden"


def generate_simple_text() -> None:
    """PDF with headings and paragraphs."""
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 12, "Document Analysis Report", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Introduction", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6,
        "This document contains structured content for testing PDF extraction. "
        "It includes headings, paragraphs, and formatted text that should be "
        "accurately captured by any document parser."
    )
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Key Findings", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6,
        "The analysis revealed three important trends. First, deterministic "
        "parsing outperforms AI-based extraction for structured Office formats. "
        "Second, AI excels at handling scanned documents and complex layouts. "
        "Third, hybrid approaches combine the best of both worlds."
    )
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Conclusion", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6,
        "Document parsing requires different strategies for different formats. "
        "A unified API that delegates to the right backend is the optimal approach."
    )

    pdf.output(str(OUTPUT_DIR / "simple_text.pdf"))

    golden = {
        "ground_truth": {
            "headings": [
                "Document Analysis Report",
                "Introduction",
                "Key Findings",
                "Conclusion",
            ],
            "paragraph_count": 3,
            "key_phrases": [
                "structured content",
                "deterministic parsing",
                "AI-based extraction",
                "hybrid approaches",
                "unified API",
            ],
            "total_words_approx": 95,
        }
    }
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    (GOLDEN_DIR / "simple_text.pdf.json").write_text(json.dumps(golden, indent=2))


def generate_table_pdf() -> None:
    """PDF with a data table."""
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Quarterly Sales Report", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6, "The following table summarizes sales by region for Q1 2026.")
    pdf.ln(4)

    # Table header
    col_widths = [50, 35, 35, 35, 35]
    headers = ["Region", "Jan", "Feb", "Mar", "Total"]
    rows = [
        ["North America", "45000", "52000", "48000", "145000"],
        ["Europe", "38000", "41000", "39000", "118000"],
        ["Asia Pacific", "29000", "33000", "35000", "97000"],
        ["Latin America", "12000", "14000", "15000", "41000"],
    ]

    pdf.set_font("Helvetica", "B", 11)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 11)
    for row in rows:
        for i, cell in enumerate(row):
            pdf.cell(col_widths[i], 8, cell, border=1, align="C")
        pdf.ln()

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6, "Total global sales for Q1 2026: $401,000.")

    pdf.output(str(OUTPUT_DIR / "table_report.pdf"))

    golden = {
        "ground_truth": {
            "headings": ["Quarterly Sales Report"],
            "tables": [
                {
                    "headers": headers,
                    "row_count": 4,
                    "sample_cells": ["North America", "45000", "145000", "Latin America", "41000"],
                }
            ],
            "key_phrases": [
                "quarterly sales",
                "Q1 2026",
                "401,000",
                "North America",
                "Asia Pacific",
            ],
        }
    }
    (GOLDEN_DIR / "table_report.pdf.json").write_text(json.dumps(golden, indent=2))


def generate_multipage() -> None:
    """Multi-page PDF with sections."""
    pdf = FPDF()

    # Page 1
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 12, "Technical Specification", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "1. Overview", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6,
        "This specification describes the DocParse document extraction system. "
        "DocParse supports Office formats natively and delegates PDF and image "
        "processing to pluggable AI backends."
    )
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "2. Architecture", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6,
        "The system uses a Block ADT with nine variants: Text, Heading, Table, "
        "Image, Audio, Video, List, Section, and Change. Each document is parsed "
        "into a flat list of blocks with metadata."
    )

    # Page 2
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "3. Supported Formats", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6,
        "Office formats (DOCX, PPTX, XLSX) are parsed deterministically via "
        "ZIP extraction and XML analysis. PDF files use AI vision models. "
        "Images use multimodal AI for description and OCR."
    )
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "4. Performance", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6,
        "Office parsing completes in under 5 seconds per file with no API calls. "
        "PDF parsing time depends on the AI backend and document complexity. "
        "Typical PDF extraction takes 2-10 seconds per page."
    )

    pdf.output(str(OUTPUT_DIR / "multipage_spec.pdf"))

    golden = {
        "ground_truth": {
            "headings": [
                "Technical Specification",
                "1. Overview",
                "2. Architecture",
                "3. Supported Formats",
                "4. Performance",
            ],
            "page_count": 2,
            "paragraph_count": 4,
            "key_phrases": [
                "Block ADT",
                "nine variants",
                "ZIP extraction",
                "XML analysis",
                "AI vision models",
                "multimodal AI",
                "5 seconds",
            ],
        }
    }
    (GOLDEN_DIR / "multipage_spec.pdf.json").write_text(json.dumps(golden, indent=2))


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    generate_simple_text()
    generate_table_pdf()
    generate_multipage()

    print(f"Generated 3 test PDFs in {OUTPUT_DIR}/")
    print(f"Generated 3 golden files in {GOLDEN_DIR}/")
