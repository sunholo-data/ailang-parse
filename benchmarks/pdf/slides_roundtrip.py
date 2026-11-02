"""Slides round trip: how well each PDF backend turns a deck exported to PDF
back into an editable deck, scored against the deck the PDF was made from.

For every source PPTX: render it to PDF with LibreOffice, parse the source
(ground truth), convert the PDF back to PPTX with each backend, parse that,
and compare:

  slides     slide count agreement (min/max of the two counts)
  titles     recall of the source slides' titles among the output's headings
  text       recall of the source's words anywhere in the output, speaker
             notes included (diagram labels move there)
  tables     table cell F1
  pictures   pictures in the output (embedded images and diagram pages)
  overflow   shapes that extend past the bottom of their slide (must be 0)

Sources are our own test decks; never add a deck from a bug report.

Usage:
    python3 benchmarks/pdf/slides_roundtrip.py
    python3 benchmarks/pdf/slides_roundtrip.py --backends default,docling --per-file
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
CLI = REPO / "bin" / "docparse"

_spec = importlib.util.spec_from_file_location("structure_roundtrip", Path(__file__).parent / "structure_roundtrip.py")
_sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sr)
norm, words, f1 = _sr.norm, _sr.words, _sr.f1

DEFAULT_SOURCES = [
    "data/test_files/pandoc_basic.pptx",
    "data/test_files/poi_sampleshow.pptx",
    "data/test_files/pptx_inline_formatting.pptx",
    "data/test_files/pptx_slide_order_notes.pptx",
    "data/test_files/unstructured_test.pptx",
    "data/test_files/poi_table.pptx",
    "data/test_files/python_pptx_table.pptx",
    "docs/assets/challenge_speaker_notes.pptx",
]
# "default" is no --pdf-backend: the CLI reads slides with poppler's slide mode.
DEFAULT_BACKENDS = ["default", "docling", "pdftotext"]
SLIDE_H = 6858000


def deck(json_path: Path, with_notes: bool) -> dict:
    """A parsed deck. `with_notes` False drops speaker notes: a source deck's
    notes never reach its PDF, so no backend could recover them."""
    blocks = json.loads(json_path.read_text()).get("document", {}).get("blocks", [])
    out = {"slides": 0, "titles": [], "firsts": [], "headings": [], "text": [], "cells": [], "pictures": 0}

    def walk(bs: list, in_slide: bool, first: list):
        for b in bs:
            t = b.get("type")
            if t == "section":
                if b.get("kind") == "slide":
                    out["slides"] += 1
                    walk(b.get("blocks", []), True, [True])
                elif b.get("kind") == "notes" and not with_notes:
                    continue
                else:
                    walk(b.get("blocks", []), in_slide, first)
                continue
            if t == "heading":
                out["headings"].append(norm(b.get("text", "")))
                if first[0]:
                    out["titles"].append(norm(b.get("text", "")))
            if first[0] and b.get("text"):
                # Generated titles are text boxes, not title placeholders, so a
                # parse of the output reads them as text: the first block of a
                # slide is its title either way.
                out["firsts"].append(norm(b.get("text", "")))
            if t in ("heading", "text") or b.get("text"):
                out["text"].append(b.get("text", ""))
            if t == "list":
                out["text"].extend(b.get("items", []))
            if t == "table":
                cells = [c.get("text", "") if isinstance(c, dict) else str(c)
                         for row in [b.get("headers", [])] + b.get("rows", []) for c in row]
                out["cells"].extend(norm(c) for c in cells if norm(c))
                out["text"].extend(cells)
            if t == "image":
                out["pictures"] += 1
            if t not in ("section",):
                first[0] = False

    walk(blocks, False, [False])
    return out


def overflow(pptx: Path) -> int:
    count = 0
    with zipfile.ZipFile(pptx) as z:
        for name in z.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                xml = z.read(name).decode("utf-8", "replace")
                for y, cy in re.findall(r'<a:off x="\d+" y="(\d+)"/><a:ext cx="\d+" cy="(\d+)"/>', xml):
                    if int(y) + int(cy) > SLIDE_H:
                        count += 1
    return count


def score(src: dict, got: dict, over: int) -> dict:
    titles = [t for t in src["titles"] if t]
    heads = set(got["headings"]) | set(got["firsts"])
    sw, gw = words(" ".join(src["text"])), words(" ".join(got["text"]))
    return {
        "slides": (min(src["slides"], got["slides"]) / max(src["slides"], got["slides"])) if max(src["slides"], got["slides"]) else None,
        "titles": (sum(1 for t in titles if t in heads or any(t in h for h in heads)) / len(titles)) if titles else None,
        "text": (len(sw & gw) / len(sw)) if sw else None,
        "tables": f1(src["cells"], got["cells"]),
        "pictures": got["pictures"],
        "overflow": over,
    }


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    return p.stdout + p.stderr


METRICS = ["slides", "titles", "text", "tables", "pictures", "overflow"]


def fmt(v, m: str) -> str:
    if v is None:
        return "—"
    return str(v) if m in ("pictures", "overflow") else f"{v * 100:.0f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--backends", default=",".join(DEFAULT_BACKENDS))
    ap.add_argument("--sources", nargs="*", default=DEFAULT_SOURCES)
    ap.add_argument("--per-file", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args()
    if not shutil.which("soffice"):
        print("soffice (LibreOffice) is required", file=sys.stderr)
        return 2
    sources = [REPO / s for s in args.sources]
    backends = [b for b in args.backends.split(",") if b]
    results: dict = {}
    with tempfile.TemporaryDirectory(prefix="slides-roundtrip-") as tmp:
        work = Path(tmp)
        (work / "pdf").mkdir()
        run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(work / "pdf"), *map(str, sources)])
        run([str(CLI), *map(str, sources), "--output-dir", str(work / "src")])
        pairs = []
        for s in sources:
            pdf, js = work / "pdf" / f"{s.stem}.pdf", work / "src" / f"{s.name}.json"
            # A deck with no text (placeholder-only slides) has nothing to score.
            if pdf.exists() and js.exists() and subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout.strip():
                pairs.append((s, pdf, deck(js, with_notes=False)))
        for backend in backends:
            per = {}
            for s, pdf, truth in pairs:
                out = work / backend / f"{s.stem}.pptx"
                out.parent.mkdir(exist_ok=True)
                cmd = [str(CLI), str(pdf), "--convert", str(out), "--output-dir", str(work / backend / "o")]
                if backend != "default":
                    cmd[2:2] = ["--pdf-backend", backend]
                log = run(cmd)
                if not out.exists():
                    per[s.stem] = {"error": "not installed" if "not installed" in log else "failed"}
                    continue
                run([str(CLI), str(out), "--output-dir", str(work / backend / "back")])
                back = work / backend / "back" / f"{out.name}.json"
                per[s.stem] = score(truth, deck(back, with_notes=True), overflow(out)) if back.exists() else {"error": "unreadable"}
            results[backend] = per
        names = [s.stem for s, _, _ in pairs]

    print(f"Slides round trip — {len(names)} decks rendered to PDF by LibreOffice, converted back to PPTX\n")
    print("| Backend | Converted | " + " | ".join(METRICS) + " |")
    print("|---|---|" + "---|" * len(METRICS))
    for backend in backends:
        ok = {k: v for k, v in results[backend].items() if "error" not in v}
        if not ok:
            reason = next(iter(results[backend].values()), {}).get("error", "failed")
            print(f"| {backend} | {reason} |" + " |" * len(METRICS))
            continue
        cells = []
        for m in METRICS:
            vals = [v[m] for v in ok.values() if v[m] is not None]
            if m in ("pictures", "overflow"):
                cells.append(str(sum(vals)))
            else:
                cells.append(fmt(sum(vals) / len(vals), m) if vals else "—")
        print(f"| {backend} | {len(ok)}/{len(names)} | " + " | ".join(cells) + " |")
    print("\npictures and overflow are totals; overflow counts shapes past a slide's bottom (0 is right).")
    if args.per_file:
        for backend in backends:
            print(f"\n{backend}\n| Deck | " + " | ".join(METRICS) + " |\n|---|" + "---|" * len(METRICS))
            for n, v in results[backend].items():
                print(f"| {n} | " + (" | ".join(fmt(v[m], m) for m in METRICS) if "error" not in v else v["error"]) + " |")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
