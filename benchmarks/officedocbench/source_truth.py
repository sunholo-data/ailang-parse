"""Read legacy OfficeDocBench facts directly from the source documents.

Every value returned here is computed from the input file with the Python
standard library (zipfile, xml.etree, csv), BeautifulSoup and markdown-it-py.
Nothing is read from AILANG Parse: not its .ail parsers, not the golden
outputs under benchmarks/office/golden, not annotate.py's normalizer.

A reader returns ``None`` for a fact the format does not define without a
parser convention (for example list groups in WordprocessingML, which has
numbered paragraphs but no list container). audit_legacy_truth.py turns those
into fields that are not scored.
"""

from __future__ import annotations

import csv
import posixpath
import re
import zipfile
import xml.etree.ElementTree as E
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdown_it import MarkdownIt

from build_structure_truth import docx as docx_assertions

# The scorer's own tokenizer (scoring.score_text_jaccard), applied per text unit.
TOKEN = re.compile(r"\b[a-zA-Z0-9]+\b")

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "opf": "http://www.idpf.org/2007/opf",
    "ocf": "urn:oasis:names:tc:opendocument:xmlns:container",
}


def q(name):
    prefix, local = name.split(":")
    return "{" + NS[prefix] + "}" + local


def tokens(text):
    return TOKEN.findall(text.lower())


def norm(text):
    return " ".join(str(text).lower().split())


def load(z, part):
    try:
        return E.fromstring(z.read(part))
    except KeyError:
        return None


def rels_of(z, part):
    root = load(
        z,
        posixpath.join(
            posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
        ),
    )
    if root is None:
        return {}
    return {
        n.get("Id"): (n.get("Type", ""), n.get("Target", ""), n.get("TargetMode", ""))
        for n in root
    }


def resolve(part, ref):
    if ref.startswith("/"):
        return ref[1:]
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), ref))


class Facts:
    """What one source file contains. ``None`` means "not defined by the format"."""

    def __init__(self, reader):
        self.reader = reader
        self.parts = []  # every content text unit, for full_text_words
        self.blocks = []  # paragraph-level text in its current (accepted) state
        self.headings = None  # [(level, text)]
        self.tables = None  # {"count", "has_merged_cells"}
        self.lists = None  # {"count", ...}
        self.images = None
        self.comments = None  # [{"author", "text"}]
        self.comment_ranges = None
        self.track_changes = None  # [{"type", "author"}]
        self.headers_footers = None  # (header parts, footer parts)
        self.notes = None  # footnote/endnote texts
        self.speaker_notes = None  # one text per slide with notes
        self.text_boxes = None
        self.metadata = {}
        self.sheets = None
        self.section_breaks = None
        self.bookmarks = None
        self.hyperlinks = None
        self.fields = None
        self.equations = None

    def words(self):
        found = set()
        for part in self.parts:
            found.update(tokens(part))
        return sorted(found)

    def contains_phrase(self, phrase):
        want = norm(phrase)
        return bool(want) and any(want in norm(b) for b in self.blocks)


def core_metadata(z):
    """OOXML docProps/core.xml: only properties the package actually sets."""
    root = load(z, "docProps/core.xml")
    out = {}
    if root is None:
        return out
    for key, path in (
        ("title", "dc:title"),
        ("author", "dc:creator"),
        ("created", "dcterms:created"),
        ("modified", "dcterms:modified"),
    ):
        node = root.find(path, NS)
        if node is not None and (node.text or "").strip():
            out[key] = node.text.strip()
    return out


# ---------------------------------------------------------------- DOCX


def _skip(node):
    # mc:Fallback repeats the mc:Choice content for older consumers.
    return node.tag == q("mc:Fallback")


def _docx_paragraphs(root):
    """(paragraph, in_text_box) for every paragraph, outside mc:Fallback."""
    out = []

    def walk(node, in_box):
        if _skip(node):
            return
        if node.tag == q("w:txbxContent"):
            in_box = True
        if node.tag == q("w:p"):
            out.append((node, in_box))
        for child in node:
            walk(child, in_box)

    walk(root, False)
    return out


def _docx_text(para):
    """(accepted text, deleted text) of one paragraph, excluding nested paragraphs."""
    accepted, removed = [], []

    def walk(node, deleted):
        # OMML has no canonical linear text (see equations below), so math
        # zones are not prose words; field instructions are code, not text.
        if _skip(node) or node.tag in (
            q("w:pPr"), q("w:rPr"), q("w:instrText"), q("m:oMath"), q("m:oMathPara")
        ):
            return
        if node is not para and node.tag == q("w:p"):
            return
        if node.tag in (q("w:del"), q("w:moveFrom")):
            deleted = True
        target = removed if deleted else accepted
        if node.tag == q("w:t"):
            target.append(node.text or "")
        elif node.tag == q("w:delText"):
            removed.append(node.text or "")
        elif node.tag == q("w:tab"):
            target.append("\t")
        elif node.tag in (q("w:br"), q("w:cr")):
            target.append("\n")
        elif node.tag == q("w:noBreakHyphen"):
            target.append("-")
        for child in node:
            walk(child, deleted)

    walk(para, False)
    return "".join(accepted), "".join(removed)


