"""Pandoc adapter for arxivbench.

Runs `pandoc --from=latex --to=json` on a .tex file and counts structural
elements from the Pandoc AST. Represents the source-based ceiling that
existing tooling can reach.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base_adapter import ArxivBenchAdapter


class PandocAdapter(ArxivBenchAdapter):
    def __init__(self):
        if not shutil.which("pandoc"):
            raise RuntimeError("pandoc not installed")

    def name(self) -> str:
        return "Pandoc"

    def version(self) -> str:
        out = subprocess.run(
            ["pandoc", "--version"], capture_output=True, text=True, timeout=10,
        ).stdout.splitlines()
        return out[0].replace("pandoc ", "") if out else "unknown"

    def input_kind(self) -> str:
        return "tex"

    def parse(self, filepath: Path) -> dict[str, Any]:
        result = subprocess.run(
            ["pandoc", "--from=latex", "--to=json", str(filepath)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pandoc failed: {result.stderr[:500]}")
        ast = json.loads(result.stdout)
        return _count_pandoc_ast(ast)


def _count_pandoc_ast(ast: dict) -> dict[str, Any]:
    counts = {
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
    blocks = ast.get("blocks", [])
    for blk in blocks:
        _walk_block(blk, counts)
    return counts


def _walk_block(node: Any, counts: dict[str, int]) -> None:
    if not isinstance(node, dict):
        return
    t = node.get("t")
    c = node.get("c")
    if t == "Header":
        counts["sections"] += 1
        if isinstance(c, list) and len(c) >= 3:
            _walk_inlines(c[2], counts)
    elif t == "Table":
        counts["tables"] += 1
    elif t == "Figure":
        counts["figures"] += 1
    elif t in ("BulletList", "OrderedList", "DefinitionList"):
        counts["lists"] += 1
        if isinstance(c, list):
            for item in c:
                if isinstance(item, list):
                    for sub in item:
                        _walk_block(sub, counts)
    elif t in ("Para", "Plain"):
        if isinstance(c, list):
            _walk_inlines(c, counts)
    elif t == "Div":
        # Pandoc represents LaTeX amsthm theorem envs as Div with class.
        if isinstance(c, list) and len(c) >= 2:
            attr = c[0]
            classes = attr[1] if isinstance(attr, list) and len(attr) >= 2 else []
            if any(cl in _THEOREM_CLASSES for cl in classes):
                counts["theorems"] += 1
            for sub in c[1]:
                _walk_block(sub, counts)
    elif t == "BlockQuote":
        if isinstance(c, list):
            for sub in c:
                _walk_block(sub, counts)
    elif t in ("LineBlock",):
        pass
    elif t == "CodeBlock":
        pass
    # Walk anything else that has list children (defensive)


def _walk_inlines(inlines: Any, counts: dict[str, int]) -> None:
    if not isinstance(inlines, list):
        return
    for node in inlines:
        if not isinstance(node, dict):
            continue
        t = node.get("t")
        c = node.get("c")
        if t == "Math":
            # c is [{t:"InlineMath"|"DisplayMath"}, "source"]
            if isinstance(c, list) and len(c) >= 1:
                kind = c[0].get("t") if isinstance(c[0], dict) else ""
                if kind == "DisplayMath":
                    counts["equations_display"] += 1
                else:
                    counts["equations_inline"] += 1
        elif t == "Cite":
            # c is [citations_list, inlines]. Each citation has citationId.
            if isinstance(c, list) and len(c) >= 1 and isinstance(c[0], list):
                counts["citation_calls"] += len(c[0])
        elif isinstance(c, list):
            _walk_inlines(c, counts)


_THEOREM_CLASSES = {
    "theorem", "thm", "lemma", "lem", "corollary", "cor",
    "proposition", "prop", "definition", "defn", "remark", "rem",
    "claim", "observation", "obs", "conjecture", "conj",
    "example", "ex", "problem", "prob", "exercise", "fact", "note",
}
