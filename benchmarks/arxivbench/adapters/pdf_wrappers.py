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

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

from .base_adapter import ArxivBenchAdapter


# The officedocbench adapters live in a sibling `adapters/` package whose
# name collides with ours. Load each one by file path via importlib so
# Python's name-based package cache doesn't redirect back to our own
# arxivbench/adapters/ directory.
_OFFICEDOCBENCH_ADAPTERS = Path(__file__).parent.parent.parent / "officedocbench" / "adapters"


def _load_officedocbench_module(stem: str):
    """Import officedocbench/adapters/<stem>.py under a unique module name."""
    unique_name = f"_odb_{stem}"
    if unique_name in sys.modules:
        return sys.modules[unique_name]
    src = _OFFICEDOCBENCH_ADAPTERS / f"{stem}.py"
    # Base class lives alongside; load it first under its expected name so
    # `from .base_adapter import ...` inside the module resolves.
    base_path = _OFFICEDOCBENCH_ADAPTERS / "base_adapter.py"
    if "_odb_base_adapter" not in sys.modules:
        spec = importlib.util.spec_from_file_location("_odb_base_adapter", base_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_odb_base_adapter"] = mod
        spec.loader.exec_module(mod)
    # Rewrite the relative import by executing the target module with the
    # officedocbench adapters dir first on sys.path just for this load.
    prev_path = sys.path[:]
    sys.path.insert(0, str(_OFFICEDOCBENCH_ADAPTERS.parent))
    try:
        # Temporarily swap our `adapters` package cache so officedocbench's
        # `from .base_adapter import ...` resolves to the right file.
        saved_adapters = sys.modules.pop("adapters", None)
        saved_base = sys.modules.pop("adapters.base_adapter", None)
        odb_pkg_spec = importlib.util.spec_from_file_location(
            "adapters", _OFFICEDOCBENCH_ADAPTERS / "__init__.py",
            submodule_search_locations=[str(_OFFICEDOCBENCH_ADAPTERS)],
        )
        odb_pkg = importlib.util.module_from_spec(odb_pkg_spec)
        sys.modules["adapters"] = odb_pkg
        odb_pkg_spec.loader.exec_module(odb_pkg)
        module_name = f"adapters.{stem}"
        spec = importlib.util.spec_from_file_location(module_name, src)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        sys.modules[unique_name] = mod
        return mod
    finally:
        sys.path[:] = prev_path
        # Restore arxivbench's adapters package
        if saved_adapters is not None:
            sys.modules["adapters"] = saved_adapters
        else:
            sys.modules.pop("adapters", None)
        if saved_base is not None:
            sys.modules["adapters.base_adapter"] = saved_base


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
        mod = _load_officedocbench_module("docling_adapter")
        return mod.DoclingAdapter()


class LlamaParseAdapter(_PdfWrapper):
    _display_name = "LlamaParse"

    def _load_inner(self):
        mod = _load_officedocbench_module("llamaparse_adapter")
        return mod.LlamaParseAdapter()


class MarkItDownAdapter(_PdfWrapper):
    _display_name = "MarkItDown"

    def _load_inner(self):
        mod = _load_officedocbench_module("markitdown_adapter")
        return mod.MarkItDownAdapter()


class UnstructuredAdapter(_PdfWrapper):
    _display_name = "Unstructured"

    def _load_inner(self):
        mod = _load_officedocbench_module("unstructured_adapter")
        return mod.UnstructuredAdapter()


class LiteParseAdapter(_PdfWrapper):
    _display_name = "LiteParse"

    def _load_inner(self):
        mod = _load_officedocbench_module("liteparse_adapter")
        return mod.LiteParseAdapter()
