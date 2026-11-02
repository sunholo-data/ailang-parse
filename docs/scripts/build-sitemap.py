"""Write sitemap.xml for the docs site into a built site directory.

Lists every top-level page (docs/*.html), with its last change from git when
history is available. Run by pages.yml after the site is assembled, so a new
page is in the sitemap the moment it is published.

    python3 docs/scripts/build-sitemap.py _site
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

BASE = "https://www.sunholo.com/ailang-parse/"
REPO = Path(__file__).resolve().parent.parent.parent


def lastmod(page: str) -> str:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", f"docs/{page}"],
                             cwd=REPO, capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        out = ""
    return out


def main() -> int:
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    pages = sorted(p.name for p in site.glob("*.html"))
    rows = []
    for page in pages:
        loc = BASE if page == "index.html" else BASE + page
        mod = lastmod(page)
        rows.append("  <url><loc>%s</loc>%s</url>" % (escape(loc), f"<lastmod>{mod}</lastmod>" if mod else ""))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n")
    (site / "sitemap.xml").write_text(xml)
    print(f"sitemap.xml: {len(rows)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
