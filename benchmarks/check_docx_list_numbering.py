"""md -> docx list numbering, read back from the package XML.

Two bugs shipped here because a list that renders with the wrong number still
opens cleanly, round-trips its text and scores 100% everywhere else:

  * every ordered list shared one <w:num>, so the second list in a document
    continued from the first (4. 5. where the markdown said 1. 2.) — a client
    document went out with its recommendations numbered 5-7;
  * numbering.xml defined level 0 only, so a nested item (ilvl 1+) pointed at
    a level that did not exist and Word/LibreOffice rendered nested bullets
    as 1. 2. 3.

Checked with no template and with a reference doc whose numbering.xml already
defines its own instances (the merge path).

Usage: python3 benchmarks/check_docx_list_numbering.py   (from the repo root)
"""

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SOURCE = """# Lists

1. alpha
2. beta
3. gamma

A paragraph between lists.

1. first
2. second

- top
  - sub one
  - sub two
    - deeper
- top two

1. step
   1. sub step
   2. sub step two
"""

# (list name, ordered, [(item text, ilvl)]) in document order
EXPECTED = [
    ("A", True, [("alpha", 0), ("beta", 0), ("gamma", 0)]),
    ("B", True, [("first", 0), ("second", 0)]),
    ("C", False, [("top", 0), ("sub one", 1), ("sub two", 1), ("deeper", 2), ("top two", 0)]),
    ("D", True, [("step", 0), ("sub step", 1), ("sub step two", 1)]),
]

# What LibreOffice must print for the lists, when it is installed.
EXPECTED_RENDER = ["1. alpha", "2. beta", "3. gamma", "1. first", "2. second",
                   "• top", "◦ sub one", "◦ sub two", "▪ deeper", "• top two",
                   "1. step", "a. sub step", "b. sub step two"]

TEMPLATE = Path("data/test_files/inline_formatting.docx")


def list_paragraphs(doc_xml):
    """(text, ilvl, numId) for every numbered paragraph, in order."""
    out = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", doc_xml, re.S):
        m = re.search(r'<w:ilvl w:val="(\d+)"/><w:numId w:val="(\d+)"/>', p)
        if m:
            text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
            out.append((text, int(m.group(1)), m.group(2)))
    return out


def numbering_model(num_xml):
    """numId -> (abstractNumId, startOverride on ilvl 0 or None);
    abstractNumId -> {ilvl: numFmt}."""
    nums = {}
    for num_id, body in re.findall(r'<w:num w:numId="(\d+)">(.*?)</w:num>', num_xml, re.S):
        abs_id = re.search(r'<w:abstractNumId w:val="(\d+)"/>', body).group(1)
        so = re.search(r'<w:lvlOverride w:ilvl="0">\s*<w:startOverride w:val="(\d+)"/>', body)
        nums[num_id] = (abs_id, int(so.group(1)) if so else None)
    abstracts = {}
    for abs_id, body in re.findall(r'<w:abstractNum w:abstractNumId="(\d+)"[^>]*>(.*?)</w:abstractNum>', num_xml, re.S):
        abstracts[abs_id] = {int(l): f for l, f in re.findall(
            r'<w:lvl w:ilvl="(\d+)"[^>]*>.*?<w:numFmt w:val="(\w+)"/>', body, re.S)}
    return nums, abstracts


def check(out, template=None):
    errors = []
    with zipfile.ZipFile(out) as z:
        paras = list_paragraphs(z.read("word/document.xml").decode())
        nums, abstracts = numbering_model(z.read("word/numbering.xml").decode())
    template_nums = set()
    if template:
        with zipfile.ZipFile(template) as z:
            template_nums = set(re.findall(r'<w:num w:numId="(\d+)"', z.read("word/numbering.xml").decode()))

    want = [(t, lvl) for _, _, items in EXPECTED for t, lvl in items]
    got = [(t, lvl) for t, lvl, _ in paras]
    if got != want:
        return [f"list items/levels: got {got}, expected {want}"]

    i, list_num = 0, {}
    for name, ordered, items in EXPECTED:
        ids = {n for _, _, n in paras[i:i + len(items)]}
        i += len(items)
        if len(ids) != 1:
            errors.append(f"list {name}: items split over numIds {sorted(ids)}")
            continue
        num_id = ids.pop()
        list_num[name] = num_id
        if num_id not in nums:
            errors.append(f"list {name}: numId {num_id} is not defined in numbering.xml")
            continue
        if num_id in template_nums:
            errors.append(f"list {name}: numId {num_id} is one the template already defines")
        abs_id, start = nums[num_id]
        if ordered and start != 1:
            errors.append(f"list {name}: numId {num_id} has no startOverride 1 on level 0 (got {start})")
        levels = abstracts.get(abs_id, {})
        for text, lvl in items:
            fmt = levels.get(lvl)
            if fmt is None:
                errors.append(f"list {name}: '{text}' is at ilvl {lvl}, which abstractNum {abs_id} does not define")
            elif (fmt == "bullet") == ordered:
                errors.append(f"list {name}: '{text}' at ilvl {lvl} renders as {fmt}")

    ordered_ids = [list_num[n] for n, o, _ in EXPECTED if o and n in list_num]
    if len(set(ordered_ids)) != len(ordered_ids):
        errors.append(f"ordered lists share a numId: {ordered_ids} (the second continues from the first)")
    return errors


def check_render(out, tmp):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        print("SKIP LibreOffice render (soffice not installed)")
        return True
    subprocess.run([soffice, "--headless", "--convert-to", "txt:Text (encoded):UTF8",
                    str(out), "--outdir", str(tmp)], check=True, capture_output=True, timeout=180)
    lines = [l.strip() for l in (Path(tmp) / f"{out.stem}.txt").read_text(encoding="utf-8-sig").splitlines()]
    got = [l for l in lines if l and l not in ("Lists", "A paragraph between lists.")]
    if got != EXPECTED_RENDER:
        print(f"FAIL LibreOffice render: got {got}, expected {EXPECTED_RENDER}")
        return False
    print("OK LibreOffice render: every list restarts at 1, nested bullets stay bullets")
    return True


def main():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "lists.md"
        src.write_text(SOURCE, encoding="utf-8")
        for label, template in (("no template", None), (f"reference doc {TEMPLATE.name}", TEMPLATE)):
            out = Path(tmp) / ("plain.docx" if template is None else "styled.docx")
            # --output-dir: otherwise the parse sidecars land in the repo root
            cmd = ["./bin/docparse", str(src), "--convert", str(out), "--output-dir", tmp]
            if template:
                cmd += ["--reference-doc", str(template)]
            subprocess.run(cmd, check=True, capture_output=True)
            errors = check(out, template)
            if errors:
                print(f"FAIL list numbering ({label})")
                for e in errors:
                    print("  " + e)
                ok = False
            else:
                print(f"OK list numbering ({label}): each ordered list has its own restarting "
                      f"instance, every nested level is defined")
            if template is None:
                ok = check_render(out, tmp) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
