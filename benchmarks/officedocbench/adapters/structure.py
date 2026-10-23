"""Map provider OUTPUT into the v2 assertions; never reopen the input file."""

from __future__ import annotations


def cell(value):
    return dict(value) if isinstance(value, dict) else {"text": str(value)}


def table_cells(rows, table, scope=""):
    out = []
    for ri, row in enumerate(rows, 1):
        ci = 1
        for i, value in enumerate(row):
            c = cell(value)
            out.append(
                {
                    "table": table,
                    "scope": scope,
                    "row": ri,
                    "col": ci,
                    "text": c.get("text", ""),
                    "col_span": c.get("colSpan", c.get("col_span", 1)),
                    "merged": c.get("merged", False),
                    **{k: c[k] for k in ("formula", "fill", "color") if k in c},
                }
            )
            span = c.get("colSpan", c.get("col_span", 1))
            # Some APIs keep covered cells; others omit them. Both map to
            # the same logical column coordinates.
            covered = i + 1 < len(row) and cell(row[i + 1]).get("merged", False)
            ci += 1 if covered else span
    return out


def raw_structure(raw):
    """AILANG's public Block JSON, preserving information lost by v1."""
    out = {
        k: []
        for k in (
            "table_cells",
            "containers",
            "element_order",
            "comment_anchors",
            "list_items",
            "runs",
            "hyperlinks",
            "bookmarks",
            "breaks",
            "notes",
            "images",
        )
    }
    table = 0

    def runs(rs):
        for run in rs:
            flags = {
                k: run.get(k, False)
                for k in ("bold", "italic", "underline", "strike", "code")
            }
            out["runs"].append(
                {
                    "text": run.get("text", ""),
                    **flags,
                    "color": run.get("color", ""),
                    "vertAlign": run.get("vertAlign", ""),
                }
            )
            if run.get("href"):
                out["hyperlinks"].append(
                    {"text": run.get("text", ""), "url": run["href"]}
                )

    def walk(blocks, scope=""):
        nonlocal table
        active = scope
        for b in blocks:
            kind, typ = b.get("kind", ""), b.get("type")
            if typ == "section":
                if kind in ("sheet", "slide"):
                    name = b.get("name", "")
                    if kind == "slide":
                        name = next(
                            (
                                x.get("text", "")
                                for x in b.get("blocks", [])
                                if x.get("type") == "heading"
                            ),
                            "",
                        )
                    active = name
                    out["containers"].append({"kind": kind, "name": name})
                    walk(b.get("blocks", []), name)
                elif kind == "notes":
                    words = [x.get("text", "") for x in b.get("blocks", [])]
                    out["notes"].append({"scope": active, "text": " ".join(words)})
                elif kind == "bookmark":
                    out["bookmarks"].append({"name": b.get("name", "")})
                elif kind.endswith("-break"):
                    out["breaks"].append({"kind": kind})
                else:
                    walk(b.get("blocks", []), active)
            elif typ == "table":
                rows = ([b["headers"]] if b.get("headers") else []) + b.get("rows", [])
                out["table_cells"] += table_cells(rows, table, active)
                out["element_order"].append({"type": "table"})
                table += 1
            elif typ in ("text", "heading"):
                if b.get("text", "").strip():
                    out["element_order"].append({"type": typ, "text": b["text"]})
                runs(b.get("runs") or [{"text": b.get("text", "")}])
            elif typ == "list":
                levels = b.get("itemLevels", [])
                for i, item in enumerate(b.get("items", [])):
                    out["list_items"].append(
                        {
                            "text": item,
                            "ordered": b.get("ordered", False),
                            "level": levels[i] if i < len(levels) else 0,
                        }
                    )
                for rs in b.get("itemRuns", []):
                    runs(rs)
                out["element_order"].append({"type": "list"})
            elif typ == "comment":
                out["comment_anchors"].append(
                    {
                        "text": b.get("text", ""),
                        "author": b.get("author", ""),
                        "annotated_text": b.get("anchorText", ""),
                        "anchored": b.get("anchored", False),
                        "parent_id": b.get("parentId", ""),
                        "resolved": b.get("resolved", False),
                        "scope": active,
                    }
                )
            elif typ == "link":
                out["hyperlinks"].append(
                    {"text": b.get("text", ""), "url": b.get("href", "")}
                )
            elif typ == "image":
                out["images"].append(
                    {
                        "mime": b.get("mime", ""),
                        "width": b.get("width", 0),
                        "height": b.get("height", 0),
                    }
                )

    walk(raw.get("document", {}).get("blocks", []))
    return out


