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

        text_elements = []
        headings = []
        tables = []
        images = []
        lists_out = []

        # Parse markdown line by line
        lines = text.split("\n")
        table_rows: list[str] = []
        in_table = False

        for line in lines:
            stripped = line.strip()

            if not stripped:
                # Flush any accumulated table
                if in_table and table_rows:
                    tables.append(self._flush_table(table_rows))
                    table_rows = []
                    in_table = False
                continue

            # Table row: starts and contains |
            if stripped.startswith("|") and "|" in stripped[1:]:
                # Skip separator rows (|---|---|)
                cells = [c.strip() for c in stripped.split("|") if c.strip()]
                if cells and all(set(c) <= {"-", ":", " "} for c in cells):
                    in_table = True
                    continue
                in_table = True
                table_rows.append(stripped)
                continue

            # Flush table if we were in one
            if in_table and table_rows:
                tables.append(self._flush_table(table_rows))
                table_rows = []
                in_table = False

            # Heading
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                heading_text = stripped.lstrip("# ").strip()
                if heading_text:
                    headings.append({"text": heading_text, "level": min(level, 6)})
                continue

            # Image
            img_match = re.match(r"!\[([^\]]*)\]\(([^)]*)\)", stripped)
            if img_match:
                images.append({"description": img_match.group(1) or img_match.group(2)})
                continue

            # Ordered list
            if re.match(r"^\d+\.\s+", stripped):
                item_text = re.sub(r"^\d+\.\s+", "", stripped)
                lists_out.append({"items": [item_text], "ordered": True})
                continue

            # Unordered list
            if re.match(r"^[-*+]\s+", stripped):
                item_text = re.sub(r"^[-*+]\s+", "", stripped)
                lists_out.append({"items": [item_text], "ordered": False})
                continue

            # Regular text
            text_elements.append({"text": stripped, "style": "paragraph"})

        # Flush trailing table
        if in_table and table_rows:
            tables.append(self._flush_table(table_rows))

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": [],
            "comments": [],
            "headers_footers": [],
            "footnotes": [],
            "speaker_notes": [],
            "text_boxes": [],
            "images": images,
            "lists": lists_out,
            "metadata": {},
        }

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
