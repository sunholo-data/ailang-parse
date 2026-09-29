"""Exact cell-position, row-position, sheet-order and comment-sheet checks.

The office suite scores tables by bag-of-words Jaccard, so a value that lands
in the wrong column or row, a sheet whose name is paired with another sheet's
data, or a comment attached to the wrong sheet still scores 100%. That is how
the bugs this guards against shipped.

  challenge_sparse_rows.xlsx          columns by r=, sheet order, rows by r= (Gaps)
  challenge_comments_multisheet.xlsx  comments resolved through sheet rels
  (the same, sheet rels stripped)     unlinked comment parts: unanchored + warned

Usage: python3 benchmarks/check_xlsx_positions.py   (from the repo root)
       python3 benchmarks/check_xlsx_positions.py --expect-json
           print the expectations only; tests/browser/wasm-smoke.spec.ts holds
           the browser workbench to this same list.
"""

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

FIXTURE = Path("data/test_files/challenge/challenge_sparse_rows.xlsx")

EXPECTED_SHEETS = ["Leads", "Summary", "Gaps"] + [f"Tab {n:02d}" for n in (2, 4, 5, 6, 7, 8, 9, 10, 11)]
EXPECTED_LEADS = [
    ["Jordan", "", "ExampleCo", "example-co.example", "Sam Placeholder", "CEO", "",
     "Intro call, 3 July 2026", "", "", ""],
    ["", "", "Northwind", "", "", "", "5551234", "", "", "", "no owner yet"],
    ["Ada", "Dr", "Analytical", "analytical.org", "Ada L", "CTO", "5550000",
     "Referral", "Won", "Mark", "signed"],
]
# Rows 1, 2, 5, 6, 400 exist. 3-4 are filled; 7-399 collapse to one separator.
EXPECTED_GAPS = [["r2", "2"], ["", ""], ["", ""], ["r5", "5"], ["r6", "6"], ["", ""], ["r400", "400"]]
EXPECTED_GAP_WARNING = "Sheet Gaps: rows 7-399 are empty; collapsed to one blank row."

COMMENTS_FIXTURE = Path("data/test_files/challenge/challenge_comments_multisheet.xlsx")
# (sheet the comment follows, author, text, anchorText), in document order
EXPECTED_COMMENTS = [
    ("Reviewed", "Ann", "Check this figure", "B1: 1200"),
    ("Threads", "Priya", "Is this final?", "C4: Q3 forecast"),
]
# With every sheet rels part removed, no sheet claims a comment part and there
# are three sheets, so nothing may be guessed onto a sheet: each part's
# comments come after the last sheet, unanchored, and each part is warned.
EXPECTED_ORPHANS = [(None, "Priya", "Is this final?", False), (None, "Ann", "Check this figure", False)]
EXPECTED_ORPHAN_WARNINGS = [
    f"Comment part {p} is not linked from any sheet; its comments are emitted unanchored after the last sheet."
    for p in ("xl/comments1.xml", "xl/comments2.xml", "xl/threadedComments/threadedComment1.xml")]


def parse(fixture):
    with tempfile.TemporaryDirectory() as out:
        subprocess.run(["./bin/docparse", str(fixture), "--output-dir", out],
                       check=True, capture_output=True)
        return json.loads((Path(out) / f"{fixture.name}.json").read_text())

# Header of the first column of these sheets: pairs each name with its part.
EXPECTED_FIRST_HEADER = {"Summary": "Metric", "Tab 02": "Sheet part"}


def text(cell):
    return cell if isinstance(cell, str) else cell.get("text", "")


def table_rows(section):
    table = next((b for b in (section or {}).get("blocks", []) if b["type"] == "table"), None)
    return [[text(c) for c in r] for r in (table or {}).get("rows", [])]


