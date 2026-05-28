#!/usr/bin/env python3
"""
Regression guard for transcluded documentation code examples.

Docs pages render real, runnable example files via `<code data-src="...">`
blocks: components.js fetches the file at page load and replaces the block's
content, falling back to the inline text if the fetch fails (offline, CDN
hiccup, moved file). That gives "code imported from real files" — but only if
two invariants hold, and nothing was enforcing either:

  1. Every `data-src` target must resolve to a real file under docs/. A moved
     or renamed example silently 404s and the stale inline fallback is shown
     instead — an invisible regression.

  2. The inline fallback must byte-match its source file. Otherwise the page
     shows different code depending on whether a network fetch succeeded. We
     found this live: api.html's curl example fallback used a different request
     schema (`sample_id` vs `filepath`) than examples/api/curl-parse.sh, and
     email-parsing.html's fallback had dropped the MBOX example.

The source file is the single source of truth. Run with `--fix` to regenerate
every inline fallback from its file (HTML-escaped), so authors edit one place.

Run from repo root:

    python3 docs/scripts/check-doc-examples.py          # check (CI)
    python3 docs/scripts/check-doc-examples.py --fix     # sync fallbacks from files

Exit code: 0 = pass, 1 = at least one invariant violated.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

# <code ...data-src="PATH"...>FALLBACK</code> — attributes in any order.
CODE_RE = re.compile(
    r'(<code\b[^>]*\bdata-src="([^"]+)"[^>]*>)(.*?)(</code>)',
    re.DOTALL,
)


def fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠ {msg}")


def resolve(src: str) -> Path:
    # data-src is relative to the docs page URL, i.e. relative to docs/.
    return DOCS / src


def collect_targets() -> set[str]:
    """Every distinct data-src path referenced anywhere in docs/*.html."""
    targets: set[str] = set()
    for hp in DOCS.rglob("*.html"):
        for m in CODE_RE.finditer(hp.read_text(encoding="utf-8")):
            targets.add(m.group(2))
    return targets


def _run(cmd: list[str], stdin: str | None = None) -> tuple[bool, str]:
    proc = subprocess.run(
        cmd, input=stdin, capture_output=True, text=True
    )
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def validate_files() -> int:
    """Syntax-check every referenced example file, by extension.

    The example folder is meant to be 'tested for validity' (the whole point of
    transcluding real files). Tools missing from the runtime are skipped with a
    warning so local dev without node/go isn't blocked; CI has all of them.
    """
    failures = 0
    checked = 0
    for src in sorted(collect_targets()):
        fp = resolve(src)
        if not fp.exists():
            continue  # missing-target is reported by check()
        ext = fp.suffix
        rel = fp.relative_to(ROOT)
        if ext == ".sh":
            tool, cmd, stdin = "bash", ["bash", "-n", str(fp)], None
        elif ext == ".py":
            tool, cmd, stdin = "python3", ["python3", "-m", "py_compile", str(fp)], None
        elif ext in (".js", ".mjs"):
            tool, cmd, stdin = "node", ["node", "--check", str(fp)], None
        elif ext == ".json":
            try:
                import json
                json.loads(fp.read_text(encoding="utf-8"))
                checked += 1
                ok(f"{rel} (json parses)")
            except (ValueError, OSError) as e:
                fail(f"{rel}: invalid JSON — {e}")
                failures += 1
            continue
        elif ext == ".go":
            # Docs .go files are illustrative fragments, not whole programs;
            # wrap in a func body so gofmt can parse-check the syntax.
            tool = "gofmt"
            cmd = ["gofmt", "-e"]
            stdin = "package p\nfunc _demo() {\n" + fp.read_text(encoding="utf-8") + "\n}\n"
        else:
            continue
        if shutil.which(tool) is None:
            warn(f"{rel}: '{tool}' not installed — skipping syntax check")
            continue
        good, out = _run(cmd, stdin)
        checked += 1
        if good:
            ok(f"{rel} ({tool} syntax ok)")
        else:
            fail(f"{rel}: {tool} syntax error\n      {out.splitlines()[0] if out else ''}")
            failures += 1
    if not failures:
        print(f"✓ All {checked} example file(s) pass syntax checks")
    return failures


def check(fix: bool) -> int:
    html_files = sorted(DOCS.rglob("*.html"))
    total = missing = drifted = fixed = 0
    for hp in html_files:
        text = hp.read_text(encoding="utf-8")
        changed = False

        def repl(m: re.Match) -> str:
            nonlocal total, missing, drifted, fixed, changed
            open_tag, src, inline, close_tag = m.groups()
            total += 1
            fp = resolve(src)
            if not fp.exists():
                fail(f"{hp.relative_to(ROOT)}: data-src=\"{src}\" → no file at {fp.relative_to(ROOT)}")
                missing += 1
                return m.group(0)
            file_text = fp.read_text(encoding="utf-8").rstrip("\n")
            inline_norm = html.unescape(inline).strip()
            if inline_norm != file_text.strip():
                if fix:
                    fixed += 1
                    changed = True
                    return open_tag + html.escape(file_text, quote=False) + close_tag
                drifted += 1
                fail(
                    f"{hp.relative_to(ROOT)}: inline fallback for \"{src}\" "
                    f"differs from the source file (run --fix to sync)"
                )
            return m.group(0)

        new_text = CODE_RE.sub(repl, text)
        if fix and changed:
            hp.write_text(new_text, encoding="utf-8")
            ok(f"synced fallback(s) in {hp.relative_to(ROOT)}")

    print()
    if fix:
        print(f"✓ Synced {fixed} fallback(s) across {total} data-src block(s)")
        if missing:
            print(f"✗ {missing} data-src target(s) missing — fix the paths", file=sys.stderr)
            return 1
        return 0
    if missing or drifted:
        print(
            f"✗ {missing} missing target(s), {drifted} drifted fallback(s) "
            f"of {total} data-src block(s)",
            file=sys.stderr,
        )
        return 1
    print(f"✓ All {total} transcluded example block(s) resolve and match their source file")
    return 0


def main(argv: list[str]) -> int:
    fix = "--fix" in argv
    rc = check(fix)
    print()
    rc |= validate_files()
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
