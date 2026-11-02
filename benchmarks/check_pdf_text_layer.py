#!/usr/bin/env python3
"""A scanned PDF must not parse as a hollow success (pdf_text_layer_sparse).

2026-11-02: 78 page scans, each with one identical ~123-character stamp laid
over it, parsed with pdftotext to 156 blocks of 92% whitespace and 23 distinct
words. It returned success, so a downstream extractor ran on blank pages. The
stamp was enough text to get past "were any blocks extracted?".

Runs bin/docparse on synthetic PDFs (benchmarks/pdf/text_layer_fixtures.py,
built in a temp dir, nothing committed) and checks, end to end:

  scanned / scanned_blank  every text-layer backend (explicit pdftotext,
                           poppler; the default ladder; --convert to docx and
                           pptx) exits non-zero, writes nothing, and reports
                           pdf_text_layer_sparse with the statistics first and
                           no file path in the message
  partial                  succeeds, with a warning naming pages 5-6
  slides, forms            succeed with no text-layer warning at all: a deck
                           has little text per page, a form repeats on every
                           page, and neither is a scan

The default ladder escalates a scan to docling. Where docling is installed it
may recover the document, which is the ladder working, so that one case
accepts either outcome; where it is not (CI), the failure must be the sparse one.

Usage:
  python3 benchmarks/check_pdf_text_layer.py [--verbose]
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCPARSE = REPO / "bin" / "docparse"
STATS = re.compile(r"Error \[pdf_text_layer_sparse\]: pages=(\d+) pages_with_text=(\d+) distinct_words=(\d+): ")


def fixtures(out: Path) -> dict[str, Path]:
    spec = importlib.util.spec_from_file_location("fx", REPO / "benchmarks" / "pdf" / "text_layer_fixtures.py")
    fx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fx)
    return fx.write_fixtures(out)


def run(pdf: Path, args: list[str], out_dir: Path) -> tuple[int, str]:
    env = dict(os.environ, DOCPARSE_OUTPUT_DIR=str(out_dir))
    proc = subprocess.run([str(DOCPARSE), str(pdf), *args], capture_output=True, text=True, cwd=REPO, env=env)
    return proc.returncode, proc.stdout + proc.stderr


def check_sparse(name: str, pdf: Path, args: list[str], tmp: Path, pages: int,
                 allow_recovery: bool = False) -> list[str]:
    out_dir = tmp / f"out-{name}"
    out_dir.mkdir()
    if args[:1] == ["--convert"]:
        args = ["--convert", str(out_dir / f"converted{Path(args[1]).suffix}"), *args[2:]]
    code, text = run(pdf, args, out_dir)
    if allow_recovery and code == 0 and "recovered via docling" in text:
        return []
    problems = []
    if code == 0:
        problems.append(f"{name}: exit 0 on a scanned PDF (the hollow success)")
    written = [p.name for p in out_dir.iterdir()]
    if written:
        problems.append(f"{name}: wrote {written} for a failed parse")
    m = STATS.search(text)
    if not m:
        tail = "\n      ".join(text.strip().splitlines()[-3:])
        problems.append(f"{name}: no 'Error [pdf_text_layer_sparse]: pages=N pages_with_text=N distinct_words=N: '\n      {tail}")
        return problems
    if int(m.group(1)) != pages or int(m.group(2)) != 0:
        problems.append(f"{name}: stats {m.group(0)!r}, expected pages={pages} pages_with_text=0")
    line = text[m.start():].splitlines()[0]
    if str(pdf.parent) in line or pdf.name in line:
        problems.append(f"{name}: the message names the file; it goes to API callers verbatim")
    for remedy in ("--pdf-backend docling", "--pdf-backend ai", 'pdfBackend "ai"'):
        if remedy not in line:
            problems.append(f"{name}: the message does not give the remedy {remedy!r}")
    return problems


def check_success(name: str, pdf: Path, args: list[str], tmp: Path, warning: str | None) -> list[str]:
    out_dir = tmp / f"out-{name}"
    out_dir.mkdir()
    code, text = run(pdf, args, out_dir)
    if code != 0:
        tail = "\n      ".join(text.strip().splitlines()[-3:])
        return [f"{name}: exit {code} on a PDF with a real text layer\n      {tail}"]
    warnings = [ln for ln in text.splitlines() if "textless_pages=" in ln]
    if warning is None and warnings:
        return [f"{name}: text-layer warning on a document that is not scanned: {warnings[0][:120]}"]
    if warning is not None and not any(warning in w for w in warnings):
        return [f"{name}: no warning containing {warning!r} (got {warnings})"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    opts = ap.parse_args()
    if not (shutil.which("pdftotext") and shutil.which("pdfimages")):
        print("poppler (pdftotext, pdfimages) not on PATH; this check cannot run.", file=sys.stderr)
        return 2

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fx = fixtures(tmp / "fixtures")
        cases = []
        for name, pages in (("scanned", 6), ("scanned_blank", 4)):
            pdf = fx[f"{name}.pdf"]
            cases += [
                (f"{name}/pdftotext", lambda p=pdf, n=name, k=pages: check_sparse(f"{n}-pdftotext", p, ["--pdf-backend", "pdftotext"], tmp, k)),
                (f"{name}/poppler", lambda p=pdf, n=name, k=pages: check_sparse(f"{n}-poppler", p, ["--pdf-backend", "poppler"], tmp, k)),
                (f"{name}/default", lambda p=pdf, n=name, k=pages: check_sparse(f"{n}-default", p, [], tmp, k, allow_recovery=True)),
                (f"{name}/convert-docx", lambda p=pdf, n=name, k=pages: check_sparse(f"{n}-docx", p, ["--convert", "x.docx", "--pdf-backend", "pdftotext"], tmp, k)),
                (f"{name}/convert-pptx", lambda p=pdf, n=name, k=pages: check_sparse(f"{n}-pptx", p, ["--convert", "x.pptx"], tmp, k)),
            ]
        for backend in ("pdftotext", "poppler"):
            cases.append((f"partial/{backend}", lambda b=backend: check_success(
                f"partial-{b}", fx["partial.pdf"], ["--pdf-backend", b], tmp, "textless_pages=5-6 pages=6")))
            for name in ("slides", "forms"):
                cases.append((f"{name}/{backend}", lambda b=backend, n=name: check_success(
                    f"{n}-{b}", fx[f"{n}.pdf"], ["--pdf-backend", b], tmp, None)))
        cases.append(("slides/default", lambda: check_success("slides-default", fx["slides.pdf"], [], tmp, None)))

        print("=== Scanned PDF text-layer check ===\n")
        for label, case in cases:
            found = case()
            problems += found
            if opts.verbose or found:
                print(f"  [{'FAIL' if found else 'ok'}] {label}")

    print()
    if problems:
        print(f"failures: {len(problems)}\n")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print(f"failures: 0 ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
