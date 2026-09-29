"""Proves the office suite's positional gate still catches the v0.47.0 bugs.

`benchmarks/office/regressions/v0_47_0_prefix/` holds what the parser at
bc7f098 (before #73 and #75) produced for the four fixtures whose bugs all
scored 100% on the old suite:

    challenge_sparse_rows.xlsx   blank cells dropped (column shift), sheet
                                 names paired with the wrong sheet's data
    poi_two_sheets.xlsx          Sheet1 and Sheet2 data swapped
    pptx_slide_order_notes.pptx  slides in string order (1, 10, 11, ... 2),
                                 speaker notes not attached to their slide
    poi_comment.pptx             slides out of order around their comments

Each is scored against today's golden and MUST fail, with the message that
names the defect. If one of these ever passes, the gate has stopped seeing
structure and the suite's 100% means what it meant before v0.47.0.

It also checks every golden scores clean against itself (no false positives)
and that extracted-image temp paths are canonicalised whatever their format.

Pure Python, no parser needed: python3 benchmarks/check_structure_gate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "metrics"))
from normalize import LOCAL_IMAGE_SRC, canonicalize_output, is_local_image_path  # noqa: E402
from structure import check_structure  # noqa: E402

GOLDEN = ROOT / "office" / "golden"
PREFIX = ROOT / "office" / "regressions" / "v0_47_0_prefix"

# file -> (check that must fail, substring its report must contain)
EXPECTED = {
    "challenge_sparse_rows.xlsx": [
        ("table_grids", "row 2 col 3 (C2): expected 'Adapt' got 'adaptagency.com'"),
        ("table_grids", "sheet 'Summary': holds the data expected under sheet 'Tab 10'"),
    ],
    "poi_two_sheets.xlsx": [
        ("table_grids", "sheet 'Sheet1': holds the data expected under sheet 'Sheet2'"),
    ],
    "pptx_slide_order_notes.pptx": [
        ("sections", 'slide 1: expected slide "Kickoff" got slide "Timeline"'),
        ("sections", "notes 'Slide 1': missing (expected after slide \"Kickoff\")"),
    ],
    "poi_comment.pptx": [
        ("sections", 'slide 1: expected slide "Removing financing obstacles through pr'),
    ],
}


def _failed(check: dict) -> bool:
    keys = [k for k in check if k.endswith("_match")]
    return bool(check.get("applicable")) and bool(keys) and not all(check[k] for k in keys)


def main() -> int:
    errors: list[str] = []

    for fname, wants in EXPECTED.items():
        golden = json.loads((GOLDEN / f"{fname}.json").read_text(encoding="utf-8"))
        old = json.loads((PREFIX / f"{fname}.json").read_text(encoding="utf-8"))
        checks = check_structure(golden, old)
        for name, needle in wants:
            c = checks[name]
            if not _failed(c):
                errors.append(f"{fname}: pre-fix output PASSES {name}; the gate no longer sees this bug")
            elif not any(needle in d for d in c.get("diffs", [])):
                errors.append(f"{fname}: {name} fails but does not say {needle!r}; got:\n      "
                              + "\n      ".join(c.get("diffs", [])))
        if not errors or not errors[-1].startswith(fname):
            print(f"ok   {fname}: pre-fix output fails "
                  + ", ".join(sorted({n for n, _ in wants})))

    # No false positives: every golden against itself.
    clean = 0
    for g in sorted(GOLDEN.glob("*.json")):
        doc = json.loads(g.read_text(encoding="utf-8"))
        bad = [n for n, c in check_structure(doc, doc).items() if _failed(c)]
        if bad:
            errors.append(f"{g.name}: fails {bad} against ITSELF")
        else:
            clean += 1
    print(f"ok   {clean} goldens score clean against themselves")

    # Image temp paths, in any format G9 (or a Windows run) might produce.
    local = ["/tmp/docparse-images/docparse-img-0.jpeg",
             "/var/folders/x1/T/docparse-images/3f2a9c.png",
             "C:\\Users\\ci\\AppData\\Local\\Temp\\docparse-img-1.png",
             "\\\\server\\share\\img.png", "file:///tmp/a.png",
             "docparse-images/docparse-img-7.emf"]
    content = ["logo.png", "images/chart.png", "https://example.com/a.png",
               "data:image/png;base64,iVBORw0KGgo=", "/9j/4AAQSkZJRgABAQEAAQABAAD/2wBDAAMCAgI="]
    for s in local:
        if not is_local_image_path(s):
            errors.append(f"temp image path not canonicalised: {s!r}")
    for s in content:
        if is_local_image_path(s):
            errors.append(f"document image src wrongly treated as a temp path: {s!r}")
    a = {"document": {"filename": "/a/x.docx", "blocks": [
        {"type": "image", "mime": "image/png", "dataLength": 40, "src": local[0]}]}}
    b = {"document": {"filename": "/b/x.docx", "blocks": [
        {"type": "image", "mime": "image/png", "dataLength": 44, "src": local[1]}]}}
    if canonicalize_output(a) != canonicalize_output(b) or \
            canonicalize_output(a)["document"]["blocks"][0]["src"] != LOCAL_IMAGE_SRC:
        errors.append("two runs differing only in filename and temp path do not compare equal")
    if any(_failed(c) for c in check_structure(a, b).values()):
        errors.append("check_structure fails on a temp-path-only difference")
    print(f"ok   image temp paths: {len(local)} path formats canonicalised, {len(content)} srcs kept")

    if errors:
        print("\nFAIL")
        for e in errors:
            print(f"  {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
