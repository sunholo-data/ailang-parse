"""LlamaParse adapter for OfficeDocBench.

Requires: uv pip install llama-parse
Requires: LLAMA_CLOUD_API_KEY environment variable
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter


class LlamaParseAdapter(OfficeDocBenchAdapter):

    def name(self) -> str:
        return "LlamaParse"

    def version(self) -> str:
        try:
            from importlib.metadata import version as pkg_version
            return pkg_version("llama-parse")
        except Exception:
            return "unknown"

    def parse(self, filepath: Path) -> dict[str, Any]:
        if not os.environ.get("LLAMA_CLOUD_API_KEY"):
            raise RuntimeError("LLAMA_CLOUD_API_KEY not set")

        try:
            from llama_parse import LlamaParse
        except ImportError:
            raise RuntimeError("llama-parse not installed: uv pip install llama-parse")

        parser = LlamaParse(result_type="markdown")
        documents = parser.load_data(str(filepath))

        text_elements = []
        headings = []
        tables = []
        lists_out = []

        for doc in documents:
            text = doc.text if hasattr(doc, "text") else str(doc)
            for line in text.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    level = len(line) - len(line.lstrip("#"))
                    headings.append({"text": line.lstrip("# ").strip(), "level": level})
                elif line.startswith("|") and "|" in line[1:]:
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if cells and not all(set(c) <= {"-", ":"} for c in cells):
                        tables.append({
                            "row_count": 1,
                            "has_merged_cells": False,
                            "cell_text": " ".join(cells),
                        })
                elif line.startswith("- ") or line.startswith("* "):
                    lists_out.append({"items": [line[2:]], "ordered": False})
                elif re.match(r"^\d+\.\s", line):
                    lists_out.append({"items": [re.sub(r"^\d+\.\s", "", line)], "ordered": True})
                else:
                    text_elements.append({"text": line, "style": "markdown"})

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
            "images": [],
            "lists": lists_out,
            "metadata": {},
        }

    def supported_formats(self) -> set[str]:
        return {"docx", "pptx", "xlsx"}
