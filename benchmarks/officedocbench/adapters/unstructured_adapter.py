"""Unstructured.io adapter for OfficeDocBench.

Requires: uv pip install unstructured
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter
from .structure import attach_formatting, html_rows, table_cells


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
        notes: dict[int, str] = {}
        if filepath.suffix.lower() == ".pptx":
            notes = self._slide_notes(
                elements, partition(filename=str(filepath), include_slide_notes=True)
            )
        return self.convert_elements(elements, filepath, notes)

    @staticmethod
    def _slide_notes(plain: list, with_notes: list) -> dict[int, str]:
        """Notes text per slide (page_number) from a notes-enabled partition.

        partition_pptx(include_slide_notes=True) emits a slide's notes as one
        NarrativeText ahead of the slide's shapes, with nothing in the element
        marking it as notes. It is the element that run adds: compare each
        slide's elements with the default run's.
        """
        def by_page(elements):
            pages: dict[int, list] = {}
            for el in elements:
                if type(el).__name__ != "PageBreak":
                    pages.setdefault(el.metadata.page_number, []).append(str(el))
            return pages

        base, extra = by_page(plain), by_page(with_notes)
        return {
            page: texts[0]
            for page, texts in extra.items()
            if texts[1:] == base.get(page, [])
        }

    @staticmethod
    def _slide(slides: dict, structure: dict, page: int) -> dict[str, str]:
        """The container of slide `page`, creating it and any before it."""
        for n in range(len(slides) + 1, page + 1):
            slides[n] = {"kind": "slide", "name": ""}
            structure["containers"].append(slides[n])
        return slides[page]

    def convert_elements(self, elements: list, filepath: Path, notes: dict[int, str] | None = None) -> dict[str, Any]:
        """Map partition() elements; no partitioning here."""
        notes = notes or {}
        suffix = filepath.suffix.lower()
        text_elements = []
        headings = []
        tables = []
        headers_footers = []
        images = []
        lists_out = []
        metadata_dict: dict[str, Any] = {}

        structure = {k: [] for k in ("element_order", "table_cells", "list_items", "hyperlinks", "runs", "containers", "notes")}
        slides: dict[Any, dict[str, str]] = {}
        in_list = False
        for el in elements:
            el_type = type(el).__name__
            text = str(el)
            meta = el.metadata if hasattr(el, "metadata") else None
            if el_type == "PageBreak":
                # A page boundary marker, not document text: page N ended,
                # page N+1 follows (a blank last slide has no other element).
                if suffix == ".pptx" and meta is not None and meta.page_number:
                    self._slide(slides, structure, meta.page_number + 1)
                continue

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

            md = meta.to_dict() if meta is not None else {}
            depth = md.get("category_depth") or 0
            sheet_name = md.get("page_name", "") if suffix == ".xlsx" else ""
            if sheet_name and not any(c["name"] == sheet_name for c in structure["containers"]):
                structure["containers"].append({"kind": "sheet", "name": sheet_name})
                metadata_dict.setdefault("sheet_names", []).append(sheet_name)
            if suffix == ".pptx" and md.get("page_number") is not None:
                # Each slide is a page; partition_pptx emits the title shape
                # as a Title at category_depth 0 (other shapes' titles are >= 1).
                slide = self._slide(slides, structure, md["page_number"])
                if el_type == "Title" and depth == 0 and not slide["name"]:
                    slide["name"] = text
            typ = {"Title": "heading", "Table": "table", "ListItem": "list"}.get(el_type, "text")
            if typ != "list" or not in_list:
                structure["element_order"].append({"type": typ, **({"text": text} if typ not in ("table", "list") else {})})
            if typ == "list" and not in_list:
                lists_out.append({"items": [], "ordered": False, "depth": 1})
            in_list = typ == "list"
            for value, url in zip(md.get("link_texts") or [], md.get("link_urls") or []):
                structure["hyperlinks"].append({"text": value, "url": url})
            for value, tags in zip(md.get("emphasized_text_contents") or [], md.get("emphasized_text_tags") or []):
                structure["runs"].append({"text": value, "bold": "b" in tags or "strong" in tags, "italic": "i" in tags or "em" in tags})
            if el_type == "Title":
                headings.append({"text": text, "level": min(depth + 1, 6)})
            elif el_type == "Table":
                html = getattr(meta, "text_as_html", "") if meta else ""
                has_merges = bool(html and ("colspan" in html.lower() or "rowspan" in html.lower()))
                rows = html_rows(html)
                structure["table_cells"] += table_cells(rows, md.get("page_number", len(tables)+1)-1 if sheet_name else len(tables), sheet_name)
                tables.append({
                    "rows": rows,
                    "row_count": html.count("<tr") if html else 0,
                    "has_merged_cells": has_merges,
                    "cell_text": text,
                })
            elif el_type == "ListItem":
                # Consecutive ListItems are one list; Unstructured does not
                # say whether a list is ordered, so list_items omit it.
                lists_out[-1]["items"].append(text)
                lists_out[-1]["depth"] = max(lists_out[-1]["depth"], depth + 1)
                structure["list_items"].append({"text": text, "level": depth})
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

        attach_formatting(text_elements, structure["runs"])
        for slide_page, slide in slides.items():
            if notes.get(slide_page):
                structure["notes"].append({"scope": slide["name"], "text": notes[slide_page]})
        return {
            "structure": structure,
            "hyperlinks": structure["hyperlinks"],
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": [],  # Unstructured doesn't extract track changes
            "comments": [],  # Unstructured doesn't extract comments
            "headers_footers": headers_footers,
            "footnotes": [],
            "speaker_notes": [{"text": n["text"]} for n in structure["notes"]],
            "text_boxes": [],
            "images": images,
            "lists": lists_out,
            "metadata": metadata_dict,
        }

    def supported_formats(self) -> set[str]:
        return {"docx", "pptx", "xlsx", "odt", "html", "csv", "tsv", "md", "epub"}
