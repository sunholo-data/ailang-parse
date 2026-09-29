#!/usr/bin/env python3
"""Image temp files: each document's `src` must hold that document's image.

DOCX/PPTX images are written to temp files under /tmp/docparse-images and the
block carries the PATH (`src` in JSON). Those names used to be
`docparse-img-<counter><ext>`, with the counter restarting at 0 for every
document. Two documents in one batch (or two concurrent requests on the hosted
API) whose first images shared an extension wrote the same file, and the
earlier document's `src` then named the later document's image (G9 in
design_docs/planned/v0_47_0/v0_47_0_partner_report_followups.md).

Checked here, on one batch of three DOCX documents:

  1. every image `src` file exists and its bytes are one of the document's own
     media entries (sha256 of file == sha256 of an entry in that document's
     ZIP), and every non-empty media entry is reachable through some `src`;
  2. documents whose images differ share no `src` path;
  3. re-parsing a document yields the same `src` values (determinism).

The first two inputs are built on the fly from image_vml.docx: identical except
for the bytes of word/media/image4.jpeg (the second gets pandoc_inline_images'
first .jpg). On the old naming both wrote docparse-img-0.jpeg, so check 1 fails
for the first of them. pandoc_inline_images.docx (two .jpg images) rides along
as a multi-image document in the same batch.

Usage:
  uv run benchmarks/check_image_temp_paths.py
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST_DIR = REPO / "data" / "test_files"
DOCPARSE = REPO / "bin" / "docparse"
MEDIA_PREFIXES = ("word/media/", "ppt/media/", "xl/media/")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def media_hashes(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as z:
        return {
            sha(z.read(n))
            for n in z.namelist()
            if n.startswith(MEDIA_PREFIXES) and not n.endswith("/") and z.getinfo(n).file_size > 0
        }


def image_srcs(obj) -> list[str]:
    out = []
    if isinstance(obj, dict):
        if obj.get("type") == "image" and obj.get("src"):
            out.append(obj["src"])
        for v in obj.values():
            out.extend(image_srcs(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(image_srcs(v))
    return out


def replace_entry(src: Path, dst: Path, entry: str, data: bytes) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, data if item.filename == entry else zin.read(item.filename))


def parse_batch(files: list[Path], outdir: Path) -> dict[str, list[str]]:
    outdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(DOCPARSE), *map(str, files), "--output-dir", str(outdir)],
        capture_output=True, text=True, cwd=REPO,
    )
    if proc.returncode != 0:
        sys.exit(f"FAIL: batch parse exited {proc.returncode}\n{proc.stdout}{proc.stderr}")
    result = {}
    for f in files:
        out = outdir / f"{f.name}.json"
        if not out.exists():
            sys.exit(f"FAIL: no JSON output for {f.name} in {outdir}")
        result[f.name] = image_srcs(json.loads(out.read_text()))
    return result


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="docparse-imgpaths-"))

    # Two DOCX that differ only in the bytes of their one .jpeg image.
    with zipfile.ZipFile(TEST_DIR / "pandoc_inline_images.docx") as z:
        other_jpeg = z.read("word/media/image1.jpg")
    doc_a = tmp / "img_collide_a.docx"
    doc_b = tmp / "img_collide_b.docx"
    doc_a.write_bytes((TEST_DIR / "image_vml.docx").read_bytes())
    replace_entry(TEST_DIR / "image_vml.docx", doc_b, "word/media/image4.jpeg", other_jpeg)

    files = [doc_a, doc_b, TEST_DIR / "pandoc_inline_images.docx"]
    expected = {f.name: media_hashes(f) for f in files}
    if expected[doc_a.name] & expected[doc_b.name]:
        sys.exit("FAIL: fixture error: the two DOCX variants share an image")

    srcs = parse_batch(files, tmp / "run1")
    problems = []

    for f in files:
        name = f.name
        got = set()
        if not srcs[name]:
            problems.append(f"{name}: no image src in output")
        for p in srcs[name]:
            fp = Path(p)
            if not fp.is_file():
                problems.append(f"{name}: src {p} does not exist")
                continue
            h = sha(fp.read_bytes())
            got.add(h)
            if h not in expected[name]:
                problems.append(f"{name}: src {p} holds bytes that are not this document's "
                                f"(sha256 {h[:12]}); another document overwrote it")
        missing = expected[name] - got
        if missing:
            problems.append(f"{name}: {len(missing)} of its media entries not reachable via any src")

    # Different images must never share a path.
    for i, a in enumerate(files):
        for b in files[i + 1:]:
            if expected[a.name] & expected[b.name]:
                continue  # a shared image may legitimately share a file
            shared = set(srcs[a.name]) & set(srcs[b.name])
            if shared:
                problems.append(f"{a.name} and {b.name} share src paths {sorted(shared)}")

    # Same input, same output.
    again = parse_batch([doc_a], tmp / "run2")
    if again[doc_a.name] != srcs[doc_a.name]:
        problems.append(f"{doc_a.name}: src changed between parses: {srcs[doc_a.name]} vs {again[doc_a.name]}")

    for f in files:
        print(f"  {f.name}: {srcs[f.name]}")
    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"\nOK: {len(files)} documents, every image src holds its own document's bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
