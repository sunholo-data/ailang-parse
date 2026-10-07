"""Exact DOCX structure checks: custom heading styles, nested lists, breaks.

The office suite compares against goldens written FROM the parser, so a golden
can carry a defect for as long as nobody looks at it: custom heading styles
came back as body text, every list paragraph as a separate one-item list, and
a page break as an empty paragraph, all at 100%. These expectations come from
how the fixtures were built (benchmarks/create_challenge_files.py and the
python-docx default template), not from parser output.

  challenge_styles.docx        ChapterTitle/SectionHeader/Subsection are based
                               on Heading 1/2/3 -> headings at those levels
  challenge_nested_lists.docx  List Bullet / 2 / 3 -> ONE list, levels 0-2
  challenge_numbering.docx     List Number / 2 / 3 and List Bullet / 2 / 3 ->
                               one numbered and one bulleted nested list
  challenge_page_breaks.docx   w:br page -> page-break marker (no empty text
                               block), mid-document sectPr -> section-break

Each fixture is also converted to .md and .docx; the .docx is parsed again and
must give back the same headings and the same list items, levels and kinds.

Usage: python3 benchmarks/check_docx_structure.py   (from the repo root)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

CHALLENGE = Path("data/test_files/challenge")


def H(level, text):
    return ("heading", level, text)


def P(text):
    return ("text", text)


def L(ordered, *items):
    """items: (level, text) pairs"""
    return ("list", ordered, tuple(items))


def BRK(kind):
    return ("section", kind)


EXPECTED = {
    "challenge_styles.docx": [
        H(1, "Annual Report 2025"),
        P("This document uses custom heading styles that inherit from built-in headings."),
        H(2, "Financial Overview"),
        P("Revenue grew 15% year-over-year driven by cloud services."),
        H(3, "Revenue Breakdown"),
        P("Cloud: $45M, On-prem: $12M, Services: $8M"),
        H(2, "Operational Highlights"),
        P("Headcount increased by 200 across engineering and sales."),
        H(3, "Engineering"),
        P("Shipped 3 major releases with 99.9% uptime."),
        H(1, "Appendix: Supplementary Data"),
        H(2, "Detailed financial tables"),
        BRK("section-break"),
    ],
    "challenge_nested_lists.docx": [
        H(1, "Project Requirements"),
        L(False, (0, "Frontend"), (1, "React components"), (2, "Button component"),
          (2, "Form component"), (1, "State management"), (0, "Backend"),
          (1, "API endpoints"), (1, "Database"), (2, "PostgreSQL schema"), (2, "Migrations")),
        H(2, "Timeline"),
        P("Phase 1: Design (2 weeks)"),
        P("Phase 2: Implementation (4 weeks)"),
        BRK("section-break"),
    ],
    "challenge_numbering.docx": [
        H(1, "Project Plan: Multi-Level Outline"),
        L(True, (0, "Introduction"), (1, "Background"), (1, "Objectives"),
          (2, "Primary objective"), (2, "Secondary objective"), (0, "Methodology"),
          (1, "Data collection"), (2, "Survey design"), (2, "Sample size calculation"),
          (2, "Recruitment strategy"), (1, "Analysis approach"), (0, "Results"),
          (0, "Discussion"), (1, "Limitations"), (1, "Future work")),
        H(2, "Requirements (Bullets)"),
        L(False, (0, "Must have features"), (1, "User authentication"), (1, "Data export"),
          (2, "CSV format"), (2, "JSON format"), (0, "Nice to have features"),
          (1, "Dark mode"), (1, "Keyboard shortcuts")),
        BRK("section-break"),
    ],
    "challenge_page_breaks.docx": [
        H(1, "Chapter 1: Introduction"),
        P("This is the first chapter content."),
        P("More content in chapter 1."),
        BRK("page-break"),
        H(1, "Chapter 2: Methods"),
        P("This is the second chapter after a page break."),
        BRK("section-break"),
        H(1, "Chapter 3: Results"),
        P("Third chapter after a section break."),
        BRK("section-break"),
    ],
}


def shape(b):
    t = b.get("type")
    if t == "heading":
        return H(b["level"], b["text"])
    if t == "text":
        return P(b["text"])
    if t == "section":
        return BRK(b.get("kind", ""))
    if t == "list":
        items = b["items"]
        levels = b.get("itemLevels") or [0] * len(items)
        kinds = b.get("itemOrdered") or [b["ordered"]] * len(items)
        if any(k != b["ordered"] for k in kinds):
            return ("list", "mixed", tuple(zip(levels, items, kinds)))
        return L(b["ordered"], *zip(levels, items))
    return (t,)


def run(args, cwd):
    return subprocess.run(["./bin/docparse", *args, "--output-dir", cwd],
                          capture_output=True, text=True)


def parse(path, out):
    r = run([str(path)], out)
    if r.returncode != 0:
        raise RuntimeError(f"parse {path} failed: {r.stderr[-500:]}")
    return json.loads((Path(out) / f"{Path(path).name}.json").read_text())["document"]["blocks"]


def structural(blocks):
    """What a docx -> docx trip owes us: headings and lists, in order."""
    return [shape(b) for b in blocks if b.get("type") in ("heading", "list")]


def main() -> int:
    failures = []
    for name, want in EXPECTED.items():
        src = CHALLENGE / name
        with tempfile.TemporaryDirectory() as out:
            got = [shape(b) for b in parse(src, out)]
            if got != want:
                failures.append(f"{name}: block sequence differs")
                for i in range(max(len(got), len(want))):
                    g = got[i] if i < len(got) else None
                    w = want[i] if i < len(want) else None
                    if g != w:
                        failures.append(f"    block {i}: expected {w!r}\n               got {g!r}")
                continue

            # Round trips: neither may crash, and docx -> docx must keep the
            # headings and the nesting.
            md = Path(out) / "rt.md"
            r = run([str(src), "--convert", str(md)], out)
            if r.returncode != 0 or not md.exists() or md.stat().st_size == 0:
                failures.append(f"{name}: docx -> md failed: {r.stderr[-300:]}")
            docx = Path(out) / "rt.docx"
            r = run([str(src), "--convert", str(docx)], out)
            if r.returncode != 0 or not docx.exists():
                failures.append(f"{name}: docx -> docx failed: {r.stderr[-300:]}")
                continue
            again = structural(parse(docx, out))
            if again != structural_from_shapes(want):
                failures.append(f"{name}: docx -> docx -> parse lost structure:\n"
                                f"    expected {structural_from_shapes(want)!r}\n"
                                f"         got {again!r}")
        print(f"  {'FAIL' if any(f.startswith(name) for f in failures) else 'ok  '} {name}")

    if failures:
        print("\n".join(failures))
        return 1
    print("DOCX structure: headings, nested lists and breaks exact; round trips intact.")
    return 0


def structural_from_shapes(shapes):
    return [s for s in shapes if s[0] in ("heading", "list")]


if __name__ == "__main__":
    sys.exit(main())
