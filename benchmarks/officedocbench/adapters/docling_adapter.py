"""IBM Docling adapter for OfficeDocBench.

Requires: uv pip install docling
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter


class DoclingAdapter(OfficeDocBenchAdapter):

    def name(self) -> str:
        return "Docling"

    def version(self) -> str:
        try:
            from importlib.metadata import version as pkg_version
            return pkg_version("docling")
        except Exception:
            return "unknown"

    def parse(self, filepath: Path) -> dict[str, Any]:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            raise RuntimeError("docling not installed: uv pip install docling")

        converter = DocumentConverter()
        result = converter.convert(str(filepath))

        text_elements = []
        headings = []
        tables = []
        images = []
        lists_out = []
        headers_footers = []
        footnotes = []
        metadata: dict[str, Any] = {}

        try:
            doc_dict = result.document.export_to_dict()

            # Docling v2 uses 'texts' list with 'label' field, 'tables' list,
            # 'pictures' list, and 'body' with $ref children
            texts_list = doc_dict.get("texts", [])
            tables_list = doc_dict.get("tables", [])
            pictures_list = doc_dict.get("pictures", [])

            for item in texts_list:
                label = item.get("label", "text")
                text = item.get("text", item.get("orig", ""))

                if label in ("title", "section_header", "section-header"):
                    headings.append({"text": text, "level": item.get("level", 1)})
                elif label == "list_item":
                    lists_out.append({"items": [text], "ordered": False})
                elif label in ("page_header", "page-header"):
                    headers_footers.append({"type": "header", "text": text})
                elif label in ("page_footer", "page-footer"):
                    headers_footers.append({"type": "footer", "text": text})
                elif label == "footnote":
                    footnotes.append({"text": text})
                else:
                    text_elements.append({"text": text, "style": label})

            for tbl in tables_list:
                # Extract table text and detect merged cells from Docling's
                # table_cells (each cell carries row_span/col_span).
                cell_text = ""
                has_merged = False
                data = tbl.get("data", {})
                if isinstance(data, dict):
                    grid = data.get("table_cells", data.get("grid", []))
                    cell_texts = []
                    if isinstance(grid, list):
                        for cell in grid:
                            if isinstance(cell, dict):
                                cell_texts.append(cell.get("text", ""))
                                if cell.get("row_span", 1) > 1 or cell.get("col_span", 1) > 1:
                                    has_merged = True
                    cell_text = " ".join(cell_texts)
                elif isinstance(data, str):
                    cell_text = data

                if not cell_text:
                    cell_text = tbl.get("text", tbl.get("orig", ""))

                num_rows = data.get("num_rows", 0) if isinstance(data, dict) else 0
                tables.append({
                    "row_count": num_rows,
                    "has_merged_cells": has_merged,
                    "cell_text": cell_text,
                })

            # Surface whatever document-level metadata Docling exposes.
            doc_name = doc_dict.get("name") or ""
            if doc_name:
                metadata["title"] = doc_name
            origin = doc_dict.get("origin") or {}
            if isinstance(origin, dict):
                if origin.get("filename"):
                    metadata.setdefault("title", origin["filename"])
                if origin.get("mimetype"):
                    metadata["mimetype"] = origin["mimetype"]

            for pic in pictures_list:
                images.append({"description": pic.get("text", pic.get("orig", ""))})

            # If texts_list approach yielded nothing, fall back to body/main-text
            if not text_elements and not headings:
                body = doc_dict.get("main-text", [])
                if isinstance(body, list):
                    for item in body:
                        if isinstance(item, dict):
                            item_type = item.get("type", "")
                            text = item.get("text", "")
                            if item_type in ("title", "section-header"):
                                headings.append({"text": text, "level": item.get("level", 1)})
                            elif item_type == "table":
                                tables.append({"row_count": 0, "has_merged_cells": False, "cell_text": text})
                            elif item_type == "list-item":
                                lists_out.append({"items": [text], "ordered": False})
                            elif item_type == "picture":
                                images.append({"description": text})
                            else:
                                text_elements.append({"text": text, "style": item_type})

        except Exception:
            # Last resort: markdown export
            md = result.document.export_to_markdown()
            for line in md.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    level = len(line) - len(line.lstrip("#"))
                    headings.append({"text": line.lstrip("# ").strip(), "level": level})
                elif line.startswith("|") and "|" in line[1:]:
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if cells and not all(set(c) <= {"-", ":"} for c in cells):
                        tables.append({"row_count": 1, "has_merged_cells": False, "cell_text": " ".join(cells)})
                elif line.startswith("- ") or line.startswith("* "):
                    lists_out.append({"items": [line[2:]], "ordered": False})
                else:
                    text_elements.append({"text": line, "style": "markdown"})

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": [],
            "comments": [],
            "headers_footers": headers_footers,
            "footnotes": footnotes,
            "speaker_notes": [],
            "text_boxes": [],
            "images": images,
            "lists": lists_out,
            "metadata": metadata,
        }

    def supported_formats(self) -> set[str]:
        return {"docx", "pptx", "xlsx"}
