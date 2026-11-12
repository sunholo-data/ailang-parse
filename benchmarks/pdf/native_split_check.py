"""Native page split: is every split page the page it came from?

docparse/services/pdf_pages.ail cuts a PDF into single-page PDFs without any
external tool. This check renders each page twice with poppler, once from the
original and once from its split file, and requires the two images to be
identical. A page that lost a font, an image or an inherited page box renders
differently, so this catches what a page count cannot.

It also reports files the splitter refused (encrypted, or a structure it does
not follow). A refusal is not a failure: callers fall back.

Usage:
    python3 benchmarks/pdf/native_split_check.py                  # the repo's own PDFs
    python3 benchmarks/pdf/native_split_check.py a.pdf dir/ ...   # these files / folders

Needs ailang and poppler (pdfinfo, pdftoppm). Exit code 1 if any page differs.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TOOL = "docparse/services/pdf_pages_tool.ail"


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def render(pdf: Path, page: int) -> tuple[str, int]:
    r = subprocess.run(["pdftoppm", "-r", "40", "-f", str(page), "-l", str(page), "-gray", str(pdf)],
                       capture_output=True)
    return hashlib.md5(r.stdout).hexdigest(), len(r.stdout)


def collect(args: list[str]) -> list[Path]:
    if not args:
        roots = [REPO / "data", REPO / "benchmarks", REPO / "docs" / "templates"]
    else:
        roots = [Path(a) for a in args]
    found: list[Path] = []
    for r in roots:
        found.extend(sorted(r.rglob("*.pdf")) if r.is_dir() else [r])
    return found


def main() -> int:
    pdfs = collect(sys.argv[1:])
    files = pages = same = refused = 0
    differ: list[str] = []
    refusals: list[str] = []
    seconds = 0.0
    for pdf in pdfs:
        n = page_count(pdf)
        if n == 0:
            continue  # poppler cannot read it either: nothing to compare against
        files += 1
        with tempfile.TemporaryDirectory(prefix="native-split-") as tmp:
            t0 = time.time()
            r = subprocess.run(["ailang", "run", "--entry", "main", "--caps", "IO,FS,Env", TOOL,
                                str(pdf.resolve()), f"{tmp}/p"], capture_output=True, text=True, cwd=REPO, timeout=900)
            seconds += time.time() - t0
            if f"pages={n}" not in r.stdout:
                refused += 1
                why = next((l for l in r.stdout.splitlines() if l.startswith(("error:", "pages="))), r.stderr.strip()[-120:])
                refusals.append(f"{pdf.name}: {why}")
                if "pages=" in r.stdout:   # split, but a different page count: a real fault
                    differ.append(f"{pdf.name}: {why}, pdfinfo says {n}")
                continue
            for k in range(1, n + 1):
                pages += 1
                a, b = render(pdf, k), render(Path(f"{tmp}/p-{k}.pdf"), 1)
                if a == b and a[1] > 0:
                    same += 1
                else:
                    differ.append(f"{pdf.name} page {k}")
    print(f"native split: {files} files, {pages} pages split, {same} identical, {len(differ)} different, "
          f"{refused} files refused, {seconds:.0f}s in the splitter")
    for line in refusals:
        print(f"  refused  {line}")
    for line in differ:
        print(f"  DIFFERENT  {line}")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
