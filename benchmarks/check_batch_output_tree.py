#!/usr/bin/env python3
"""Batch output layout: folders are kept, same-named files never collide.

Until this check, bin/docparse named every output after its input file alone,
so `docparse a/Proposal.docx b/Proposal.docx` wrote one Proposal.docx.json and
the second file silently replaced the first, and a folder input only read its
top level. Both broke parsing an archive, where the same file name turns up in
many folders.

Checks, against the real CLI:
  1. -r on a nested folder: every document parsed, outputs mirror the tree,
     the two Proposal.docx outputs are different documents.
  2. A folder without -r: top level only, flat outputs (unchanged), and a note
     on stderr that subfolders were skipped.
  3. Same-named files from two folders: mirrored below their common folder.
  4. Differently named files from two folders: flat, exactly as before (a
     first version mirrored every multi-folder batch, which moved the outputs
     of `docparse ~/Downloads/a.docx ~/Desktop/b.docx` into subfolders).
  5. Files from one folder: flat outputs, exactly as before.
  6. -r on a folder whose documents all sit in one subfolder: mirrored
     relative to the folder given, not flattened.
  7. DOCPARSE_INPUT_ROOT set: separate runs over slices of one archive (the
     xargs -P recipe on the archives page) share one layout.

Run from the repo root:  python3 benchmarks/check_batch_output_tree.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "docparse"
SMALL = ROOT / "data/test_files/challenge/challenge_real_world.docx"
OTHER = ROOT / "data/test_files/comments.docx"

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def run(args, cwd):
    return subprocess.run([str(CLI), *args], cwd=cwd, capture_output=True, text=True, timeout=600)


def outputs(out):
    return sorted(str(p.relative_to(out)) for p in out.rglob("*.json"))


def source_of(path):
    data = json.loads(path.read_text())
    return json.dumps(data["document"])[:20000]


def main():
    for f in (SMALL, OTHER):
        if not f.exists():
            sys.exit(f"missing fixture {f}")
    tmp = Path(tempfile.mkdtemp(prefix="docparse-tree-"))
    try:
        arch = tmp / "Archive"
        (arch / "Clients/Acme Co/2019").mkdir(parents=True)
        (arch / "Clients/Beta/old copies").mkdir(parents=True)
        shutil.copy(SMALL, arch / "Clients/Acme Co/2019/Proposal.docx")
        shutil.copy(OTHER, arch / "Clients/Beta/old copies/Proposal.docx")
        shutil.copy(SMALL, arch / "Top level.docx")

        print("1. -r on a nested folder")
        out = tmp / "out1"
        r = run(["-r", str(arch), "--output-dir", str(out)], tmp)
        check(r.returncode == 0, "exit 0" if r.returncode == 0 else f"exit 0 (got {r.returncode}: {r.stderr[-300:]})")
        got = outputs(out)
        want = ["Clients/Acme Co/2019/Proposal.docx.json",
                "Clients/Beta/old copies/Proposal.docx.json",
                "Top level.docx.json"]
        check(got == want, f"outputs mirror the tree: {got}")
        a, b = (out / want[0]), (out / want[1])
        if a.exists() and b.exists():
            check(source_of(a) != source_of(b), "the two Proposal.docx outputs are different documents")

        print("2. folder without -r")
        out = tmp / "out2"
        r = run([str(arch), "--output-dir", str(out)], tmp)
        check(r.returncode == 0, "exit 0")
        check(outputs(out) == ["Top level.docx.json"], f"top level only, flat: {outputs(out)}")
        check("Add -r" in r.stderr, "stderr says subfolders were skipped")

        print("3. same-named files from two folders")
        out = tmp / "out3"
        r = run(["Archive/Clients/Acme Co/2019/Proposal.docx",
                 "Archive/Clients/Beta/old copies/Proposal.docx", "--output-dir", str(out)], tmp)
        check(r.returncode == 0, "exit 0")
        check(outputs(out) == ["Acme Co/2019/Proposal.docx.json", "Beta/old copies/Proposal.docx.json"],
              f"mirrored below the common folder: {outputs(out)}")

        print("4. differently named files from two folders")
        out = tmp / "out3b"
        shutil.copy(OTHER, tmp / "elsewhere.docx")
        r = run(["Archive/Top level.docx", "elsewhere.docx", "--output-dir", str(out)], tmp)
        check(r.returncode == 0, "exit 0")
        check(outputs(out) == ["Top level.docx.json", "elsewhere.docx.json"], f"flat, as before: {outputs(out)}")

        print("5. files from one folder")
        flat = tmp / "flat"
        flat.mkdir()
        shutil.copy(SMALL, flat / "one.docx")
        shutil.copy(OTHER, flat / "two.docx")
        out = tmp / "out4"
        r = run([str(flat / "one.docx"), str(flat / "two.docx"), "--output-dir", str(out)], tmp)
        check(r.returncode == 0, "exit 0")
        check(outputs(out) == ["one.docx.json", "two.docx.json"], f"flat, as before: {outputs(out)}")

        print("6. -r where every document sits in one subfolder")
        deep = tmp / "Deep"
        (deep / "2019/Q1").mkdir(parents=True)
        shutil.copy(SMALL, deep / "2019/Q1/memo.docx")
        out = tmp / "out6"
        r = run(["-r", str(deep), "--output-dir", str(out)], tmp)
        check(r.returncode == 0, "exit 0")
        check(outputs(out) == ["2019/Q1/memo.docx.json"], f"relative to the folder given: {outputs(out)}")

        print("7. DOCPARSE_INPUT_ROOT across separate runs")
        out = tmp / "out5"
        env = dict(__import__("os").environ, DOCPARSE_INPUT_ROOT=str(arch))
        for one in ("Clients/Acme Co/2019/Proposal.docx", "Clients/Beta/old copies/Proposal.docx"):
            r = subprocess.run([str(CLI), str(arch / one), "--output-dir", str(out)], cwd=tmp,
                               capture_output=True, text=True, timeout=600, env=env)
            check(r.returncode == 0, f"exit 0 for {one}")
        check(outputs(out) == ["Clients/Acme Co/2019/Proposal.docx.json",
                               "Clients/Beta/old copies/Proposal.docx.json"],
              f"one layout across runs: {outputs(out)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} check(s) failed")
        sys.exit(1)
    print("\nbatch output layout: all checks passed")


if __name__ == "__main__":
    main()
