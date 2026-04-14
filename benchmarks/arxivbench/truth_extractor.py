"""Structural truth extractor for arXiv LaTeX source.

Extracts structural element counts directly from raw .tex files using
simple, reliable regex. These counts are the "ground truth" against
which each adapter's output is scored — no hand-curation required.

This works because .tex source is authoritative: if the source contains
\\section{Introduction}, a correct parser must emit that heading. If the
source has 42 equations, a correct parser must preserve 42 equation
blocks (modulo trivial normalization).

Limitations:
- We count, we don't compare content. A parser that emits 42 random
  equations scores equally with one that emits the 42 right ones. In
  practice structural drift is the dominant failure mode for PDF-OCR
  baselines, so counts are a useful first signal.
- Macro-defined sectioning (harvmac \\chap, \\sec) is not counted; those
  papers show as "0 sections" in truth, consistent with our scope.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# --- Regex fragments ---------------------------------------------------------

# Strip comments before counting. A comment starts at an unescaped %.
COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)

# Sectioning commands. Note that starred variants (\section*) and optional
# args (\section[short]{full}) both count.
SECTION_RE = re.compile(
    r"\\(chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*(?:\[[^\]]*\])?\s*\{",
)

# Display equations.  $$...$$ and \[...\] count as one each.  equation/align/
# gather/multline/eqnarray envs count as one each (align with \\ inside is
# still one display).
DISPLAY_DOLLAR_RE = re.compile(r"(?<!\\)\$\$[^$]+\$\$", re.DOTALL)
DISPLAY_BRACKET_RE = re.compile(r"\\\[.+?\\\]", re.DOTALL)
DISPLAY_ENV_NAMES = (
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "eqnarray", "eqnarray*", "flalign", "flalign*",
)

# Inline math: $...$ not preceded by \ and not $$.
INLINE_MATH_RE = re.compile(r"(?<!\\)(?<!\$)\$(?!\$)[^$]+?(?<!\\)\$(?!\$)")

# Tables
TABULAR_RE = re.compile(r"\\begin\{tabular[x*]?\}")

# Citations
CITE_RE = re.compile(r"\\(?:cite|citep|citet|citeauthor|citeyear|citealp|citealt)\*?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")

# Bibliography entries
BIBITEM_RE = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{")

# Figures
FIGURE_RE = re.compile(r"\\begin\{figure\*?\}")

# List envs
LIST_RE = re.compile(r"\\begin\{(itemize|enumerate|description)\}")

# Theorem-like envs (matches the set recognized by tex_parser.ail)
THEOREM_ENV_NAMES = (
    "theorem", "thm", "lemma", "lem", "corollary", "cor",
    "proposition", "prop", "definition", "defn", "defi",
    "remark", "rem", "claim", "observation", "obs",
    "conjecture", "conj", "example", "ex", "problem", "prob",
    "exercise", "fact", "note", "parag",
)


def _strip_comments(src: str) -> str:
    return COMMENT_RE.sub("", src)


def _count_env(src: str, env_names: tuple[str, ...]) -> int:
    total = 0
    for name in env_names:
        total += len(re.findall(r"\\begin\{" + re.escape(name) + r"\}", src))
    return total


def extract_truth(tex_source: str) -> dict[str, Any]:
    """Return structural element counts from raw LaTeX source."""
    src = _strip_comments(tex_source)

    sections = len(SECTION_RE.findall(src))
    display_envs = _count_env(src, DISPLAY_ENV_NAMES)
    display_dollars = len(DISPLAY_DOLLAR_RE.findall(src))
    display_brackets = len(DISPLAY_BRACKET_RE.findall(src))
    equations_display = display_envs + display_dollars + display_brackets
    equations_inline = len(INLINE_MATH_RE.findall(src))

    tables = len(TABULAR_RE.findall(src))
    figures = len(FIGURE_RE.findall(src))

    citation_calls = CITE_RE.findall(src)
    citation_keys: set[str] = set()
    for group in citation_calls:
        for key in group.split(","):
            key = key.strip()
            if key:
                citation_keys.add(key)

    bib_entries = len(BIBITEM_RE.findall(src))
    lists = len(LIST_RE.findall(src))
    theorems = _count_env(src, THEOREM_ENV_NAMES)

    has_documentclass = bool(re.search(r"\\documentclass", src))
    has_begin_document = bool(re.search(r"\\begin\{document\}", src))
    has_input = bool(re.search(r"\\(?:input|include)\b", src))

    return {
        "sections": sections,
        "equations_display": equations_display,
        "equations_inline": equations_inline,
        "tables": tables,
        "figures": figures,
        "citation_calls": len(citation_calls),
        "citation_unique_keys": len(citation_keys),
        "bibliography_entries": bib_entries,
        "lists": lists,
        "theorems": theorems,
        "has_documentclass": has_documentclass,
        "has_begin_document": has_begin_document,
        "uses_input": has_input,
        "source_bytes": len(tex_source),
    }


def extract_truth_from_file(tex_path: Path) -> dict[str, Any]:
    with open(tex_path, encoding="utf-8", errors="replace") as f:
        return extract_truth(f.read())


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("usage: truth_extractor.py <tex-file> [<tex-file> ...]", file=sys.stderr)
        sys.exit(1)

    out = {}
    for path_str in sys.argv[1:]:
        p = Path(path_str)
        out[p.name] = extract_truth_from_file(p)
    print(json.dumps(out, indent=2))
