"""Exact PPTX -> PPTX speaker-notes round trip for pptx_slide_order_notes.pptx.

PPTX -> PPTX conversion used to drop every speaker note: the generator kept
only SectionBlock(kind="slide") and wrote no notes parts at all, so
parse(convert(parse(deck))) came back with 0 of the fixture's 12 notes. The
office suite scores parse output only, and verify_generated.py checked that a
generated deck opens, so nothing saw the notes go (design doc G1).

For the plain generator and for three reference decks, this asserts:

  * the (kind, name, text) list of top-level sections is identical before and
    after the round trip — every note, every slide, in order;
  * each notes section directly follows the slide section it belongs to, and
    that slide is the one its "Slide N" name says;
  * the package wires each note the right way: slideN's notesSlide relation
    points at a notes part whose own slide relation points back at slideN, a
    notes master is listed in presentation.xml's <p:notesMasterIdLst> and
    related from it, and every notes part has a content-type override.

Reference decks, chosen for how they carry a notes master:

  pandoc_basic.pptx            none            -> ours is added
  poi_sampleshow.pptx          related+listed  -> reused
  pptx_slide_order_notes.pptx  related only    -> reused, id list added
                               (python-pptx writes no notesMasterIdLst)

Usage: python3 benchmarks/check_pptx_notes_roundtrip.py   (from the repo root)
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "data" / "test_files" / "pptx_slide_order_notes.pptx"
TEMPLATES = [None, "pandoc_basic.pptx", "poi_sampleshow.pptx", "pptx_slide_order_notes.pptx"]
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def docparse(outdir: Path, *args: str) -> None:
    subprocess.run([str(REPO / "bin" / "docparse"), *args], cwd=REPO, check=True,
                   capture_output=True, timeout=300,
                   env={**os.environ, "DOCPARSE_OUTPUT_DIR": str(outdir)})


def sections(outdir: Path, name: str) -> list[tuple[str, str, str]]:
    doc = json.load(open(outdir / f"{name}.json"))
    out = []
    for b in doc["document"]["blocks"]:
        if b.get("type") == "section":
            texts = [c.get("text", "") for c in b.get("blocks", [])]
            out.append((b.get("kind", ""), b.get("name", ""), "|".join(texts)))
    return out


def attachment_errors(secs: list[tuple[str, str, str]]) -> list[str]:
    """Each notes section must directly follow slide N, where N is its name."""
    errs, slide_no = [], 0
    for i, (kind, name, _) in enumerate(secs):
        if kind == "slide":
            slide_no += 1
        elif kind == "notes":
            if i == 0 or secs[i - 1][0] != "slide":
                errs.append(f"notes {name!r} does not directly follow a slide section")
            elif name != f"Slide {slide_no}":
                errs.append(f"notes {name!r} follows slide {slide_no}")
    return errs


def rels(z: zipfile.ZipFile, part: str) -> list[tuple[str, str, str]]:
    """(Id, Type suffix, resolved target) for a part's relationships."""
    d, f = posixpath.split(part)
    rp = f"{d}/_rels/{f}.rels"
    if rp not in z.namelist():
        return []
    out = []
    for m in re.finditer(r"<Relationship\s[^>]*>", z.read(rp).decode()):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(0)))
        out.append((a["Id"], a["Type"].rsplit("/", 1)[1],
                    posixpath.normpath(posixpath.join(d, a["Target"]))))
    return out


def package_errors(path: Path) -> list[str]:
    errs = []
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    ct = z.read("[Content_Types].xml").decode()
    pres = z.read("ppt/presentation.xml").decode()
    pres_rels = {i: (t, tgt) for i, t, tgt in rels(z, "ppt/presentation.xml")}

    ids = re.findall(r'<p:notesMasterId r:id="([^"]+)"', pres)
    if len(ids) != 1:
        errs.append(f"presentation.xml lists {len(ids)} notes masters, want 1")
    for i in ids:
        t, tgt = pres_rels.get(i, ("", ""))
        if t != "notesMaster" or tgt not in names:
            errs.append(f"notesMasterId {i} does not resolve to a notes master part")
    if len(re.findall(r'<p:notesMasterIdLst', pres)) > 1:
        errs.append("presentation.xml has more than one notesMasterIdLst")

    slide_parts = [tgt for i, (t, tgt) in pres_rels.items() if t == "slide"]
    for sp in slide_parts:
        for _, t, tgt in rels(z, sp):
            if t != "notesSlide":
                continue
            if tgt not in names:
                errs.append(f"{sp} -> missing notes part {tgt}")
                continue
            back = [x for _, tt, x in rels(z, tgt) if tt == "slide"]
            if back != [sp]:
                errs.append(f"{tgt} relates back to {back}, not {sp}")
            masters = [x for _, tt, x in rels(z, tgt) if tt == "notesMaster"]
            if len(masters) != 1 or masters[0] not in names:
                errs.append(f"{tgt} has no resolvable notes master ({masters})")
            if f'PartName="/{tgt}"' not in ct:
                errs.append(f"no content-type override for {tgt}")
    for n in names:
        if re.fullmatch(r"ppt/notes(Slides/notesSlide|Masters/notesMaster)\d+\.xml", n) \
                and f'PartName="/{n}"' not in ct:
            errs.append(f"no content-type override for {n}")
    return errs


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        docparse(out, str(FIXTURE))
        want = sections(out, FIXTURE.name)
        want_notes = [s for s in want if s[0] == "notes"]
        if not want_notes:
            print(f"FAIL source parse has no notes sections — fixture or parser broken")
            return 1
        for tpl in TEMPLATES:
            label = f"reference {tpl}" if tpl else "plain"
            deck = out / f"rt_{(tpl or 'plain').replace('.pptx', '')}.pptx"
            args = [str(FIXTURE), "--convert", str(deck)]
            if tpl:
                args += ["--reference-doc", str(REPO / "data" / "test_files" / tpl)]
            docparse(out, *args)
            docparse(out, str(deck))
            got = sections(out, deck.name)
            got_notes = [s for s in got if s[0] == "notes"]
            errs = []
            if got_notes != want_notes:
                errs.append(f"notes differ: {len(got_notes)} != {len(want_notes)}")
                for i in range(max(len(want_notes), len(got_notes))):
                    w = want_notes[i] if i < len(want_notes) else None
                    g = got_notes[i] if i < len(got_notes) else None
                    if w != g:
                        errs.append(f"  want {w}\n       got  {g}")
            elif got != want:
                errs.append("slide sections differ after the round trip")
                errs += [f"  want {w}\n       got  {g}" for w, g in zip(want, got) if w != g]
            errs += attachment_errors(got)
            errs += package_errors(deck)
            if errs:
                failures += 1
                print(f"FAIL {label}")
                for e in errs:
                    print(f"     {e}")
            else:
                print(f"ok   {label}: {len(got_notes)} notes, {len(got) - len(got_notes)} slides, "
                      f"each note on its own slide")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
