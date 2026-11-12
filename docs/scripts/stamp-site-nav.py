#!/usr/bin/env python3
"""Write the navigation between pages from one map, docs/data/site-map.json.

Why this exists
---------------
Pages were reachable from the docs index and little else: a reader on the
Word-to-Markdown page had no route to track changes, and nobody could find
Word-to-Markdown in a flat grid of 35 cards. Links typed into each page by hand
drift the same way benchmark numbers did, so the links that express "how the
site is organised" are generated instead:

  docs.html        the index, grouped by what the reader wants to do, with a
                   filter box (between <!-- nav:index --> markers)
  every page       breadcrumbs under the header   (<!-- nav:crumbs -->)
                   BreadcrumbList structured data (<!-- nav:ld -->)
                   "Related pages" at the end     (<!-- nav:related -->)
                   on format pages, a switcher to the other formats
  components.js    the footer's link columns      (/* nav:footer */)
  llms.txt         every page, grouped the same way (<!-- nav:llms -->)

Everything is written into the HTML, not injected at load, because crawlers
and AI engines read the HTML.

Run:
  python3 docs/scripts/stamp-site-nav.py          # rewrite in place
  python3 docs/scripts/stamp-site-nav.py --check  # CI: exit 1 on drift, on a page
                                                  # missing from the map, or a
                                                  # link to a page that is gone
"""
import html
import json
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
MAP = DOCS / "data/site-map.json"
SITE = "https://www.sunholo.com/ailang-parse/"
ARROW = '<span class="dp-doc-card-arrow">&rarr;</span>'


def esc(text):
    return html.escape(text, quote=True)


def block(name, body, js=False):
    if js:
        return f"/* nav:{name} */\n{body}\n/* /nav:{name} */"
    return f"<!-- nav:{name} -->\n{body}\n<!-- /nav:{name} -->"


def replace_block(text, name, body, js=False):
    """Replace an existing marked block. Returns None if the page has none yet."""
    open_, close = (
        (f"/* nav:{name} */", f"/* /nav:{name} */")
        if js
        else (f"<!-- nav:{name} -->", f"<!-- /nav:{name} -->")
    )
    start = text.find(open_)
    if start < 0:
        return None
    end = text.index(close, start) + len(close)
    return text[:start] + block(name, body, js) + text[end:]


def members(site, group_id):
    return [
        name
        for name, page in site["pages"].items()
        if page["group"] == group_id or group_id in page.get("also", [])
    ]


def card(name, page):
    find = esc(" ".join([page["title"], page["desc"], page.get("find", "")]).lower())
    return (
        f'      <a href="{name}" class="dp-doc-card" data-find="{find}">\n'
        f'        <div class="dp-doc-card-body">\n'
        f'          <div class="dp-doc-card-title">{esc(page["title"])}</div>\n'
        f'          <div class="dp-doc-card-desc">{esc(page["desc"])}</div>\n'
        f"        </div>\n"
        f"        {ARROW}\n"
        f"      </a>"
    )


def index_html(site):
    parts = [
        '  <div class="dp-docs-filter">\n'
        '    <input type="search" id="dp-docs-filter" placeholder="Find a page: try &ldquo;docx to markdown&rdquo;, &ldquo;ChatGPT&rdquo; or &ldquo;merged cells&rdquo;" aria-label="Find a page" autocomplete="off">\n'
        '    <p id="dp-docs-filter-empty" hidden>No page matches that. <a href="mailto:docparse@sunholo.com">Tell us what you were looking for.</a></p>\n'
        "  </div>"
    ]
    for group in site["groups"]:
        cards = "\n".join(card(n, site["pages"][n]) for n in members(site, group["id"]))
        parts.append(
            f'  <section class="dp-docs-section" id="{group["id"]}">\n'
            f'    <div class="dp-docs-section-head">\n'
            f'      <h2>{esc(group["title"])}</h2>\n'
            f'      <p>{esc(group["blurb"])}</p>\n'
            f"    </div>\n"
            f'    <div class="dp-docs-grid">\n{cards}\n    </div>\n'
            f"  </section>"
        )
    return "\n\n".join(parts)


def crumbs_html(site, name):
    page = site["pages"][name]
    group = next(g for g in site["groups"] if g["id"] == page["group"])
    return (
        '  <nav class="dp-crumbs" aria-label="Breadcrumb">'
        '<a href="docs.html">Docs</a><span aria-hidden="true">&rsaquo;</span>'
        f'<a href="docs.html#{group["id"]}">{esc(group["title"])}</a><span aria-hidden="true">&rsaquo;</span>'
        f'<span aria-current="page">{esc(page["title"])}</span></nav>'
    )


def crumbs_ld(site, name):
    page = site["pages"][name]
    group = next(g for g in site["groups"] if g["id"] == page["group"])
    trail = [
        ("AILANG Parse", SITE),
        ("Docs", SITE + "docs.html"),
        (group["title"], SITE + "docs.html#" + group["id"]),
        (page["title"], SITE + name),
    ]
    data = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": label, "item": url}
            for i, (label, url) in enumerate(trail, 1)
        ],
    }
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"


