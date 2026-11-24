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
from .structure import markdown_output, add_sheet_scopes

# markdownify (MarkItDown's HTML->Markdown step for DOCX, HTML and EPUB)
# writes an all-empty GFM header row above a table whose first row has no
# <th>: a placeholder, not a source row (markdownify convert_tr).
_PLACEHOLDER_HEAD = {".docx", ".html", ".epub"}
# MarkItDown's PPTX converter: one marker per slide, the title shape as
# "# ", and the slide's notes after a "### Notes:" heading.
_SLIDE = re.compile(r"^<!-- Slide number: \d+ -->[ \t]*$", re.M)
_NOTES = re.compile(r"^### Notes:[ \t]*$", re.M)


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

        suffix = filepath.suffix.lower()
        if suffix == ".pptx":
            return self.convert_slides(text)
        output = markdown_output(text, placeholder_header=suffix in _PLACEHOLDER_HEAD)
        return add_sheet_scopes(output) if suffix == ".xlsx" else output

    def convert_slides(self, text: str) -> dict[str, Any]:
        """Slides from MarkItDown's slide markers; notes from "### Notes:"."""
        slides = []
        for chunk in _SLIDE.split(text)[1:]:
            body, *notes = _NOTES.split(chunk, maxsplit=1)
            heads = [h for h in markdown_output(body)["headings"] if h["level"] == 1]
            slides.append(
                (body, heads[0]["text"] if heads else "", " ".join("".join(notes).split()))
            )
        output = markdown_output("\n\n".join(body for body, _, _ in slides))
        structure = output["structure"]
        scopes = [
            name
            for body, name, _ in slides
            for _ in markdown_output(body)["tables"]
        ]
        for c in structure["table_cells"]:
            c["scope"] = scopes[c["table"]] if c["table"] < len(scopes) else ""
        structure["containers"] = [{"kind": "slide", "name": name} for _, name, _ in slides]
        structure["notes"] = [
            {"scope": name, "text": notes} for _, name, notes in slides if notes
        ]
        output["speaker_notes"] = [{"text": n["text"]} for n in structure["notes"]]
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
        # md and tsv go through MarkItDown's plain-text converter: it returns
        # their text (TSV is not turned into a table).
        return {"docx", "pptx", "xlsx", "html", "csv", "tsv", "md", "epub", "pdf"}
