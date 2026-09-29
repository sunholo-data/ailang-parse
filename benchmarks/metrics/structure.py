"""Positional structure metric for the office suite (v0.47.0 G8).

Every other office check is a count or a bag of words, so a value in the wrong
column, a sheet name paired with another sheet's data, slides in the wrong
order and speaker notes under the wrong slide all scored 100%. That is how the
v0.47.0 XLSX and PPTX bugs shipped. This module compares the parsed document
to its golden by POSITION and says exactly what moved:

    sheet 'Leads' row 2 col 3 (C2): expected 'ExampleCo' got 'example-co.example'

Three checks, each gated through a ``*_match`` key:

1. ``sections_match`` - the document outline: every SectionBlock (kind, name,
   and the first text inside it, so unnamed slides are still distinguishable)
   and every CommentBlock (id), recursively, in document order. Catches slide
   order, sheet names and order, and notes/comments attached after the wrong
   slide or sheet.
2. ``grid_match`` - the i-th table in document order, cell by cell at
   (row, col). Headers are row 1, so on a sheet read from A1 the row/col are
   the spreadsheet's own coordinates. Catches column shifts, row shifts,
   padding, and header/body swaps.
3. ``blocks_match`` - the recursive sequence of block types (headings with
   their level, lists with ordered/unordered). Catches list-wrapping and
   blocks that split or merge.

Cell and label text is whitespace-normalised (runs collapsed, ends stripped);
nothing else is forgiven.
"""

from __future__ import annotations

import difflib
from typing import Any

from normalize import canonicalize_output

MAX_REPORTED = 20
MAX_CELLS_PER_TABLE = 6

# --- Shared helpers ---------------------------------------------------------

def _ws(s: Any) -> str:
    return " ".join(str(s).split())


