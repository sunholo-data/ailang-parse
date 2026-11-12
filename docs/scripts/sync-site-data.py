#!/usr/bin/env python3
"""Keep docs/js/site-data.js equal to what the hosted API reports.

Why this exists
---------------
Prices, plan limits and the list of supported formats are facts about the
product, and the product publishes them: GET /api/v1/pricing and
GET /api/v1/formats. site-data.js was a hand-kept copy, and pages then typed
their own copies of the copy, so the site said 13, 14, 15, 16 and 17 formats
at once and one FAQ quoted request limits from a year earlier.

This script rewrites the two marked blocks of site-data.js from the API:

  /* api:tiers */    free, pro and business, as the API returns them
  /* api:formats */  input (parse), generate (convert targets), parse_output,
                     and the counts pages bind to with data-dp

docs/scripts/stamp-prices.js then writes those values into the HTML, and
docs/scripts/sync-bench-fallbacks.py into meta descriptions and FAQ data.

Run:
  python3 docs/scripts/sync-site-data.py          # rewrite site-data.js
  python3 docs/scripts/sync-site-data.py --check  # CI: exit 1 if the API differs

If the API cannot be reached, --check prints a warning and passes: an outage
must not block an unrelated change.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
SITE_DATA = DOCS / "js/site-data.js"
API = "https://docparse.ailang.sunholo.com"
# Not in the API: how each plan is supported.
SUPPORT = {"free": "Community", "pro": "Email", "business": "Dedicated"}
# Explanatory strings in the API response; the site writes its own wording.
DROP = re.compile(r"_note$|_endpoint$")


def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "site-data-sync"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def js(value, indent):
    text = json.dumps(value, indent=2, ensure_ascii=False)
    return text.replace("\n", "\n" + " " * indent)


def tiers_block(pricing):
    out = []
    for name in ("free", "pro", "business"):
        tier = {k: v for k, v in pricing["tiers"][name].items() if not DROP.search(k)}
        tier["support"] = SUPPORT[name]
        out.append(f"      {name}: {js(tier, 6)}")
    return ",\n".join(out)


def formats_block(formats):
    up = lambda xs: [x.upper() for x in xs]
    data = {
        "input": up(formats["parse"]),
        "generate": up(formats["generate"]),
        "parse_output": formats["output_formats"],
        "ai_required": up(formats["ai_required"]),
        "ai_on_request": up(formats["ai_on_request"]),
        "input_count": len(formats["parse"]),
        "generate_count": len(formats["generate"]),
        "parse_output_count": len(formats["output_formats"]),
    }
    # Older pages bind to formats.output_count for "formats you can convert to".
    data["output"] = data["generate"]
    data["output_count"] = data["generate_count"]
    return "  formats: " + js(data, 2) + ","


def replace(text, name, body):
    open_, close = f"/* api:{name} */", f"/* /api:{name} */"
    start = text.index(open_)
    end = text.index(close, start) + len(close)
    return text[:start] + open_ + "\n" + body + "\n      "[: 0 if name == "formats" else None] + close + text[end:]


def main():
    check = "--check" in sys.argv[1:]
    try:
        pricing, formats = get("/api/v1/pricing"), get("/api/v1/formats")
    except Exception as exc:  # network, timeout, bad JSON
        print(f"warning: could not read {API} ({exc}); site-data.js not checked")
        return 0 if check else 1
    old = SITE_DATA.read_text()
    new = replace(old, "tiers", tiers_block(pricing))
    new = replace(new, "formats", formats_block(formats))
    if new == old:
        print("site-data.js matches the API")
        return 0
    if check:
        print("docs/js/site-data.js differs from the hosted API (pricing or formats).")
        print("Fix: python3 docs/scripts/sync-site-data.py && node docs/scripts/stamp-prices.js"
              " && python3 docs/scripts/sync-bench-fallbacks.py")
        return 1
    SITE_DATA.write_text(new)
    print("updated docs/js/site-data.js from the API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
