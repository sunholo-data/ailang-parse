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

Three more things ride on the same summary, so that no benchmark figure,
tool version, count or run date is ever typed by hand:

1. Meta descriptions. A crawler reads `content="..."`, which cannot hold a
   data-bench span. docs/data/bench-text.json holds one template per page and
   meta name, with `{adapter.path}` placeholders; this script writes the result.

2. FAQ structured data. On a benchmark page the JSON-LD answer for a question
   that quotes a benchmark figure is regenerated from the visible answer to the
   same question, so the figure is written once (a data-bench span in the HTML).

3. A lint. On any page, a score like `98.1%` or a `PR #123` reference outside
   a data-bench element fails --check. Figures that are meant to be
   fixed (a history table, another benchmark) sit between
   `<!-- bench:static why -->` and `<!-- /bench:static -->`.

4. A release gate. The published AILANG Parse entry must have been measured on
   the version in ailang.toml, with no `+label` suffix. A release that bumps the
   version therefore reruns the benchmark (.claude/skills/benchmark/scripts/
   quick.sh, about 15 seconds), and the site never describes a score as coming
   from a candidate or an older build.

Run:
  python3 docs/scripts/sync-bench-fallbacks.py          # rewrite in place
  python3 docs/scripts/sync-bench-fallbacks.py --check  # CI: exit 1 on drift
"""
import html as htmllib
import json
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
SUMMARY = DOCS / "data/officedocbench-summary.json"
TEXT = DOCS / "data/bench-text.json"

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


PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_.]*)\}")


def render(template, summary, where):
    """Fill `{adapter.path}` placeholders, formatted as the page shows them."""

    def fill(m):
        value = resolve(summary, m.group(1))
        if value is None or isinstance(value, (dict, list)):
            raise SystemExit(f"{where}: no value for {{{m.group(1)}}} in the summary")
        return fmt_text(value, m.group(1))

    return PLACEHOLDER.sub(fill, template)


def stamp_meta(html, templates, summary, page):
    """Write rendered templates into <meta name|property="KEY" content="...">."""
    for key, template in templates.items():
        text = htmllib.escape(render(template, summary, f"{page} {key}"), quote=True)
        tag = re.compile(
            rf'(<meta\s+(?:name|property)="{re.escape(key)}"\s+content=")[^"]*(")'
        )
        if not tag.search(html):
            raise SystemExit(f"{page}: no <meta> named {key} to stamp")
        html = tag.sub(lambda m: m.group(1) + text + m.group(2), html)
    return html


VISIBLE_FAQ = re.compile(
    r"<summary>(?P<q>.*?)</summary>\s*<div class=\"dp-faq-answer\">(?P<a>.*?)</div>\s*</details>",
    re.S,
)
JSONLD = re.compile(r'(<script type="application/ld\+json">)(.*?)(</script>)', re.S)
STRING = r'"(?:[^"\\]|\\.)*"'


def plain(fragment):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def faq_with_figures(html):
    """Visible FAQ answers that carry a benchmark figure: {question: plain answer}.

    Only these are copied into the structured data. An answer with no figure
    keeps whatever wording its JSON-LD already has.
    """
    return {
        plain(m.group("q")): plain(m.group("a"))
        for m in VISIBLE_FAQ.finditer(html)
        if "data-bench=" in m.group("a")
    }


def sync_faq(html):
    """Regenerate each JSON-LD FAQ answer from the visible answer to that question."""
    visible = faq_with_figures(html)
    if not visible:
        return html

    def fix_block(block):
        body = block.group(2)
        if '"FAQPage"' not in body:
            return block.group(0)
        for question, answer in visible.items():
            entry = re.compile(
                r'("name":\s*' + re.escape(json.dumps(question, ensure_ascii=False))
                + r'.*?"text":\s*)' + STRING,
                re.S,
            )
            body = entry.sub(
                lambda m: m.group(1) + json.dumps(answer, ensure_ascii=False), body, count=1
            )
        return block.group(1) + body + block.group(3)

    return JSONLD.sub(fix_block, html)


SCORE = re.compile(r"\b\d{1,3}\.\d%|PR #\d+")
STATIC = re.compile(r"<!-- bench:static\b.*?<!-- /bench:static -->", re.S)


def lint(html, stamped_meta):
    """Hand-typed scores on a benchmark page: (line, text) for each one found."""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))  # keep line numbers
    text = STATIC.sub(blank, html)
    text = ELEMENT.sub(blank, text)
    text = OPEN_TAG.sub(blank, text)
    text = JSONLD.sub(lambda m: m.group(0) if '"FAQPage"' in m.group(2) else blank(m), text)
    for question in faq_with_figures(html):  # derived answers are checked where they are written
        text = re.sub(
            r'"name":\s*' + re.escape(json.dumps(question, ensure_ascii=False))
            + r'.*?"text":\s*' + STRING,
            blank, text, count=1, flags=re.S,
        )
    text = re.sub(r"<(script|style)\b(?![^>]*ld\+json).*?</\1>", blank, text, flags=re.S)
    text = re.sub(r'\sstyle="[^"]*"', blank, text)
    for key in stamped_meta:
        text = re.sub(rf'<meta\s+(?:name|property)="{re.escape(key)}"[^>]*>', blank, text)
    return [
        (text.count("\n", 0, m.start()) + 1, m.group(0)) for m in SCORE.finditer(text)
    ]


def release_gate(summary):
    """The message to print if the published score is not for this release."""
    import tomllib

    released = tomllib.loads((DOCS.parent / "ailang.toml").read_text())["package"]["version"]
    measured = resolve(summary, "ailang_parse.version")
    if measured == released:
        return None
    return (
        f"The published AILANG Parse score was measured on {measured}, but ailang.toml is "
        f"{released}.\nFix: .claude/skills/benchmark/scripts/quick.sh, then commit the results."
    )


def main():
    check = "--check" in sys.argv[1:]
    summary = json.loads(SUMMARY.read_text())
    stale = release_gate(summary)
    if stale:
        print(stale)
    templates = json.loads(TEXT.read_text()) if TEXT.exists() else {}
    drift = []
    typed = []
    for page in sorted(DOCS.glob("*.html")):
        old = page.read_text()
        meta = templates.get(page.name, {})  # every page is linted, bound or not
        new = sync(old, summary)
        new = stamp_meta(new, meta, summary, page.name)
        new = sync_faq(new)
        typed += [(page.name, line, found) for line, found in lint(new, meta)]
        if new != old:
            drift.append(page.name)
            if not check:
                page.write_text(new)
    if typed:
        print("Benchmark figures typed by hand (bind them with data-bench, or mark the")
        print("block <!-- bench:static why --> ... <!-- /bench:static --> if it is meant to be fixed):")
        for name, line, found in typed:
            print(f"  docs/{name}:{line}: {found}")
    if check and drift:
        print("Benchmark fallbacks out of date with docs/data/officedocbench-summary.json:")
        for name in drift:
            print(f"  docs/{name}")
        print("Fix: python3 docs/scripts/sync-bench-fallbacks.py")
        return 1
    verb = "would update" if check else "updated"
    print(f"{verb} {len(drift)} page(s)" + (": " + ", ".join(drift) if drift else ""))
    return 1 if typed or stale else 0


if __name__ == "__main__":
    sys.exit(main())