def _short(s: str, n: int = 40) -> str:
    s = _ws(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _cell_text(c: Any) -> str:
    if isinstance(c, dict):
        return _ws(c.get("text", ""))
    return _ws(c if c is not None else "")


def _first_text(blocks: list) -> str:
    """First non-empty text inside a section, depth-first."""
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t in ("heading", "text") and _ws(b.get("text", "")):
            return _ws(b["text"])
        if t == "list":
            for it in b.get("items", []):
                if _ws(it):
                    return _ws(it)
        if t == "table":
            for c in b.get("headers", []) + [c for r in b.get("rows", []) for c in r]:
                if _cell_text(c):
                    return _cell_text(c)
        inner = _first_text(b.get("blocks", []))
        if inner:
            return inner
    return ""


def _blocks(doc: dict) -> list:
    return doc.get("document", {}).get("blocks", [])


class _Namer:
    """Human names for sections: sheet 'Leads', slide 3 "Kickoff", notes 'Slide 2'."""

    def __init__(self) -> None:
        self.ordinals: dict[str, int] = {}

    def name(self, b: dict) -> str:
        kind = b.get("kind", "section")
        self.ordinals[kind] = self.ordinals.get(kind, 0) + 1
        if b.get("name"):
            return f"{kind} '{b['name']}'"
        label = _first_text(b.get("blocks", []))
        n = self.ordinals[kind]
        return f"{kind} {n} \"{_short(label)}\"" if label else f"{kind} {n}"


# --- 1. Outline: sections and comments in order --------------------------

# Entries that belong to the section before them rather than standing alone:
# PPTX speaker notes follow their slide, PPTX comment blocks follow their
# slide, XLSX comment sections follow their sheet.
ATTACHED_KINDS = {"notes", "comment"}


def _plain(b: dict) -> str:
    """Ordinal-free display: sheet 'Leads', slide "Kickoff", comment id=2."""
    if b.get("type") == "comment":
        anchor = _short(b.get("anchorText", ""), 30)
        return f"comment id={b.get('id', '')}" + (f" on \"{anchor}\"" if anchor else "")
    kind = b.get("kind", "section")
    if b.get("name"):
        return f"{kind} '{_ws(b['name'])}'"
    label = _first_text(b.get("blocks", []))
    return f"{kind} \"{_short(label)}\"" if label else f"{kind} (no text)"


def _ident(b: dict) -> tuple:
    if b.get("type") == "comment":
        return ("comment", str(b.get("id", "")))
    return ("section", b.get("kind", ""), _ws(b.get("name", "")),
            _first_text(b.get("blocks", []))[:80])


def _is_attached(b: dict) -> bool:
    return b.get("type") == "comment" or b.get("kind") in ATTACHED_KINDS


def _children(blocks: list) -> list[tuple[tuple, dict]]:
    """Outline children of one container, each with an ident that is unique
    among its siblings (two slides both titled "Project preparation" get
    occurrence 0 and 1)."""
    seen: dict[tuple, int] = {}
    out = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") in ("section", "comment"):
            i = _ident(b)
            n = seen.get(i, 0)
            seen[i] = n + 1
            out.append((i + (n,), b))
    return out


def _containers(doc: dict) -> dict[tuple, tuple[str, list]]:
    """path -> (display, blocks) for the root and every section, where path is
    the chain of sibling-unique idents from the root."""
    out: dict[tuple, tuple[str, list]] = {(): ("the document root", _blocks(doc))}

    def walk(path: tuple, blocks: list) -> None:
        for ident, b in _children(blocks):
            if b.get("type") == "section":
                p = path + (ident,)
                out[p] = (_plain(b), b.get("blocks", []))
                walk(p, b.get("blocks", []))

    walk((), _blocks(doc))
    return out


def section_outline(doc: dict) -> list[tuple[tuple, str]]:
    """[(key, display)] for every section and comment, depth-first. Exact
    equality of the keys is the gate; the rest of this section only explains
    a failure."""
    out: list[tuple[tuple, str]] = []

    def walk(blocks: list, depth: int) -> None:
        for ident, b in _children(blocks):
            out.append(((depth,) + ident, "  " * depth + _plain(b)))
            if b.get("type") == "section":
                walk(b.get("blocks", []), depth + 1)

    walk(_blocks(doc), 0)
    return out


def _sequence_diff(golden: list[tuple[tuple, str]], actual: list[tuple[tuple, str]],
                   what: str) -> list[str]:
    """Explain how `actual` differs from `golden`, moves first.

    An entry that is missing at one position and present at another (same key
    AND same display) is a move, reported with the neighbour before it on each
    side. What is left of a replaced run is paired position by position
    (expected X got Y); anything else is missing or unexpected.
    """
    gk = [k for k, _ in golden]
    ak = [k for k, _ in actual]
    sm = difflib.SequenceMatcher(a=gk, b=ak, autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    removed = [i for _, i1, i2, _, _ in ops for i in range(i1, i2)]
    added = [j for _, _, _, j1, j2 in ops for j in range(j1, j2)]

    moved_g: dict[int, int] = {}
    free_added = list(added)
    for i in removed:
        j = next((j for j in free_added if golden[i] == actual[j]), None)
        if j is not None:
            free_added.remove(j)
            moved_g[i] = j
    moved_a = set(moved_g.values())

    def disp(side: list, i: int) -> str:
        return side[i][1].strip()

    def after(side: list, i: int) -> str:
        return f"after {disp(side, i - 1)}" if i > 0 else "first"

    msgs: list[str] = []
    for op, i1, i2, j1, j2 in ops:
        gs = [i for i in range(i1, i2) if i not in moved_g]
        as_ = [j for j in range(j1, j2) if j not in moved_a]
        for i in range(i1, i2):
            if i in moved_g:
                j = moved_g[i]
                msgs.append(f"{disp(golden, i)} moved: expected {what} {i + 1} ({after(golden, i)}), "
                            f"got {what} {j + 1} ({after(actual, j)})")
        for i, j in zip(gs, as_):
            msgs.append(f"{what} {i + 1}: expected {disp(golden, i)} got {disp(actual, j)}")
        for i in gs[len(as_):]:
            msgs.append(f"{what} {i + 1}: missing {disp(golden, i)} ({after(golden, i)})")
        for j in as_[len(gs):]:
            msgs.append(f"{what} {j + 1}: unexpected {disp(actual, j)} ({after(actual, j)})")
    return msgs


def _order_diffs(where: str, g_kids: list, a_kids: list) -> list[str]:
    """Order of standalone sections (slides, sheets, ...) under one container."""
    msgs = []
    kinds = []
    for _, b in g_kids + a_kids:
        k = b.get("kind") if b.get("type") == "section" else None
        if k and not _is_attached(b) and k not in kinds:
            kinds.append(k)
    for kind in kinds:
        gl = [(i, b) for i, b in g_kids if b.get("kind") == kind and b.get("type") == "section"]
        al = [(i, b) for i, b in a_kids if b.get("kind") == kind and b.get("type") == "section"]
        if [i for i, _ in gl] == [i for i, _ in al]:
            continue
        def names(lst):
            shown = ", ".join(_plain(b)[len(kind) + 1:] or "(empty)" for _, b in lst[:8])
            return f"[{shown}{', …' if len(lst) > 8 else ''}]"
        scope = "" if where == "the document root" else f" in {where}"
        msgs.append(f"{kind} order{scope}: expected {names(gl)} got {names(al)}")
        for n in range(max(len(gl), len(al))):
            gi = gl[n] if n < len(gl) else None
            ai = al[n] if n < len(al) else None
            if gi and ai and gi[0] == ai[0]:
                continue
            exp = _plain(gi[1]) if gi else "nothing"
            got = _plain(ai[1]) if ai else "nothing"
            msgs.append(f"{kind} {n + 1}{scope}: expected {exp} got {got}")
    return msgs


def _attachment_diffs(where: str, g_kids: list, a_kids: list) -> list[str]:
    """Which section each notes/comment entry follows."""
    def anchors(kids):
        out: dict[tuple, tuple[str, str]] = {}
        prev = "the start"
        for ident, b in kids:
            if _is_attached(b):
                out[ident] = (_plain(b), prev)
            else:
                prev = _plain(b)
        return out
    ga, aa = anchors(g_kids), anchors(a_kids)
    scope = "" if where == "the document root" else f" in {where}"
    msgs = []
    for ident, (disp, anchor) in ga.items():
        if ident not in aa:
            msgs.append(f"{disp}{scope}: missing (expected after {anchor})")
        elif aa[ident][1] != anchor:
            msgs.append(f"{disp}{scope}: expected after {anchor}, got after {aa[ident][1]}")
    for ident, (disp, anchor) in aa.items():
        if ident not in ga:
            msgs.append(f"{disp}{scope}: unexpected (after {anchor})")
    return msgs


def check_sections(golden_json: dict, actual_json: dict) -> dict:
    golden, actual = section_outline(golden_json), section_outline(actual_json)
    if not golden and not actual:
        return {"applicable": False}
    diffs: list[str] = []
    if [k for k, _ in golden] != [k for k, _ in actual]:
        gc, ac = _containers(golden_json), _containers(actual_json)
        for path, (where, gblocks) in gc.items():
            if path not in ac:
                continue
            gk, ak = _children(gblocks), _children(ac[path][1])
            diffs += _order_diffs(where, gk, ak)
            diffs += _attachment_diffs(where, gk, ak)
        if not diffs:
            # Nesting changed, or a kind appeared/vanished: the generic view.
            diffs = _sequence_diff(golden, actual, "outline entry")
    return {
        "applicable": True,
        "sections_match": not diffs,
        "golden_entries": len(golden),
        "actual_entries": len(actual),
        "diffs": diffs[:MAX_REPORTED],
        "diff_count": len(diffs),
    }


# --- 2. Table grids, cell by cell -----------------------------------------

def _trim(row: list) -> list:
    """A header row without trailing empty cells (padding width varies)."""
    row = list(row)
    while row and row[-1] == "":
        row.pop()
    return row


def _col_letters(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def table_grids(doc: dict) -> list[dict]:
    """Every table in document order with its grid and a human location."""
    tables: list[dict] = []
    namer = _Namer()

    def walk(blocks: list, where: str | None, kind: str | None, counter: dict) -> None:
        for b in blocks:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "section":
                walk(b.get("blocks", []), namer.name(b), b.get("kind"), {"n": 0})
            elif t == "table":
                counter["n"] += 1
                headers = [_cell_text(c) for c in b.get("headers", [])]
                rows = [[_cell_text(c) for c in r] for r in b.get("rows", []) if isinstance(r, list)]
                tables.append({
                    "where": where,
                    "kind": kind,
                    "index_in_section": counter["n"],
                    "has_header": bool(headers),
                    "grid": ([headers] if headers else []) + rows,
                })
            else:
                walk(b.get("blocks", []), where, kind, counter)

    walk(_blocks(doc), None, None, {"n": 0})
    for i, t in enumerate(tables):
        t["doc_index"] = i + 1
    return tables


def _table_label(t: dict, many_in_section: bool) -> str:
    if t["where"] is None:
        return f"table {t['doc_index']}"
    if many_in_section or t["index_in_section"] > 1:
        return f"{t['where']} table {t['index_in_section']}"
    return t["where"]


def check_grids(golden_json: dict, actual_json: dict) -> dict:
    golden, actual = table_grids(golden_json), table_grids(actual_json)
    if not golden and not actual:
        return {"applicable": False}

    per_section: dict[str | None, int] = {}
    for t in golden:
        per_section[t["where"]] = per_section.get(t["where"], 0) + 1

    diffs: list[str] = []
    if len(golden) != len(actual):
        diffs.append(f"table count: expected {len(golden)} got {len(actual)}")

    def cells(label: str, gg: list, ag: list, sheet: bool) -> tuple[int, int, list[str]]:
        """(matched, total, messages) comparing two grids at every (row, col)."""
        m = t = 0
        out: list[str] = []
        gdim = f"{len(gg)}x{max((len(r) for r in gg), default=0)}"
        adim = f"{len(ag)}x{max((len(r) for r in ag), default=0)}"
        if gdim != adim:
            out.append(f"{label}: grid expected {gdim} (rows x cols), got {adim}")
        cell_msgs: list[str] = []
        for r in range(max(len(gg), len(ag))):
            grow = gg[r] if r < len(gg) else None
            arow = ag[r] if r < len(ag) else None
            for c in range(max(len(grow or []), len(arow or []))):
                gv = grow[c] if grow is not None and c < len(grow) else None
                av = arow[c] if arow is not None and c < len(arow) else None
                t += 1
                if gv == av:
                    m += 1
                    continue
                ref = f" ({_col_letters(c + 1)}{r + 1})" if sheet else ""
                exp = "no cell" if gv is None else repr(gv)
                got = "no cell" if av is None else repr(av)
                cell_msgs.append(f"{label} row {r + 1} col {c + 1}{ref}: expected {exp} got {got}")
        # Cap per table so one broken sheet cannot hide the others.
        out += cell_msgs[:MAX_CELLS_PER_TABLE]
        if len(cell_msgs) > MAX_CELLS_PER_TABLE:
            out.append(f"{label}: … {len(cell_msgs) - MAX_CELLS_PER_TABLE} more cells differ")
        return m, t, out

    def lab(t: dict) -> str:
        return _table_label(t, per_section.get(t["where"], 0) > 1)

    matched = total = 0
    for g, a in zip(golden, actual):
        label = lab(g)
        if a["where"] != g["where"]:
            diffs.append(f"{label}: table found under {a['where'] or 'the document root'} instead")
        if g["has_header"] != a["has_header"]:
            diffs.append(f"{label}: expected {'a' if g['has_header'] else 'no'} header row, "
                         f"got {'one' if a['has_header'] else 'none'}")
        gg, ag = g["grid"], a["grid"]
        sheet = g["kind"] == "sheet"
        if gg != ag:
            # The table belongs elsewhere (a sheet name paired with another
            # sheet's data). Say so, and when it is not an exact copy compare
            # it against the table it belongs to, so a column shift inside the
            # misplaced data still shows cell by cell.
            owner = next((o for o in golden if o is not g and o["grid"] == ag), None)
            if owner is not None:
                diffs.append(f"{label}: holds the data expected under {lab(owner)}")
                total += max(sum(map(len, gg)), sum(map(len, ag)))
                continue
            if ag and gg and _trim(ag[0]) != _trim(gg[0]):
                owner = next((o for o in golden
                              if o is not g and o["grid"] and _trim(o["grid"][0]) == _trim(ag[0])), None)
                if owner is not None:
                    diffs.append(f"{label}: holds the data expected under {lab(owner)} "
                                 f"(same header row), which differs from it:")
                    m, t, msgs = cells(f"{label} (data of {lab(owner)})", owner["grid"], ag, sheet)
                    total += max(t, sum(map(len, gg)))
                    diffs += msgs
                    continue
        m, t, msgs = cells(label, gg, ag, sheet)
        matched += m
        total += t
        diffs += msgs

    cell_accuracy = matched / total if total else 1.0
    return {
        "applicable": True,
        "grid_match": not diffs,
        "golden_tables": len(golden),
        "actual_tables": len(actual),
        "cell_accuracy": round(cell_accuracy, 4),
        "diffs": diffs[:MAX_REPORTED],
        "diff_count": len(diffs),
    }


# --- 3. Block type sequence -------------------------------------------------

def _block_entry(b: dict) -> tuple[tuple, str]:
    t = b.get("type", "?")
    if t == "heading":
        lab = f"heading/{b.get('level', 1)}"
    elif t == "list":
        lab = "list/ordered" if b.get("ordered") else "list/bullet"
    elif t == "section":
        lab = f"section/{b.get('kind', '')}"
    else:
        lab = t
    key: tuple = (lab,)
    if t == "section" or t == "comment":
        return key, _plain(b)
    if t == "list":
        items = b.get("items", [])
        disp = f"{lab} ({len(items)} items, first \"{_short(items[0] if items else '', 30)}\")"
    elif t == "table":
        disp = lab
    else:
        snippet = _short(b.get("text", "") or b.get("description", ""), 30)
        disp = f"{lab} \"{snippet}\"" if snippet else lab
    if t == "image":
        # src is canonicalised first, so a temp path compares as the
        # placeholder whatever the machine or naming scheme.
        key += (b.get("mime", ""), b.get("src", ""), b.get("dataLength"))
        disp += f" [{b.get('mime', '')} src={_short(str(b.get('src', '')), 40)!r}]"
    return key, disp


def block_sequence(doc: dict) -> list[tuple[tuple, str]]:
    """Recursive block type sequence, the gated value."""
    out: list[tuple[tuple, str]] = []

    def walk(blocks: list, depth: int) -> None:
        for b in blocks:
            if isinstance(b, dict):
                k, d = _block_entry(b)
                out.append(((depth,) + k, d))
                walk(b.get("blocks", []), depth + 1)

    walk(_blocks(doc), 0)
    return out


def check_blocks(golden_json: dict, actual_json: dict) -> dict:
    golden, actual = block_sequence(golden_json), block_sequence(actual_json)
    diffs: list[str] = []
    if [k for k, _ in golden] != [k for k, _ in actual]:
        # Explain per container (slide, sheet, ...), matched by identity, so a
        # reordered deck reports as a section problem (check_sections) and not
        # as every block in it having moved.
        gc, ac = _containers(golden_json), _containers(actual_json)
        for path, (where, gblocks) in gc.items():
            if path not in ac:
                continue
            # Sections and comments are check_sections' job; here only the
            # content blocks of each container.
            def content(bl):
                return [_block_entry(b) for b in bl
                        if isinstance(b, dict) and b.get("type") not in ("section", "comment")]
            ge, ae = content(gblocks), content(ac[path][1])
            if [k for k, _ in ge] != [k for k, _ in ae]:
                diffs += [f"in {where}: {m}" for m in _sequence_diff(ge, ae, "block")]
        missing = [gc[p][0] for p in gc if p not in ac]
        if missing:
            diffs.append(f"{len(missing)} section(s) not found to compare blocks in, "
                         f"e.g. {missing[0]} (see sections)")
        if not diffs:
            diffs = ["content blocks match inside every section; only section or "
                     "comment placement differs (see sections)"]
    return {
        "applicable": True,
        "blocks_match": not diffs,
        "golden_blocks": len(golden),
        "actual_blocks": len(actual),
        "diffs": diffs[:MAX_REPORTED],
        "diff_count": len(diffs),
    }


def check_structure(golden_json: dict, actual_json: dict) -> dict[str, dict]:
    """All three positional checks, on canonicalised copies of both sides."""
    g, a = canonicalize_output(golden_json), canonicalize_output(actual_json)
    return {
        "sections": check_sections(g, a),
        "table_grids": check_grids(g, a),
        "block_sequence": check_blocks(g, a),
    }
