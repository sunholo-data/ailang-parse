"""Source-derived cell-formatting gate; --expect-json is shared with Chromium.

The source case has explicit bold/colour runs inside table cells. Verify public
JSON against those runs, including after DOCX generation and read-back. An old
golden supplied with --actual-file proves that dropping all run data fails.
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
SOURCE = REPO / "data/test_files/table_header_rowspan.docx"
sys.path.insert(0, str(REPO / "benchmarks/officedocbench"))
from build_structure_truth import docx
from adapters.structure import raw_structure
from structure_v2 import score_structure


def expectations():
    with zipfile.ZipFile(SOURCE) as z:
        return {"runs": docx(z)["runs"]}


def check(raw):
    return score_structure(expectations(), {"structure": raw_structure(raw)})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expect-json", action="store_true")
    ap.add_argument("--actual-file", type=Path)
    args = ap.parse_args()
    if args.expect_json:
        print(json.dumps(expectations()))
        return 0
    if args.actual_file:
        result = check(json.loads(args.actual_file.read_text()))
        print(result)
        return int(result["score"] != 1)
    with tempfile.TemporaryDirectory(prefix="cell-runs-") as tmp:
        out = Path(tmp)
        env = {**os.environ, "DOCPARSE_OUTPUT_DIR": str(out), "AILANG_NO_TRACE": "1"}
        for name, command in [
            (SOURCE.name, [str(SOURCE), "--convert", str(out / "roundtrip.docx")]),
            ("roundtrip.docx", [str(out / "roundtrip.docx")]),
        ]:
            run = subprocess.run(
                [str(REPO / "bin/docparse"), *command],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if run.returncode:
                print(run.stderr, file=sys.stderr)
                return 1
            result = check(json.loads((out / (name + ".json")).read_text()))
            print(name, result["details"])
            if result["score"] != 1:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
