"""LiteParse adapter for OfficeDocBench.

Requires: uv pip install liteparse
Requires: Node.js 18+ installed

LiteParse is LlamaIndex's open-source local document parser. It converts
documents to spatial text via PDF.js (with optional LibreOffice for Office
formats). No API key or cloud dependency needed.

Output is flat text — no structural features like track changes, comments,
headers/footers, or metadata are extracted. This makes it a useful free/local
baseline for measuring structural extraction gaps.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter
from .structure import markdown_output


class LiteParseAdapter(OfficeDocBenchAdapter):

    def name(self) -> str:
        return "LiteParse"

    def version(self) -> str:
        try:
            from importlib.metadata import version as pkg_version
            return pkg_version("liteparse")
        except Exception:
            return "unknown"

    def parse(self, filepath: Path) -> dict[str, Any]:
        try:
            from liteparse import LiteParse
        except ImportError:
            raise RuntimeError("liteparse not installed: uv pip install liteparse")

        parser = LiteParse(extract_structure_tree=True, extract_links=True, extract_annotations=True)
        result = parser.parse(str(filepath))
        text = result.text or ""

        output = markdown_output(text)
        for page in result.pages:
            for annotation in page.annotations or []:
                if annotation.uri:
                    output["hyperlinks"].append({"url": annotation.uri, "text": annotation.contents or ""})
            for block in getattr(page, "blocks", None) or []:
                # Only explicit structured blocks, never font-size guesses.
                if getattr(block, "type", "") == "table" and getattr(block, "rows", None):
                    from .structure import table_cells
                    rows = [[getattr(c, "text", str(c)) for c in row] for row in block.rows]
                    output["structure"]["table_cells"] += table_cells(rows, len(output["tables"]))
                    output["tables"].append({"rows": rows, "row_count": len(rows), "cell_text": " ".join(x for row in rows for x in row), "has_merged_cells": False})
        return output

    def _flush_table(self, rows: list[str]) -> dict[str, Any]:
        """Convert accumulated table rows into adapter schema."""
        cell_texts = []
        for row in rows:
            cells = [c.strip() for c in row.split("|") if c.strip()]
            cell_texts.extend(cells)
        return {
            "row_count": len(rows),
            "has_merged_cells": False,
            "cell_text": " ".join(cell_texts),
        }

    def supported_formats(self) -> set[str]:
        return {"docx", "pptx", "xlsx", "odt", "odp", "ods", "csv", "tsv"}
