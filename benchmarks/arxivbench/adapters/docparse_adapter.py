"""AILANG Parse adapter for arxivbench.

Runs AILANG Parse on a .tex file and normalizes the JSON output to the
arxivbench structural-count schema.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base_adapter import ArxivBenchAdapter


REPO_DIR = Path(__file__).parent.parent.parent.parent


class DocParseAdapter(ArxivBenchAdapter):
    def name(self) -> str:
        return "AILANG Parse"

    def version(self) -> str:
        return "0.15.0-dev"

    def input_kind(self) -> str:
        return "tex"

    def parse(self, filepath: Path) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                **os.environ,
                "AILANG_NO_TRACE": "1",
                "DOCPARSE_OUTPUT_DIR": tmpdir,
            }
            result = subprocess.run(
                [
                    "ailang", "run", "--entry", "main",
                    "--caps", "IO,FS,Env",
                    "--max-recursion-depth", "50000",
                    "docparse/main.ail", str(filepath),
                ],
                capture_output=True, text=True,
                cwd=str(REPO_DIR), timeout=300, env=env,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"AILANG Parse failed: {result.stderr[:500]}"
                )
            out_path = Path(tmpdir) / f"{filepath.name}.json"
            if not out_path.exists():
                raise RuntimeError(f"Missing output: {out_path}")
            with open(out_path) as f:
                raw = json.load(f)

        return _count_blocks(raw.get("document", {}).get("blocks", []))


# Inline-math markers left in TextBlock text by the LaTeX parser are
# preserved as `$...$` spans inside paragraph text. Count them so adapters
# are comparable on inline-math fidelity.
INLINE_MATH_RE = re.compile(r"(?<!\\)\$[^$]+\$")
# Citation markers left as [cite:key] or [cite:key,key2] inline.
CITE_MARKER_RE = re.compile(r"\[cite:([^\]]+)\]")


def _count_blocks(blocks: list[dict]) -> dict[str, Any]:
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

    def walk(bs: list[dict]):
        for b in bs:
            btype = b.get("type", "")
            style = b.get("style", "")
            if btype == "heading":
                text = b.get("text", "")
                # Theorem-env HeadingBlocks are level=4 with labels like
                # "Theorem" / "Lemma (Uniqueness)". Count them as theorems
                # only, not sections, so the two columns don't double-count.
                is_theorem = b.get("level") == 4 and any(
                    text.startswith(lab) for lab in (
                        "Theorem", "Lemma", "Corollary", "Proposition",
                        "Definition", "Remark", "Claim", "Observation",
                        "Conjecture", "Example", "Problem", "Exercise",
                        "Fact", "Note", "Paragraph",
                    )
                )
                if is_theorem:
                    counts["theorems"] += 1
                else:
                    counts["sections"] += 1
            elif btype == "text":
                if style == "equation-display":
                    counts["equations_display"] += 1
                elif style == "bibitem":
                    counts["bibliography_entries"] += 1
                # Inline math and citation markers live in text content
                text = b.get("text", "")
                counts["equations_inline"] += len(INLINE_MATH_RE.findall(text))
                for m in CITE_MARKER_RE.finditer(text):
                    keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
                    counts["citation_calls"] += len(keys) if keys else 1
            elif btype == "table":
                counts["tables"] += 1
            elif btype == "image":
                counts["figures"] += 1
            elif btype == "list":
                counts["lists"] += 1
            elif btype == "section":
                walk(b.get("blocks", []))

    walk(blocks)
    return counts
