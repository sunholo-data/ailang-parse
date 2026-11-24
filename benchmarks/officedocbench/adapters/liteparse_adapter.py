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

    # Pinned so the score does not depend on the machine: once
    # `lit models pull ocria-nano` has run, LiteParse >= 2.21 makes that model
    # its default backend, and its table/layout model then runs on every page.
    # The OCRia-nano-1 run is its own adapter (liteparse_ocria_adapter.py).
    OCR_BACKEND = "tesseract"

    def provider_config(self) -> dict[str, Any]:
        return {"ocr_backend": self.OCR_BACKEND}

    def parse(self, filepath: Path) -> dict[str, Any]:
        try:
            from liteparse import LiteParse
        except ImportError:
            raise RuntimeError("liteparse not installed: uv pip install liteparse")

        parser = LiteParse(
            extract_structure_tree=True,
            extract_links=True,
            extract_annotations=True,
            extract_blocks=True,
            extract_images=True,
            extract_text_metadata=True,
            output_format="markdown",
            ocr_backend=self.OCR_BACKEND,
        )
        return self.convert_result(parser.parse(str(filepath)), filepath)

    def convert_result(self, result, filepath):
        from .structure import table_cells

        text = "\n\n".join(getattr(p, "markdown", "") or p.text for p in result.pages)
        output = markdown_output(text)
        blocks = [
            b for page in result.pages for b in (getattr(page, "blocks", None) or [])
        ]
        if blocks:
            output.update(text_elements=[], headings=[], tables=[], lists=[])
            output["structure"].update(element_order=[], table_cells=[], list_items=[])
            for block in blocks:
                kind = block.kind
                value = block.text or ""
                if kind == "heading":
                    output["headings"].append(
                        {"text": value, "level": block.level or 1}
                    )
                    output["structure"]["element_order"].append(
                        {"type": "heading", "text": value}
                    )
                elif kind in ("table", "merged_table"):
                    # merged_table: LayoutNet's table (ocria-nano backend), whose
                    # cells carry colspan/rowspan in the HTML rendering.
                    rows = (
                        [[c.text for c in block.header]] if block.header else []
                    ) + [[c.text for c in row] for row in block.rows or []]
                    output["structure"]["table_cells"] += table_cells(
                        rows, len(output["tables"])
                    )
                    output["structure"]["element_order"].append({"type": "table"})
                    output["tables"].append(
                        {
                            "rows": rows,
                            "row_count": len(block.rows or []),
                            "cell_text": " ".join(x for row in rows for x in row),
                            "has_merged_cells": kind == "merged_table",
                        }
                    )
                elif kind == "list_item":
                    output["lists"].append(
                        {"items": [value], "ordered": bool(block.ordered)}
                    )
                    output["structure"]["list_items"].append(
                        {
                            "text": value,
                            "ordered": bool(block.ordered),
                            "level": block.level or 0,
                        }
                    )
                elif kind in ("page_header", "page_footer"):
                    # LayoutNet page furniture (ocria-nano backend): score it as
                    # headers/footers, as the Docling and Reducto adapters do.
                    if value:
                        output.setdefault("headers_footers", []).append(
                            {"type": kind.removeprefix("page_"), "text": value}
                        )
                    continue
                elif value:
                    output["text_elements"].append({"text": value, "style": kind})
                    output["structure"]["element_order"].append(
                        {"type": "text", "text": value}
                    )
                if value:
                    output["structure"]["runs"].append(
                        {
                            "text": value,
                            "bold": bool(block.bold),
                            "italic": bool(block.italic),
                        }
                    )
        output["images"] = [
            {"description": str(getattr(image, "id", ""))}
            for image in getattr(result, "images", [])
        ]
        for page in result.pages:
            for annotation in getattr(page, "annotations", None) or []:
                if annotation.uri:
                    output["hyperlinks"].append(
                        {"url": annotation.uri, "text": annotation.contents or ""}
                    )
            for item in getattr(page, "text_items", []) or []:
                weight = getattr(item, "font_weight", None)
                if weight is not None:
                    output["structure"]["runs"].append(
                        {"text": item.text, "bold": weight >= 600}
                    )
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
