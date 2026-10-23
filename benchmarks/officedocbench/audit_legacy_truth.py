"""Repair selected stale v1 fields from source HTML/XML, never parser output.

This is deliberately a bounded audit. legacy_verification lists exactly which
fields were checked; it does not certify the rest of a historical annotation.
Run with --check in CI, or without it to rebuild the audited fields.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from build_structure_truth import (
    ROOT,
    GT,
    NS,
    docx,
    drawingml_paragraph_text,
    rels,
    tag,
    target,
    val,
    words,
    xml,
)

CASES = (
    "test_complex.html",
    "challenge_complex.html",
    "challenge_footnotes.docx",
    "challenge_nested_lists.docx",
    "pandoc_inline_images.docx",
    "nested_sdt.docx",
    "pandoc_basic.pptx",
    "poi_comment.pptx",
)


def tokens(text):
    return sorted(set(re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())))


def html_fields(source):
    soup = BeautifulSoup(source.read_text(), "html.parser")
    for node in soup(["script", "style"]):
        node.decompose()
    body = soup.body or soup
    headings = body.find_all(re.compile(r"^h[1-6]$"))
    lists = body.find_all(["ol", "ul"])
    paragraphs = body.find_all(["p", "dt", "dd", "pre", "figcaption"])
    prose = [
        p for p in paragraphs if not p.find_parent(["header", "footer", "table", "li"])
    ]
    text = " ".join(str(n) for n in body.descendants if isinstance(n, NavigableString))
    phrases = [p.get_text("", strip=False).strip() for p in headings + prose]
    features = {
        "text": {
            "paragraph_count": len(prose),
            "total_words": len(tokens(text)),
            "key_phrases": phrases,
        },
        "headings": {
            "present": bool(headings),
            "count": len(headings),
            "by_level": dict(Counter(h.name[1:] for h in headings)),
        },
        "tables": {
            "present": bool(body.find("table")),
            "count": len(body.find_all("table")),
            "total_rows": 0,
            "has_merged_cells": any(
                int(c.get("colspan", 1)) > 1 or int(c.get("rowspan", 1)) > 1
                for c in body.find_all(["td", "th"])
            ),
        },
        "lists": {
            "present": bool(lists),
            "count": len(lists),
            "ordered_count": sum(n.name == "ol" for n in lists),
            "unordered_count": sum(n.name == "ul" for n in lists),
            "max_depth": max(
                (1 + len(n.find_parents(["ol", "ul"])) for n in lists), default=0
            ),
            "has_nested": any(n.find_parent(["ol", "ul"]) is not None for n in lists),
        },
        "images": {
            "present": bool(body.find("img")),
            "count": len(body.find_all("img")),
        },
        "metadata": {
            "title": soup.title.get_text() if soup.title else "",
            "author": "",
            "created": "",
            "modified": "",
        },
    }
    author = soup.find("meta", attrs={"name": "author"})
    if author:
        features["metadata"]["author"] = author.get("content", "")
    order = []

    def walk(node):
        if not isinstance(node, Tag):
            return
        if re.fullmatch(r"h[1-6]", node.name):
            order.append(
                {
                    "type": "heading",
                    "text": node.get_text(),
                    "level": int(node.name[1:]),
                }
            )
        elif node.name in ("p", "dt", "dd", "pre", "figcaption"):
            order.append({"type": "text", "text": node.get_text()})
        elif node.name in ("table", "ol", "ul"):
            order.append({"type": "table" if node.name == "table" else "list"})
            # Nested containers are distinct source structures, not extra text
            # paragraphs. Count them once without walking their cell/list text.
            for child in node.find_all(["table", "ol", "ul"]):
                if child.find_parent(["table", "ol", "ul"]) is node:
                    walk(child)
        elif node.name == "img":
            order.append({"type": "image"})
        else:
            for child in node.children:
                walk(child)

    walk(body)
    return features, tokens(text), order


def audited(source: Path, original: dict):
    gt = copy.deepcopy(original)
    fields = []

    def put(path, value):
        obj = gt
        for part in path.split(".")[:-1]:
            obj = obj.setdefault(part, {})
        obj[path.split(".")[-1]] = value
        fields.append(path)

    if source.suffix == ".html":
        features, text_words, order = html_fields(source)
        for name, value in features.items():
            put("features." + name, value)
        put("full_text_words", text_words)
        put("element_order", order)
    elif source.suffix == ".pptx":
        with zipfile.ZipFile(source) as z:
            order = []
            all_text = []
            part = "ppt/presentation.xml"
            relationships = rels(z, part)

            def walk(node):
                if node.tag == tag("p:sp"):
                    ph = node.find("p:nvSpPr/p:nvPr/p:ph", NS)
                    kind = ph.get("type", "body") if ph is not None else "none"
                    for para in node.findall("p:txBody/a:p", NS):
                        value = drawingml_paragraph_text(para)
                        if not value.strip():
                            continue
                        record = {
                            "type": "heading"
                            if kind in ("title", "ctrTitle", "subTitle")
                            else "text",
                            "text": value,
                        }
                        if record["type"] == "heading":
                            record["level"] = 2 if kind == "subTitle" else 1
                        order.append(record)
                elif node.tag == tag("p:pic"):
                    order.append({"type": "image"})
                elif node.tag == tag("p:graphicFrame"):
                    if node.find(".//a:tbl", NS) is not None:
                        order.append({"type": "table"})
                else:
                    for child in node:
                        walk(child)

            for slide in xml(z, part).findall("p:sldIdLst/p:sldId", NS):
                root = xml(z, target(part, relationships[slide.get(tag("r:id"))]))
                walk(root)
                all_text += [drawingml_paragraph_text(p) for p in root.iter(tag("a:p"))]
            headings = [r for r in order if r["type"] == "heading"]
            paragraphs = [r for r in order if r["type"] == "text"]
            text_words = tokens(" ".join(all_text))
            put("full_text_words", text_words)
            put(
                "features.text",
                {
                    "paragraph_count": len(paragraphs),
                    "total_words": len(text_words),
                    "key_phrases": [r["text"] for r in headings + paragraphs[:3]],
                },
            )
            put(
                "features.headings",
                {
                    "present": bool(headings),
                    "count": len(headings),
                    "by_level": dict(Counter(str(r["level"]) for r in headings)),
                },
            )
            images = sum(r["type"] == "image" for r in order)
            put("features.images", {"present": bool(images), "count": images})
            put("element_order", order)
    else:
        with zipfile.ZipFile(source) as z:
            root = xml(z, "word/document.xml")
            paragraphs = [p for p in root.iter(tag("w:p")) if words(p).strip()]
            if source.name == "challenge_footnotes.docx":
                notes = []
                for name, kind in [
                    ("word/footnotes.xml", "footnote"),
                    ("word/endnotes.xml", "endnote"),
                ]:
                    for note in xml(z, name).findall("w:" + kind, NS):
                        if int(val(note, "w:id", "0")) > 0:
                            notes.append(words(note))
                put(
                    "features.footnotes_endnotes",
                    {"present": bool(notes), "count": len(notes), "texts": notes},
                )
                if not notes:
                    put("input_profile", "recovery")
                    put(
                        "input_note",
                        "References footnotes/endnotes but contains no note parts; missing note text cannot be extracted.",
                    )
            elif source.name == "pandoc_inline_images.docx":
                count = len(root.findall(".//a:blip", NS))
                put("features.images", {"present": bool(count), "count": count})
                put("features.text.paragraph_count", len(paragraphs))
                order = [{"type": "text", "text": words(p)} for p in paragraphs]
                put(
                    "element_order",
                    order + [{"type": "image", "text": ""} for _ in range(count)],
                )
            elif source.name == "nested_sdt.docx":
                text = " ".join(words(p) for p in paragraphs)
                put(
                    "features.text",
                    {
                        "paragraph_count": len(paragraphs),
                        "total_words": len(tokens(text)),
                        "key_phrases": [words(p) for p in paragraphs],
                    },
                )
                put("full_text_words", tokens(text))
            elif source.name == "challenge_nested_lists.docx":
                source_items = {r["text"]: r for r in docx(z)["list_items"]}
                order = []
                groups = []
                prose = 0
                for p in paragraphs:
                    content = words(p)
                    if content in source_items:
                        item = source_items[content]
                        if (
                            not order
                            or order[-1]["type"] != "list"
                            or groups[-1]["ordered"] != item["ordered"]
                        ):
                            groups.append(item)
                            order.append({"type": "list"})
                    else:
                        style = val(p.find("w:pPr/w:pStyle", NS), "w:val")
                        heading = re.fullmatch(r"Heading([1-6])", style)
                        order.append(
                            {"type": "heading" if heading else "text", "text": content}
                        )
                        prose += not bool(heading)
                put(
                    "features.lists",
                    {
                        "present": bool(groups),
                        "count": len(groups),
                        "ordered_count": sum(r["ordered"] for r in groups),
                        "unordered_count": sum(not r["ordered"] for r in groups),
                        "max_depth": max(r["level"] for r in source_items.values()) + 1,
                        "has_nested": any(
                            r["level"] > 0 for r in source_items.values()
                        ),
                    },
                )
                put("features.text.paragraph_count", prose)
                put("element_order", order)
    gt["legacy_verification"] = {
        "method": "Selected legacy fields independently checked against source HTML/XML",
        "oracle": "audit_legacy_truth.py v1",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "fields": fields,
    }
    return gt


def main():
    check = "--check" in sys.argv
    bad = []
    for name in CASES:
        sources = list((ROOT / "data/test_files").rglob(name))
        if len(sources) != 1:
            raise ValueError("Expected one source for " + name)
        dest = GT / (name + ".json")
        result = audited(sources[0], json.loads(dest.read_text()))
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if check:
            if dest.read_text() != rendered:
                bad.append(name)
        else:
            dest.write_text(rendered)
    print(f"{len(CASES)} legacy annotations audited against their sources")
    if bad:
        raise SystemExit("Legacy source audit needs updating: " + ", ".join(bad))


if __name__ == "__main__":
    main()
