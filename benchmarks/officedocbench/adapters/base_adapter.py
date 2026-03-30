"""Base adapter interface for OfficeDocBench.

All parsers must implement this interface to be evaluated.
The parse() method returns a dict matching adapter_output.schema.json.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class OfficeDocBenchAdapter(ABC):
    """Abstract base class for OfficeDocBench parser adapters."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable name (e.g., 'AILANG Parse', 'Unstructured')."""
        ...

    @abstractmethod
    def version(self) -> str:
        """Version string for the parser."""
        ...

    @abstractmethod
    def parse(self, filepath: Path) -> dict[str, Any]:
        """Parse a file and return OfficeDocBench-compatible output.

        Must return a dict matching adapter_output.schema.json:
        {
            "text_elements": [{"text": str, "style": str}],
            "headings": [{"text": str, "level": int}],
            "tables": [{"rows": [...], "row_count": int, "has_merged_cells": bool, "cell_text": str}],
            "track_changes": [{"type": str, "author": str, "text": str}],
            "comments": [{"author": str, "text": str}],
            "headers_footers": [{"type": "header"|"footer", "text": str}],
            "footnotes": [{"text": str}],
            "speaker_notes": [{"text": str}],
            "text_boxes": [{"text": str}],
            "images": [{"description": str}],
            "lists": [{"items": [str], "ordered": bool}],
            "metadata": {"title": str, "author": str, "created": str, "modified": str, "sheet_names": [str]}
        }
        """
        ...

    @abstractmethod
    def supported_formats(self) -> set[str]:
        """Set of file extensions this adapter supports (e.g., {'docx', 'pptx'})."""
        ...
