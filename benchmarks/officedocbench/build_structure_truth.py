"""Build v2 assertions from Office XML, never from AILANG output.

The original 69 annotations are retained. Newly added Office regression files
are scored on these independently derived assertions only. Source SHA-256 and
oracle revision are recorded so the ground truth can be audited/reproduced.
"""

from __future__ import annotations
import hashlib
import json
import posixpath
import re
import zipfile
import sys
from pathlib import Path
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[2]
GT = Path(__file__).parent / "ground_truth"
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}


def tag(n):
    p, k = n.split(":")
    return "{" + NS[p] + "}" + k


def xml(z, p):
    try:
        return E.fromstring(z.read(p))
    except KeyError:
        return E.Element("missing")


def words(e, ns="w"):
    return "".join(n.text or "" for n in e.iter(tag(ns + ":t")))


def rels(z, part):
    root = xml(
        z,
        posixpath.join(
            posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
        ),
    )
    return {n.get("Id"): n for n in root}


def target(part, rel):
    t = rel.get("Target", "")
    return (
        posixpath.normpath(posixpath.join(posixpath.dirname(part), t))
        if not t.startswith("/")
        else t[1:]
    )


def val(n, key, default=""):
    return n.get(tag(key), default) if n is not None else default


def enabled(n):
    return n is not None and val(n, "w:val", "1") not in ("0", "false", "off", "none")


def put(out, key, rows):
    if rows:
        out[key] = rows