def _docx_part_text(root, facts):
    """Text of a header/footer/notes/comments subtree, added to the facts."""
    if root is None:
        return []
    texts = []
    for para, _ in _docx_paragraphs(root):
        kept, deleted = _docx_text(para)
        texts += [kept, deleted]
        if kept.strip():
            facts.blocks.append(kept)
    facts.parts += texts
    return texts


def _docx_heading_level(para, styles):
    """Outline level from the paragraph, else its style chain, else 'heading N'."""
    outline = para.find("w:pPr/w:outlineLvl", NS)
    if outline is not None:
        level = int(outline.get(q("w:val"), "9"))
        return level + 1 if level < 9 else None
    style = para.find("w:pPr/w:pStyle", NS)
    sid = style.get(q("w:val"), "") if style is not None else ""
    if not sid:
        sid = styles.get("__default_paragraph__", "")
    seen = set()
    if sid and sid not in styles:
        # A reference to an undefined built-in style id ("Heading1") still
        # names the built-in heading; no definition can contradict it.
        match = re.fullmatch(r"heading ?([1-9])", sid.lower())
        return int(match[1]) if match else None
    while sid and sid not in seen and sid in styles:
        seen.add(sid)
        node = styles[sid]
        outline = node.find("w:pPr/w:outlineLvl", NS)
        if outline is not None:
            level = int(outline.get(q("w:val"), "9"))
            return level + 1 if level < 9 else None
        name = node.find("w:name", NS)
        match = re.fullmatch(
            r"heading ([1-9])",
            (name.get(q("w:val"), "") if name is not None else "").strip().lower(),
        )
        if match:
            return int(match[1])
        based = node.find("w:basedOn", NS)
        sid = based.get(q("w:val"), "") if based is not None else ""
    return None