def html_rows(markup):
    """Preserve empty cells and expand HTML spans into their logical grid."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(markup or "", "html.parser")
    rows, occupied = [], {}
    for ri, tr in enumerate(soup.select("tr")):
        row, ci = [], 0
        for node in tr.find_all(["th", "td"], recursive=False):
            while (ri, ci) in occupied:
                row.append(occupied[ri, ci])
                ci += 1
            cs, rs = int(node.get("colspan", 1)), int(node.get("rowspan", 1))
            row.append({"text": node.get_text(" ", strip=True), "colSpan": cs})
            for dy in range(rs):
                for dx in range(cs):
                    if dx or dy:
                        occupied[ri + dy, ci + dx] = {"text": "", "merged": True}
            ci += 1
        while (ri, ci) in occupied:
            row.append(occupied[ri, ci])
            ci += 1
        rows.append(row)
    return rows


def markdown_output(source):
    """Read only features explicitly present in a provider's Markdown/HTML."""
    from markdown_it import MarkdownIt

    parser = MarkdownIt("commonmark").enable("table")
    tokens = parser.parse(source)
    out = {
        k: []
        for k in (
            "text_elements",
            "headings",
            "tables",
            "lists",
            "images",
            "hyperlinks",
        )
    }
    structure = {
        k: []
        for k in ("element_order", "table_cells", "runs", "list_items", "hyperlinks")
    }
    list_stack, table, row, _cells = [], None, [], []
    heading = 0
    for token in tokens:
        if token.type == "heading_open":
            heading = int(token.tag[1:])
        elif token.type in ("bullet_list_open", "ordered_list_open"):
            list_stack.append(token.type == "ordered_list_open")
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            list_stack.pop()
        elif token.type == "table_open":
            table = []
        elif token.type == "tr_open":
            row = []
        elif token.type == "tr_close":
            table.append(row)
        elif token.type == "table_close":
            idx = len(out["tables"])
            structure["table_cells"] += table_cells(table, idx)
            out["tables"].append(
                {
                    "rows": table,
                    "row_count": max(len(table) - 1, 0),
                    "cell_text": " ".join(x for r in table for x in r),
                    "has_merged_cells": False,
                }
            )
            structure["element_order"].append({"type": "table"})
            table = None
        elif token.type == "html_block" and "<table" in token.content:
            structure["element_order"].append({"type": "table"})
            rows = html_rows(token.content)
            idx = len(out["tables"])
            structure["table_cells"] += table_cells(rows, idx)
            out["tables"].append(
                {
                    "rows": rows,
                    "row_count": max(len(rows) - 1, 0),
                    "has_merged_cells": any(
                        cell(c).get("colSpan", 1) > 1 or cell(c).get("merged")
                        for r in rows
                        for c in r
                    ),
                    "cell_text": " ".join(cell(c)["text"] for r in rows for c in r),
                }
            )
        elif token.type == "inline":
            value = "".join(
                c.content
                for c in (token.children or [])
                if c.type in ("text", "code_inline", "softbreak")
            )
            flags = {"bold": False, "italic": False, "strike": False}
            href = ""
            for child in token.children or []:
                for tag, key in (("strong", "bold"), ("em", "italic"), ("s", "strike")):
                    if child.type == tag + "_open":
                        flags[key] = True
                    elif child.type == tag + "_close":
                        flags[key] = False
                if child.type == "link_open":
                    href = child.attrGet("href") or ""
                elif child.type == "link_close":
                    href = ""
                elif child.type in ("text", "code_inline"):
                    structure["runs"].append(
                        {
                            "text": child.content,
                            **flags,
                            "code": child.type == "code_inline",
                        }
                    )
                    if href:
                        structure["hyperlinks"].append(
                            {"text": child.content, "url": href}
                        )
                elif child.type == "image":
                    out["images"].append({"description": child.content})
            if table is not None:
                row.append(value)
            elif heading:
                out["headings"].append({"text": value, "level": heading})
                structure["element_order"].append({"type": "heading", "text": value})
                heading = 0
            elif list_stack:
                out["lists"].append(
                    {
                        "items": [value],
                        "ordered": list_stack[-1],
                        "depth": len(list_stack),
                    }
                )
                structure["list_items"].append(
                    {
                        "text": value,
                        "ordered": list_stack[-1],
                        "level": len(list_stack) - 1,
                    }
                )
            elif value.strip():
                out["text_elements"].append({"text": value, "style": "paragraph"})
                structure["element_order"].append({"type": "text", "text": value})
    out["hyperlinks"] = structure["hyperlinks"]
    out["structure"] = structure
    out["metadata"] = {}
    return out


