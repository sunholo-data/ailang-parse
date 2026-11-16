#!/usr/bin/env python3
"""Write the PDF backend comparison into the pages from its published summary.

docs/data/pdf-headings-summary.json is written by
`python3 benchmarks/pdf/arxiv_headings.py --publish`. This script fills every

    <!-- pdfbench:NAME -->...<!-- /pdfbench:NAME -->

block in docs/*.html from it, so no figure from that benchmark is typed by hand.

NAME is one of:
  table             the comparison table, one row per backend
  note              what was measured, when, and on which version
  papers            number of papers
  source_headings   number of headings in the papers' LaTeX source
  <backend>.recall | .precision | .seconds | .model
                    one value, for use inside a sentence

Run:
  python3 docs/scripts/sync-pdf-bench.py          # rewrite in place
  python3 docs/scripts/sync-pdf-bench.py --check  # CI: exit 1 on drift
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
SUMMARY = DOCS / "data/pdf-headings-summary.json"

# Row order and what each backend is, in the words the PDF page uses.
BACKENDS = [
    ("pdftotext", "Text only (the default)"),
    ("poppler", "Rules over the PDF&rsquo;s own text and fonts"),
    ("docling", "Layout model on your machine"),
    ("liteparse", "Text positions and font size"),
    ("ai", "AI model, one request per page"),
]
BLOCK = re.compile(r"(<!-- pdfbench:(?P<name>[a-z_.]+) -->)(?P<body>.*?)(<!-- /pdfbench:(?P=name) -->)", re.S)


def pct(v):
    return "&mdash;" if v is None else f"{round(v * 100)}%"


def seconds(v):
    return f"{v:.1f}&nbsp;s" if v < 10 else f"{round(v)}&nbsp;s"


def long_date(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def table(summary):
    rows = []
    for backend, what in BACKENDS:
        e = summary["backends"].get(backend)
        if not e:
            continue
        style = ' style="background:rgba(34,197,94,0.08)"' if backend == "poppler" else ""
        rows.append(
            f"        <tr{style}><td><code>{backend}</code></td><td>{what}</td>"
            f"<td>{pct(e['heading_recall'])}</td><td>{pct(e['heading_precision'])}</td>"
            f"<td>{seconds(e['seconds_per_paper'])}</td></tr>"
        )
    return (
        '\n    <div style="overflow-x:auto;max-width:100%"><table class="dp-results-table">\n'
        "      <thead>\n"
        "        <tr><th>Backend</th><th>How it reads the page</th><th>Headings found</th>"
        "<th>Reported headings that are real</th><th>Time per paper</th></tr>\n"
        "      </thead>\n      <tbody>\n" + "\n".join(rows) + "\n      </tbody>\n    </table></div>\n    "
    )


def note(summary):
    b = summary["backends"]
    local = [e for k, e in b.items() if k != "ai"]
    dates = sorted({e["run_date"] for e in local})
    versions = sorted({e["version"] for e in local})
    text = (
        f"{summary['papers']} arXiv papers, {summary['source_headings']} section headings taken from "
        f"each paper&rsquo;s LaTeX source. Measured {long_date(dates[-1])} on AILANG Parse "
        f"{versions[-1]}, from the command line on one laptop."
    )
    ai = b.get("ai")
    if ai:
        text += f" The <code>ai</code> row used {ai['model']}"
        if ai["run_date"] != dates[-1]:
            text += f", measured {long_date(ai['run_date'])} on {ai['version']}"
        elif ai["version"] != versions[-1]:
            text += f" on {ai['version']}"
        text += "; a model&rsquo;s answers vary from run to run."
    return text


def value(summary, name):
    if name == "table":
        return table(summary)
    if name == "note":
        return note(summary)
    if name in ("papers", "source_headings"):
        return str(summary[name])
    backend, _, field = name.partition(".")
    e = summary["backends"].get(backend)
    if e is None:
        raise SystemExit(f"pdfbench:{name}: no entry for backend {backend!r} in {SUMMARY.name}")
    if field == "recall":
        return pct(e["heading_recall"])
    if field == "precision":
        return pct(e["heading_precision"])
    if field == "seconds":
        return seconds(e["seconds_per_paper"])
    if field == "model" and "model" in e:
        return e["model"]
    raise SystemExit(f"pdfbench:{name}: unknown field")


def main():
    check = "--check" in sys.argv
    summary = json.loads(SUMMARY.read_text())
    stale = []
    for page in sorted(DOCS.glob("*.html")):
        html = page.read_text()
        new = BLOCK.sub(lambda m: m.group(1) + value(summary, m.group("name")) + m.group(4), html)
        if new != html:
            stale.append(page.name)
            if not check:
                page.write_text(new)
    if check and stale:
        print("PDF benchmark figures are out of date in: " + ", ".join(stale))
        print("Run: python3 docs/scripts/sync-pdf-bench.py")
        return 1
    print(("would update " if check else "updated ") + (", ".join(stale) or "nothing"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