def read_docx(path):
    facts = Facts("docx: word/document.xml, headers/footers, notes, comments, docProps/core.xml")
    z = zipfile.ZipFile(path)
    doc = load(z, "word/document.xml")
    body = doc.find("w:body", NS)
    rels = rels_of(z, "word/document.xml")
    styles = {}
    style_root = load(z, "word/styles.xml")
    if style_root is not None:
        for node in style_root.findall("w:style", NS):
            styles[node.get(q("w:styleId"), "")] = node
            if node.get(q("w:type")) == "paragraph" and node.get(q("w:default")) in (
                "1",
                "true",
            ):
                styles["__default_paragraph__"] = node.get(q("w:styleId"), "")

    # Each OMML run is a text atom of a 2-D layout. Its words count as
    # content, but runs are not joined: any linear spelling is a convention.
    def math_atoms(node):
        if _skip(node):
            return
        if node.tag == q("m:t"):
            facts.parts.append(node.text or "")
        for child in node:
            math_atoms(child)

    math_atoms(body)
    headings = []
    for para, in_box in _docx_paragraphs(body):
        kept, deleted = _docx_text(para)
        facts.parts += [kept, deleted]
        if kept.strip():
            facts.blocks.append(kept)
        if not in_box and kept.strip():
            level = _docx_heading_level(para, styles)
            if level:
                headings.append((level, kept.strip()))

    def walk(node, visit):
        if _skip(node):
            return
        visit(node)
        for child in node:
            walk(child, visit)

    found = Counter()
    tables_merged = []
    changes = []
    images = 0

    def visit(node):
        nonlocal images
        tag = node.tag
        if tag == q("w:txbxContent"):
            if "".join(_docx_text(p)[0] for p, _ in _docx_paragraphs(node)).strip():
                found["text_boxes"] += 1
        elif tag == q("w:tbl"):
            found["tables"] += 1
            tables_merged.append(
                any(
                    int(g.get(q("w:val"), "1")) > 1
                    for g in node.iter(q("w:gridSpan"))
                )
                or node.find(".//w:vMerge", NS) is not None
            )
        elif tag in (q("w:ins"), q("w:del"), q("w:moveFrom"), q("w:moveTo")):
            content = "".join(
                n.text or "" for n in node.iter() if n.tag in (q("w:t"), q("w:delText"))
            )
            if content.strip():
                kind = {
                    q("w:ins"): "insert",
                    q("w:del"): "delete",
                    q("w:moveFrom"): "move-from",
                    q("w:moveTo"): "move-to",
                }[tag]
                changes.append({"type": kind, "author": node.get(q("w:author"), "")})
        elif tag == q("a:blip"):
            rel = rels.get(node.get(q("r:embed"), ""))
            if rel and rel[0].endswith("/image") and rel[2] != "External":
                images += 1
        elif tag == q("v:imagedata"):
            rel = rels.get(node.get(q("r:id"), ""))
            if rel and rel[0].endswith("/image") and rel[2] != "External":
                images += 1
        elif tag == q("w:pPr") and node.find("w:sectPr", NS) is not None:
            found["section_breaks"] += 1

    walk(body, visit)
    facts.headings = headings
    facts.tables = {
        "count": found["tables"],
        "has_merged_cells": any(tables_merged),
    }
    facts.track_changes = changes
    facts.images = images
    facts.text_boxes = found["text_boxes"]
    facts.section_breaks = found["section_breaks"]

    # Header and footer parts referenced by any section, counted once each.
    counts = {"header": 0, "footer": 0}
    seen = set()
    for sect in body.iter(q("w:sectPr")):
        for ref in sect:
            kind = {
                q("w:headerReference"): "header",
                q("w:footerReference"): "footer",
            }.get(ref.tag)
            rel = rels.get(ref.get(q("r:id"), "")) if kind else None
            if not rel:
                continue
            part = resolve("word/document.xml", rel[1])
            if part in seen:
                continue
            seen.add(part)
            texts = _docx_part_text(load(z, part), facts)
            if "".join(texts).strip():
                counts[kind] += 1
    facts.headers_footers = (counts["header"], counts["footer"])

    notes = []
    for part, kind in (("word/footnotes.xml", "footnote"), ("word/endnotes.xml", "endnote")):
        root = load(z, part)
        if root is None:
            continue
        for note in root.findall("w:" + kind, NS):
            if note.get(q("w:type"), "normal") != "normal":
                continue  # separator / continuationSeparator / continuationNotice
            texts = _docx_part_text(note, facts)[::2]
            notes.append(" ".join(t.strip() for t in texts if t.strip()))
    facts.notes = notes

    comments = []
    root = load(z, "word/comments.xml")
    if root is not None:
        for c in root.findall("w:comment", NS):
            texts = _docx_part_text(c, facts)[::2]
            comments.append(
                {
                    "author": c.get(q("w:author"), ""),
                    "text": " ".join(t.strip() for t in texts if t.strip()),
                }
            )
    facts.comments = comments
    # Anchors come from the structural oracle's commentRangeStart/End walk.
    facts.comment_ranges = [
        {
            "comment_text": r["text"],
            "annotated_text": r["annotated_text"],
            "author": r["author"],
        }
        for r in docx_assertions(z).get("comment_anchors", [])
        if r["anchored"]
    ]

    names = []
    for mark in body.iter(q("w:bookmarkStart")):
        name = mark.get(q("w:name"), "")
        if name and not name.startswith("_") and name not in names:
            names.append(name)
    facts.bookmarks = names

    links = []
    for link in body.iter(q("w:hyperlink")):
        label = "".join(n.text or "" for n in link.iter(q("w:t")))
        rel = rels.get(link.get(q("r:id"), ""))
        url = rel[1] if rel else "#" + link.get(q("w:anchor"), "")
        if label.strip() and url != "#":
            links.append({"text": label, "url": url})
    facts.hyperlinks = links

    # Field results are the cached text between fldChar separate and end.
    fields = []
    for para in body.iter(q("w:p")):
        state, instr, result = None, [], []
        for node in para.iter():
            if node.tag == q("w:fldChar"):
                kind = node.get(q("w:fldCharType"))
                if kind == "begin":
                    state, instr, result = "instr", [], []
                elif kind == "separate":
                    state = "result"
                elif kind == "end" and state:
                    fields.append(("".join(instr), "".join(result)))
                    state = None
            elif node.tag == q("w:instrText") and state == "instr":
                instr.append(node.text or "")
            elif node.tag == q("w:t") and state == "result":
                result.append(node.text or "")
    for simple in body.iter(q("w:fldSimple")):
        fields.append(
            (
                simple.get(q("w:instr"), ""),
                "".join(n.text or "" for n in simple.iter(q("w:t"))),
            )
        )
    facts.fields = [
        {"type": (instr.split() or [""])[0].upper(), "display": shown}
        for instr, shown in fields
        if shown.strip()
    ]

    # OMML has no text form; only formulas with no layout structure are linear.
    structured = {
        q("m:" + t)
        for t in (
            "f rad sSup sSub sSubSup sPre nary d func acc bar box borderBox "
            "eqArr limLow limUpp m groupChr phant"
        ).split()
    }
    equations = []
    for math in body.iter(q("m:oMath")):
        if any(n.tag in structured for n in math.iter()):
            equations.append(None)
        else:
            equations.append("".join(n.text or "" for n in math.iter(q("m:t"))))
    facts.equations = equations
    facts.metadata = core_metadata(z)
    return facts


# ---------------------------------------------------------------- PPTX


def _a_text(para):
    return "".join(
        "\n" if n.tag == q("a:br") else "".join(t.text or "" for t in n.iter(q("a:t")))
        for n in para
        if n.tag in (q("a:r"), q("a:fld"), q("a:br"))
    )


