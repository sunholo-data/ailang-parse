"""Exact cell-position and sheet-order check for challenge_sparse_rows.xlsx.

The office suite scores tables by bag-of-words Jaccard, so a value that lands
in the wrong column, or a sheet whose name is paired with another sheet's
data, still scores 100%. That is how both bugs this guards against shipped.

Usage: python3 benchmarks/check_xlsx_positions.py   (from the repo root)
       python3 benchmarks/check_xlsx_positions.py --expect-json
           print the expectations only; tests/browser/wasm-smoke.spec.ts holds
           the browser workbench to this same list.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURE = Path("data/test_files/challenge/challenge_sparse_rows.xlsx")

EXPECTED_SHEETS = ["Leads", "Summary"] + [f"Tab {n:02d}" for n in (2, 4, 5, 6, 7, 8, 9, 10, 11)]
EXPECTED_LEADS = [
    ["Jordan", "", "ExampleCo", "example-co.example", "Sam Placeholder", "CEO", "",
     "Intro call, 3 July 2026", "", "", ""],
    ["", "", "Northwind", "", "", "", "5551234", "", "", "", "no owner yet"],
    ["Ada", "Dr", "Analytical", "analytical.org", "Ada L", "CTO", "5550000",
     "Referral", "Won", "Mark", "signed"],
]

# Header of the first column of these sheets: pairs each name with its part.
EXPECTED_FIRST_HEADER = {"Summary": "Metric", "Tab 02": "Sheet part"}


def text(cell):
    return cell if isinstance(cell, str) else cell.get("text", "")


def main():
    if "--expect-json" in sys.argv:
        print(json.dumps({"sheets": EXPECTED_SHEETS, "leads": EXPECTED_LEADS,
                          "firstHeader": EXPECTED_FIRST_HEADER}))
        return
    with tempfile.TemporaryDirectory() as out:
        subprocess.run(["./bin/docparse", str(FIXTURE), "--output-dir", out],
                       check=True, capture_output=True)
        doc = json.loads((Path(out) / f"{FIXTURE.name}.json").read_text())["document"]

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

    if errors:
        print("FAIL challenge_sparse_rows.xlsx")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print(f"OK challenge_sparse_rows.xlsx: {len(names)} sheets in tab order, {len(rows)} rows column-exact")


if __name__ == "__main__":
    main()
