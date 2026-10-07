"""Exact checks for DOCX run and anchor fidelity, and the warnings channel.

The office suite scores text by bag-of-words and blocks by type sequence, so a
dropped run colour, a footnote whose text never arrives, a bookmark that
vanishes or a warning that never fires all still score 100%. Each check here
states what the fixture contains and requires exactly that back.

  challenge_formatting.docx        run colour (w:color) on PASSED/FAILED/WARNING
  challenge_run_details.docx       colour + highlight + shading, theme/auto
                                   colour, bookmarks (not _GoBack), an internal
                                   w:anchor link, field / custom-style / table
                                   bookmark warnings; DOCX and HTML round trip
  poi_footnotes.docx               footnote text, linked to its reference
  pandoc_notes.docx                footnote 1 and endnote 1 kept apart
  challenge_footnotes.docx         the public sample: both notes, no warnings
  challenge_footnote_no_part.docx  a reference with no footnotes part: warned
  challenge_fields.docx            cached field results: warned
  challenge_comment_orphans.docx   an unterminated comment range: warned

Usage: python3 benchmarks/check_docx_runs.py   (from the repo root)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

T = Path("data/test_files")
C = T / "challenge"

FAILURES = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)


def run(args):
    subprocess.run(["./bin/docparse", *args], check=True, capture_output=True)


def parse(fixture):
    with tempfile.TemporaryDirectory() as out:
        run([str(fixture), "--output-dir", out])
        doc = json.loads((Path(out) / f"{fixture.name}.json").read_text())
        md = (Path(out) / f"{fixture.name}.md").read_text()
        return doc, md


def convert(fixture, ext):
    with tempfile.TemporaryDirectory() as out:
        target = Path(out) / f"converted.{ext}"
        run([str(fixture), "--convert", str(target)])
        if ext == "html":
            return target.read_text()
        doc, _ = parse(target)
        return doc


def blocks(doc):
    return doc["document"]["blocks"]


def walk(bs):
    for b in bs:
        yield b
        yield from walk(b.get("blocks", []))


def runs_by_text(doc):
    out = {}
    for b in walk(blocks(doc)):
        for r in b.get("runs", []):
            out.setdefault(r["text"], r)
    return out


def sections(doc, kind):
    return {b.get("name", ""): b for b in blocks(doc)
            if b.get("type") == "section" and b.get("kind") == kind}


def section_text(sec):
    return " ".join(b.get("text", "") for b in sec.get("blocks", []))


# --- P5: run colour ----------------------------------------------------------

def check_formatting():
    doc, _ = parse(C / "challenge_formatting.docx")
    runs = runs_by_text(doc)
    for text, colour in (("PASSED", "#008000"), ("FAILED", "#ff0000"), ("WARNING", "#ffa500")):
        r = runs.get(text, {})
        check(r.get("color") == colour, f"formatting: {text} colour {r.get('color')!r}, want {colour}")
        check(r.get("bold") is True, f"formatting: {text} lost bold")
    check("color" not in runs.get(" — Sample A; ", {}), "formatting: uncoloured run gained a colour")
    check(doc["warnings"] == [], f"formatting: unexpected warnings {doc['warnings']}")


EXPECTED_RUN_COLOURS = {
    # text: (color, highlight)
    "ON TRACK": ("#00b050", None),
    "AT RISK": (None, "#ffff00"),             # w:highlight="yellow"
    "BLOCKED": ("#9c0006", "#ffc7ce"),        # w:color + run w:shd fill
    "PLANNED": ("#1f4e79", None),             # theme colour: w:val fallback
}

EXPECTED_RUN_DETAIL_WARNINGS = [
    "Paragraph style 'CalloutNote' is a custom style with no heading or list mapping; 1 paragraph(s) returned as plain text",
    "Field FILENAME returned as its cached result (1 occurrence(s)); the value is what Word last computed, not recomputed",
    "Field PAGE returned as its cached result (1 occurrence(s)); the value is what Word last computed, not recomputed",
    "1 bookmark(s) are in a table cell, a list item or between paragraphs and are not attached to any block: milestone_pilot",
]


def check_run_colours(doc, label):
    runs = runs_by_text(doc)
    for text, (colour, hl) in EXPECTED_RUN_COLOURS.items():
        r = runs.get(text, {})
        check(r.get("color") == colour, f"{label}: {text} colour {r.get('color')!r}, want {colour!r}")
        check(r.get("highlight") == hl, f"{label}: {text} highlight {r.get('highlight')!r}, want {hl!r}")
    # w:color="auto" is not a colour the document chose.
    auto = next((r for t, r in runs.items() if "default" in t), {})
    check("color" not in auto, f"{label}: auto colour came back as {auto.get('color')!r}")


def check_run_details():
    f = C / "challenge_run_details.docx"
    doc, md = parse(f)
    check_run_colours(doc, "run_details")

    # P6: the heading carries its bookmark; _GoBack is never listed.
    heading = blocks(doc)[0]
    check(heading.get("bookmarks") == ["overview"],
          f"run_details: heading bookmarks {heading.get('bookmarks')}, want ['overview']")
    all_marks = [m for b in walk(blocks(doc)) for m in b.get("bookmarks", [])]
    check("_GoBack" not in all_marks, "run_details: _GoBack reported as a bookmark")

    # The internal link resolves to the block carrying the bookmark.
    link = runs_by_text(doc).get("overview", {})
    check(link.get("href") == "#overview", f"run_details: internal link href {link.get('href')!r}")
    target = link.get("href", "#")[1:]
    check(any(target in b.get("bookmarks", []) for b in walk(blocks(doc))),
          f"run_details: link target {target!r} resolves to no block")
    check("[overview](#overview)" in md, "run_details: markdown lost the internal link")

    # P4: warnings, exactly.
    check(doc["warnings"] == EXPECTED_RUN_DETAIL_WARNINGS,
          "run_details: warnings\n      got  " + json.dumps(doc["warnings"], indent=1)
          + "\n      want " + json.dumps(EXPECTED_RUN_DETAIL_WARNINGS, indent=1))

    # DOCX -> DOCX keeps colour, highlight and the internal link.
    back = convert(f, "docx")
    check_run_colours(back, "run_details docx->docx")
    link2 = runs_by_text(back).get("overview", {})
    check(link2.get("href") == "#overview", f"run_details docx->docx: link href {link2.get('href')!r}")

    # DOCX -> HTML renders colour as style and the link with its anchor.
    html = convert(f, "html")
    for frag in ('<span style="color:#00b050">', 'background-color:#ffff00',
                 '<span style="color:#9c0006;background-color:#ffc7ce">',
                 '<a id="overview"></a>', '<a href="#overview">'):
        check(frag in html, f"run_details html: missing {frag!r}")

    # Determinism: the same bytes in, the same JSON out.
    again, _ = parse(f)
    check(again == doc, "run_details: two parses differ")


# --- P2b: footnote and endnote text ----------------------------------------

def note_ref(doc, href):
    return next((r for b in walk(blocks(doc)) for r in b.get("runs", []) if r.get("href") == href), None)


def check_poi_footnotes():
    doc, md = parse(T / "poi_footnotes.docx")
    body = blocks(doc)[0]
    check(body.get("text") == "Eto ochen prostoy[1] text so snoskoy",
          f"poi_footnotes: body text {body.get('text')!r}")
    ref = note_ref(doc, "#footnote-1")
    check(ref is not None and ref.get("text") == "[1]" and ref.get("vertAlign") == "superscript",
          f"poi_footnotes: reference run {ref}")
    fns = sections(doc, "footnote")
    check(list(fns) == ["1"], f"poi_footnotes: footnote sections {list(fns)}")
    check(section_text(fns.get("1", {})) == "snoska", f"poi_footnotes: note text {section_text(fns.get('1', {}))!r}")
    check("prostoy[^1] text" in md and "[^1]: snoska" in md, "poi_footnotes: markdown footnote pair missing")
    check(doc["warnings"] == [], f"poi_footnotes: unexpected warnings {doc['warnings']}")


def check_pandoc_notes():
    doc, md = parse(T / "pandoc_notes.docx")
    check(note_ref(doc, "#footnote-1") is not None, "pandoc_notes: no footnote reference run")
    check(note_ref(doc, "#endnote-1") is not None, "pandoc_notes: no endnote reference run")
    check(section_text(sections(doc, "footnote").get("1", {})) == "My note.", "pandoc_notes: footnote 1 text")
    check(section_text(sections(doc, "endnote").get("1", {})) ==
          "This is an endnote at the end of the document.", "pandoc_notes: endnote 1 text")
    check("[^1]: My note." in md and "[^e1]: This is an endnote" in md,
          "pandoc_notes: markdown keeps footnote 1 and endnote 1 apart")


def check_sample_footnotes():
    f = C / "challenge_footnotes.docx"
    doc, md = parse(f)
    check(section_text(sections(doc, "footnote").get("1", {})) ==
          "This is the first footnote with additional detail.", "challenge_footnotes: footnote text")
    check(section_text(sections(doc, "endnote").get("1", {})) ==
          "This endnote provides a reference citation.", "challenge_footnotes: endnote text")
    check(note_ref(doc, "#footnote-1") is not None and note_ref(doc, "#endnote-1") is not None,
          "challenge_footnotes: reference runs missing")
    check(doc["warnings"] == [], f"challenge_footnotes: unexpected warnings {doc['warnings']}")
    html = convert(f, "html")
    check('id="footnote-1"' in html and 'href="#footnote-1"' in html,
          "challenge_footnotes html: footnote link does not resolve")


# --- P4: warnings ------------------------------------------------------------

def check_warnings():
    doc, _ = parse(C / "challenge_footnote_no_part.docx")
    check(doc["warnings"] == ["1 footnote reference(s) but the package has no word/footnotes.xml part; "
                              "the footnote text is not available, only the reference mark"],
          f"footnote_no_part: warnings {doc['warnings']}")
    check(any("Figures are provisional[7] until the audit closes." == b.get("text") for b in blocks(doc)),
          "footnote_no_part: body text not kept")

    doc, _ = parse(C / "challenge_fields.docx")
    names = [w.split()[1] for w in doc["warnings"] if w.startswith("Field ")]
    check(names == ["DATE", "NUMPAGES", "FILENAME"], f"fields: field warnings {doc['warnings']}")

    doc, _ = parse(C / "challenge_comment_orphans.docx")
    check(doc["warnings"] == ["Comment range w:id=5 is opened (commentRangeStart) but never closed; "
                              "the comment is returned unanchored"],
          f"comment_orphans: warnings {doc['warnings']}")

    # Documents that need no approximation say nothing.
    for clean in (T / "sample.docx", C / "challenge_bookmarks.docx", C / "challenge_hyperlinks.docx",
                  T / "comments.docx", C / "challenge_equations.docx"):
        doc, _ = parse(clean)
        check(doc["warnings"] == [], f"{clean.name}: unexpected warnings {doc['warnings']}")


def main():
    for fn in (check_formatting, check_run_details, check_poi_footnotes, check_pandoc_notes,
               check_sample_footnotes, check_warnings):
        before = len(FAILURES)
        fn()
        print(f"  {'ok  ' if len(FAILURES) == before else 'FAIL'} {fn.__name__}")
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All DOCX run/anchor/warning checks passed.")


if __name__ == "__main__":
    main()
