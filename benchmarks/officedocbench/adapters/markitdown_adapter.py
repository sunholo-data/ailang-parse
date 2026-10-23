"""Microsoft MarkItDown adapter for OfficeDocBench.

Requires: uv pip install markitdown[all]

MarkItDown converts documents to Markdown. Output is flat text — no structural
features like track changes, comments, headers/footers, or metadata are extracted.
This makes it a useful baseline for measuring structural extraction gaps.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter
from .structure import markdown_output


class MarkItDownAdapter(OfficeDocBenchAdapter):

    def name(self) -> str:
        return "MarkItDown"

    def version(self) -> str:
        try:
            from importlib.metadata import version as pkg_version
            return pkg_version("markitdown")
        except Exception:
            return "unknown"

    def parse(self, filepath: Path) -> dict[str, Any]:
        try:
            from markitdown import MarkItDown
        except ImportError:
            raise RuntimeError("markitdown not installed: uv pip install markitdown[all]")

        md = MarkItDown()
        result = md.convert(str(filepath))
        text = result.text_content or ""

        return markdown_output(text)

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
        return {"docx", "pptx", "xlsx", "html", "csv", "epub", "pdf"}
