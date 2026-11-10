#!/usr/bin/env python3
"""Keep the inline benchmark numbers in the HTML equal to the published summary.

Why this exists
---------------
Benchmark figures on the site are `data-bench="<adapter>.<path>"` elements.
js/bench-data.js replaces their text with values from
docs/data/officedocbench-summary.json once the page loads. The text written in
the HTML is only a fallback, so nothing noticed when it went stale: after the
v2 rerun, why.html and vs-pdf-conversion.html still said MarkItDown scored
67.9% / 51.2% (v1 numbers) where the summary says 58.7% / 46.6%.

That fallback is not cosmetic. It is what crawlers, link previews, no-JS
readers and LLMs reading llms.txt targets see. This script rewrites it from
the summary, using the same resolution and formatting rules as bench-data.js.

Run:
  python3 docs/scripts/sync-bench-fallbacks.py          # rewrite in place
  python3 docs/scripts/sync-bench-fallbacks.py --check  # CI: exit 1 on drift
"""
import json
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
SUMMARY = DOCS / "data/officedocbench-summary.json"

# Mirrors format() in js/bench-data.js.
RATIO_KEY = re.compile(
    r"composite|coverage|adjusted|score|recall|quality|fidelity|jaccard|count|"
    r"metadata|detection|fields|fmt",
    re.I,
)

# An element carrying data-bench whose content is plain text (no child tags).
# Group 1: the opening tag, 2: the attribute value, 3: the text, 4: the close.
ELEMENT = re.compile(
    r'(<(?P<tag>[a-zA-Z][a-zA-Z0-9]*)\b[^>]*?\sdata-bench="(?P<path>[^"]+)"[^>]*>)'
    r"(?P<text>[^<]*)"
    r"(</(?P=tag)>)"
)
OPEN_TAG = re.compile(r'<[a-zA-Z][a-zA-Z0-9]*\b[^>]*?\sdata-bench="[^"]+"[^>]*>')


def resolve(summary, path):
    """Mirror resolve() in js/bench-data.js (adapters and top-level keys)."""
    parts = path.split(".")
    top = parts[0]
    if top in summary and top != "adapters":
        return summary[top]
    node = next((a for a in summary.get("adapters", []) if a.get("id") == top), None)
    for part in parts[1:]:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def is_ratio(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def fmt_text(value, path):
    if value is None:
        return "—"  # bench-data.js shows an em dash for a missing value
    if is_ratio(value) and RATIO_KEY.search(path):
        return f"{value * 100:.1f}%"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def fmt_pct(value):
    """Raw percentage as bench-data.js writes it for data-bench-attr/-style."""
    if value is None:
        return "0"
    if is_ratio(value):
        return f"{value * 100:.1f}"
    return str(value)


def sync_tag(tag, summary):
    """Fix the attribute/style fallback of one opening tag."""
    path = re.search(r'\sdata-bench="([^"]+)"', tag).group(1)
    value = resolve(summary, path)
    if isinstance(value, (dict, list)):
        return tag
    attr = re.search(r'\sdata-bench-attr="([^"]+)"', tag)
    style = re.search(r'\sdata-bench-style="([^"]+)"', tag)
    if attr:
        name = re.escape(attr.group(1))
        return re.sub(
            rf'(\s{name}=")[^"]*(")', lambda m: m.group(1) + fmt_pct(value) + m.group(2), tag, count=1
        )
    if style:
        prop = re.escape(style.group(1))
        pct = fmt_pct(value) + ("%" if is_ratio(value) or value is None else "")
        return re.sub(
            rf'(\sstyle="[^"]*?\b{prop}\s*:\s*)[^;"]*', lambda m: m.group(1) + pct, tag, count=1
        )
    return tag


def sync(html, summary):
    def fix_element(m):
        open_tag = m.group(1)
        if re.search(r"\sdata-bench-(attr|style)=", open_tag):
            return m.group(0)  # handled by the tag pass below
        value = resolve(summary, m.group("path"))
        if isinstance(value, (dict, list)):
            return m.group(0)
        text = m.group("text")
        new = fmt_text(value, m.group("path"))
        if text.strip() == new:
            return m.group(0)
        return open_tag + new + m.group(5)

    html = ELEMENT.sub(fix_element, html)
    return OPEN_TAG.sub(lambda m: sync_tag(m.group(0), summary), html)


def main():
    check = "--check" in sys.argv[1:]
    summary = json.loads(SUMMARY.read_text())
    drift = []
    for page in sorted(DOCS.glob("*.html")):
        old = page.read_text()
        if "data-bench" not in old:
            continue
        new = sync(old, summary)
        if new != old:
            drift.append(page.name)
            if not check:
                page.write_text(new)
    if check and drift:
        print("Benchmark fallbacks out of date with docs/data/officedocbench-summary.json:")
        for name in drift:
            print(f"  docs/{name}")
        print("Fix: python3 docs/scripts/sync-bench-fallbacks.py")
        return 1
    verb = "would update" if check else "updated"
    print(f"{verb} {len(drift)} page(s)" + (": " + ", ".join(drift) if drift else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
