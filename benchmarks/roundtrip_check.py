#!/usr/bin/env python3
"""Round-trip check: parse(f) -> markdown -> parse(markdown).

The office suite scores structural counts and text similarity against JSON
goldens, and no golden is markdown. That leaves the markdown writer and reader
completely unscored — which is how a DOCX table with a two-paragraph cell came
to shatter into three lines of broken pipe syntax while the suite read 100%.

This checks the one property the writer and reader owe each other: what
markdown can represent must survive the trip.

  tables    same count, same dimensions, same cell text
  headings  same (level, text) sequence

Blocks markdown cannot represent (images, comments, track changes, section
containers) are out of scope by construction and are not asserted on.

Usage:
  uv run benchmarks/roundtrip_check.py            # all office test files
  uv run benchmarks/roundtrip_check.py --verbose  # show every mismatch
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST_DIR = REPO / "data" / "test_files"
OUT_DIR = REPO / "docparse" / "data"

MAX_MD_BYTES = 64 * 1024

EXTS = (".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods",
        ".epub", ".html", ".csv", ".tsv", ".md")


def collect_files() -> list[Path]:
    files = [p for p in sorted(TEST_DIR.iterdir())
             if p.is_file() and p.suffix.lower() in EXTS]
    files += sorted((TEST_DIR / "challenge").glob("*.eml"))
    files += sorted((TEST_DIR / "challenge").glob("*.mbox"))
    files += [p for p in sorted((TEST_DIR / "challenge").iterdir())
              if p.is_file() and p.suffix.lower() in EXTS]
    return files


def batch_parse(files: list[Path], timeout: int = 300) -> None:
    """Parse every file in one AILANG batch run (compile once)."""
    cmd = ["ailang", "run", "--entry", "main", "--caps", "IO,FS,Env",
           "--max-recursion-depth", "50000", "--batch",
           "docparse/main.ail", *[str(f) for f in files]]
    subprocess.run(cmd, cwd=str(REPO), stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=timeout)


def walk(blocks: list[dict]):
    """Yield every block, descending into sections."""
    for b in blocks:
        yield b
        if b.get("type") == "section":
            yield from walk(b.get("blocks", []))


def tables(blocks: list[dict]) -> list[tuple]:
    out = []
    for b in walk(blocks):
        if b.get("type") != "table":
            continue
        width = grid_width(b.get("headers", []))
        headers = strip_trailing_empty([cell_text(c) for c in b.get("headers", [])])
        # Trailing empty cells are padding, not content: a short row is padded
        # out to the header width on the way back in, which is a repair rather
        # than a corruption.
        rows = [strip_trailing_empty([cell_text(c) for c in r])
                for r in b.get("rows", [])]
        # Rows WIDER than the header. Short rows are legitimately padded out
        # (a repair), so only overflow is interesting: a row covering more
        # columns than the header means the table describes a grid no row
        # fits, which is what Word offers to repair.
        overflow = sorted({grid_width(r) for r in b.get("rows", [])
                           if grid_width(r) > width})
        out.append((tuple(headers), tuple(tuple(r) for r in rows), width, overflow))
    return out


def grid_width(cells: list) -> int:
    """Columns a row covers.

    A merged cell sitting inside a preceding cell's span occupies no column of
    its own, so summing every colSpan over-counts: "Total {colspan=4}" plus its
    three continuations is 4 columns, not 7. Getting this wrong is what padded
    every data row of a merged-header table out to seven cells.
    """
    total = 0
    cover = 0
    for c in cells:
        span = c.get("colSpan", 1) if isinstance(c, dict) else 1
        merged = c.get("merged", False) if isinstance(c, dict) else False
        if merged and cover > 0:
            cover -= 1
            continue
        total += span
        cover = span - 1
    return total


def strip_trailing_empty(cells: list[str]) -> list[str]:
    out = list(cells)
    while out and out[-1] == "":
        out.pop()
    return out


def cell_text(c) -> str:
    # A pipe table pads its cells with spaces, so a reader must trim them and
    # leading/trailing whitespace inside a cell is not representable. Compare
    # trimmed; everything else about the cell must survive exactly.
    return (c if isinstance(c, str) else c.get("text", "")).strip()


def headings(blocks: list[dict]) -> list[tuple]:
    # Markdown headings are one line: a heading whose text contains a newline
    # cannot come back byte-identical, so compare on collapsed whitespace.
    return [(b.get("level"), " ".join((b.get("text") or "").split()))
            for b in walk(blocks) if b.get("type") == "heading"]


def load(path: Path) -> list[dict]:
    with open(path) as fh:
        return json.load(fh)["document"]["blocks"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    files = collect_files()
    print(f"=== Round-trip check: {len(files)} files ===\n")

    # Pass 1: source -> .json + .md
    batch_parse(files)

    # Pass 2: the emitted .md back through the parser. Copied aside first so a
    # document's own name does not collide with its round-trip output.
    rt_dir = OUT_DIR / "roundtrip"
    rt_dir.mkdir(exist_ok=True)
    pairs, skipped = [], []
    for f in files:
        md = OUT_DIR / f"{f.name}.md"
        if not md.exists():
            continue
        # Markdown parsing is super-linear in document length (pre-existing;
        # the 1.3MB Moby Dick render takes minutes). Cap the input rather than
        # let one file dominate the run — and say which ones were skipped.
        size = md.stat().st_size
        if size > MAX_MD_BYTES:
            skipped.append((f.name, size))
            continue
        rt = rt_dir / f"{f.name}.rt.md"
        # Some parsers emit bytes that are not valid UTF-8 (legacy RTF/ODF
        # encodings); copy them through verbatim rather than failing the run.
        rt.write_bytes(md.read_bytes())
        pairs.append((f, OUT_DIR / f"{f.name}.json", rt))

    if skipped:
        print(f"skipped {len(skipped)} file(s) whose markdown exceeds "
              f"{MAX_MD_BYTES // 1024}KB:")
        for name, size in skipped:
            print(f"  - {name} ({size // 1024}KB)")
        print()

    batch_parse([rt for _, _, rt in pairs])

    failures, checked = [], 0
    for src, first_json, rt_md in pairs:
        second_json = OUT_DIR / f"{rt_md.name}.json"
        if not first_json.exists() or not second_json.exists():
            failures.append((src.name, "no output produced"))
            continue
        a, b = load(first_json), load(second_json)
        checked += 1

        ta, tb = tables(a), tables(b)
        if len(ta) != len(tb):
            failures.append((src.name, f"table count {len(ta)} -> {len(tb)}"))
        else:
            for i, (x, y) in enumerate(zip(ta, tb)):
                # Grid width, not cell count: trailing-empty tolerance below
                # hides a header that gained phantom columns, which is exactly
                # how a merged-header table padded every data row to 7.
                if x[2] != y[2]:
                    failures.append((src.name,
                                     f"table {i} grid width {x[2]} -> {y[2]}"))
                elif set(y[3]) - set(x[3]):
                    # Overflow that was not there before. Short rows being
                    # padded out is a repair and is fine; a row growing PAST
                    # the header is a grid no row fits.
                    failures.append((src.name,
                                     f"table {i} rows now overflow the header: "
                                     f"header covers {y[2]} columns, rows cover "
                                     f"{sorted(set(y[3]) - set(x[3]))}"))
                elif len(x[0]) != len(y[0]):
                    failures.append((src.name,
                                     f"table {i} width {len(x[0])} -> {len(y[0])}"))
                elif len(x[1]) != len(y[1]):
                    failures.append((src.name,
                                     f"table {i} rows {len(x[1])} -> {len(y[1])}"))
                elif x != y:
                    where = next((f"{r},{c}" for r, (ra, rb) in enumerate(zip(x[1], y[1]))
                                  for c, (ca, cb) in enumerate(zip(ra, rb)) if ca != cb),
                                 "header")
                    failures.append((src.name, f"table {i} cell text at {where}"))

        # Markdown legitimately gains headings the block list did not have: a
        # section's name and the document title have nowhere else to live in a
        # text format. So the requirement is that no original heading is lost
        # or altered — a subsequence, not equality.
        ha, hb = headings(a), headings(b)
        missing = subsequence_gap(ha, hb)
        if missing is not None:
            failures.append((src.name, f"heading lost or altered: {missing!r}"))

    print(f"checked:  {checked}")
    print(f"failures: {len(failures)}\n")
    if failures:
        shown = failures if args.verbose else failures[:25]
        for name, why in shown:
            print(f"  FAIL {name}: {why}")
        if len(failures) > len(shown):
            print(f"  ... and {len(failures) - len(shown)} more (--verbose)")
        return 1
    print("All round-trips preserve tables and headings.")
    return 0


def subsequence_gap(want: list, have: list):
    """Return the first element of `want` missing from `have` in order."""
    it = iter(have)
    for w in want:
        for h in it:
            if h == w:
                break
        else:
            return w
    return None


def first_delta(a: list, b: list):
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else None
        y = b[i] if i < len(b) else None
        if x != y:
            return f"{x!r} -> {y!r}"
    return "none"


if __name__ == "__main__":
    sys.exit(main())
