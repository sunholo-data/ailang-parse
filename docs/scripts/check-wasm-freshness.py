#!/usr/bin/env python3
"""
Regression guard for WASM binary freshness.

The browser WASM bundle (docs/wasm/ailang.wasm) embeds a specific AILANG
compiler version. If the AILANG source modules under docparse/ use syntax
introduced after that WASM build, the browser will fail to parse them at
runtime even though the CLI (`./bin/docparse --check`) passes — because CI
rebuilds the CLI from dev branch, while the WASM is a checked-in blob.

We hit this on the v0.13 string-interpolation migration: CLI happily parsed
`"${first}${join("", fixed)}"` but the pre-v0.13 WASM choked on the nested
string literal inside `${...}`.

NOT WIRED INTO CI. The timestamp comparison cannot fire under a shallow
clone (actions/checkout's default), so it never failed there; and locally it
fires on every .ail edit, because editing a file does not imply using syntax
newer than the pin. Kept as a manual "should I rebuild the WASM?" prompt.

The checks that actually cover this are check-wasm-bindings.py (version-floor
on the loaded subset) and the wasm-smoke CI job (real Chromium). If you run
this by hand and see it fail:

    cd /path/to/ailang && make build-wasm
    cp bin/ailang.wasm /path/to/ailang-parse/docs/wasm/ailang.wasm
    git add docs/wasm/ailang.wasm && git commit

Run from repo root:

    python3 docs/scripts/check-wasm-freshness.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WASM_PATH = REPO_ROOT / "docs" / "wasm" / "ailang.wasm"
SOURCE_GLOB = "docparse/**/*.ail"


def last_commit_timestamp(path: Path) -> int:
    rel = path.relative_to(REPO_ROOT)
    out = subprocess.check_output(
        ["git", "log", "-1", "--format=%ct", "--", str(rel)],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    return int(out) if out else 0


def main() -> int:
    if not WASM_PATH.exists():
        print(f"error: {WASM_PATH.relative_to(REPO_ROOT)} missing", file=sys.stderr)
        return 1

    wasm_ts = last_commit_timestamp(WASM_PATH)
    if wasm_ts == 0:
        print(
            f"error: no git history for {WASM_PATH.relative_to(REPO_ROOT)}",
            file=sys.stderr,
        )
        return 1

    stale: list[tuple[Path, int]] = []
    for ail in REPO_ROOT.glob(SOURCE_GLOB):
        ts = last_commit_timestamp(ail)
        if ts > wasm_ts:
            stale.append((ail.relative_to(REPO_ROOT), ts))

    if stale:
        print(
            f"error: {len(stale)} .ail file(s) have newer commits than docs/wasm/ailang.wasm",
            file=sys.stderr,
        )
        for path, _ in sorted(stale, key=lambda x: -x[1])[:10]:
            print(f"  - {path}", file=sys.stderr)
        if len(stale) > 10:
            print(f"  ... and {len(stale) - 10} more", file=sys.stderr)
        print(
            "\nRebuild the WASM from the matching ailang commit:\n"
            "  cd /path/to/ailang && make build-wasm\n"
            "  cp bin/ailang.wasm /path/to/ailang-parse/docs/wasm/ailang.wasm\n"
            "  git add docs/wasm/ailang.wasm && git commit\n",
            file=sys.stderr,
        )
        return 1

    print(f"WASM is fresh (no .ail file newer than docs/wasm/ailang.wasm).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
