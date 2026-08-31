#!/usr/bin/env python3
"""Failure check: a parse that did not happen must not look like one that did.

Every other suite here scores documents that parsed. This one scores the
failures, because the ways a failure can be mistaken for a success are not
visible to any of them:

  - the office suite compares JSON goldens for files that parse
  - roundtrip_check re-parses markdown it just wrote
  - verify_generated opens generated Office files

None of them ever asks what happens when a parse *fails*. That gap shipped a
real defect: an explicit `--pdf-backend` failure was caught, formatted into a
sentence, and returned as the document's only block. The CLI then exited 0 and
wrote a 114-byte .md reading "PDF extraction failed: …". A nine-file batch
reported 9/9 succeeded with one contract replaced by its own error message,
and it was noticed only because someone was eyeballing output sizes.

The property, for every way a parse can fail:

  exit code is non-zero, and no output file is written

A file on disk must mean a document was parsed. Anything else and the caller
has no way to tell the two apart — which is what "9/9" meant.

The positive controls are load-bearing: making everything fail would satisfy
the property above, so a working parse is asserted to still exit 0 and write
real content.

Usage:
  uv run benchmarks/failure_check.py
  uv run benchmarks/failure_check.py --verbose
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST_DIR = REPO / "data" / "test_files"
DOCPARSE = REPO / "bin" / "docparse"

# A PDF header with no xref table or trailer. poppler rejects it, so the
# adapter exits non-zero — a backend failure with no network, no AI, no OCR
# and no dependence on how long a model takes.
CORRUPT_PDF = b"%PDF-1.4\nthis is not a real pdf body\n"


def run(args: list[str], out_path: Path) -> tuple[int, str, bool]:
    """Run docparse with --convert and report (exit code, output, file written)."""
    proc = subprocess.run(
        [str(DOCPARSE), *args, "--convert", str(out_path)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    return proc.returncode, proc.stdout + proc.stderr, out_path.exists()


def check_failure(name: str, args: list[str], tmp: Path,
                  expect_in_output: str, verbose: bool) -> list[str]:
    """A failing parse must exit non-zero AND leave no output file."""
    out = tmp / f"{name}.md"
    code, text, wrote = run(args, out)
    problems = []

    if code == 0:
        problems.append(f"{name}: exit 0 on a parse that failed")
    if wrote:
        size = out.stat().st_size
        body = out.read_text(errors="replace").strip()
        problems.append(
            f"{name}: wrote {size}-byte output for a failed parse "
            f"(this is the 9/9 bug: {body[:80]!r})"
        )
    if expect_in_output not in text:
        problems.append(f"{name}: message does not mention {expect_in_output!r}")

    if verbose:
        status = "FAIL" if problems else "ok"
        print(f"  [{status}] {name}: exit={code} wrote={wrote}")
    return problems


def check_success(name: str, args: list[str], tmp: Path,
                  min_bytes: int, verbose: bool) -> list[str]:
    """Positive control: a parse that works still writes a real document."""
    out = tmp / f"{name}.md"
    code, text, wrote = run(args, out)
    problems = []

    if code != 0:
        problems.append(f"{name}: exit {code} on a parse that should succeed")
    elif not wrote:
        problems.append(f"{name}: exit 0 but wrote no output file")
    elif out.stat().st_size < min_bytes:
        problems.append(
            f"{name}: wrote only {out.stat().st_size} bytes "
            f"(expected >= {min_bytes}); a stub is not a parse"
        )

    if verbose:
        size = out.stat().st_size if wrote else 0
        status = "FAIL" if problems else "ok"
        print(f"  [{status}] {name}: exit={code} bytes={size}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    good_pdf = TEST_DIR / "simple_text.pdf"
    if not good_pdf.exists():
        print(f"missing test file: {good_pdf}", file=sys.stderr)
        print("run: bash benchmarks/download_test_files.sh", file=sys.stderr)
        return 2

    problems: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        corrupt = tmp / "corrupt.pdf"
        corrupt.write_bytes(CORRUPT_PDF)

        unsupported = tmp / "thing.wombat"
        unsupported.write_text("not a format docparse knows")

        print("=== Failure check ===\n")
        print("failures must exit non-zero and write nothing:")

        # The reported defect: an explicit backend choice that fails. No AI
        # fallback is allowed here (the caller asked for something free), so
        # this is the branch that used to launder the error into content.
        problems += check_failure(
            "pdf_backend_failure",
            [str(corrupt), "--pdf-backend", "pdftotext"],
            tmp, "pdf_backend_failed", args.verbose,
        )

        # Same laundering, different route: a format nothing can parse.
        problems += check_failure(
            "unsupported_format",
            [str(unsupported)],
            tmp, "parse_refused", args.verbose,
        )

        print("\nsuccesses must still exit 0 and write a real document:")

        problems += check_success(
            "pdf_backend_success",
            [str(good_pdf), "--pdf-backend", "pdftotext"],
            tmp, 100, args.verbose,
        )

        problems += check_success(
            "docx_success",
            [str(TEST_DIR / "sample.docx")],
            tmp, 100, args.verbose,
        ) if (TEST_DIR / "sample.docx").exists() else []

    print()
    if problems:
        print(f"failures: {len(problems)}\n")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    print("failures: 0")
    print("\nNo failed parse produced an output file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