def docx(z):
    doc = xml(z, "word/document.xml")
    body = doc.find("w:body", NS)
    out = {}
    if body is None:
        return out
    rs = rels(z, "word/document.xml")
    tables = []
    runs = []
    links = []
    lists = []
    styles = {
        val(n, "w:styleId"): n for n in xml(z, "word/styles.xml").findall("w:style", NS)
    }
    numbering = xml(z, "word/numbering.xml")
    nums = {
        val(n, "w:numId"): val(n.find("w:abstractNumId", NS), "w:val")
        for n in numbering.findall("w:num", NS)
    }
    abstracts = {
        val(n, "w:abstractNumId"): n for n in numbering.findall("w:abstractNum", NS)
    }
    for para in body.iter(tag("w:p")):
        para.find("w:pPr", NS)
        np = para.find("w:pPr/w:numPr", NS)
        if np is None:
            style = styles.get(val(para.find("w:pPr/w:pStyle", NS), "w:val"))
            if style is not None:
                np = style.find("w:pPr/w:numPr", NS)
        sid = val(para.find("w:pPr/w:pStyle", NS), "w:val")
        if sid.startswith("Heading") or sid in ("Title", "Subtitle"):
            continue
        ancestor = styles.get(sid)
        seen = set()
        is_heading = False
        while ancestor is not None and sid not in seen:
            seen.add(sid)
            outline = ancestor.find("w:pPr/w:outlineLvl", NS)
            if outline is not None and int(val(outline, "w:val", "9")) < 9:
                is_heading = True
            sid = val(ancestor.find("w:basedOn", NS), "w:val")
            ancestor = styles.get(sid)
        if is_heading:
            continue
        if np is not None:
            if val(np.find("w:numId", NS), "w:val") == "0":
                continue
            level = int(val(np.find("w:ilvl", NS), "w:val", "0"))
            num = val(np.find("w:numId", NS), "w:val")
            ab = abstracts.get(nums.get(num))
            fmt = None
            if ab is not None:
                fmt = ab.find(f"w:lvl[@w:ilvl='{level}']/w:numFmt", NS)
            if ab is not None:
                indent = ab.find(f"w:lvl[@w:ilvl='{level}']/w:pPr/w:ind", NS)
                if indent is not None and level == 0:
                    level = max(0, int(val(indent, "w:left", "360")) // 360 - 1)
            if words(para):
                lists.append(
                    {
                        "text": words(para),
                        "ordered": val(fmt, "w:val") not in ("bullet", "none", ""),
                        "level": level,
                    }
                )
    for ti, tbl in enumerate(body.iter(tag("w:tbl"))):
        for ri, tr in enumerate(tbl.findall("w:tr", NS), 1):
            ci = 1
            for tc in tr.findall("w:tc", NS):
                cs = int(val(tc.find("w:tcPr/w:gridSpan", NS), "w:val", "1"))
                vm = tc.find("w:tcPr/w:vMerge", NS)
                tables.append(
                    {
                        "table": ti,
                        "row": ri,
                        "col": ci,
                        "text": " ".join(
                            words(p) for p in tc.findall("w:p", NS)
                        ).strip(),
                        "col_span": cs,
                        "merged": vm is not None and val(vm, "w:val") != "restart",
                    }
                )
                ci += cs
    for run in body.iter(tag("w:r")):
        content = words(run)
        pr = run.find("w:rPr", NS)
        if not content.strip() or pr is None:
            continue
        record = {"text": content}
        for source, key in [
            ("b", "bold"),
            ("i", "italic"),
            ("u", "underline"),
            ("strike", "strike"),
        ]:
            node = pr.find("w:" + source, NS)
            if node is not None:
                record[key] = enabled(node)
        color = val(pr.find("w:color", NS), "w:val")
        if re.fullmatch("[0-9a-fA-F]{6}", color):
            record["color"] = "#" + color.lower()
        vert = val(pr.find("w:vertAlign", NS), "w:val")
        if vert:
            record["vertAlign"] = vert
        if len(record) > 1:
            runs.append(record)
    for link in body.iter(tag("w:hyperlink")):
        rel = rs.get(link.get(tag("r:id")))
        url = rel.get("Target") if rel is not None else "#" + val(link, "w:anchor")
        if words(link):
            links.append({"text": words(link), "url": url})
    comments = xml(z, "word/comments.xml")
    texts = {val(c, "w:id"): c for c in comments}
    active = {}
    anchors = {}

    # The XML range, including table/sdt paragraphs, is the source of truth.
    def walk(node):
        if node.tag == tag("w:commentRangeStart"):
            active[val(node, "w:id")] = []
        elif node.tag == tag("w:commentRangeEnd"):
            cid = val(node, "w:id")
            anchors[cid] = "".join(active.pop(cid, []))
        elif node.tag == tag("w:t"):
            for parts in active.values():
                parts.append(node.text or "")
        elif node.tag == tag("w:tab"):
            for parts in active.values():
                parts.append("\t")
        for child in node:
            walk(child)
        if node.tag == tag("w:p"):
            for parts in active.values():
                parts.append(" ")

    walk(body)
    for para in body.iter(tag("w:p")):
        for ref in para.iter(tag("w:commentReference")):
            cid = val(ref, "w:id")
            if cid not in anchors:
                anchors[cid] = words(para)
    records = [
        {
            "text": " ".join(words(p) for p in c.findall("w:p", NS)),
            "author": val(c, "w:author"),
            "annotated_text": " ".join(anchors.get(cid, "").split()),
            "anchored": bool(anchors.get(cid, "").strip()),
        }
        for cid, c in texts.items()
        if words(c)
    ]
    put(out, "comment_anchors", records)
    put(out, "table_cells", tables)
    put(out, "runs", runs)
    put(out, "list_items", lists)
    put(out, "hyperlinks", links)
    put(
        out,
        "bookmarks",
        [
            {"name": val(b, "w:name")}
            for b in body.iter(tag("w:bookmarkStart"))
            if val(b, "w:name") and not val(b, "w:name").startswith("_")
        ],
    )
    put(out, "breaks", [{"kind": "section-break"} for b in body.iter(tag("w:sectPr"))])
    return out


def xlsx(z):
    wb = xml(z, "xl/workbook.xml")
    rs = rels(z, "xl/workbook.xml")
    strings = ["".join(x.itertext()) for x in xml(z, "xl/sharedStrings.xml")]
    out = {}
    containers = []
    cells = []
    anchors = []
    links = []
    people = {}
    for name in z.namelist():
        if name.startswith("xl/persons/") and name.endswith(".xml"):
            people.update({p.get("id"): p.get("displayName", "") for p in xml(z, name)})
    st = xml(z, "xl/styles.xml")
    fills = st.find("s:fills", NS)
    fonts = st.find("s:fonts", NS)
    xfs = st.find("s:cellXfs", NS)
    for ti, sh in enumerate(wb.findall("s:sheets/s:sheet", NS)):
        name = sh.get("name")
        containers.append({"kind": "sheet", "name": name})
        rel = rs.get(sh.get(tag("r:id")))
        if rel is None:
            parts = [
                p
                for p in z.namelist()
                if re.fullmatch("xl/worksheets/sheet[0-9]+.xml", p)
            ]
            if len(parts) != 1:
                continue
            part = parts[0]
        else:
            part = target("xl/workbook.xml", rel)
        sheet = xml(z, part)
        sr = rels(z, part)
        ct = {}
        for c in sheet.findall(".//s:sheetData/s:row/s:c", NS):
            ref = c.get("r", "")
            m = re.fullmatch("([A-Z]+)([0-9]+)", ref)
            if not m:
                continue
            col = 0
            for ch in m[1]:
                col = col * 26 + ord(ch) - 64
            ri = int(m[2])
            v = c.find("s:v", NS)
            typ = c.get("t")
            value = v.text or "" if v is not None else ""
            if typ == "s":
                value = strings[int(value)] if value else ""
            elif typ == "inlineStr":
                value = words(c, "s")
            elif typ == "b":
                value = "true" if value == "1" else "false"
            ct[ref] = value
            rec = {"table": ti, "scope": name, "row": ri, "col": col}
            xf = xfs[int(c.get("s", "0"))] if xfs is not None else None
            fmt = int(xf.get("numFmtId", "0")) if xf is not None else 0
            # Do not confuse raw stored numbers with display-formatted values.
            if typ in ("s", "inlineStr", "str") or fmt in (0, 1, 2):
                rec["text"] = value
            formula = c.find("s:f", NS)
            if formula is not None and formula.text:
                rec["formula"] = formula.text
                if not value:
                    rec.pop("text", None)
            if xf is not None:
                for group, idkey, prop in [
                    (fills, "fillId", "fill"),
                    (fonts, "fontId", "color"),
                ]:
                    if group is None:
                        continue
                    item = group[int(xf.get(idkey, "0"))]
                    node = (
                        item.find("s:patternFill/s:fgColor", NS)
                        if prop == "fill"
                        else item.find("s:color", NS)
                    )
                    rgb = node.get("rgb", "") if node is not None else ""
                    if re.fullmatch("[0-9A-Fa-f]{8}", rgb):
                        rec[prop] = "#" + rgb[-6:].lower()
            # AILANG intentionally collapses gaps > 100 rows; assertions keep
            # source coordinates only before the first such gap.
            if ri <= 100 and len(rec) > 4:
                cells.append(rec)

        # Merge ranges identify logical anchor/covered coordinates independently
        # of how many empty cells the workbook happened to serialize.
        def coord(ref):
            m = re.fullmatch(r"([A-Z]+)([0-9]+)", ref)
            col = 0
            for ch in m[1]:
                col = col * 26 + ord(ch) - 64
            return int(m[2]), col

        for merge in sheet.findall("s:mergeCells/s:mergeCell", NS):
            refs = merge.get("ref").split(":")
            first, last = refs[0], refs[-1]
            r1, c1 = coord(first)
            r2, c2 = coord(last)
            for ri in range(r1, min(r2, 100) + 1):
                for ci in range(c1, c2 + 1):
                    rec = next(
                        (
                            c
                            for c in cells
                            if c["table"] == ti and c["row"] == ri and c["col"] == ci
                        ),
                        None,
                    )
                    if rec is None:
                        rec = {"table": ti, "scope": name, "row": ri, "col": ci}
                        cells.append(rec)
                    rec["merged"] = (ri, ci) != (r1, c1)
                    if (ri, ci) == (r1, c1):
                        rec["col_span"] = c2 - c1 + 1
                    else:
                        rec["text"] = ""
        for link in sheet.findall("s:hyperlinks/s:hyperlink", NS):
            rel = sr.get(link.get(tag("r:id")))
            if rel is not None:
                links.append(
                    {"text": ct.get(link.get("ref"), ""), "url": rel.get("Target", "")}
                )
        for rel in sr.values():
            if "threadedComment" in rel.get("Type", ""):
                for c in xml(z, target(part, rel)):
                    content = "".join(c.itertext()).strip()
                    ref = c.get("ref", "")
                    record = {
                        "text": content,
                        "author": people.get(c.get("personId"), ""),
                        "annotated_text": f"{ref}: {ct.get(ref, '')}",
                        "anchored": True,
                        "scope": name,
                    }
                    if c.get("parentId"):
                        record["parent_id"] = c.get("parentId")
                    anchors.append(record)
            if rel.get("Type", "").endswith("/comments"):
                cm = xml(z, target(part, rel))
                authors = cm.find("s:authors", NS)
                authors = [a.text or "" for a in authors] if authors is not None else []
                for c in cm.findall("s:commentList/s:comment", NS):
                    if words(c, "s").startswith("[Threaded comment]"):
                        continue
                    ref = c.get("ref", "")
                    author = int(c.get("authorId", "0"))
                    anchors.append(
                        {
                            "text": words(c, "s"),
                            "author": authors[author] if author < len(authors) else "",
                            "annotated_text": f"{ref}: {ct.get(ref, '')}",
                            "anchored": True,
                            "scope": name,
                        }
                    )
    put(out, "containers", containers)
    put(out, "table_cells", cells)
    put(out, "comment_anchors", anchors)
    put(out, "hyperlinks", links)
    return out


def pptx(z):
    part = "ppt/presentation.xml"
    pres = xml(z, part)
    rs = rels(z, part)
    out = {}
    containers = []
    notes = []
    runs = []
    for slide in pres.findall("p:sldIdLst/p:sldId", NS):
        rel = rs.get(slide.get(tag("r:id")))
        if rel is None:
            continue
        sp = target(part, rel)
        root = xml(z, sp)
        title = ""
        for shape in root.findall(".//p:sp", NS):
            ph = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
            if ph is not None and ph.get("type") in ("title", "ctrTitle"):
                title = words(shape, "a")
                break
        containers.append({"kind": "slide", "name": title})
        for rel in rels(z, sp).values():
            if rel.get("Type", "").endswith("/notesSlide"):
                nr = xml(z, target(sp, rel))
                paras = []
                for shape in nr.findall(".//p:sp", NS):
                    ph = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
                    if ph is not None and ph.get("type") in (
                        "sldNum",
                        "dt",
                        "hdr",
                        "ftr",
                        "sldImg",
                    ):
                        continue
                    paras += [
                        words(p, "a")
                        for p in shape.findall(".//a:p", NS)
                        if words(p, "a")
                    ]
                if paras:
                    notes.append({"scope": title, "text": " ".join(paras)})
        for run in root.findall(".//a:r", NS):
            pr = run.find("a:rPr", NS)
            content = words(run, "a")
            if pr is None or not content:
                continue
            rec = {"text": content}
            for src, key in [("b", "bold"), ("i", "italic")]:
                if src in pr.attrib:
                    rec[key] = pr.get(src) in ("1", "true")
            if pr.get("u"):
                rec["underline"] = pr.get("u") != "none"
            if len(rec) > 1:
                runs.append(rec)
    put(out, "containers", containers)
    put(out, "notes", notes)
    put(out, "runs", runs)
    return out


def main():
    declared = set(json.loads((GT.parent / "corpus.json").read_text())["files"])
    count = 0
    added = 0
    errors = []
    check = "--check" in sys.argv
    for source in sorted((ROOT / "data/test_files").rglob("*")):
        if source.suffix not in (".docx", ".pptx", ".xlsx") or "stress" in source.parts:
            continue
        if source.name not in declared:
            continue
        dest = GT / (source.name + ".json")
        with zipfile.ZipFile(source) as z:
            expect = {"docx": docx, "xlsx": xlsx, "pptx": pptx}[source.suffix[1:]](z)
        if not expect:
            continue
        if dest.exists():
            gt = json.loads(dest.read_text())
        else:
            gt = {
                "file": source.name,
                "format": source.suffix[1:],
                "source": "Existing Office regression fixture",
                "features": {"text": {"paragraph_count": 0, "total_words": 0}},
                "structure_only": True,
            }
            added += 1
        gt["structure"] = expect
        if source.suffix == ".docx":
            with zipfile.ZipFile(source) as package:
                if not words(xml(package, "word/document.xml")).strip():
                    gt["allow_empty_output"] = True
        elif source.suffix == ".pptx":
            with zipfile.ZipFile(source) as package:
                slides = [
                    p
                    for p in package.namelist()
                    if re.fullmatch(r"ppt/slides/slide[0-9]+.xml", p)
                ]
                if slides and not any(
                    words(xml(package, p), "a").strip() for p in slides
                ):
                    gt["allow_empty_output"] = True
        if source.name == "challenge_threaded_comments.xlsx":
            gt["input_profile"] = "recovery"
            gt["input_note"] = (
                "Minimal XLSX without xl/_rels/workbook.xml.rels; tests recovery as well as threaded comments."
            )
        gt["verification"] = {
            "method": "Office XML assertions; independent of parser output",
            "oracle": "build_structure_truth.py v2",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        gt["benchmark_version"] = "2.0.0"
        rendered = json.dumps(gt, indent=2, ensure_ascii=False) + "\n"
        if check:
            if not dest.exists() or dest.read_text() != rendered:
                errors.append(source.name)
        else:
            dest.write_text(rendered)
        count += 1
    print(f"{count} source-verified annotations; {added} new fixtures")
    if errors:
        raise SystemExit("Source assertions need updating: " + ", ".join(errors))


if __name__ == "__main__":
    main()
