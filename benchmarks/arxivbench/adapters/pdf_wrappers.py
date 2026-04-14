"""Thin wrappers over existing OfficeDocBench adapters to reuse their
PDF-parsing implementations for arxivbench.

Each wrapper calls the underlying adapter's `parse()` method on the PDF
and maps its OfficeDocBench-schema output into arxivbench's structural
count schema.

Equation and citation counting: PDF-OCR parsers don't preserve LaTeX
source, so equations/citations are extracted heuristically from the
flattened text — this is deliberately the weakest signal, because that's
precisely what the OCR-vs-source comparison is supposed to demonstrate.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from .base_adapter import ArxivBenchAdapter


# Make officedocbench adapters importable.
_OFFICEDOCBENCH = Path(__file__).parent.parent.parent / "officedocbench"
if str(_OFFICEDOCBENCH) not in sys.path:
    sys.path.insert(0, str(_OFFICEDOCBENCH))


# Heuristic post-processing on flattened PDF text. OCR'd papers have math
# that renders as mangled unicode or inline char soup — we count only the
# clear cases (explicit `$...$` spans, LaTeX-escaped sequences) to avoid
# inflating baselines with false positives.
_INLINE_MATH_RE = re.compile(r"(?<!\\)\$[^$\n]+\$")
_DISPLAY_MATH_RE = re.compile(r"\$\$[^$]+\$\$")
_CITATION_RE = re.compile(r"\\cite[a-z]*\{[^}]+\}|\[(\d+(?:\s*,\s*\d+)+|\d+)\]")


def _zero_counts() -> dict[str, Any]:
    return {
        "sections": 0,
        "equations_display": 0,
        "equations_inline": 0,
        "tables": 0,
        "figures": 0,
        "citation_calls": 0,
        "bibliography_entries": 0,
        "lists": 0,
        "theorems": 0,
    }


def _count_from_officedocbench_output(out: dict[str, Any]) -> dict[str, Any]:
    """Map an OfficeDocBench-schema adapter output to arxivbench counts."""
    counts = _zero_counts()

    counts["sections"] = len(out.get("headings") or [])
    counts["tables"] = len(out.get("tables") or [])
    counts["figures"] = len(out.get("images") or [])
    counts["lists"] = len(out.get("lists") or [])

    # Flatten all text for math/citation heuristics
    chunks = []
    for el in (out.get("text_elements") or []):
        chunks.append(el.get("text", ""))
    for h in (out.get("headings") or []):
        chunks.append(h.get("text", ""))
    for tbl in (out.get("tables") or []):
        chunks.append(tbl.get("cell_text", ""))
    for fn in (out.get("footnotes") or []):
        chunks.append(fn.get("text", ""))
    text = "\n".join(chunks)

    counts["equations_display"] = len(_DISPLAY_MATH_RE.findall(text))
    counts["equations_inline"] = len(_INLINE_MATH_RE.findall(text))
    counts["citation_calls"] = len(_CITATION_RE.findall(text))

    # Bibliography: heuristic from text_elements whose style contains "ref"
    # or "bibliography". OCR adapters rarely preserve this structurally.
    for el in (out.get("text_elements") or []):
        style = (el.get("style") or "").lower()
        if "bib" in style or "reference" in style:
            counts["bibliography_entries"] += 1

    return counts


class _PdfWrapper(ArxivBenchAdapter):
    """Base for wrappers that forward to an OfficeDocBench adapter on PDF input."""

    _odb_class_name: str = ""
    _display_name: str = ""

    def __init__(self):
        self._inner = self._load_inner()

    def _load_inner(self):
        raise NotImplementedError

    def name(self) -> str:
        return self._display_name or self._inner.name()

    def version(self) -> str:
        try:
            return self._inner.version()
        except Exception:
            return "unknown"

    def input_kind(self) -> str:
        return "pdf"

    def parse(self, filepath: Path) -> dict[str, Any]:
        raw = self._inner.parse(filepath)
        return _count_from_officedocbench_output(raw)


class DoclingAdapter(_PdfWrapper):
    _display_name = "Docling"

    def _load_inner(self):
        from adapters.docling_adapter import DoclingAdapter as Inner
        return Inner()


class LlamaParseAdapter(_PdfWrapper):
    _display_name = "LlamaParse"

    def _load_inner(self):
        from adapters.llamaparse_adapter import LlamaParseAdapter as Inner
        return Inner()


class MarkItDownAdapter(_PdfWrapper):
    _display_name = "MarkItDown"

    def _load_inner(self):
        from adapters.markitdown_adapter import MarkItDownAdapter as Inner
        return Inner()


class UnstructuredAdapter(_PdfWrapper):
    _display_name = "Unstructured"

    def _load_inner(self):
        from adapters.unstructured_adapter import UnstructuredAdapter as Inner
        return Inner()


class LiteParseAdapter(_PdfWrapper):
    _display_name = "LiteParse"

    def _load_inner(self):
        from adapters.liteparse_adapter import LiteParseAdapter as Inner
        return Inner()
