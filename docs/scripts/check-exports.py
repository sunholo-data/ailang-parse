"""Every module an exported module imports must itself be exported.

A package consumer (docparse, the hosted API) loads exported modules from the
installed package; an import of a module missing from [exports] fails there
with LDR001 'module not found' — while the CLI, which runs from the package's
own files, keeps working, so nothing else notices. ailang_parse 0.54.0 shipped
that way (pdf_furniture) and could not be loaded by docparse.

    python3 docs/scripts/check-exports.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    toml = (REPO / "ailang.toml").read_text()
    block = toml[toml.index("[exports]"):]
    block = block[:block.index("]", block.index("modules")) + 1]
    exports = set(re.findall(r'"(docparse/[^"]+)"', block))
    seen: set[str] = set()
    todo = list(exports)
    missing: dict[str, str] = {}
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = REPO / f"{mod}.ail"
        if not path.exists():
            print(f"exported module has no source: {mod}", file=sys.stderr)
            return 1
        for imp in re.findall(r"^import (docparse/[A-Za-z0-9_/]+)", path.read_text(), re.M):
            if imp not in exports:
                missing.setdefault(imp, mod)
            todo.append(imp)
    if missing:
        for imp, by in sorted(missing.items()):
            print(f"::error::{imp} is imported by {by} but not in ailang.toml [exports]")
        return 1
    print(f"exports cover every imported module ({len(exports)} exported, {len(seen)} reachable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