def read_pptx(path):
    facts = Facts("pptx: slides in presentation order, notes slides, comments, docProps/core.xml")
    z = zipfile.ZipFile(path)
    part = "ppt/presentation.xml"
    pres = load(z, part)
    rels = rels_of(z, part)
    headings, tables, merged, images, notes = [], 0, False, 0, []
    for sld in pres.findall("p:sldIdLst/p:sldId", NS):
        rel = rels.get(sld.get(q("r:id"), ""))
        if not rel:
            continue
        slide_part = resolve(part, rel[1])
        slide = load(z, slide_part)
        if slide is None:
            continue
        slide_rels = rels_of(z, slide_part)

        def walk(node):
            nonlocal tables, merged, images
            if _skip(node):
                return
            if node.tag == q("a:p"):
                value = _a_text(node)
                facts.parts.append(value)
                if value.strip():
                    facts.blocks.append(value)
            elif node.tag == q("p:sp"):
                ph = node.find("p:nvSpPr/p:nvPr/p:ph", NS)
                if ph is not None and ph.get("type") in ("title", "ctrTitle"):
                    value = " ".join(
                        _a_text(p).strip() for p in node.iter(q("a:p")) if _a_text(p).strip()
                    )
                    if value:
                        headings.append((1, value))
            elif node.tag == q("a:tbl"):
                tables += 1
                for cell in node.iter(q("a:tc")):
                    if (
                        int(cell.get("gridSpan", "1")) > 1
                        or int(cell.get("rowSpan", "1")) > 1
                        or cell.get("hMerge") in ("1", "true")
                        or cell.get("vMerge") in ("1", "true")
                    ):
                        merged = True
            elif node.tag == q("p:pic"):
                blip = node.find(".//a:blip", NS)
                target = slide_rels.get(blip.get(q("r:embed"), "")) if blip is not None else None
                if target and target[0].endswith("/image") and target[2] != "External":
                    images += 1
            for child in node:
                walk(child)

        walk(slide)
        for kind, ref, _ in slide_rels.values():
            if kind.endswith("/notesSlide"):
                root = load(z, resolve(slide_part, ref))
                paras = []
                for shape in root.iter(q("p:sp")) if root is not None else []:
                    ph = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
                    if ph is not None and ph.get("type") in (
                        "sldNum",
                        "dt",
                        "hdr",
                        "ftr",
                        "sldImg",
                    ):
                        continue
                    paras += [_a_text(p) for p in shape.iter(q("a:p"))]
                facts.parts += paras
                text = " ".join(p.strip() for p in paras if p.strip())
                if text:
                    notes.append(text)
                    facts.blocks += [p for p in paras if p.strip()]
            elif kind.endswith("/comments") or "comment" in kind.lower():
                root = load(z, resolve(slide_part, ref))
                if root is not None:
                    facts.parts += [
                        "".join(t.text or "" for t in node.iter() if t.tag.endswith("}t") or t.tag.endswith("}text"))
                        for node in root
                    ]
    facts.headings = headings
    facts.tables = {"count": tables, "has_merged_cells": merged}
    facts.images = images
    facts.speaker_notes = notes
    facts.metadata = core_metadata(z)
    return facts


# ---------------------------------------------------------------- XLSX


def _general_number(value):
    """How a General-format number is shown: integral values have no '.0'."""
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return value


def read_xlsx(path):
    facts = Facts("xlsx: workbook sheet order, sheet cells, comments, docProps/core.xml")
    z = zipfile.ZipFile(path)
    wb_part = "xl/workbook.xml"
    wb = load(z, wb_part)
    rels = rels_of(z, wb_part)
    sst = load(z, "xl/sharedStrings.xml")
    strings = (
        ["".join(t.text or "" for t in si.iter(q("s:t"))) for si in sst.findall("s:si", NS)]
        if sst is not None
        else []
    )
    styles = load(z, "xl/styles.xml")
    xfs = styles.find("s:cellXfs", NS) if styles is not None else None
    names, images = [], 0
    for sheet in wb.findall("s:sheets/s:sheet", NS):
        name = sheet.get("name", "")
        names.append(name)  # scored as sheet names, not as body words
        rel = rels.get(sheet.get(q("r:id"), ""))
        if rel:
            part = resolve(wb_part, rel[1])
        else:
            parts = [p for p in z.namelist() if re.fullmatch(r"xl/worksheets/sheet[0-9]+\.xml", p)]
            if len(parts) != 1:
                continue
            part = parts[0]
        root = load(z, part)
        if root is None:
            continue
        for cell in root.iter(q("s:c")):
            kind = cell.get("t", "n")
            v = cell.find("s:v", NS)
            raw = (v.text or "") if v is not None else ""
            if kind == "s":
                value = strings[int(raw)] if raw.strip() else ""
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iter(q("s:t")))
            elif kind == "b":
                value = "TRUE" if raw == "1" else "FALSE" if raw else ""
            elif kind in ("str", "e"):
                value = raw
            else:
                fmt = 0
                if xfs is not None:
                    index = int(cell.get("s", "0"))
                    if index < len(xfs):
                        fmt = int(xfs[index].get("numFmtId", "0"))
                # Other number formats change the shown text (dates, %, currency).
                value = _general_number(raw) if fmt in (0, 1) and raw else ""
            if value:
                facts.parts.append(value)
                facts.blocks.append(value)
        sheet_rels = rels_of(z, part)
        for kind, ref, mode in sheet_rels.values():
            target = resolve(part, ref)
            if kind.endswith("/comments") or "threadedComment" in kind:
                root_c = load(z, target)
                if root_c is not None:
                    for node in root_c.iter():
                        if node.tag in (q("s:comment"),) or node.tag.endswith("}threadedComment"):
                            facts.parts.append(
                                "".join(t.text or "" for t in node.iter() if t.tag in (q("s:t"),) or t.tag.endswith("}text"))
                            )
            elif kind.endswith("/drawing"):
                drawing = load(z, target)
                drels = rels_of(z, target)
                for pic in drawing.iter(q("xdr:pic")) if drawing is not None else []:
                    blip = pic.find(".//a:blip", NS)
                    rel_pic = drels.get(blip.get(q("r:embed"), "")) if blip is not None else None
                    if rel_pic and rel_pic[0].endswith("/image") and rel_pic[2] != "External":
                        images += 1
    facts.sheets = names
    facts.images = images
    facts.metadata = core_metadata(z)
    return facts