def related_html(site, name):
    page = site["pages"][name]
    out = []
    if page["group"] == "formats":
        chips = "".join(
            f'<span class="dp-chip dp-chip--here" aria-current="page">{esc(site["pages"][n]["chip"])}</span>'
            if n == name
            else f'<a class="dp-chip" href="{n}">{esc(site["pages"][n]["chip"])}</a>'
            for n in members(site, "formats")
        )
        out.append(
            '      <nav class="dp-format-switch" aria-label="Other formats">'
            f'<span class="dp-format-switch-label">Other formats</span>{chips}</nav>'
        )
    cards = "\n".join(card(n, site["pages"][n]) for n in page["related"])
    out.append(
        '      <aside class="dp-related" aria-label="Related pages">\n'
        '        <h2 id="related">Related pages</h2>\n'
        f'        <div class="dp-related-grid">\n{cards}\n        </div>\n'
        '        <p class="dp-related-all"><a href="docs.html">All documentation &rarr;</a></p>\n'
        "      </aside>"
    )
    return "\n".join(out)


def footer_js(site):
    cols = [
        {
            "title": g["title"],
            "links": [[n, site["pages"][n].get("chip") or site["pages"][n]["title"]] for n in members(site, g["id"])],
        }
        for g in site["groups"]
    ]
    return "  var FOOTER_COLS = " + json.dumps(cols, ensure_ascii=False) + ";"


def llms_md(site):
    out = ["## All pages, by what you want to do"]
    for group in site["groups"]:
        out.append(f"\n### {group['title']}: {group['blurb']}\n")
        out += [
            f"- [{site['pages'][n]['title']}]({n}): {site['pages'][n]['desc']}"
            for n in members(site, group["id"])
        ]
    return "\n".join(out)


def place(text, name, body, before):
    """Replace the marked block, or insert it before the first anchor that matches."""
    done = replace_block(text, name, body)
    if done is not None:
        return done
    for anchor in before:
        m = re.search(anchor, text)
        if m:
            return text[: m.start()] + block(name, body) + "\n\n" + text[m.start():]
    raise SystemExit(f"no place for the {name} block")


def stamp_page(site, name, text):
    text = place(text, "crumbs", crumbs_html(site, name), [r'[ \t]*<section class="hero"', r'[ \t]*<section\b', r'[ \t]*<div class="dp-docs-layout"'])
    text = place(text, "ld", crumbs_ld(site, name), [r"</head>"])
    text = place(text, "related", related_html(site, name), [r"[ \t]*</main>", r'[ \t]*<div id="footer-mount"'])
    return text


def problems(site):
    """Pages missing from the map, and links in the map to pages that do not exist."""
    out = []
    on_disk = {p.name for p in DOCS.glob("*.html")}
    known = set(site["pages"]) | set(site["unlisted"])
    out += [f"docs/{n} is not in docs/data/site-map.json" for n in sorted(on_disk - known)]
    out += [f"site-map.json lists {n}, which does not exist" for n in sorted(known - on_disk)]
    groups = {g["id"] for g in site["groups"]}
    for name, page in site["pages"].items():
        if page["group"] not in groups:
            out.append(f"{name}: unknown group {page['group']}")
        for target in page["related"]:
            if target not in site["pages"] or target == name:
                out.append(f"{name}: related page {target} is not a listed page")
    return out


def main():
    check = "--check" in sys.argv[1:]
    site = json.loads(MAP.read_text())
    bad = problems(site)
    drift = []

    def write(path, new):
        if new != path.read_text():
            drift.append(str(path.relative_to(DOCS.parent)))
            if not check:
                path.write_text(new)

    index = DOCS / "docs.html"
    new = replace_block(index.read_text(), "index", index_html(site))
    if new is None:
        bad.append("docs/docs.html has no <!-- nav:index --> block")
    else:
        write(index, new)

    for name in site["pages"]:
        if name == "workbench.html":  # an app, not a document page
            continue
        path = DOCS / name
        if path.exists():
            write(path, stamp_page(site, name, path.read_text()))

    comp = DOCS / "js/components.js"
    new = replace_block(comp.read_text(), "footer", footer_js(site), js=True)
    if new is None:
        bad.append("docs/js/components.js has no /* nav:footer */ block")
    else:
        write(comp, new)

    llms = DOCS / "llms.txt"
    new = replace_block(llms.read_text(), "llms", llms_md(site))
    if new is None:
        bad.append("docs/llms.txt has no <!-- nav:llms --> block")
    else:
        write(llms, new)

    for line in bad:
        print(line)
    if check and drift:
        print("Navigation out of date with docs/data/site-map.json:")
        for name in drift:
            print(f"  {name}")
        print("Fix: python3 docs/scripts/stamp-site-nav.py")
    else:
        print(("would update" if check else "updated") + f" {len(drift)} file(s)")
    return 1 if bad or (check and drift) else 0


if __name__ == "__main__":
    sys.exit(main())
