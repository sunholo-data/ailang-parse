"""Exact source-derived text checks for PPTX whitespace-only separator runs.

Finds nonblank source paragraphs containing standalone whitespace a:t nodes.
Checks their text in the same slide, including run text when present, without
using a golden as truth. --expect-json supplies the same data to browser tests.
--actual-dir checks saved pre-fix outputs as a negative control.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "benchmarks/officedocbench"))
from build_structure_truth import NS, drawingml_paragraph_text, rels, tag, target, xml

CASES = ("pandoc_basic.pptx", "poi_comment.pptx")


def expectations(path):
    records = []
    with zipfile.ZipFile(path) as z:
        part = "ppt/presentation.xml"
        relationships = rels(z, part)
        for number, slide in enumerate(
            xml(z, part).findall("p:sldIdLst/p:sldId", NS), 1
        ):
            slide_part = target(part, relationships[slide.get(tag("r:id"))])
            for para in xml(z, slide_part).iter(tag("a:p")):
                value = drawingml_paragraph_text(para)
                if value.strip() and any(
                    t.text and t.text.isspace() for t in para.iter(tag("a:t"))
                ):
                    records.append({"slide": number, "text": value})
    return records


def check(records, blocks):
    slides = [
        b for b in blocks if b.get("type") == "section" and b.get("kind") == "slide"
    ]
    errors = []
    for want in records:
        number = want["slide"]
        children = slides[number - 1].get("blocks", []) if number <= len(slides) else []
        matches = [b for b in children if b.get("text") == want["text"]]
        if not matches:
            errors.append(f"slide {number}: missing exact source text {want['text']!r}")
        elif (
            matches[0].get("runs")
            and "".join(r.get("text", "") for r in matches[0]["runs"]) != want["text"]
        ):
            errors.append(
                f"slide {number}: run text differs from paragraph {want['text']!r}"
            )
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expect-json", action="store_true")
    ap.add_argument("--actual-dir", type=Path)
    args = ap.parse_args()
    expected = {name: expectations(REPO / "data/test_files" / name) for name in CASES}
    if args.expect_json:
        print(json.dumps(expected))
        return 0
    with tempfile.TemporaryDirectory(prefix="pptx-text-") as tmp:
        out = args.actual_dir or Path(tmp)
        if args.actual_dir is None:
            run = subprocess.run(
                [
                    "ailang",
                    "run",
                    "--batch",
                    "--entry",
                    "main",
                    "--caps",
                    "IO,FS,Env",
                    "--max-recursion-depth",
                    "50000",
                    "docparse/main.ail",
                ]
                + [str(REPO / "data/test_files" / name) for name in CASES],
                cwd=REPO,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "AILANG_NO_TRACE": "1",
                    "DOCPARSE_OUTPUT_DIR": str(out),
                },
                timeout=120,
            )
            if run.returncode:
                print(run.stderr, file=sys.stderr)
                return 1
        errors = []
        for name, records in expected.items():
            if not records:
                raise ValueError(
                    "Fixture has no whitespace separator assertions: " + name
                )
            raw = json.loads((out / (name + ".json")).read_text())
            errors += [
                name + ": " + e for e in check(records, raw["document"]["blocks"])
            ]
        for error in errors:
            print(error, file=sys.stderr)
        print(
            f"{sum(map(len, expected.values()))} exact source paragraph checks across {len(CASES)} PPTX files; {len(errors)} failures"
        )
        return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