# ---------------------------------------------------------------- ODF


ODF_SKIP = {
    q(t)
    for t in (
        "text:note",
        "office:annotation",
        "draw:frame",
        "draw:custom-shape",
        "text:tracked-changes",
    )
}


def _odf_text(node):
    """Text of one ODF paragraph/heading, without notes, comments or frames."""
    out = []

    def walk(n, top=False):
        if not top and n.tag in ODF_SKIP:
            return
        if n.tag == q("text:s"):
            out.append(" " * int(n.get(q("text:c"), "1")))
        elif n.tag == q("text:tab"):
            out.append("\t")
        elif n.tag == q("text:line-break"):
            out.append("\n")
        else:
            out.append(n.text or "")
            for child in n:
                walk(child)
                out.append(child.tail or "")

    walk(node, True)
    return "".join(out)


def _odf_meta(z):
    root = load(z, "meta.xml")
    out = {}
    if root is None:
        return out
    meta = root.find("office:meta", NS)
    if meta is None:
        return out

    def get(path):
        node = meta.find(path, NS)
        return (node.text or "").strip() if node is not None else ""

    if get("dc:title"):
        out["title"] = get("dc:title")
    # ODF: meta:initial-creator made the document; dc:creator last modified it.
    initial, last = get("meta:initial-creator"), get("dc:creator")
    if initial and (not last or last == initial):
        out["author"] = initial
    if get("meta:creation-date"):
        out["created"] = get("meta:creation-date")
    if get("dc:date"):
        out["modified"] = get("dc:date")
    return out


def _odf_list_styles(roots):
    styles = {}
    for root in roots:
        if root is None:
            continue
        for node in root.iter(q("text:list-style")):
            styles[node.get(q("style:name"), "")] = node
    return styles


def _odf_lists(body, list_styles):
    """Top-level text:list elements with at least one non-empty item."""
    tops = []

    def walk(node, depth):
        if node.tag == q("text:list"):
            if depth == 0:
                tops.append(node)
            depth += 1
        for child in node:
            walk(child, depth)

    walk(body, 0)
    tops = [n for n in tops if any(_odf_text(p).strip() for p in n.iter(q("text:p")))]

    def depth_of(node, level=1):
        nested = [
            depth_of(c, level + 1)
            for item in node.findall("text:list-item", NS)
            for c in item.findall("text:list", NS)
        ]
        return max(nested, default=level)

    kinds = []
    for node in tops:
        style = list_styles.get(node.get(q("text:style-name"), ""))
        first = None
        if style is not None:
            first = next(
                (c for c in style if c.get(q("text:level")) in (None, "1")), None
            )
        if first is None:
            kinds.append(None)
        elif first.tag == q("text:list-level-style-number") and first.get(
            q("style:num-format"), "1"
        ):
            kinds.append("ordered")
        elif first.tag == q("text:list-level-style-bullet"):
            kinds.append("unordered")
        else:
            kinds.append(None)
    depth = max((depth_of(n) for n in tops), default=0)
    result = {"count": len(tops)}
    if tops and None not in kinds:
        result.update(
            ordered_count=kinds.count("ordered"),
            unordered_count=kinds.count("unordered"),
            max_depth=depth,
            has_nested=depth > 1,
        )
    return result


def _odf_frames(root, z):
    images, boxes = 0, 0
    names = set(z.namelist())
    for frame in root.iter(q("draw:frame")):
        if frame.find("draw:object", NS) is not None or frame.find("draw:object-ole", NS) is not None:
            continue
        image = frame.find("draw:image", NS)
        if image is not None:
            href = image.get(q("xlink:href"), "")
            if href in names or href.lstrip("./") in names:
                images += 1
        box = frame.find("draw:text-box", NS)
        if box is not None and any(_odf_text(p).strip() for p in box.iter() if p.tag in (q("text:p"), q("text:h"))):
            boxes += 1
    return images, boxes


def _odf_paragraph_parts(root, facts):
    for node in root.iter():
        if node.tag in (q("text:p"), q("text:h")):
            value = _odf_text(node)
            facts.parts.append(value)
    # Deleted text of tracked changes is content a reviewer sees.
    for region in root.iter(q("text:changed-region")):
        for deletion in region.iter(q("text:deletion")):
            for p in deletion.iter():
                if p.tag in (q("text:p"), q("text:h")):
                    facts.parts.append(_odf_text(p))


