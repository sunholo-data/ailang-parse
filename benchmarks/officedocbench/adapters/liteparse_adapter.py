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

        parser = LiteParse()
        result = parser.parse(str(filepath))
        text = result.text or ""

        text_elements: list[dict[str, Any]] = []
        headings: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []
        lists_out: list[dict[str, Any]] = []

        lines = text.split("\n")
        table_rows: list[str] = []
        in_table = False

        for line in lines:
            stripped = line.strip()

            if not stripped:
                if in_table and table_rows:
                    tables.append(self._flush_table(table_rows))
                    table_rows = []
                    in_table = False
                continue

            # Table row: starts and contains |
            if stripped.startswith("|") and "|" in stripped[1:]:
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
        return {"docx", "pptx", "xlsx", "odt", "odp", "ods", "html", "csv", "tsv", "epub", "md"}
