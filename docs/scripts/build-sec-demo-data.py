#!/usr/bin/env python3
"""Build docs/data/sec-s1-demo.json for sec-filings.html from a real parse.

Every number and excerpt on the page comes from docparse's own JSON output for
Anthropic's S-1 (a public SEC filing). Nothing here calls a model: the digest
views are plain walks over the typed blocks, the same walks a reader of the
JSON can do with jq.

    curl -sL -A "Your Name you@example.com" -o anthropicpbc-sx1.htm \\
      https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/anthropicpbc-sx1.htm
    docparse anthropicpbc-sx1.htm                # writes anthropicpbc-sx1.htm.json
    python3 docs/scripts/build-sec-demo-data.py anthropicpbc-sx1.htm.json \\
      --source-bytes 14169252 --seconds 7.4

Writes the page summary (sec-s1-demo.json) and the whole document as compact
blocks (sec-s1/blocks.json) so the page can show any section in full. Each
block is a list whose first item says what it is:

    ["g", page]                  page marker: the printed page that starts here
    ["h", level, text]           heading
    ["p", text]                  paragraph
    ["l", ordered, [items]]      list
    ["t", headers, rows]         table; a cell is a string, or [text, colSpan, merged]
    ["i", src]                   image (web copies live in sec-s1/img/<src>)
"""
import argparse
import json
import re
import sys

SOURCE_URL = ("https://www.sec.gov/Archives/edgar/data/2130357/"
              "000162828026067168/anthropicpbc-sx1.htm")


def cell_text(c):
    return c if isinstance(c, str) else c.get("text", "")


def cell_out(c):
    if isinstance(c, str):
        return c
    out = {"t": c.get("text", "")}
    if c.get("colSpan", 1) > 1:
        out["s"] = c["colSpan"]
    if c.get("merged"):
        out["m"] = 1
    return out


def words(s):
    return len(s.split())


def block_text(b):
    t = b.get("type")
    if t in ("text", "heading"):
        return b.get("text", "")
    if t == "list":
        return "\n".join(b.get("items", []))
    if t == "table":
        rows = [b.get("headers", [])] + b.get("rows", [])
        return "\n".join(" | ".join(cell_text(c) for c in r) for r in rows)
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parse_json")
    ap.add_argument("--source-bytes", type=int, required=True)
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("-o", "--out", default="docs/data/sec-s1-demo.json")
    ap.add_argument("--blocks-out", default="docs/data/sec-s1/blocks.json")
    a = ap.parse_args()

    doc = json.load(open(a.parse_json))["document"]
    blocks = doc["blocks"]

    # Page of every block: the name of the most recent page-break marker.
    page, pages = "", []
    for b in blocks:
        if b.get("type") == "section" and b.get("kind") == "page-break":
            page = b.get("name", "")
        pages.append(page)

    n = len(blocks)
    heads = [i for i, b in enumerate(blocks) if b.get("type") == "heading"]

    def section_end(i):
        lvl = blocks[i]["level"]
        for j in heads:
            if j > i and blocks[j]["level"] <= lvl:
                return j
        return n

    def section_words(i, j):
        return sum(words(block_text(b)) for b in blocks[i:j])

    # Outline: levels 1-3, with page, size, and a short preview of the section.
    outline = []
    for i in heads:
        b = blocks[i]
        if b["level"] > 3:
            continue
        j = section_end(i)
        first = next((x["text"] for x in blocks[i + 1:j]
                      if x.get("type") == "text" and len(x.get("text", "")) > 80), "")
        outline.append({
            "t": b["text"], "l": b["level"], "p": pages[i], "i": i,
            "w": section_words(i, j),
            "tables": sum(1 for x in blocks[i:j] if x.get("type") == "table"),
            "sub": sum(1 for k in heads if i < k < j),
            "preview": first[:420] + ("…" if len(first) > 420 else ""),
        })

    # Risk factors: the H4 titles under each H2 inside the "Risk Factors" H1.
    rf = next(i for i in heads if blocks[i]["level"] == 1 and blocks[i]["text"] == "Risk Factors")
    rf_end = section_end(rf)
    groups, cur = [], None
    for i in range(rf, rf_end):
        b = blocks[i]
        if b.get("type") != "heading":
            continue
        if b["level"] == 2:
            cur = {"t": b["text"], "p": pages[i], "items": []}
            groups.append(cur)
        elif b["level"] == 4 and cur is not None:
            cur["items"].append({"t": b["text"], "p": pages[i]})

    # Tables: the first table under a named heading.
    def table_after(title):
        i = next(k for k in heads if blocks[k]["text"] == title)
        t = next(x for x in blocks[i:section_end(i)] if x.get("type") == "table")
        return {"title": title, "p": pages[i],
                "headers": [cell_out(c) for c in t["headers"]],
                "rows": [[cell_out(c) for c in r] for r in t["rows"]]}

    tables = [table_after("Consolidated Statements of Operations Data"),
              table_after("Consolidated Balance Sheet Data")]

    images = [{"src": b.get("src", ""), "p": pages[i]}
              for i, b in enumerate(blocks) if b.get("type") == "image"]

    full_words = sum(words(block_text(b)) for b in blocks)
    rf_words = section_words(rf, rf_end)
    outline_words = sum(words(o["t"]) + 2 for o in outline)

    kinds = {}
    for b in blocks:
        k = b.get("type")
        if k == "section":
            k = "section:" + b.get("kind", "")
        kinds[k] = kinds.get(k, 0) + 1
    levels = {}
    for i in heads:
        levels[str(blocks[i]["level"])] = levels.get(str(blocks[i]["level"]), 0) + 1

    out = {
        "source": {"url": SOURCE_URL, "title": doc["metadata"]["title"],
                   "bytes": a.source_bytes},
        "parse": {"seconds": a.seconds, "blocks": n, "kinds": kinds,
                  "headingLevels": levels,
                  "pages": kinds.get("section:page-break", 0),
                  "riskFactors": sum(len(g["items"]) for g in groups)},
        "tokens": {"full": round(full_words * 1.3), "riskFactors": round(rf_words * 1.3),
                   "outline": round(outline_words * 1.3)},
        "outline": outline,
        "riskGroups": groups,
        "tables": tables,
        "images": images,
    }
    json.dump(out, open(a.out, "w"), ensure_ascii=False, separators=(",", ":"))

    def compact_cell(c):
        if isinstance(c, str):
            return c
        if c.get("colSpan", 1) > 1 or c.get("merged"):
            return [c.get("text", ""), c.get("colSpan", 1), 1 if c.get("merged") else 0]
        return c.get("text", "")

    def compact(b):
        t = b.get("type")
        if t == "section" and b.get("kind") == "page-break":
            return ["g", b.get("name", "")]
        if t == "heading":
            return ["h", b["level"], b["text"]]
        if t == "list":
            return ["l", 1 if b.get("ordered") else 0, b.get("items", [])]
        if t == "table":
            return ["t", [compact_cell(c) for c in b.get("headers", [])],
                    [[compact_cell(c) for c in r] for r in b.get("rows", [])]]
        if t == "image":
            return ["i", b.get("src", "")]
        return ["p", b.get("text", "")]

    json.dump([compact(b) for b in blocks], open(a.blocks_out, "w"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {a.out}: {len(outline)} outline entries, "
          f"{out['parse']['riskFactors']} risk factors, {len(images)} images", file=sys.stderr)


if __name__ == "__main__":
    main()
