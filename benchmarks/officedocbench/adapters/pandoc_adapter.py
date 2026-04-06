"""Pandoc adapter for OfficeDocBench.

Requires: pandoc CLI installed (brew install pandoc or https://pandoc.org/installing.html)

Pandoc converts documents to a structured JSON AST via `-t json`. With
`--track-changes=all`, it preserves insertions and deletions as attributed
Span elements. This adapter walks the AST to extract headings, tables,
lists, images, footnotes, track changes, and metadata.

Limitations (returns empty):
  - Comments (w:comment not exposed by pandoc)
  - Headers/footers (pandoc strips these)
  - Text boxes / VML shapes
  - Speaker notes (PPTX not supported)
  - Merged cell detection (pandoc flattens table structure)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter


class PandocAdapter(OfficeDocBenchAdapter):

    def name(self) -> str:
        return "Pandoc"

    def version(self) -> str:
        try:
            result = subprocess.run(
                ["pandoc", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            # First line: "pandoc 3.1.9"
            return result.stdout.split("\n")[0].replace("pandoc ", "").strip()
        except Exception:
            return "unknown"

    def parse(self, filepath: Path) -> dict[str, Any]:
        if not shutil.which("pandoc"):
            raise RuntimeError(
                "pandoc not installed: brew install pandoc or see https://pandoc.org/installing.html"
            )

        # Build command — use --track-changes=all for DOCX
        cmd = ["pandoc", str(filepath), "-t", "json"]
        ext = filepath.suffix.lower().lstrip(".")
        if ext == "docx":
            cmd.insert(1, "--track-changes=all")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"pandoc failed: {result.stderr.strip()}")

        ast = json.loads(result.stdout)

        # Collectors
        text_elements: list[dict[str, Any]] = []
        headings: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        track_changes: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []
        footnotes: list[dict[str, Any]] = []
        lists_out: list[dict[str, Any]] = []
        metadata_dict: dict[str, Any] = {}

        # Walk blocks
        self._walk_blocks(
            ast.get("blocks", []),
            text_elements, headings, tables, track_changes,
            images, footnotes, lists_out,
        )

        # Extract metadata
        meta = ast.get("meta", {})
        metadata_dict = self._extract_metadata(meta)

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": track_changes,
            "comments": [],            # Pandoc does not extract comments
            "headers_footers": [],     # Pandoc strips headers/footers
            "footnotes": footnotes,
            "speaker_notes": [],       # Pandoc does not handle PPTX
            "text_boxes": [],          # Pandoc does not extract text boxes
            "images": images,
            "lists": lists_out,
            "metadata": metadata_dict,
        }

    def _walk_blocks(
        self,
        blocks: list[dict],
        text_elements: list[dict],
        headings: list[dict],
        tables: list[dict],
        track_changes: list[dict],
        images: list[dict],
        footnotes: list[dict],
        lists_out: list[dict],
    ) -> None:
        """Recursively walk pandoc AST blocks."""
        for block in blocks:
            t = block.get("t", "")
            c = block.get("c")

            if t == "Header":
                # c = [level, attr, [inlines]]
                level = c[0]
                text = self._inlines_to_text(c[2], track_changes, images, footnotes)
                if text.strip():
                    headings.append({"text": text.strip(), "level": level})

            elif t == "Para" or t == "Plain":
                text = self._inlines_to_text(c, track_changes, images, footnotes)
                if text.strip():
                    text_elements.append({"text": text.strip(), "style": "paragraph"})

            elif t == "Table":
                tables.append(self._parse_table(c))

            elif t == "BulletList":
                # c = [[blocks], [blocks], ...]
                items = []
                for item_blocks in c:
                    item_text = self._blocks_to_text(item_blocks, track_changes, images, footnotes)
                    if item_text.strip():
                        items.append(item_text.strip())
                if items:
                    lists_out.append({"items": items, "ordered": False})

            elif t == "OrderedList":
                # c = [list_attrs, [[blocks], [blocks], ...]]
                items = []
                for item_blocks in c[1]:
                    item_text = self._blocks_to_text(item_blocks, track_changes, images, footnotes)
                    if item_text.strip():
                        items.append(item_text.strip())
                if items:
                    lists_out.append({"items": items, "ordered": True})

            elif t == "BlockQuote":
                self._walk_blocks(c, text_elements, headings, tables,
                                  track_changes, images, footnotes, lists_out)

            elif t == "Div":
                # c = [attr, [blocks]]
                self._walk_blocks(c[1], text_elements, headings, tables,
                                  track_changes, images, footnotes, lists_out)

            elif t == "CodeBlock":
                # c = [attr, text_str]
                if c[1].strip():
                    text_elements.append({"text": c[1].strip(), "style": "code"})

    def _inlines_to_text(
        self,
        inlines: list[dict],
        track_changes: list[dict],
        images: list[dict],
        footnotes: list[dict],
    ) -> str:
        """Extract plain text from pandoc inline elements, collecting side effects."""
        parts = []
        for inline in inlines:
            t = inline.get("t", "")
            c = inline.get("c")

            if t == "Str":
                parts.append(c)
            elif t == "Space":
                parts.append(" ")
            elif t == "SoftBreak" or t == "LineBreak":
                parts.append(" ")
            elif t in ("Emph", "Strong", "Strikeout", "Underline", "SmallCaps", "Superscript", "Subscript"):
                parts.append(self._inlines_to_text(c, track_changes, images, footnotes))
            elif t == "Quoted":
                # c = [quote_type, [inlines]]
                parts.append(self._inlines_to_text(c[1], track_changes, images, footnotes))
            elif t == "Link":
                # c = [attr, [inlines], [url, title]]
                parts.append(self._inlines_to_text(c[1], track_changes, images, footnotes))
            elif t == "Image":
                # c = [attr, [inlines], [url, title]]
                alt = self._inlines_to_text(c[1], track_changes, images, footnotes)
                images.append({"description": alt or c[2][0] if c[2] else alt})
            elif t == "Note":
                # c = [blocks] — footnote/endnote content
                note_text = self._blocks_to_text(c, track_changes, images, footnotes)
                if note_text.strip():
                    footnotes.append({"text": note_text.strip()})
            elif t == "Span":
                # c = [attr, [inlines]]
                # attr = [id, [classes], [[key, val], ...]]
                attr = c[0]
                classes = attr[1] if len(attr) > 1 else []
                kvs = dict(attr[2]) if len(attr) > 2 else {}
                span_text = self._inlines_to_text(c[1], track_changes, images, footnotes)

                if "insertion" in classes:
                    track_changes.append({
                        "type": "insertion",
                        "author": kvs.get("author", ""),
                        "text": span_text,
                    })
                    parts.append(span_text)
                elif "deletion" in classes:
                    track_changes.append({
                        "type": "deletion",
                        "author": kvs.get("author", ""),
                        "text": span_text,
                    })
                else:
                    parts.append(span_text)
            elif t == "Code":
                # c = [attr, text_str]
                parts.append(c[1])
            elif t == "Math":
                # c = [math_type, text_str]
                parts.append(c[1])
            elif t == "RawInline":
                pass  # Skip raw HTML/LaTeX

        return "".join(parts)

    def _blocks_to_text(
        self,
        blocks: list[dict],
        track_changes: list[dict],
        images: list[dict],
        footnotes: list[dict],
    ) -> str:
        """Extract plain text from a list of blocks."""
        parts = []
        for block in blocks:
            t = block.get("t", "")
            c = block.get("c")
            if t in ("Para", "Plain"):
                parts.append(self._inlines_to_text(c, track_changes, images, footnotes))
            elif t == "Header":
                parts.append(self._inlines_to_text(c[2], track_changes, images, footnotes))
            elif t == "CodeBlock":
                parts.append(c[1])
            elif t in ("BulletList", "OrderedList"):
                item_list = c if t == "BulletList" else c[1]
                for item_blocks in item_list:
                    parts.append(self._blocks_to_text(item_blocks, track_changes, images, footnotes))
            elif t == "Div":
                parts.append(self._blocks_to_text(c[1], track_changes, images, footnotes))
            elif t == "BlockQuote":
                parts.append(self._blocks_to_text(c, track_changes, images, footnotes))
        return " ".join(parts)

    def _parse_table(self, c: Any) -> dict[str, Any]:
        """Parse a pandoc Table AST node.

        Pandoc 3.x table format (pandoc-types 1.23):
        c = [attr, caption, colspecs, thead, [tbody, ...], tfoot]

        Each thead/tbody/tfoot contains rows, each row is [attr, [cells]],
        each cell is [attr, alignment, rowspan, colspan, [blocks]].
        """
        row_count = 0
        cell_texts = []

        def extract_rows(rows: list) -> None:
            nonlocal row_count
            for row in rows:
                if not isinstance(row, list) or len(row) < 2:
                    continue
                row_count += 1
                cells = row[1] if isinstance(row[1], list) else []
                for cell in cells:
                    if isinstance(cell, list) and len(cell) >= 5:
                        cell_blocks = cell[4]
                        text = self._blocks_to_text(cell_blocks, [], [], [])
                        if text.strip():
                            cell_texts.append(text.strip())

        try:
            # thead: [attr, [rows]]
            thead = c[3]
            if isinstance(thead, list) and len(thead) >= 2:
                extract_rows(thead[1])

            # tbody: list of [attr, row_head_count, [row_heads], [rows]]
            tbodies = c[4]
            if isinstance(tbodies, list):
                for tbody in tbodies:
                    if isinstance(tbody, list) and len(tbody) >= 4:
                        extract_rows(tbody[2])  # row heads
                        extract_rows(tbody[3])  # body rows

            # tfoot: [attr, [rows]]
            tfoot = c[5]
            if isinstance(tfoot, list) and len(tfoot) >= 2:
                extract_rows(tfoot[1])
        except (IndexError, TypeError):
            pass

        return {
            "row_count": row_count,
            "has_merged_cells": False,  # Pandoc does not expose merge info
            "cell_text": " ".join(cell_texts),
        }

    def _extract_metadata(self, meta: dict) -> dict[str, Any]:
        """Extract metadata from pandoc's meta field."""
        result: dict[str, Any] = {}

        for key in ("title", "author", "date"):
            val = meta.get(key)
            if not val:
                continue
            text = self._meta_to_text(val)
            if text:
                result[key.replace("date", "created")] = text

        return result

    def _meta_to_text(self, val: dict) -> str:
        """Convert a pandoc MetaValue to plain text."""
        t = val.get("t", "")
        c = val.get("c")

        if t == "MetaString":
            return c
        elif t == "MetaInlines":
            return self._inlines_to_text(c, [], [], [])
        elif t == "MetaList":
            # e.g., multiple authors — take the first
            if c:
                return self._meta_to_text(c[0])
        elif t == "MetaBlocks":
            parts = []
            for block in c:
                if block.get("t") in ("Para", "Plain"):
                    parts.append(self._inlines_to_text(block["c"], [], [], []))
            return " ".join(parts)
        return ""

    def supported_formats(self) -> set[str]:
        return {"docx", "html", "epub", "md", "odt"}