def check_comments():
    """Each comment follows its own sheet, anchored to that sheet's cell."""
    doc = parse(COMMENTS_FIXTURE)
    got, sheet = [], None
    for b in doc["document"]["blocks"]:
        if b.get("type") == "section" and b.get("kind") == "sheet":
            sheet = b["name"]
        elif b.get("type") == "section" and b.get("kind") == "comment":
            for c in b["blocks"]:
                got.append((sheet, c.get("author"), c.get("text"), c.get("anchorText")))
    errors = []
    if got != EXPECTED_COMMENTS:
        errors.append("comments on the wrong sheet/cell:\n  got      " + "\n           ".join(map(str, got))
                      + "\n  expected " + "\n           ".join(map(str, EXPECTED_COMMENTS)))
    if doc["warnings"]:
        errors.append(f"unexpected warnings: {doc['warnings']}")
    if errors:
        print(f"FAIL {COMMENTS_FIXTURE.name}")
        for e in errors:
            print("  " + e)
        return False
    print(f"OK {COMMENTS_FIXTURE.name}: {len(got)} comments on their own sheets")
    return True


def check_orphans():
    """Comment parts that no sheet links are kept, unanchored, with a warning."""
    with tempfile.TemporaryDirectory() as tmp:
        stripped = Path(tmp) / "comments_no_sheet_rels.xlsx"
        with zipfile.ZipFile(COMMENTS_FIXTURE) as src, zipfile.ZipFile(stripped, "w") as dst:
            for info in src.infolist():
                if not info.filename.startswith("xl/worksheets/_rels/"):
                    dst.writestr(info, src.read(info.filename))
        doc = parse(stripped)
    blocks = doc["document"]["blocks"]
    last_sheet = max(i for i, b in enumerate(blocks) if b.get("kind") == "sheet")
    got = []
    for i, b in enumerate(blocks):
        if b.get("kind") == "comment":
            for c in b["blocks"]:
                got.append((None if i > last_sheet else "before last sheet",
                            c.get("author"), c.get("text"), c.get("anchored")))
    errors = []
    if got != EXPECTED_ORPHANS:
        errors.append(f"orphan comments: got {got}, expected {EXPECTED_ORPHANS}")
    if doc["warnings"] != EXPECTED_ORPHAN_WARNINGS:
        errors.append(f"orphan warnings: got {doc['warnings']}")
    if errors:
        print("FAIL comments with no sheet rels")
        for e in errors:
            print("  " + e)
        return False
    print(f"OK comments with no sheet rels: {len(got)} kept unanchored after the last sheet, "
          f"{len(doc['warnings'])} parts warned")
    return True


def main():
    if "--expect-json" in sys.argv:
        print(json.dumps({"sheets": EXPECTED_SHEETS, "leads": EXPECTED_LEADS,
                          "firstHeader": EXPECTED_FIRST_HEADER}))
        return
    comments_ok = check_comments() & check_orphans()
    result = parse(FIXTURE)
    doc = result["document"]

    sheets = [b for b in doc["blocks"] if b.get("type") == "section" and b.get("kind") == "sheet"]
    names = [s["name"] for s in sheets]
    errors = []
    if names != EXPECTED_SHEETS:
        errors.append(f"sheet order/names: got {names}")

    by_name = {s["name"]: s for s in sheets}
    for name, first in EXPECTED_FIRST_HEADER.items():
        table = next((b for b in by_name.get(name, {}).get("blocks", []) if b["type"] == "table"), None)
        if not table or text(table["headers"][0]) != first:
            errors.append(f"sheet {name!r} is paired with the wrong part's data")

    leads = next((b for b in by_name.get("Leads", {}).get("blocks", []) if b["type"] == "table"), None)
    rows = [[text(c) for c in r] for r in (leads or {}).get("rows", [])]
    if rows != EXPECTED_LEADS:
        errors.append("Leads rows misaligned:\n  got      " + "\n           ".join(map(str, rows))
                      + "\n  expected " + "\n           ".join(map(str, EXPECTED_LEADS)))

    gaps = table_rows(by_name.get("Gaps"))
    if gaps != EXPECTED_GAPS:
        errors.append("Gaps rows misplaced:\n  got      " + "\n           ".join(map(str, gaps))
                      + "\n  expected " + "\n           ".join(map(str, EXPECTED_GAPS)))
    if result["warnings"] != [EXPECTED_GAP_WARNING]:
        errors.append(f"warnings: got {result['warnings']}, expected {[EXPECTED_GAP_WARNING]}")

    if errors:
        print("FAIL challenge_sparse_rows.xlsx")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print(f"OK challenge_sparse_rows.xlsx: {len(names)} sheets in tab order, {len(rows)} rows column-exact, "
          f"{len(gaps)} Gaps rows at their sheet positions")
    if not comments_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
