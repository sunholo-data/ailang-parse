"""Base adapter interface for arxivbench.

An adapter runs one tool on one arXiv paper input (either .tex source or
.pdf rendering) and returns a normalized structural-count dict. The eval
script scores these counts against ground truth extracted from the .tex
source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ArxivBenchAdapter(ABC):
    @abstractmethod
    def name(self) -> str:
        """Display name of this adapter."""

    @abstractmethod
    def version(self) -> str:
        """Version string (for the report)."""

    @abstractmethod
    def input_kind(self) -> str:
        """'tex' or 'pdf' — which file this adapter consumes."""

    @abstractmethod
    def parse(self, filepath: Path) -> dict[str, Any]:
        """Parse the input and return structural counts.

        Returns a dict with keys:
          sections, equations_display, equations_inline, tables, figures,
          citation_calls, bibliography_entries, lists, theorems
        Missing keys are treated as 0.
        """
