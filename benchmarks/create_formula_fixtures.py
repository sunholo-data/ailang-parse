#!/usr/bin/env python3
"""Build the XLSX formula fixture with KNOWN expected values, and check it.

Until v0.44 a formula cell came back empty: the parser read <v> only, and the
public sample (challenge_formulas.xlsx, written by openpyxl) stores <v></v>,
so Profit and Total had neither a value nor a formula. No fixture had a cached
formula value, a shared formula or an array formula, so nothing noticed.

xlsx_formulas.xlsx is written here as raw SpreadsheetML (no openpyxl: it cannot
write cached values, shared formulas or array formulas), with fixed ZIP
timestamps so a rebuild is byte-identical. EXPECTED below is the oracle: the
values are the cached results the file stores, and the shared-formula
dependents' formulas are worked out by hand, not copied from the parser.

  Budget!D2:D4  shared formula (si=0), master B2*C2*Rates!$A$1, all cached
  Budget!E2:E4  shared formula (si=1) with a string literal that looks like a
                ref ("over A1"); E4 is saved WITHOUT a cached value
  Budget!F2:F4  array formula on F2, values only on F3:F4
  Budget!B5     SUM, D5 mixed absolute/relative, E5 t="b", B6 t="e"

Usage (from the repo root):
    python3 benchmarks/create_formula_fixtures.py            # (re)build
    python3 benchmarks/create_formula_fixtures.py --verify   # parse + compare
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "data" / "test_files" / "xlsx_formulas.xlsx"
CHALLENGE = REPO / "data" / "test_files" / "challenge" / "challenge_formulas.xlsx"

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def s(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def n(ref: str, v) -> str:
    return f'<c r="{ref}"><v>{v}</v></c>'


BUDGET = (
    '<row r="1">' + s("A1", "Item") + s("B1", "Units") + s("C1", "Price") + s("D1", "Cost")
    + s("E1", "Band") + s("F1", "Double") + '</row>'
    '<row r="2">' + s("A2", "Pens") + n("B2", 10) + n("C2", 2)
    + '<c r="D2"><f t="shared" ref="D2:D4" si="0">B2*C2*Rates!$A$1</f><v>20</v></c>'
    + '<c r="E2" t="str"><f t="shared" ref="E2:E4" si="1">IF(D2&gt;15,"over A1","ok")</f><v>over A1</v></c>'
    + '<c r="F2"><f t="array" ref="F2:F4">B2:B4*2</f><v>20</v></c></row>'
    '<row r="3">' + s("A3", "Paper") + n("B3", 5) + n("C3", 3)
    + '<c r="D3"><f t="shared" si="0"/><v>15</v></c>'
    + '<c r="E3" t="str"><f t="shared" si="1"/><v>ok</v></c>'
    + n("F3", 10) + '</row>'
    '<row r="4">' + s("A4", "Ink") + n("B4", 1) + n("C4", 40)
    + '<c r="D4"><f t="shared" si="0"/><v>40</v></c>'
    + '<c r="E4"><f t="shared" si="1"/><v></v></c>'
    + n("F4", 2) + '</row>'
    '<row r="5">' + s("A5", "Total") + '<c r="B5"><f>SUM(B2:B4)</f><v>16</v></c>'
    + '<c r="D5"><f>SUM($D$2:D4)</f><v>75</v></c>'
    + '<c r="E5" t="b"><f>D5&gt;50</f><v>1</v></c></row>'
    '<row r="6">' + s("A6", "Ratio") + '<c r="B6" t="e"><f>B5/0</f><v>#DIV/0!</v></c></row>'
)
RATES = '<row r="1">' + n("A1", 1) + '</row>'

# (row, col) in the table (row 0 = header) -> (text, formula). Cells absent
# here have no formula.
EXPECTED = {
    "Budget": {
        (1, 3): ("20", "B2*C2*Rates!$A$1"),
        (2, 3): ("15", "B3*C3*Rates!$A$1"),
        (3, 3): ("40", "B4*C4*Rates!$A$1"),
        (1, 4): ("over A1", 'IF(D2>15,"over A1","ok")'),
        (2, 4): ("ok", 'IF(D3>15,"over A1","ok")'),
        (3, 4): ("", 'IF(D4>15,"over A1","ok")'),
        (1, 5): ("20", "B2:B4*2"),
        (4, 1): ("16", "SUM(B2:B4)"),
        (4, 3): ("75", "SUM($D$2:D4)"),
        (4, 4): ("TRUE", "D5>50"),
        (5, 1): ("#DIV/0!", "B5/0"),
    },
}
EXPECTED_TEXT = {  # plain values that must be unchanged around the formulas
    "Budget": {(2, 5): "10", (3, 5): "2", (1, 1): "10"},
}
EXPECTED_WARNINGS = [
    'Sheet "Budget": 1 formula cell(s) have no cached value (the file was saved '
    'without calculating them); their formula is reported instead of a value'
]
EXPECTED_MD_LINE = '| Ink | 1 | 40 | 40 | =IF(D4>15,"over A1","ok") | 2 |'

# The public sample: openpyxl wrote <v></v>; the values Excel would cache.
CHALLENGE_CACHED = {"D2": "20000", "D3": "30000", "B4": "115000", "C4": "65000", "D4": "50000"}
CHALLENGE_EXPECTED = {(1, 3): ("20000", "B2-C2"), (2, 3): ("30000", "B3-C3"),
                      (3, 1): ("115000", "SUM(B2:B3)"), (3, 2): ("65000", "SUM(C2:C3)"),
                      (3, 3): ("50000", "SUM(D2:D3)")}


def sheet_xml(rows: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{NS}"><sheetData>{rows}</sheetData></worksheet>'


def build() -> None:
    parts = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        "xl/workbook.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{NS}" xmlns:r="{RNS}"><sheets>'
            '<sheet name="Budget" sheetId="1" r:id="rId1"/><sheet name="Rates" sheetId="2" r:id="rId2"/>'
            '</sheets></workbook>',
        "xl/_rels/workbook.xml.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '</Relationships>',
        "xl/worksheets/sheet1.xml": sheet_xml(BUDGET),
        "xl/worksheets/sheet2.xml": sheet_xml(RATES),
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(FIXTURE, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in parts.items():
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), body)
    print(f"wrote {FIXTURE.relative_to(REPO)}")


def store_challenge_cache() -> None:
    """Give challenge_formulas.xlsx the cached values openpyxl leaves out.

    Only sheet1.xml changes; every other part is copied byte for byte. Running
    it again is a no-op (the empty <v></v> it fills is gone).
    """
    with zipfile.ZipFile(CHALLENGE) as src:
        items = [(i, src.read(i.filename)) for i in src.infolist()]
    out = []
    for info, data in items:
        if info.filename == "xl/worksheets/sheet1.xml":
            xml = data.decode()
            for ref, v in CHALLENGE_CACHED.items():
                start = xml.index(f'<c r="{ref}"')
                end = xml.index("</c>", start)
                xml = xml[:start] + xml[start:end].replace("<v></v>", f"<v>{v}</v>") + xml[end:]
            data = xml.encode()
        out.append((info, data))
    with zipfile.ZipFile(CHALLENGE, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, data in out:
            dst.writestr(info, data)
    print(f"stored cached values in {CHALLENGE.relative_to(REPO)}")


def parse(path: Path, out: str) -> tuple[dict, str]:
    subprocess.run([str(REPO / "bin" / "docparse"), str(path), "--output-dir", out],
                   check=True, capture_output=True, cwd=REPO)
    return (json.loads((Path(out) / f"{path.name}.json").read_text()),
            (Path(out) / f"{path.name}.md").read_text())


def sheet_tables(doc: dict) -> dict:
    out = {}
    for b in doc["document"]["blocks"]:
        if b.get("kind") == "sheet":
            t = next(x for x in b["blocks"] if x["type"] == "table")
            out[b["name"]] = [t["headers"]] + t["rows"]
    return out


def cell(c) -> tuple[str, str]:
    return (c, "") if isinstance(c, str) else (c.get("text", ""), c.get("formula", ""))


def compare(name: str, rows: list, expected: dict, texts: dict) -> list[str]:
    errors = []
    got = {(r, c): cell(v) for r, row in enumerate(rows) for c, v in enumerate(row) if cell(v)[1]}
    for k in sorted(set(got) | set(expected)):
        if got.get(k) != expected.get(k):
            errors.append(f"{name} row {k[0]} col {k[1]}: got {got.get(k)}, expected {expected.get(k)}")
    for (r, c), t in texts.items():
        if cell(rows[r][c]) != (t, ""):
            errors.append(f"{name} row {r} col {c}: got {cell(rows[r][c])}, expected plain {t!r}")
    return errors


def verify() -> int:
    errors = []
    with tempfile.TemporaryDirectory() as out:
        doc, md = parse(FIXTURE, out)
        tables = sheet_tables(doc)
        for name, exp in EXPECTED.items():
            errors += compare(name, tables.get(name, []), exp, EXPECTED_TEXT.get(name, {}))
        if doc["warnings"] != EXPECTED_WARNINGS:
            errors.append(f"warnings: got {doc['warnings']}")
        if EXPECTED_MD_LINE not in md.splitlines():
            errors.append(f"markdown lacks {EXPECTED_MD_LINE!r}")

        cdoc, cmd = parse(CHALLENGE, out)
        errors += compare("challenge Revenue", sheet_tables(cdoc).get("Revenue", []), CHALLENGE_EXPECTED, {})
        if cdoc["warnings"]:
            errors.append(f"challenge warnings: got {cdoc['warnings']}")
        if "| Total | 115000 | 65000 | 50000 |" not in cmd.splitlines():
            errors.append("challenge markdown lacks the Total row values")
    if errors:
        print("FAIL xlsx formulas")
        for e in errors:
            print("  " + e)
        return 1
    print(f"OK xlsx formulas: {sum(map(len, EXPECTED.values()))} formula cells (shared, array, "
          f"typed caches, one uncached + warning) and the challenge sample's {len(CHALLENGE_EXPECTED)}")
    return 0


if __name__ == "__main__":
    if "--verify" in sys.argv:
        sys.exit(verify())
    build()
    if "--store-challenge-cache" in sys.argv:
        store_challenge_cache()