def _odf_blocks(root, facts):
    def walk(node, deleted):
        if node.tag == q("text:tracked-changes"):
            return
        if node.tag in (q("text:p"), q("text:h")):
            value = _odf_text(node)
            if value.strip():
                facts.blocks.append(value)
        for child in node:
            walk(child, deleted)

    walk(root, False)


def _odf_tables(root):
    count, merged = 0, False
    for table in root.iter(q("table:table")):
        count += 1
        for cell in table.iter(q("table:table-cell")):
            if int(cell.get(q("table:number-columns-spanned"), "1")) > 1 or int(
                cell.get(q("table:number-rows-spanned"), "1")
            ) > 1:
                merged = True
    return {"count": count, "has_merged_cells": merged}


def read_odt(path):
    facts = Facts("odt: content.xml office:text, styles.xml master pages, meta.xml")
    z = zipfile.ZipFile(path)
    content = load(z, "content.xml")
    styles = load(z, "styles.xml")
    body = content.find("office:body/office:text", NS)
    _odf_paragraph_parts(body, facts)
    _odf_blocks(body, facts)
    facts.headings = [
        (int(h.get(q("text:outline-level"), "1")), _odf_text(h).strip())
        for h in body.iter(q("text:h"))
        if _odf_text(h).strip()
    ]
    facts.tables = _odf_tables(body)
    facts.lists = _odf_lists(body, _odf_list_styles([content, styles]))
    facts.images, facts.text_boxes = _odf_frames(body, z)
    facts.notes = [
        " ".join(_odf_text(p).strip() for p in note.iter(q("text:p")) if _odf_text(p).strip())
        for note in body.iter(q("text:note"))
    ]
    changes = []
    for region in body.iter(q("text:changed-region")):
        for kind, label in (("text:insertion", "insert"), ("text:deletion", "delete")):
            node = region.find(kind, NS)
            if node is not None:
                author = node.find("office:change-info/dc:creator", NS)
                changes.append(
                    {"type": label, "author": (author.text or "") if author is not None else ""}
                )
    facts.track_changes = changes
    # Headers/footers of the master pages the document uses.
    counts = [0, 0]
    if styles is not None:
        masters = styles.findall("office:master-styles/style:master-page", NS)
        used = {masters[0].get(q("style:name"))} if masters else set()
        for root in (content, styles):
            for node in root.iter():
                name = node.get(q("style:master-page-name"))
                if name:
                    used.add(name)
        for master in masters:
            if master.get(q("style:name")) not in used:
                continue
            for child in master:
                local = child.tag.split("}")[1]
                if not local.startswith(("header", "footer")) or child.get(q("style:display")) == "false":
                    continue
                texts = [_odf_text(p) for p in child.iter() if p.tag in (q("text:p"), q("text:h"))]
                facts.parts += texts
                facts.blocks += [t for t in texts if t.strip()]
                if "".join(texts).strip():
                    counts[0 if local.startswith("header") else 1] += 1
    facts.headers_footers = tuple(counts)
    facts.metadata = _odf_meta(z)
    return facts


def read_ods(path):
    facts = Facts("ods: content.xml office:spreadsheet, meta.xml")
    z = zipfile.ZipFile(path)
    content = load(z, "content.xml")
    body = content.find("office:body/office:spreadsheet", NS)
    names = []
    for table in body.findall("table:table", NS):
        names.append(table.get(q("table:name"), ""))  # scored as sheet names
    _odf_paragraph_parts(body, facts)
    _odf_blocks(body, facts)
    facts.sheets = names
    facts.images, _ = _odf_frames(body, z)
    facts.metadata = _odf_meta(z)
    return facts


def read_odp(path):
    facts = Facts("odp: content.xml draw:page order, presentation:notes, meta.xml")
    z = zipfile.ZipFile(path)
    content = load(z, "content.xml")
    body = content.find("office:body/office:presentation", NS)
    headings, notes = [], []
    images = 0
    tables = {"count": 0, "has_merged_cells": False}
    for page in body.findall("draw:page", NS):
        notes_node = page.find("presentation:notes", NS)
        for child in page:
            if child.tag == q("presentation:notes"):
                continue
            _odf_paragraph_parts(child, facts)
            _odf_blocks(child, facts)
            found = _odf_tables(child)
            tables["count"] += found["count"]
            tables["has_merged_cells"] |= found["has_merged_cells"]
            pics, _ = _odf_frames(child, z) if child.tag != q("draw:frame") else (0, 0)
            images += pics
            if child.tag == q("draw:frame"):
                image = child.find("draw:image", NS)
                if (
                    image is not None
                    and child.find("draw:object", NS) is None
                    and image.get(q("xlink:href"), "") in z.namelist()
                ):
                    images += 1
                if child.get(q("presentation:class")) == "title":
                    value = " ".join(
                        _odf_text(p).strip()
                        for p in child.iter()
                        if p.tag in (q("text:p"), q("text:h")) and _odf_text(p).strip()
                    )
                    if value:
                        headings.append((1, value))
                        continue
            for h in child.iter(q("text:h")):
                if _odf_text(h).strip():
                    headings.append((int(h.get(q("text:outline-level"), "1")), _odf_text(h).strip()))
        if notes_node is not None:
            paras = []
            for frame in notes_node.findall("draw:frame", NS):
                if frame.get(q("presentation:class")) != "notes":
                    continue
                paras += [_odf_text(p) for p in frame.iter(q("text:p"))]
            facts.parts += paras
            text = " ".join(p.strip() for p in paras if p.strip())
            if text:
                notes.append(text)
                facts.blocks += [p for p in paras if p.strip()]
    facts.headings = headings
    facts.tables = tables
    facts.images = images
    facts.speaker_notes = notes
    facts.metadata = _odf_meta(z)
    return facts