def pandoc_structure(ast, table_parser):
    out = {
        k: []
        for k in (
            "element_order",
            "table_cells",
            "runs",
            "list_items",
            "hyperlinks",
            "bookmarks",
        )
    }

    def inline(nodes, flags=None):
        flags = flags or {}
        for n in nodes:
            t, c = n.get("t"), n.get("c")
            key = {
                "Strong": "bold",
                "Emph": "italic",
                "Underline": "underline",
                "Strikeout": "strike",
            }.get(t)
            if key:
                inline(c, {**flags, key: True})
            elif t in ("Str", "Code"):
                out["runs"].append({"text": c if t == "Str" else c[1], **flags})
            elif t == "Link":
                out["hyperlinks"].append({"text": plain(c[1]), "url": c[2][0]})
                inline(c[1], flags)
            elif t == "Span":
                if c[0][0]:
                    out["bookmarks"].append({"name": c[0][0]})
                inline(c[1], flags)

    def plain(ns):
        return "".join(
            n.get("c", "")
            if n.get("t") == "Str"
            else " "
            if n.get("t") in ("Space", "SoftBreak")
            else plain(n["c"])
            if n.get("t") in ("Strong", "Emph", "Underline", "Strikeout")
            else ""
            for n in ns
        )

    def walk(bs, level=0):
        for b in bs:
            t, c = b.get("t"), b.get("c")
            if t in ("Para", "Plain", "Header"):
                ins = c[2] if t == "Header" else c
                inline(ins)
                if not level:
                    out["element_order"].append(
                        {
                            "type": "heading" if t == "Header" else "text",
                            "text": plain(ins),
                        }
                    )
            elif t in ("OrderedList", "BulletList"):
                its = c[1] if t == "OrderedList" else c
                for item in its:
                    value = " ".join(
                        plain(x["c"]) for x in item if x.get("t") in ("Para", "Plain")
                    )
                    out["list_items"].append(
                        {"text": value, "ordered": t == "OrderedList", "level": level}
                    )
                    walk(item, level + 1)
                if not level:
                    out["element_order"].append({"type": "list"})
            elif t == "Table":
                table = table_parser(c)
                idx = len({x["table"] for x in out["table_cells"]})
                out["table_cells"] += table_cells(table.get("rows", []), idx)
                out["element_order"].append({"type": "table"})
            elif t == "Div":
                walk(c[1], level)
            elif t == "BlockQuote":
                walk(c, level)

    walk(ast.get("blocks", []))
    return out


def docling_structure(document):
    out = {
        k: []
        for k in ("element_order", "table_cells", "runs", "list_items", "hyperlinks")
    }
    for item in document.get("texts", []):
        fmt = item.get("formatting") or {}
        out["runs"].append(
            {
                "text": item.get("text", ""),
                "bold": fmt.get("bold", False),
                "italic": fmt.get("italic", False),
                "underline": fmt.get("underline", False),
                "strike": fmt.get("strikethrough", False),
                "vertAlign": {"super": "superscript", "sub": "subscript"}.get(
                    fmt.get("script"), ""
                ),
            }
        )
        if item.get("hyperlink"):
            out["hyperlinks"].append(
                {"text": item.get("text", ""), "url": item["hyperlink"]}
            )
    sheet_groups = [g for g in document.get("groups", []) if g.get("label") == "sheet"]
    table_sheets = {
        r["$ref"]: (i, g.get("name", ""))
        for i, g in enumerate(sheet_groups)
        for r in g.get("children", [])
    }
    out["containers"] = [
        {"kind": "sheet", "name": g.get("name", "")} for g in sheet_groups
    ]
    for group in document.get("groups", []):
        if group.get("label") == "chapter" and group.get("name", "").startswith(
            "slide-"
        ):
            title = ""
            for ref in group.get("children", []):
                parts = ref.get("$ref", "").split("/")
                if len(parts) == 3 and parts[1] == "texts":
                    item = document["texts"][int(parts[2])]
                    if item.get("label") in ("title", "section_header"):
                        title = item.get("text", "")
                        break
            out["containers"].append({"kind": "slide", "name": title})

    for ti, tbl in enumerate(document.get("tables", [])):
        sheet_index, scope = table_sheets.get(tbl.get("self_ref"), (ti, ""))
        provenance = tbl.get("prov", [])
        bbox = provenance[0].get("bbox", {}) if provenance and scope else {}
        row_offset, col_offset = int(bbox.get("t", 0)), int(bbox.get("l", 0))
        for c in tbl.get("data", {}).get("table_cells", []):
            out["table_cells"].append(
                {
                    "table": sheet_index,
                    "scope": scope,
                    "row": c.get("start_row_offset_idx", 0) + 1 + row_offset,
                    "col": c.get("start_col_offset_idx", 0) + 1 + col_offset,
                    "text": c.get("text", ""),
                    "col_span": c.get("col_span", 1),
                    "merged": False,
                }
            )

    def walk(node, level=0):
        label = node.get("label", "")
        value = node.get("text", "")
        typ = {
            "section_header": "heading",
            "title": "heading",
            "table": "table",
            "list_item": "list",
        }.get(label, "text")
        if label == "list_item":
            out["list_items"].append(
                {
                    "text": value,
                    "ordered": node.get("enumerated", False),
                    "level": max(level - 1, 0),
                }
            )
        if value or label == "table":
            out["element_order"].append(
                {"type": typ, **({"text": value} if typ != "table" else {})}
            )
        for ref in node.get("children", []):
            parts = ref.get("$ref", "").split("/")
            if len(parts) == 3:
                walk(
                    document[parts[1]][int(parts[2])],
                    level + int(label in ("list", "ordered_list")),
                )

    walk(document.get("body", {}))
    return out


