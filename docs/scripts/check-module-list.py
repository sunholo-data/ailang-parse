#!/usr/bin/env python3
"""Assert bin/docparse's MODULES array lists every .ail module under docparse/.

MODULES drives --check and --prove. It was hand-maintained and had drifted: an
audit found 12 modules in neither, including tex_parser.ail, which carries 19
contracts — more than any other module in the repo. Nothing type-checked it and
nothing verified it, so a break there would have reached a release green.

This runs in CI so the list cannot silently fall behind again.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "bin" / "docparse"
SRC = ROOT / "docparse"


def listed_modules() -> set[str]:
    text = CLI.read_text()
    m = re.search(r"^MODULES=\((.*?)^\)", text, re.S | re.M)
    if not m:
        sys.exit("could not find the MODULES=( ... ) array in bin/docparse")
    body = m.group(1)
    # Drop comment lines so a commented-out path never counts as listed.
    lines = [ln.split("#", 1)[0] for ln in body.splitlines()]
    return set(re.findall(r"docparse/[\w/]+\.ail", "\n".join(lines)))


def actual_modules() -> set[str]:
    return {str(p.relative_to(ROOT)) for p in SRC.rglob("*.ail")}


def main() -> int:
    listed, actual = listed_modules(), actual_modules()

    missing = sorted(actual - listed)
    stale = sorted(listed - actual)

    for path in missing:
        n = len(re.findall(r"^\s*(?:requires|ensures) ", Path(ROOT / path).read_text(), re.M))
        print(f"  MISSING from MODULES: {path}  (contracts: {n})")
    for path in stale:
        print(f"  STALE in MODULES (no such file): {path}")

    if missing or stale:
        print(
            f"\nFAIL: bin/docparse MODULES is out of sync "
            f"({len(missing)} missing, {len(stale)} stale).\n"
            "--check and --prove only cover what this array lists."
        )
        return 1

    print(f"MODULES lists all {len(actual)} modules under docparse/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