# ---------------------------------------------------------------- HTML / EPUB

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "body", "caption", "dd", "details",
    "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1",
    "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
    "pre", "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "ul", "br", "html", "title", "head",
}


def _html_blocks(root):
    """Text split at block boundaries; inline markup does not split words."""
    out, current = [], []

    def flush():
        value = "".join(current)
        if value.strip():
            out.append(value)
        current.clear()

    def walk(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            current.append(str(node))
            return
        if not isinstance(node, Tag):
            return
        block = node.name in BLOCK_TAGS
        if block:
            flush()
        for child in node.children:
            walk(child)
        if block:
            flush()

    walk(root)
    flush()
    return out


def _html_lists(body):
    lists = body.find_all(["ol", "ul"])
    tops = [n for n in lists if n.find_parent(["ol", "ul"]) is None and n.get_text().strip()]

    max_depth = max(
        (1 + len(n.find_parents(["ol", "ul"])) for n in lists if n.get_text().strip()),
        default=0,
    )
    return {
        "count": len(tops),
        "ordered_count": sum(n.name == "ol" for n in tops),
        "unordered_count": sum(n.name == "ul" for n in tops),
        "max_depth": max_depth,
        "has_nested": max_depth > 1,
    }


def _html_merge(facts, soup):
    body = soup.body or soup
    for node in body(["script", "style", "template", "noscript"]):
        node.decompose()
    blocks = _html_blocks(body)
    facts.parts += blocks
    facts.blocks += blocks
    headings = [
        (int(h.name[1]), " ".join(h.get_text().split()))
        for h in body.find_all(re.compile(r"^h[1-6]$"))
        if h.get_text().strip()
    ]
    facts.headings = (facts.headings or []) + headings
    tables = body.find_all("table")
    merged = any(
        int(re.sub(r"\D", "", c.get("colspan", "1")) or 1) > 1
        or int(re.sub(r"\D", "", c.get("rowspan", "1")) or 1) > 1
        for c in body.find_all(["td", "th"])
    )
    old = facts.tables or {"count": 0, "has_merged_cells": False}
    facts.tables = {
        "count": old["count"] + len(tables),
        "has_merged_cells": old["has_merged_cells"] or merged,
    }
    lists = _html_lists(body)
    if facts.lists:
        lists = {
            "count": facts.lists["count"] + lists["count"],
            "ordered_count": facts.lists["ordered_count"] + lists["ordered_count"],
            "unordered_count": facts.lists["unordered_count"] + lists["unordered_count"],
            "max_depth": max(facts.lists["max_depth"], lists["max_depth"]),
            "has_nested": facts.lists["has_nested"] or lists["has_nested"],
        }
    facts.lists = lists
    facts.images = (facts.images or 0) + len(body.find_all("img"))


def read_html(path):
    facts = Facts("html: BeautifulSoup(html.parser) body, <title>, <meta name=author>")
    soup = BeautifulSoup(Path(path).read_bytes(), "html.parser")
    title = soup.title.get_text().strip() if soup.title else ""
    author = soup.find("meta", attrs={"name": re.compile("^author$", re.I)})
    _html_merge(facts, soup)
    if title:
        facts.metadata["title"] = title
    if author and author.get("content", "").strip():
        facts.metadata["author"] = author["content"].strip()
    return facts


def read_epub(path):
    facts = Facts("epub: OPF spine XHTML via BeautifulSoup(html.parser), OPF dc:title/dc:creator")
    z = zipfile.ZipFile(path)
    container = load(z, "META-INF/container.xml")
    opf_path = container.find(".//ocf:rootfile", NS).get("full-path")
    opf = load(z, opf_path)
    manifest = {
        item.get("id"): resolve(opf_path, item.get("href", ""))
        for item in opf.find("opf:manifest", NS)
    }
    for ref in opf.find("opf:spine", NS).findall("opf:itemref", NS):
        part = manifest.get(ref.get("idref"))
        if part and part in z.namelist():
            _html_merge(facts, BeautifulSoup(z.read(part), "html.parser"))
    metadata = opf.find("opf:metadata", NS)
    titles = [n.text.strip() for n in metadata.findall("dc:title", NS) if (n.text or "").strip()]
    creators = [n.text.strip() for n in metadata.findall("dc:creator", NS) if (n.text or "").strip()]
    if titles:
        facts.metadata["title"] = titles[0]
    if len(creators) == 1:
        facts.metadata["author"] = creators[0]
    for node in metadata.findall("opf:meta", NS):
        if node.get("property") == "dcterms:modified" and (node.text or "").strip():
            facts.metadata["modified"] = node.text.strip()
    return facts


# ---------------------------------------------------------------- Markdown

GRID_BORDER = re.compile(r"^\+(?:[-=:]+\+)+\s*$")


def _grid_tables(lines):
    """Pandoc grid tables: (start, end, has_merged_cells) line ranges."""
    found, i = [], 0
    while i < len(lines):
        if GRID_BORDER.match(lines[i]):
            j = i + 1
            while j < len(lines) and lines[j][:1] in ("+", "|"):
                j += 1
            block = lines[i:j]
            columns = {m.start() for m in re.finditer(r"\+", block[0])}
            merged = False
            for line in block[1:]:
                if re.fullmatch(r"[|+=:\- ]+", line.rstrip()) and "+" in line:
                    # A separator crossed by '|' continues a cell down (row span);
                    # a missing '+' joins two columns (column span).
                    if "|" in line or {m.start() for m in re.finditer(r"\+", line)} != columns:
                        merged = True
                elif line.startswith("|"):
                    bars = {m.start() for m in re.finditer(r"\|", line)}
                    if not columns <= bars | {len(line)}:
                        merged = True
            found.append((i, j, merged))
            i = j
        else:
            i += 1
    return found


def read_md(path):
    facts = Facts("md: markdown-it-py CommonMark + GFM tables; Pandoc grid tables by syntax")
    source = Path(path).read_text(encoding="utf-8")
    lines = source.split("\n")
    grids = _grid_tables(lines)
    kept = list(lines)
    for start, end, _ in grids:
        for line in lines[start:end]:
            cells = [c for c in re.split(r"[|+]", line) if c.strip() and not re.fullmatch(r"[-=: ]+", c)]
            text = " ".join(c.strip() for c in cells)
            text = re.sub(r"\\(.)", r"\1", text)
            facts.parts.append(text)
            if text.strip():
                facts.blocks += [c.strip() for c in cells]
        for k in range(start, end):
            kept[k] = ""
    md = MarkdownIt("commonmark").enable("table")
    stream = md.parse("\n".join(kept))
    headings, tables, images = [], len(grids), 0
    depth, max_depth, tops = 0, 0, []
    merged = any(m for _, _, m in grids)
    for i, tok in enumerate(stream):
        if tok.type == "heading_open":
            inline = stream[i + 1]
            text = "".join(c.content for c in inline.children or [] if c.type in ("text", "code_inline"))
            if text.strip():
                headings.append((int(tok.tag[1]), text.strip()))
        elif tok.type == "table_open":
            tables += 1
        elif tok.type in ("bullet_list_open", "ordered_list_open"):
            if depth == 0:
                tops.append(tok.type == "ordered_list_open")
            depth += 1
            max_depth = max(max_depth, depth)
        elif tok.type in ("bullet_list_close", "ordered_list_close"):
            depth -= 1
        elif tok.type == "inline":
            pieces = []
            for child in tok.children or []:
                if child.type == "image":
                    images += 1
                    continue
                if child.type in ("text", "code_inline"):
                    pieces.append(child.content)
                elif child.type in ("softbreak", "hardbreak"):
                    pieces.append(" ")
                elif child.type == "html_inline":
                    pieces.append("")
            value = "".join(pieces)
            facts.parts.append(value)
            if value.strip():
                facts.blocks.append(value)
        elif tok.type in ("fence", "code_block"):
            facts.parts.append(tok.content)
            facts.blocks += [line for line in tok.content.split("\n") if line.strip()]
        elif tok.type == "html_block":
            value = BeautifulSoup(tok.content, "html.parser").get_text(" ")
            facts.parts.append(value)
            if value.strip():
                facts.blocks.append(value)
    facts.headings = headings
    facts.tables = {"count": tables, "has_merged_cells": merged}
    facts.images = images
    facts.lists = {
        "count": len(tops),
        "ordered_count": sum(tops),
        "unordered_count": len(tops) - sum(tops),
        "max_depth": max_depth,
        "has_nested": max_depth > 1,
    }
    return facts


# ---------------------------------------------------------------- CSV / TSV


def read_delimited(path, delimiter):
    facts = Facts(f"{'tsv' if delimiter == chr(9) else 'csv'}: Python csv module")
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle, delimiter=delimiter))
    for row in rows:
        for cell in row:
            facts.parts.append(cell)
            if cell.strip():
                facts.blocks.append(cell)
    facts.tables = {"count": 1 if any(any(c.strip() for c in r) for r in rows) else 0,
                    "has_merged_cells": False}
    return facts


READERS = {
    "docx": read_docx,
    "pptx": read_pptx,
    "xlsx": read_xlsx,
    "odt": read_odt,
    "ods": read_ods,
    "odp": read_odp,
    "html": read_html,
    "epub": read_epub,
    "md": read_md,
    "csv": lambda p: read_delimited(p, ","),
    "tsv": lambda p: read_delimited(p, "\t"),
}


def read(path, fmt):
    return READERS[fmt](path)