def kreuzberg_structure(result):
    out = {
        k: []
        for k in (
            "element_order",
            "table_cells",
            "containers",
            "runs",
            "list_items",
            "notes",
        )
    }
    meta = result.metadata or {}
    names = meta.get("sheet_names", []) if isinstance(meta, dict) else []
    if names:
        out["containers"] = [{"kind": "sheet", "name": n} for n in names]
    nodes = (
        (result.document or {}).get("nodes", [])
        if isinstance(result.document, dict)
        else []
    )
    scope = ""
    ti = 0
    for node in nodes:
        c = node.get("content", {})
        typ = c.get("node_type")
        value = c.get("text", "")
        if (
            typ == "group"
            and isinstance(meta, dict)
            and meta.get("format_type") == "pptx"
        ):
            out["containers"].append(
                {"kind": "slide", "name": c.get("heading_text", "")}
            )
        if typ == "group" and c.get("heading_text") in names:
            scope = c["heading_text"]
        if typ == "table":
            grid = c.get("grid", {})
            for item in grid.get("cells", []):
                out["table_cells"].append(
                    {
                        "table": ti,
                        "scope": scope,
                        "row": item.get("row", 0) + 1,
                        "col": item.get("col", 0) + 1,
                        "text": item.get("content", ""),
                        "col_span": item.get("col_span", 1),
                        "merged": False,
                    }
                )
            out["element_order"].append({"type": "table"})
            ti += 1
        elif typ in ("paragraph", "heading") and value:
            out["element_order"].append(
                {"type": "text" if typ == "paragraph" else typ, "text": value}
            )
        elif typ == "list_item":
            out["list_items"].append(
                {
                    "text": value,
                    "level": c.get("level", 0),
                    "ordered": c.get("ordered", False),
                }
            )
    # Older versions may expose only ExtractedTable.cells.
    if not out["table_cells"]:
        for ti, tbl in enumerate(result.tables or []):
            rows = getattr(tbl, "cells", []) or []
            out["table_cells"] += table_cells(
                rows, ti, names[ti] if ti < len(names) else ""
            )
    return out


def add_sheet_scopes(output):
    """Worksheet headings explicitly emitted by Markdown providers are names.

    Uses provider reading order only. Does not consult the workbook or truth.
    Native container mappings always take precedence.
    """
    structure = output.setdefault("structure", {})
    if structure.get("containers"):
        return output
    scopes = {}
    names = []
    active = ""
    table = 0
    headings = output.get("headings", [])
    minimum = min((h.get("level", 1) for h in headings), default=1)
    eligible = {h["text"] for h in headings if h.get("level", 1) == minimum}
    for element in structure.get("element_order", []):
        if element.get("type") == "heading" and element.get("text") in eligible:
            active = element["text"]
            names.append(active)
        elif element.get("type") == "table":
            scopes[table] = active
            table += 1
    if names:
        structure["containers"] = [{"kind": "sheet", "name": n} for n in names]
        output.setdefault("metadata", {})["sheet_names"] = names
        for c in structure.get("table_cells", []):
            c["scope"] = scopes.get(c["table"], "")
    return output
