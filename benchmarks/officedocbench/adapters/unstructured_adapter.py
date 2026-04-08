"""Unstructured.io adapter for OfficeDocBench.

Requires: uv pip install unstructured
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter


class UnstructuredAdapter(OfficeDocBenchAdapter):

    def name(self) -> str:
        return "Unstructured"

    def version(self) -> str:
        try:
            from importlib.metadata import version as pkg_version
            return pkg_version("unstructured")
        except Exception:
            return "unknown"

    def parse(self, filepath: Path) -> dict[str, Any]:
        try:
            from unstructured.partition.auto import partition
        except ImportError:
            raise RuntimeError("unstructured not installed: uv pip install unstructured")

        elements = partition(filename=str(filepath))

        text_elements = []
        headings = []
        tables = []
        headers_footers = []
        images = []
        lists_out = []
        metadata_dict: dict[str, Any] = {}

        for el in elements:
            el_type = type(el).__name__
            text = str(el)
            meta = el.metadata if hasattr(el, "metadata") else None

            # Pull document-level metadata from the first element that has it.
            # ElementMetadata.to_dict() exposes filename, last_modified, page_number,
            # languages, and (for partition_docx) author/title where the DOCX core
            # properties were populated.
            if meta is not None and not metadata_dict:
                try:
                    md = meta.to_dict()
                except Exception:
                    md = {}
                for src, dst in (
                    ("filename", "title"),
                    ("last_modified", "modified"),
                    ("file_directory", None),
                ):
                    if dst and md.get(src):
                        metadata_dict.setdefault(dst, md[src])

            if el_type == "Title":
                headings.append({"text": text, "level": 1})
            elif el_type == "Table":
                html = getattr(meta, "text_as_html", "") if meta else ""
                has_merges = bool(html and ("colspan" in html.lower() or "rowspan" in html.lower()))
                tables.append({
                    "row_count": html.count("<tr") if html else 0,
                    "has_merged_cells": has_merges,
                    "cell_text": text,
                })
            elif el_type == "ListItem":
                # Group consecutive list items later
                lists_out.append({"items": [text], "ordered": False})
            elif el_type == "Header":
                headers_footers.append({"type": "header", "text": text})
            elif el_type == "Footer":
                headers_footers.append({"type": "footer", "text": text})
            elif el_type == "Image":
                images.append({"description": text})
            elif el_type in ("NarrativeText", "UncategorizedText", "FigureCaption",
                             "Address", "EmailAddress", "Formula"):
                text_elements.append({"text": text, "style": el_type})
            else:
                text_elements.append({"text": text, "style": el_type})

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": [],  # Unstructured doesn't extract track changes
            "comments": [],  # Unstructured doesn't extract comments
            "headers_footers": headers_footers,
            "footnotes": [],
            "speaker_notes": [],
            "text_boxes": [],
            "images": images,
            "lists": lists_out,
            "metadata": metadata_dict,
        }

    def supported_formats(self) -> set[str]:
        return {"docx", "pptx", "xlsx"}
