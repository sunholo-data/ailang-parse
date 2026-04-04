"""Kreuzberg adapter for OfficeDocBench.

Requires: pip install kreuzberg>=4.0.0

Kreuzberg is a Rust-core polyglot document intelligence framework
that extracts text, tables, metadata, and images from 91+ formats.
https://github.com/kreuzberg-dev/kreuzberg

This adapter uses include_document_structure=True to access the
richer node-based output (headings, lists, content layers for
headers/footers, image nodes) rather than just flat text.

Kreuzberg v4.7+ returns:
  - result.content: str (markdown/plain text)
  - result.tables: list[ExtractedTable] with .cells, .markdown, .page_number
  - result.images: list[dict] with 'data', 'format', 'description' keys
  - result.metadata: dict with 'authors', 'created_at', 'core_properties', etc.
  - result.document: dict with 'nodes' list (when include_document_structure=True)
  - result.pages: list[dict] with 'page_number', 'content', etc.

Features Kreuzberg does NOT extract (confirmed absent in v4.7.1):
  - Track changes (w:ins, w:del, w:moveTo)
  - Comments (w:comment)
  - Text boxes / VML shapes (mc:AlternateContent, v:shape)
  - Merged cell metadata (colspan/rowspan preserved in cells but not flagged)
  - Footnotes / endnotes as separate elements
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter


class KreuzbergAdapter(OfficeDocBenchAdapter):

    def name(self) -> str:
        return "Kreuzberg"

    def version(self) -> str:
        try:
            from importlib.metadata import version as pkg_version
            return pkg_version("kreuzberg")
        except Exception:
            return "unknown"

    def parse(self, filepath: Path) -> dict[str, Any]:
        try:
            from kreuzberg import extract_file_sync, ExtractionConfig
        except ImportError:
            raise RuntimeError(
                "kreuzberg not installed: pip install kreuzberg>=4.0.0"
            )

        config = ExtractionConfig(include_document_structure=True)
        result = extract_file_sync(str(filepath), config=config)

        text_elements: list[dict[str, Any]] = []
        headings: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []
        lists_out: list[dict[str, Any]] = []
        headers_footers: list[dict[str, Any]] = []
        speaker_notes: list[dict[str, Any]] = []
        metadata_dict: dict[str, Any] = {}

        # ── Tables from result.tables ──────────────────────────────
        # ExtractedTable is a Rust-backed object with .cells, .markdown,
        # .page_number, .bounding_box — NOT a dict, so use getattr().
        if result.tables:
            for tbl in result.tables:
                row_count = 0
                cell_text = ""

                cells = getattr(tbl, "cells", None)
                if cells and isinstance(cells, list):
                    row_count = len(cells)
                    all_cell_texts = []
                    for row in cells:
                        if isinstance(row, (list, tuple)):
                            all_cell_texts.extend(str(c) for c in row)
                    cell_text = " ".join(all_cell_texts)

                markdown = getattr(tbl, "markdown", None)
                if markdown:
                    if not cell_text:
                        cell_text = markdown
                    # Count data rows (not separator rows)
                    md_row_count = 0
                    for line in markdown.split("\n"):
                        stripped = line.strip()
                        if stripped.startswith("|"):
                            pieces = [c.strip() for c in stripped.split("|") if c.strip()]
                            if pieces and not all(set(c) <= {"-", ":", " "} for c in pieces):
                                md_row_count += 1
                    row_count = max(row_count, md_row_count)

                tables.append({
                    "row_count": row_count,
                    "has_merged_cells": False,  # Kreuzberg does not expose merge info
                    "cell_text": cell_text,
                })

        # ── Images from result.images ──────────────────────────────
        if result.images:
            for img in result.images:
                desc = ""
                if isinstance(img, dict):
                    desc = img.get("description", "") or img.get("alt_text", "") or ""
                else:
                    desc = getattr(img, "description", "") or getattr(img, "alt_text", "") or ""
                images.append({"description": desc})

        # ── Metadata ───────────────────────────────────────────────
        meta = result.metadata or {}
        if isinstance(meta, dict):
            # Author
            author = ""
            authors = meta.get("authors", [])
            if authors and isinstance(authors, list):
                author = authors[0]
            if not author:
                cp = meta.get("core_properties", {})
                if isinstance(cp, dict):
                    author = cp.get("creator", "") or ""
            if author:
                metadata_dict["author"] = author

            # Title
            cp = meta.get("core_properties", {})
            if isinstance(cp, dict) and cp.get("title"):
                metadata_dict["title"] = cp["title"]

            # Dates
            if meta.get("created_at"):
                metadata_dict["created"] = meta["created_at"]
            if meta.get("modified_at"):
                metadata_dict["modified"] = meta["modified_at"]

            # Sheet names (XLSX)
            if meta.get("sheet_names"):
                metadata_dict["sheet_names"] = list(meta["sheet_names"])

        # ── Document structure (headings, lists, headers/footers, images) ──
        doc = result.document
        if doc and isinstance(doc, dict):
            nodes = doc.get("nodes", [])
            self._walk_nodes(
                nodes, text_elements, headings, headers_footers,
                speaker_notes, images, lists_out,
            )

        # ── Fall back to content parsing if structure yielded nothing ──
        if not headings and not text_elements:
            self._parse_markdown_content(
                result.content or "",
                text_elements, headings, images, lists_out, tables,
                has_structured_tables=bool(result.tables),
            )

        # ── PPTX speaker notes heuristic ───────────────────────────
        # Kreuzberg inlines notes as "Notes:" paragraphs — extract them
        if not speaker_notes and str(filepath).endswith(".pptx"):
            self._extract_inline_notes(result.content or "", speaker_notes, text_elements)

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": [],      # Kreuzberg does not extract track changes
            "comments": [],           # Kreuzberg does not extract comments
            "headers_footers": headers_footers,
            "footnotes": [],          # Kreuzberg does not extract footnotes separately
            "speaker_notes": speaker_notes,
            "text_boxes": [],         # Kreuzberg does not extract text boxes / VML shapes
            "images": images,
            "lists": lists_out,
            "metadata": metadata_dict,
        }

    def _walk_nodes(
        self,
        nodes: list[dict],
        text_elements: list[dict],
        headings: list[dict],
        headers_footers: list[dict],
        speaker_notes: list[dict],
        images: list[dict],
        lists_out: list[dict],
    ) -> None:
        """Recursively walk document structure nodes."""
        current_list_items: list[str] = []
        current_list_ordered = False

        for node in nodes:
            if not isinstance(node, dict):
                continue

            content = node.get("content", {})
            # Guard: content can sometimes be an int or str in edge cases
            if not isinstance(content, dict):
                continue

            ntype = content.get("node_type", "")
            text = str(content.get("text", "") or "")
            level = content.get("level", 0)
            layer = node.get("content_layer", "")

            # Content layer: header / footer
            if layer == "header" and text.strip():
                headers_footers.append({"type": "header", "text": text.strip()})
                continue
            if layer == "footer" and text.strip():
                headers_footers.append({"type": "footer", "text": text.strip()})
                continue

            # Flush accumulated list items before non-list nodes
            if ntype not in ("list_item", "list") and current_list_items:
                lists_out.append({
                    "items": current_list_items,
                    "ordered": current_list_ordered,
                })
                current_list_items = []

            if ntype == "heading" and text.strip():
                lvl = level if isinstance(level, int) and 1 <= level <= 6 else 1
                headings.append({"text": text.strip(), "level": lvl})

            elif ntype == "image":
                desc = str(content.get("description", "") or "")
                if not any(i.get("description") == desc for i in images):
                    images.append({"description": desc})

            elif ntype == "list_item" and text.strip():
                current_list_items.append(text.strip())

            elif ntype in ("list", "group"):
                # Walk children
                children = node.get("children", [])
                if isinstance(children, list) and children:
                    self._walk_nodes(
                        children, text_elements, headings,
                        headers_footers, speaker_notes, images, lists_out,
                    )

            elif ntype == "paragraph" and text.strip():
                text_elements.append({"text": text.strip(), "style": "paragraph"})

            elif ntype in ("table", "slide"):
                pass  # Tables via result.tables; slides are markers

            elif text.strip():
                text_elements.append({"text": text.strip(), "style": ntype or "unknown"})

        # Flush trailing list items
        if current_list_items:
            lists_out.append({
                "items": current_list_items,
                "ordered": current_list_ordered,
            })

    def _parse_markdown_content(
        self,
        content: str,
        text_elements: list[dict],
        headings: list[dict],
        images: list[dict],
        lists_out: list[dict],
        tables: list[dict],
        has_structured_tables: bool = False,
    ) -> None:
        """Parse markdown content as fallback when document structure is empty."""
        lines = content.split("\n")
        table_rows: list[str] = []
        in_table = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_table and table_rows:
                    if not has_structured_tables:
                        tables.append(self._flush_table(table_rows))
                    table_rows = []
                    in_table = False
                continue

            # Table row
            if stripped.startswith("|") and "|" in stripped[1:]:
                cells = [c.strip() for c in stripped.split("|") if c.strip()]
                if cells and all(set(c) <= {"-", ":", " "} for c in cells):
                    in_table = True
                    continue
                in_table = True
                table_rows.append(stripped)
                continue

            if in_table and table_rows:
                if not has_structured_tables:
                    tables.append(self._flush_table(table_rows))
                table_rows = []
                in_table = False

            # Heading
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                heading_text = stripped.lstrip("# ").strip()
                if heading_text and 1 <= level <= 6:
                    headings.append({"text": heading_text, "level": level})
                    continue

            # Image
            img_match = re.match(r"!\[([^\]]*)\]\(([^)]*)\)", stripped)
            if img_match:
                desc = img_match.group(1) or img_match.group(2)
                if not any(i.get("description") == desc for i in images):
                    images.append({"description": desc})
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

            text_elements.append({"text": stripped, "style": "paragraph"})

        if in_table and table_rows and not has_structured_tables:
            tables.append(self._flush_table(table_rows))

    def _extract_inline_notes(
        self,
        content: str,
        speaker_notes: list[dict],
        text_elements: list[dict],
    ) -> None:
        """Extract PPTX speaker notes that Kreuzberg inlines as 'Notes:' sections."""
        lines = content.split("\n")
        in_notes = False
        note_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped == "Notes:":
                in_notes = True
                note_lines = []
                continue

            if in_notes:
                if not stripped:
                    if note_lines:
                        speaker_notes.append({"text": " ".join(note_lines)})
                        note_lines = []
                    in_notes = False
                else:
                    note_lines.append(stripped)

        if note_lines:
            speaker_notes.append({"text": " ".join(note_lines)})

        # Remove "Notes:" and note content from text_elements
        if speaker_notes:
            note_texts = {n["text"] for n in speaker_notes}
            text_elements[:] = [
                el for el in text_elements
                if el["text"] != "Notes:" and el["text"] not in note_texts
                and not any(el["text"] in nt for nt in note_texts)
            ]

    def _flush_table(self, rows: list[str]) -> dict[str, Any]:
        """Convert accumulated markdown table rows into adapter schema."""
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
        # Note: odp is excluded — Kreuzberg v4.7 raises ValidationError on ODP files.
        return {
            "docx", "pptx", "xlsx",
            "odt", "ods",
            "html", "csv", "tsv", "md",
            "epub",
        }
