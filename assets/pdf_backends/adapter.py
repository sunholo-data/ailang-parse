"""External PDF backend adapter for AILANG Parse.

Invoked from AILANG via std/process.exec. Reads (backend, pdf_path) from argv,
prints a JSON object on stdout matching the shape AILANG's pdf_backend_external
module expects:

    {
      "metadata": {"title": str, "author": str, "created": str,
                   "modified": str, "pageCount": int},
      "blocks": [
        {"kind": "heading", "text": str, "level": int} |
        {"kind": "text",    "text": str, "style": str, "level": int} |
        {"kind": "table",   "rows": [[str]], "headers": [str], "caption": str} |
        {"kind": "list",    "items": [str], "ordered": bool, "levels": [int]} |
        {"kind": "image",   "data": str (base64), "mime": str, "width": int,
                            "height": int, "description": str}
      ]
    }

Every block may also carry:
    "page":   int     1-based page the block came from
    "region": str     "body" (default) | "header" | "footer" -- page furniture
                      the backend located; AILANG wraps it in a header/footer
                      section and pdf_furniture merges the occurrences
    "runs":   [{"text": str, "bold": bool, "italic": bool, "href": str}]
                      on text/heading only; inline formatting the backend saw
Omitted fields keep their old meaning, so a backend that emits none of them
(pdftotext) produces byte-identical output to before they existed.

All errors print "ERR: <message>" to stderr and exit 1 (AILANG checks
Result[ProcessOutput, ProcessError] for non-zero exit).
"""

from __future__ import annotations

import contextlib
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _empty_meta() -> dict:
    return {"title": "", "author": "", "created": "", "modified": "", "pageCount": 0}


def _heading(text: str, level: int) -> dict:
    return {"kind": "heading", "text": text, "level": max(1, min(6, level))}


def _text(text: str, style: str = "Normal", level: int = 0) -> dict:
    return {"kind": "text", "text": text, "style": style, "level": level}


def _table(rows: list[list[str]], headers: list[str], caption: str = "") -> dict:
    return {"kind": "table", "rows": rows, "headers": headers, "caption": caption}


def _list(items: list[str], ordered: bool = False, levels: list[int] | None = None) -> dict:
    block = {"kind": "list", "items": items, "ordered": ordered}
    if levels and any(levels):
        block["levels"] = levels
    return block


def _image(data_b64: str, mime: str, width: int = 0, height: int = 0, description: str = "") -> dict:
    return {"kind": "image", "data": data_b64, "mime": mime,
            "width": width, "height": height, "description": description}


def _placed(block: dict, page: int = 0, region: str = "body") -> dict:
    """Tag a block with where it sat on the page. Body blocks on an unknown
    page stay untagged, so their JSON is unchanged."""
    if page:
        block["page"] = page
    if region != "body":
        block["region"] = region
    return block


def _blocks_from_markdown(md: str) -> list[dict]:
    """Split markdown into heading/text blocks. Tables become joined text rows."""
    blocks: list[dict] = []
    para: list[str] = []
    in_table = False
    table_rows: list[list[str]] = []

    def flush_para():
        if para:
            text = " ".join(p.strip() for p in para if p.strip()).strip()
            if text:
                blocks.append(_text(text))
            para.clear()

    def flush_table():
        nonlocal table_rows, in_table
        if table_rows:
            headers = table_rows[0] if table_rows else []
            rest = [r for r in table_rows[1:] if not all(re.fullmatch(r"-+\s*:?", c) for c in r if c)]
            blocks.append(_table(rest or table_rows[1:], headers))
        table_rows = []
        in_table = False

    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and "|" in stripped[1:-1]:
            flush_para()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            table_rows.append(cells)
            in_table = True
            continue
        if in_table:
            flush_table()
        if not stripped:
            flush_para()
            continue
        if stripped.startswith("#"):
            flush_para()
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped.lstrip("# ").strip()
            if text:
                blocks.append(_heading(text, level))
            continue
        para.append(stripped)

    if in_table:
        flush_table()
    flush_para()
    return blocks


def _pdf_page_count(pdf: Path) -> int:
    """Authoritative page count via poppler's pdfinfo (same toolchain as
    pdftotext). Returns 0 if pdfinfo is unavailable or the field is missing —
    callers treat 0 as "unknown", never as an error on its own."""
    try:
        out = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, check=False
        )
        for line in out.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    return 0


def _blocks_from_plaintext(text: str) -> list[dict]:
    """Convert pdftotext -layout output into text blocks. Paragraphs are
    blank-line separated; layout (column alignment, indentation) is preserved
    verbatim inside each block so tables and signature grids stay faithful.
    No structural inference — pdftotext is the deterministic plain extractor."""
    blocks: list[dict] = []
    para: list[str] = []

    def flush():
        if para:
            chunk = "\n".join(para).rstrip()
            if chunk.strip():
                blocks.append(_text(chunk))
            para.clear()

    # Form feeds delimit pages; treat them as paragraph breaks.
    for raw in text.replace("\f", "\n").splitlines():
        if not raw.strip():
            flush()
            continue
        para.append(raw.rstrip())
    flush()
    return blocks


def run_pdftotext(pdf: Path) -> dict:
    """Deterministic text extraction via poppler's pdftotext -layout.
    Reliable for text-based PDFs (incl. Mindworking-generated DK real-estate
    documents). Returns empty blocks for scanned/image-only PDFs with no text
    layer — the adapter's empty guard turns that into a loud failure."""
    proc = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"pdftotext exited {proc.returncode}: {proc.stderr.strip()}"
        )
    blocks = _blocks_from_plaintext(proc.stdout)
    meta = _empty_meta()
    meta["pageCount"] = _pdf_page_count(pdf)
    return {"metadata": meta, "blocks": blocks}


def _rank_levels(sizes: list[float], max_levels: int = 3, step: float = 0.75) -> dict[float, int]:
    """Map heading sizes (font size, or a heading box's height) to levels 1..n.

    Sizes are clustered from the largest down: a size starts a new level when
    it drops below `step` x the largest size of the level above. That keeps
    the jitter inside one level together (a 14pt and an 18pt box are both H2
    when H1 is 27pt) while separating real tiers. Levels past `max_levels`
    collapse into the last one.
    """
    levels: dict[float, int] = {}
    level, top = 0, None
    for size in sorted(set(sizes), reverse=True):
        if top is None or size < top * step:
            level, top = min(level + 1, max_levels), size
        levels[size] = level
    return levels


def _docling_label(item: Any) -> str:
    label = getattr(item, "label", "")
    return getattr(label, "value", label) or ""


def _docling_page(item: Any) -> int:
    prov = getattr(item, "prov", None) or []
    return int(getattr(prov[0], "page_no", 0) or 0) if prov else 0


def _docling_height(item: Any) -> float:
    prov = getattr(item, "prov", None) or []
    bbox = getattr(prov[0], "bbox", None) if prov else None
    return round(float(getattr(bbox, "height", 0.0) or 0.0), 1) if bbox is not None else 0.0


def _docling_table(item: Any) -> dict | None:
    grid = getattr(getattr(item, "data", None), "grid", None) or []
    rows = [[(getattr(c, "text", "") or "").strip() for c in row] for row in grid]
    rows = [r for r in rows if any(r)]
    if not rows:
        return None
    return _table(rows[1:], rows[0])


def _docling_picture(item: Any, document: Any, budget: list) -> dict | None:
    """A docling picture as an image block, by the same rules as poppler's
    images: logos in the header/footer band, tiny decorations and full-page
    backgrounds are left out. Needs the pipeline's generate_picture_images."""
    import base64
    import io
    prov = getattr(item, "prov", None) or []
    if document is None or not prov or not hasattr(item, "get_image"):
        return None
    try:
        size = document.pages[prov[0].page_no].size
        box = prov[0].bbox.to_top_left_origin(size.height)
        w, h = box.r - box.l, box.b - box.t
        cy = (box.t + box.b) / 2
        in_band = (cy <= size.height * (_PP_MARGIN + 0.03) or cy >= size.height * (1 - _PP_MARGIN - 0.03)) \
            and h <= size.height * 0.15
        if in_band or w < _PP_IMAGE_MIN_PT or h < _PP_IMAGE_MIN_PT or w * h > 0.8 * size.width * size.height:
            return None
        img = item.get_image(document)
        if img is None:
            return None
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
    except Exception:
        return None
    if len(data) > budget[0]:
        return None
    budget[0] -= len(data)
    return _image(base64.b64encode(data).decode("ascii"), "image/png",
                  round(w * 96 / 72), round(h * 96 / 72))


def _docling_blocks(items: list[tuple[Any, int]], document: Any = None) -> list[dict]:
    """Blocks from DoclingDocument.iterate_items() output: (item, depth) pairs.

    Walking the items rather than export_to_markdown() keeps what the
    Markdown round trip threw away: list items stay lists (the old
    _blocks_from_markdown joined them into one paragraph), page_header /
    page_footer items arrive tagged as furniture, and pictures are skipped
    instead of leaking "<!-- image -->" into the document as text.

    Heading levels: docling reports section_header level 1 for every heading
    of a typical PDF (measured on ailang-proposal.pdf: 17 of 17). When its
    levels are all the same, rank the headings' box heights instead.
    """
    headers = [it for it, _ in items if _docling_label(it) == "section_header"]
    doc_levels = {getattr(h, "level", 1) or 1 for h in headers}
    by_height = _rank_levels([_docling_height(h) for h in headers if _docling_height(h) > 0]) \
        if len(doc_levels) <= 1 else {}

    blocks: list[dict] = []
    budget = [_PP_IMAGE_BUDGET]
    pending: list[tuple[str, int, bool, int]] = []  # list items: text, depth, ordered, page

    def flush_list():
        if pending:
            base = min(d for _, d, _, _ in pending)
            blocks.append(_placed(_list([t for t, _, _, _ in pending], pending[0][2],
                                        [d - base for _, d, _, _ in pending]), pending[0][3]))
            pending.clear()

    for item, depth in items:
        label = _docling_label(item)
        text = (getattr(item, "text", "") or "").strip()
        page = _docling_page(item)
        if label == "list_item":
            if text:
                pending.append((text, depth, bool(getattr(item, "enumerated", False)), page))
            continue
        flush_list()
        if label in ("picture", "chart"):
            picture = _docling_picture(item, document, budget)
            if picture:
                blocks.append(_placed(picture, page))
            continue
        if label == "table":
            table = _docling_table(item)
            if table:
                blocks.append(_placed(table, page))
            continue
        if not text:
            continue
        if label == "title":
            blocks.append(_placed(_heading(text, 1), page))
        elif label == "section_header":
            level = by_height.get(_docling_height(item)) if by_height else None
            level = level or (getattr(item, "level", 1) or 1) + (1 if any(_docling_label(i) == "title" for i, _ in items) else 0)
            blocks.append(_placed(_heading(text, level), page))
        elif label in ("page_header", "page_footer"):
            blocks.append(_placed(_text(text), page, "header" if label == "page_header" else "footer"))
        else:
            blocks.append(_placed(_text(text), page))
    flush_list()
    return blocks


def _docling_converter():
    """Docling with the pypdfium text backend when available. The default
    docling-parse backend reads glyphs that a PDF draws twice as two letters
    ("matteers", "Thee", "Confidrm" on ailang-proposal.pdf, a LibreOffice
    export); pypdfium reads the same file cleanly and ~4x faster (2.7s vs
    ~10s measured), with the same headings, tables and lists."""
    from docling.document_converter import DocumentConverter
    try:
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        # Pictures rendered at 2x so they can be carried into the output.
        options = PdfPipelineOptions(generate_picture_images=True, images_scale=2.0)
        return DocumentConverter(format_options={
            InputFormat.PDF: PdfFormatOption(backend=PyPdfiumDocumentBackend, pipeline_options=options)})
    except ImportError:
        return DocumentConverter()


def _docling_items(document: Any, traverse_pictures: bool = False) -> list[tuple[Any, int]]:
    try:
        from docling_core.types.doc.document import ContentLayer
        layers = {ContentLayer.BODY, ContentLayer.FURNITURE}
    except ImportError:
        layers = None
    kwargs: dict[str, Any] = {}
    if layers is not None:
        kwargs["included_content_layers"] = layers
    if traverse_pictures:
        kwargs["traverse_pictures"] = True
    try:
        return list(document.iterate_items(**kwargs))
    except TypeError:
        return list(document.iterate_items())


def run_docling(pdf: Path) -> dict:
    result = _docling_converter().convert(str(pdf))
    blocks = _docling_blocks(_docling_items(result.document), result.document)
    # A scanned page is laid out as ONE picture, and docling files its OCR text
    # as that picture's children, which the default walk skips. Only when that
    # leaves nothing substantive, walk again descending into pictures, so
    # text-layer PDFs with figures are unchanged.
    if not _has_substance(blocks):
        blocks = _docling_blocks(_docling_items(result.document, traverse_pictures=True), result.document)

    meta = _empty_meta()
    try:
        doc_dict = result.document.export_to_dict()
        if isinstance(doc_dict, dict):
            for k in ("title", "author"):
                v = doc_dict.get(k) or doc_dict.get("meta", {}).get(k, "")
                if isinstance(v, str):
                    meta[k] = v
            pages = doc_dict.get("pages") or []
            if isinstance(pages, (list, dict)):
                meta["pageCount"] = len(pages)
    except Exception:
        pass
    return {"metadata": meta, "blocks": blocks}


def _lp_items(page: Any) -> list:
    """Text items of a liteparse page. liteparse 2.x names them text_items /
    font_size; older releases textItems / fontSize. Reading only the camelCase
    names returned nothing on 2.6, which is why liteparse found 0 headings."""
    return list(getattr(page, "text_items", None) or getattr(page, "textItems", None) or [])


def _lp_size(item: Any) -> float | None:
    size = getattr(item, "font_size", None)
    if size is None:
        size = getattr(item, "fontSize", None)
    return float(size) if isinstance(size, (int, float)) else None


def _liteparse_heading_levels(textitems: list, lines: set[str] | None = None) -> dict[str, int]:
    """Heading text -> level. Any font size strictly larger than the modal
    (body-text) size marks a heading, body size being whichever size covers
    the most characters; larger sizes rank as higher levels.

    Only text that stands as a whole line in `lines` can become a heading,
    so only those sizes are ranked: the 24pt logo word "AILANG" shares its
    line with "PROPOSAL", and ranking it pushed every real H2 down to H3."""
    from collections import Counter

    weights: Counter = Counter()
    for ti in textitems:
        size = _lp_size(ti)
        if size is not None:
            weights[size] += len(getattr(ti, "text", "") or "")
    if not weights:
        return {}
    body_size = weights.most_common(1)[0][0]
    candidates: dict[str, float] = {}
    for ti in textitems:
        size = _lp_size(ti)
        text = (getattr(ti, "text", "") or "").strip()
        if size is not None and size > body_size and text and len(text) < 200 \
                and (lines is None or text in lines):
            candidates[text] = max(size, candidates.get(text, 0.0))
    ranks = _rank_levels(list(candidates.values()), step=0.9)
    return {t: ranks[s] for t, s in candidates.items()}


_BULLET_RE = re.compile(r"^(?:[•▪◦‣∙·\-–]|\d{1,3}[.)])\s+")


def run_liteparse(pdf: Path) -> dict:
    from liteparse import LiteParse

    # ocr_enabled is a constructor option (liteparse 2.14.x); parse() takes only
    # the file and raises TypeError on the old keyword.
    result = LiteParse(ocr_enabled=False).parse(str(pdf))
    all_textitems = []
    for page in result.pages:
        all_textitems.extend(_lp_items(page))
    page_lines = {ln.strip() for page in result.pages for ln in page.text.splitlines() if ln.strip()}
    heading_levels = _liteparse_heading_levels(all_textitems, page_lines)

    blocks: list[dict] = []
    para: list[str] = []
    items: list[str] = []
    ordered = [False]

    def flush():
        if para:
            text = " ".join(p.strip() for p in para if p.strip()).strip()
            if text:
                blocks.append(_text(text))
            para.clear()
        if items:
            blocks.append(_list(list(items), ordered[0]))
            items.clear()

    for page in result.pages:
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                flush()
                continue
            if line in heading_levels:
                flush()
                blocks.append(_heading(line, heading_levels[line]))
                continue
            bullet = _BULLET_RE.match(line)
            if bullet:
                if para:
                    flush()
                if not items:
                    ordered[0] = bullet.group(0).strip()[0].isdigit()
                items.append(line[bullet.end():].strip())
            elif items and raw_line.startswith((" ", "\t")):
                items[-1] = f"{items[-1]} {line}"
            else:
                if items:
                    flush()
                para.append(line)
        flush()

    meta = _empty_meta()
    meta["pageCount"] = getattr(result, "num_pages", 0) or len(result.pages)
    return {"metadata": meta, "blocks": blocks}


def run_words(pdf: Path) -> dict:
    """Word-level bounding boxes via poppler's `pdftotext -bbox`.

    Used to resolve what a PDF highlight actually covers: annotations carry
    /QuadPoints in PDF user space, and without positions for the text there is
    no way to say which words fall inside them.

    Coordinates are returned in PDF user space (origin bottom-left) so the
    AILANG side can compare them to /QuadPoints directly. pdftotext reports a
    top-left origin, so y is flipped here against each page's own height —
    doing it once, next to the tool that defines the convention, rather than
    leaving a flip for every caller to get wrong.
    """
    proc = subprocess.run(
        ["pdftotext", "-bbox", str(pdf), "-"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pdftotext -bbox exited {proc.returncode}: {proc.stderr.strip()}")

    words: list[dict] = []
    page_no = 0
    page_h = 0.0
    page_re = re.compile(r'<page width="([\d.]+)" height="([\d.]+)"')
    word_re = re.compile(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>'
    )
    for line in proc.stdout.splitlines():
        pm = page_re.search(line)
        if pm:
            page_no += 1
            page_h = float(pm.group(2))
            continue
        wm = word_re.search(line)
        if wm:
            x0, y0, x1, y1, text = wm.groups()
            words.append({
                "page": page_no,
                "x0": float(x0),
                "x1": float(x1),
                # flip to PDF user space (origin bottom-left)
                "y0": page_h - float(y1),
                "y1": page_h - float(y0),
                "text": html.unescape(text),
            })

    return {"metadata": _empty_meta(), "blocks": [], "words": words}


# ---------------------------------------------------------------------------
# poppler: structure from the poppler output we already ship
# ---------------------------------------------------------------------------
#
# Same binaries as the pdftotext backend (poppler-utils), read for structure:
#
#   pdftotext -bbox-layout   text + geometry: every line and word with its box,
#                            in PDF points. Its text is the reliable one: it
#                            drops glyphs a PDF draws twice at one position.
#   pdftohtml -xml           style: font size, <b>/<i>, <a href> per text run.
#                            Its text is NOT used: it keeps those duplicate
#                            glyphs ("diffeerent", "Thee" on ailang-proposal).
#
# Words take their style from the pdftohtml run whose box contains the word's
# centre. Lines are then grouped into visual rows and each row classified as
# page furniture, a list item, part of a table, a heading, or paragraph text.
# The core (_poppler_blocks) is pure over the two XML strings so it can be
# tested without poppler.

import xml.etree.ElementTree as _ET

_PP_MARGIN = 0.09          # top/bottom share of the page where furniture sits
_PP_HEADING_RATIO = 1.15   # size over body size that makes a heading
_PP_BOLD_HEADING_RATIO = 1.05  # ... when the whole row is bold
_PP_IMAGE_MIN_PT = 24.0    # smaller images are rules, bullets and decorations
_PP_IMAGE_BUDGET = 6_000_000  # raw image bytes per document: base64 inflates by 4/3
                              # and the hosted API caps adapter output at 10 MB
_PP_BULLETS = set("•▪◦‣∙·●○■□–-*")
_PP_NUMBERED = re.compile(r"^\(?(\d{1,3}|[a-zA-Z]|[ivxIVX]{1,4})[.)]$")


def _pp_strip_ns(xml_text: str) -> str:
    return re.sub(r'\sxmlns="[^"]+"', "", xml_text, count=1)


def _pp_key(text: str) -> str:
    """Same normalisation as pdf_furniture.ail's pdfFurnitureKey: lower case,
    whitespace collapsed, digit runs (and spaces between digits) -> '#'."""
    t = " ".join(text.lower().split())
    t = re.sub(r"\d[\d ]*\d|\d", "#", t)
    return t


def _pp_parse_bbox(xml_text: str) -> list[dict]:
    """Pages from `pdftotext -bbox-layout`: [{w, h, lines: [line]}], each line
    {x0, y0, x1, y1, words: [{x0, y0, x1, y1, text}]} in points."""
    if "<doc" not in xml_text:
        return []
    body = xml_text[xml_text.index("<doc"):xml_text.rindex("</doc>") + 6]
    root = _ET.fromstring(_pp_strip_ns(body))
    pages = []
    for page in root.iter("page"):
        lines = []
        for line in page.iter("line"):
            words = [{"x0": float(w.get("xMin")), "y0": float(w.get("yMin")),
                      "x1": float(w.get("xMax")), "y1": float(w.get("yMax")),
                      "text": w.text or ""} for w in line.iter("word") if (w.text or "").strip()]
            if words:
                lines.append({"x0": min(w["x0"] for w in words), "y0": min(w["y0"] for w in words),
                              "x1": max(w["x1"] for w in words), "y1": max(w["y1"] for w in words),
                              "words": words})
        pages.append({"w": float(page.get("width")), "h": float(page.get("height")), "lines": lines})
    return pages


def _pp_parse_html(xml_text: str) -> list[dict]:
    """Pages from `pdftohtml -xml`: [{h, runs: [{x0, y0, x1, y1, size, bold,
    italic, href}]}]. Coordinates are pdftohtml's pixels; the caller scales."""
    if not xml_text or "<pdf2xml" not in xml_text:
        return []
    root = _ET.fromstring(xml_text[xml_text.index("<pdf2xml"):])
    fonts: dict[str, dict] = {}
    pages = []
    for page in root.iter("page"):
        for spec in page.iter("fontspec"):
            fam = (spec.get("family") or "").lower()
            fonts[spec.get("id")] = {"size": float(spec.get("size") or 0),
                                     "bold": "bold" in fam or "black" in fam or "heavy" in fam,
                                     "italic": "italic" in fam or "oblique" in fam}
        runs = []
        for t in page.iter("text"):
            font = fonts.get(t.get("font"), {"size": 0.0, "bold": False, "italic": False})
            full = "".join(t.itertext()).strip()
            bold_text = "".join("".join(b.itertext()) for b in t.iter("b")).strip()
            ital_text = "".join("".join(i.itertext()) for i in t.iter("i")).strip()
            href = next((a.get("href") for a in t.iter("a") if a.get("href")), "")
            x0, y0 = float(t.get("left")), float(t.get("top"))
            runs.append({"x0": x0, "y0": y0, "x1": x0 + float(t.get("width")),
                         "y1": y0 + float(t.get("height")), "size": font["size"],
                         "bold": font["bold"] or (bool(full) and bold_text == full),
                         "italic": font["italic"] or (bool(full) and ital_text == full),
                         "href": href if href.startswith(("http://", "https://", "mailto:")) else ""})
        images = [{"x0": float(im.get("left")), "y0": float(im.get("top")),
                   "x1": float(im.get("left")) + float(im.get("width")),
                   "y1": float(im.get("top")) + float(im.get("height")),
                   "src": im.get("src") or ""} for im in page.iter("image")]
        pages.append({"h": float(page.get("height") or 0), "runs": runs, "images": images})
    return pages


def _pp_body_images(page: dict, html_page: dict | None) -> list[dict]:
    """The page's content images in points, top to bottom. Left out: images
    in the header/footer band (logos: a template brings its own, and Word
    header parts cannot take our images), tiny ones (rules, bullets,
    decorations) and full-page backgrounds."""
    if not html_page or not page["h"]:
        return []
    scale = html_page["h"] / page["h"]
    out = []
    for im in html_page.get("images", []):
        x0, y0, x1, y1 = (im[k] / scale for k in ("x0", "y0", "x1", "y1"))
        w, h = x1 - x0, y1 - y0
        cy = (y0 + y1) / 2
        in_band = (cy <= page["h"] * (_PP_MARGIN + 0.03) or cy >= page["h"] * (1 - _PP_MARGIN - 0.03)) \
            and h <= page["h"] * 0.15
        if in_band or w < _PP_IMAGE_MIN_PT or h < _PP_IMAGE_MIN_PT or w * h > 0.8 * page["w"] * page["h"]:
            continue
        out.append({"y0": y0, "w": w, "h": h, "src": im["src"]})
    return sorted(out, key=lambda i: i["y0"])


def _pp_image_block(im: dict, load, budget: list) -> dict | None:
    """An image block sized as it appeared on the page (CSS px at 96 dpi,
    which is what the generators read), or None when unreadable or over the
    document's byte budget."""
    import base64
    try:
        data = load(im["src"])
    except Exception:
        return None
    if not data or len(data) > budget[0]:
        return None
    budget[0] -= len(data)
    ext = im["src"].rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(ext, "image/png")
    return _image(base64.b64encode(data).decode("ascii"), mime,
                  round(im["w"] * 96 / 72), round(im["h"] * 96 / 72))


def _pp_style_words(page: dict, html_page: dict | None) -> None:
    """Give every word size/bold/italic/href from the pdftohtml run holding
    its centre. Without pdftohtml, size falls back to the word box height."""
    scale = (html_page["h"] / page["h"]) if html_page and page["h"] else 0.0
    runs = []
    if scale > 0:
        for r in html_page["runs"]:
            runs.append({**r, "x0": r["x0"] / scale, "y0": r["y0"] / scale,
                         "x1": r["x1"] / scale, "y1": r["y1"] / scale, "size": r["size"] / scale})
    for line in page["lines"]:
        for w in line["words"]:
            cx, cy = (w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2
            hit = next((r for r in runs if r["x0"] - 1 <= cx <= r["x1"] + 1 and r["y0"] - 1 <= cy <= r["y1"] + 1), None)
            if hit:
                w.update(size=round(hit["size"], 1), bold=hit["bold"], italic=hit["italic"], href=hit["href"])
            else:
                w.update(size=round((w["y1"] - w["y0"]) * 0.85, 1), bold=False, italic=False, href="")


# Symbol-font glyphs decks use for bullets and arrows land in Unicode's
# private-use area; show them as the characters they draw.
_PP_PUA = str.maketrans({"\uf0e0": "→", "\uf0e8": "→", "\uf0b7": "•", "\uf0a7": "▪", "\uf0d8": "➢", "\uf0fc": "✓"})


def _pp_line_text(line: dict) -> str:
    return " ".join(w["text"] for w in line["words"]).translate(_PP_PUA)


def _pp_line_size(line: dict) -> float:
    weights: dict[float, int] = {}
    for w in line["words"]:
        weights[w["size"]] = weights.get(w["size"], 0) + len(w["text"])
    return max(weights.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _pp_line_bold(line: dict) -> bool:
    chars = sum(len(w["text"]) for w in line["words"])
    return chars > 0 and sum(len(w["text"]) for w in line["words"] if w["bold"]) >= 0.8 * chars


def _pp_runs(words: list[dict]) -> list[dict]:
    """Inline runs for a paragraph, or [] when it carries no formatting
    worth keeping (all plain, or all bold the way a heading is)."""
    runs: list[dict] = []
    for w in words:
        style = (w["bold"], w["italic"], w["href"])
        if runs and (runs[-1]["bold"], runs[-1]["italic"], runs[-1]["href"]) == style:
            runs[-1]["text"] += " " + w["text"]
        else:
            if runs:
                # The space between differently styled words belongs to
                # neither: inside a bold run it renders as "**bold **then".
                if not (runs[-1]["bold"] or runs[-1]["italic"] or runs[-1]["href"]):
                    runs[-1]["text"] += " "
                else:
                    runs.append({"text": " ", "bold": False, "italic": False, "href": ""})
            runs.append({"text": w["text"], "bold": w["bold"], "italic": w["italic"], "href": w["href"]})
    if len(runs) == 1 and not runs[0]["href"]:
        return []
    return [{k: v for k, v in r.items() if v or k == "text"} for r in runs]


def _pp_rows(lines: list[dict]) -> list[list[dict]]:
    """Group lines into visual rows (vertical overlap), left to right."""
    rows: list[list[dict]] = []
    for line in sorted(lines, key=lambda l: (l["y0"], l["x0"])):
        cy, h = (line["y0"] + line["y1"]) / 2, line["y1"] - line["y0"]
        if rows:
            last = rows[-1]
            ly0, ly1 = min(l["y0"] for l in last), max(l["y1"] for l in last)
            if abs(cy - (ly0 + ly1) / 2) <= 0.5 * min(h, ly1 - ly0):
                last.append(line)
                continue
        rows.append([line])
    return [sorted(r, key=lambda l: l["x0"]) for r in rows]


def _pp_bullet(row: list[dict]) -> tuple[bool, bool, list[dict]] | None:
    """(is_item, ordered, content_lines) when the row is a list item: a lone
    bullet or number glyph left of the text, or text that starts with one."""
    first = row[0]
    marker = _pp_line_text(first)
    if len(row) >= 2 and (marker in _PP_BULLETS or _PP_NUMBERED.match(marker)):
        return True, bool(_PP_NUMBERED.match(marker)), row[1:]
    words = first["words"]
    if len(words) >= 2 and (words[0]["text"] in _PP_BULLETS or _PP_NUMBERED.match(words[0]["text"])):
        rest = {**first, "words": words[1:], "x0": words[1]["x0"]}
        return True, bool(_PP_NUMBERED.match(words[0]["text"])), [rest] + row[1:]
    return None


def _pp_table(rows: list[list[dict]], page_w: float) -> tuple[str, Any] | None:
    """Read consecutive multi-segment rows. Returns ("table", block) when the
    segments fall into shared columns (columns from the rows with the most
    segments; each segment lands in a distinct column), ("columns", [text per
    column]) when they are prose set in columns, else None."""
    counts = [len(r) for r in rows]
    k = max(counts)
    if k < 2 or len(rows) < 2:
        return None
    full = [r for r in rows if len(r) == k]
    cols = [(min(r[j]["x0"] for r in full), max(r[j]["x1"] for r in full)) for j in range(k)]
    if any(cols[j][1] > cols[j + 1][0] + 2 for j in range(k - 1)):
        return None
    grid = []
    for r in rows:
        cells = [""] * k
        for seg in r:
            mid = (seg["x0"] + seg["x1"]) / 2
            j = min(range(k), key=lambda c: 0 if cols[c][0] - 2 <= mid <= cols[c][1] + 2
                    else min(abs(mid - cols[c][0]), abs(mid - cols[c][1])))
            if cells[j]:
                return None
            cells[j] = _pp_line_text(seg)
        grid.append(cells)
    # Prose set in columns is not a table: every column is wide and the cells
    # are sentences. A real table has at least one narrow (label) column.
    lengths = [len(c) for row in grid for c in row if c]
    all_wide = all(c1 - c0 > 0.28 * page_w for c0, c1 in cols)
    if lengths and sum(lengths) / len(lengths) > 30 and all_wide:
        return "columns", [" ".join(row[j] for row in grid if row[j]) for j in range(k)]
    if lengths and sum(lengths) / len(lengths) > 60:
        return None
    return "table", _table(grid[1:], grid[0])


def _pp_line_gap(pages: list[dict]) -> float:
    """The document's gap between lines of one paragraph: the low end of the
    gaps between consecutive single-line rows of the same size. Paragraph
    spacing is larger (measured 2.5pt vs 10.5pt on ailang-proposal, 5.9pt vs
    9.6pt on multipage_spec), so a gap well above this starts a paragraph."""
    gaps = []
    for page in pages:
        rows = _pp_rows(page["lines"])
        for a, b in zip(rows, rows[1:]):
            if len(a) == 1 and len(b) == 1 and abs(_pp_line_size(a[0]) - _pp_line_size(b[0])) <= 0.6:
                gap = b[0]["y0"] - a[0]["y1"]
                if -2 <= gap <= 1.5 * (a[0]["y1"] - a[0]["y0"]):
                    gaps.append(gap)
    if not gaps:
        return 3.0
    gaps.sort()
    return gaps[len(gaps) // 5]


def _pp_fold_into_cell(run: list[list[dict]], line: dict) -> bool:
    """Fold a wrapped cell line into the table's last row when it starts at
    one of the run's column edges and fits inside that column. Returns False
    (leave it alone) otherwise. Before this, a wrapped cell ended the table
    and split it in two; the fit test keeps a following heading or paragraph
    (which starts at the page margin, left of the table) out of the cells."""
    edges = sorted({round(l["x0"]) for r in run for l in r})
    if line["x0"] < edges[0] - 1:
        return False
    col = next((e for e in edges if abs(e - line["x0"]) <= 3), None)
    if col is None:
        return False
    nxt = next((e for e in edges if e > col + 3), None)
    if nxt is not None and line["x1"] > nxt + 2:
        return False
    last = run[-1]
    for i, seg in enumerate(last):
        if abs(seg["x0"] - line["x0"]) <= 3:
            last[i] = {**seg, "words": seg["words"] + line["words"],
                       "x1": max(seg["x1"], line["x1"]), "y1": max(seg["y1"], line["y1"])}
            return True
    last.append(line)
    last.sort(key=lambda l: l["x0"])
    return True


def _pp_continues_table(run: list[list[dict]], row: list[dict], gap: float, height: float) -> bool:
    """Whether `row` belongs to the table being collected. A new table starts
    when the column layout changes (a row whose segment count differs and
    whose left edges match no column seen so far: three tables stacked with
    4, 2 and 2 columns read as one 4-column table before this) or when the
    gap breaks the run's row rhythm."""
    if gap > 3 * height:
        return False
    prev_gaps = [b[0]["y0"] - max(l["y1"] for l in a) for a, b in zip(run, run[1:])]
    if prev_gaps and gap > 1.6 * max(prev_gaps) + 2:
        return False
    if len(row) != len(run[0]):
        lefts = [l["x0"] for r in run for l in r]
        if not all(any(abs(seg["x0"] - x) <= 6 for x in lefts) for seg in row):
            return False
    return True


def _pp_furniture_keys(pages: list[dict]) -> dict[str, set[str]]:
    """Normalised keys of margin lines that recur on 2+ pages, by region."""
    seen: dict[tuple[str, str], set[int]] = {}
    for pi, page in enumerate(pages):
        for line in page["lines"]:
            region = ("header" if line["y1"] <= page["h"] * _PP_MARGIN
                      else "footer" if line["y0"] >= page["h"] * (1 - _PP_MARGIN) else "")
            if region:
                seen.setdefault((region, _pp_key(_pp_line_text(line))), set()).add(pi)
    out: dict[str, set[str]] = {"header": set(), "footer": set()}
    for (region, key), on in seen.items():
        if len(on) >= 2:
            out[region].add(key)
    return out


_PP_DIAGRAM_COVERAGE = 0.04   # drawn share of the page that makes it a picture (text slides measure 0.0)
_PP_DIAGRAM_SHORT = 0.6        # share of text fragments of five words or fewer


def _pp_is_margin_furniture(row: list[dict], page: dict, furniture: dict[str, set[str]]) -> str:
    """'header' / 'footer' when the row is recurring page furniture, else ''."""
    top, bottom = min(l["y0"] for l in row), max(l["y1"] for l in row)
    keys = [_pp_key(_pp_line_text(l)) for l in row]
    if bottom <= page["h"] * _PP_MARGIN and all(k in furniture["header"] for k in keys):
        return "header"
    if top >= page["h"] * (1 - _PP_MARGIN) and all(k in furniture["footer"] for k in keys):
        return "footer"
    return ""


def _pp_diagram_page(page: dict, pno: int, rows: list, furniture: dict, heading_size, ranks: dict,
                     html_page: dict | None, slides: dict, budget: list) -> list[dict] | None:
    """A slide page drawn as a diagram, as [title, picture of the page below
    the title, its text as notes]; None for an ordinary page.

    A PDF keeps shapes (circles, arrows, boxes) as vector drawing, so a reader
    sees only their labels: reflowed, a Venn diagram became 'diagram BRAINS'
    and a two-column table of circle labels. A page is a diagram when its
    text is mostly short fragments AND a real share of it is drawn: the page
    rendered at low resolution has ink outside every text line and picture.
    """
    body = [r for r in rows if not _pp_is_margin_furniture(r, page, furniture)]
    if not body:
        return None
    title_rows: list = []
    for r in body:
        size = heading_size(r)
        if size and (not title_rows or abs(size - heading_size(title_rows[0])) < 0.6):
            title_rows.append(r)
        else:
            break
    rest = body[len(title_rows):]
    # A title that wraps can share its second row with a label beside it
    # ("diagram" next to "BRAINS"): a title-sized line in the next row that
    # starts under the title is the title's.
    if title_rows and rest:
        size0 = heading_size(title_rows[0])
        x0 = min(l["x0"] for l in title_rows[0])
        nxt = rest[0]
        wrap = [l for l in nxt if abs(_pp_line_size(l) - size0) < 0.6 and abs(l["x0"] - x0) <= 20]
        if wrap:
            title_rows.append(wrap)
            others = [l for l in nxt if l not in wrap]
            rest = ([others] if others else []) + rest[1:]
    frags = [l for r in rest for l in r]
    if len(frags) < 3:
        return None
    words = [len(_pp_line_text(l).split()) for l in frags]
    short = sum(1 for w in words if w <= 5) / len(frags)
    bullets = sum(1 for r in rest if _pp_bullet(r)) / max(len(rest), 1)
    if short < _PP_DIAGRAM_SHORT or max(words) >= 15 or bullets >= 0.5:
        return None
    # A table draws its borders too, but its rows nearly all hold several
    # aligned cells; read it as a table, not a picture.
    multi = [r for r in rest if len(r) >= 2]
    if len(multi) >= 2 and len(multi) >= 0.8 * len(rest):
        read = _pp_table(multi, page["w"])
        if read and read[0] == "table":
            return None
    text_boxes = [(l["x0"], l["y0"], l["x1"], l["y1"]) for r in body for l in r]
    scale = (html_page["h"] / page["h"]) if html_page and page["h"] else 0.0
    image_boxes = [(im["x0"] / scale, im["y0"] / scale, im["x1"] / scale, im["y1"] / scale)
                   for im in (html_page or {}).get("images", [])] if scale else []
    try:
        coverage = slides["coverage"](pno, page, text_boxes, image_boxes)
    except Exception:
        return None
    if coverage < _PP_DIAGRAM_COVERAGE:
        return None

    out: list[dict] = []
    top = page["h"] * _PP_MARGIN
    if title_rows:
        title = " ".join(_pp_line_text(l) for r in title_rows for l in r)
        out.append(_placed(_heading(title, ranks.get(heading_size(title_rows[0]), 1)), pno))
        # Crop below the title, unless other content starts beside a wrapped
        # title line: then below its first line, so the drawing's top is kept.
        title_bottom = max(l["y1"] for l in title_rows[-1])
        first_other = min((l["y0"] for r in rest for l in r), default=title_bottom)
        top = (title_bottom if first_other >= title_bottom
               else max(l["y1"] for l in title_rows[0])) + 4
    bottom = page["h"] * (1 - _PP_MARGIN)
    import base64
    try:
        png = slides["render"](pno, top, bottom)
    except Exception:
        png = None
    if png and len(png) <= budget[0]:
        budget[0] -= len(png)
        out.append(_placed(_image(base64.b64encode(png).decode("ascii"), "image/png",
                                  round(page["w"] * 96 / 72), round((bottom - top) * 96 / 72),
                                  "Diagram from page %d" % pno), pno))
    for r in rest:
        out.append(_placed(_text("  ".join(_pp_line_text(l) for l in r)), pno, "notes"))
    # Page furniture stays tagged, as on any page.
    for r in rows:
        region = _pp_is_margin_furniture(r, page, furniture)
        if region:
            for l in r:
                out.append(_placed(_text(_pp_line_text(l)), pno, region))
    return out


def _pp_ppm_coverage(ppm: bytes, page_w: float, page_h: float, boxes: list) -> float:
    """Share of a page's pixels that differ from its background colour,
    outside the given boxes (points) and the header/footer bands. `ppm` is a
    binary P6 render of the whole page."""
    head = ppm.split(maxsplit=4)
    if len(head) < 5 or head[0] != b"P6":
        return 0.0
    w, h, data = int(head[1]), int(head[2]), head[4]
    if w <= 0 or h <= 0 or len(data) < w * h * 3:
        return 0.0
    sx, sy = w / page_w, h / page_h
    masked = bytearray(w * h)
    for (x0, y0, x1, y1) in boxes:
        for y in range(max(0, int(y0 * sy) - 1), min(h, int(y1 * sy) + 2)):
            row = y * w
            for x in range(max(0, int(x0 * sx) - 1), min(w, int(x1 * sx) + 2)):
                masked[row + x] = 1
    band_top, band_bottom = int(h * _PP_MARGIN), int(h * (1 - _PP_MARGIN))
    counts: dict = {}
    for i in range(0, w * h * 3, 3 * 7):
        key = (data[i] >> 4, data[i + 1] >> 4, data[i + 2] >> 4)
        counts[key] = counts.get(key, 0) + 1
    bg = max(counts.items(), key=lambda kv: kv[1])[0]
    bg_rgb = [c * 16 + 8 for c in bg]
    drawn = total = 0
    for y in range(band_top, band_bottom):
        for x in range(w):
            p = y * w + x
            total += 1
            if masked[p]:
                continue
            i = p * 3
            if max(abs(data[i] - bg_rgb[0]), abs(data[i + 1] - bg_rgb[1]), abs(data[i + 2] - bg_rgb[2])) > 40:
                drawn += 1
    return drawn / total if total else 0.0


def _poppler_blocks(bbox_xml: str, html_xml: str | None, load_image=None,
                    slides: dict | None = None) -> tuple[list[dict], int]:
    """`load_image(src) -> bytes` reads an image pdftohtml extracted; without
    it, images are left out.

    `slides` (slide conversion only) enables diagram pages: a dict with
    `coverage(pno, page, text_boxes, image_boxes) -> float`, the share of the
    page drawn outside text and pictures, and `render(pno, top_pt, bottom_pt)
    -> bytes | None`, a PNG of that band of the page."""
    pages = _pp_parse_bbox(bbox_xml)
    html_pages = _pp_parse_html(html_xml or "")
    budget = [_PP_IMAGE_BUDGET]
    for i, page in enumerate(pages):
        _pp_style_words(page, html_pages[i] if i < len(html_pages) else None)
    all_lines = [l for p in pages for l in p["lines"]]
    if not all_lines:
        return [], len(pages)
    weights: dict[float, int] = {}
    for line in all_lines:
        size = _pp_line_size(line)
        weights[size] = weights.get(size, 0) + sum(len(w["text"]) for w in line["words"])
    body = max(weights.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    furniture = _pp_furniture_keys(pages)

    def heading_size(row: list[dict]) -> float | None:
        # Every segment must be heading-sized: "1." + "Overview" at 16pt is a
        # numbered heading, while a small "•" beside the text is a list item.
        text = " ".join(_pp_line_text(l) for l in row)
        if len(text) > 150 or not any(c.isalpha() for c in text):
            return None
        smallest = min(_pp_line_size(l) for l in row)
        if smallest >= body * _PP_HEADING_RATIO:
            return max(_pp_line_size(l) for l in row)
        # Bold and a little larger: Word/LibreOffice's Heading 2-3 at 13pt
        # over a 12pt body (ratio 1.11) is a heading too.
        if smallest >= body * _PP_BOLD_HEADING_RATIO and all(_pp_line_bold(l) for l in row):
            return max(_pp_line_size(l) for l in row)
        return None

    line_gap = _pp_line_gap(pages)

    head_sizes = [heading_size(r) for p in pages for r in _pp_rows(p["lines"])]
    ranks = _rank_levels([s for s in head_sizes if s])

    blocks: list[dict] = []
    for pi, page in enumerate(pages):
        pno = pi + 1
        rows = _pp_rows(page["lines"])
        para: list[dict] = []        # lines of the open paragraph
        items: list[tuple[str, int]] = []
        item_x: list[float] = []
        ordered = [False]
        table_rows: list[list[dict]] = []

        def flush_para():
            if para:
                words = [w for l in para for w in l["words"]]
                text = " ".join(w["text"] for w in words)
                text = re.sub(r"(\w)- (\w)", r"\1\2", text) if any(l is not para[-1] and _pp_line_text(l).endswith("-") for l in para) else text
                runs = _pp_runs(words)
                block = _text(text)
                if runs:
                    block["runs"] = runs
                blocks.append(_placed(block, pno))
                para.clear()

        def flush_items():
            if items:
                base = min(item_x)
                levels = [0 if x - base < 8 else 1 for x in item_x]
                blocks.append(_placed(_list([t for t, _ in items], ordered[0], levels), pno))
                items.clear()
                item_x.clear()

        def flush_table():
            if table_rows:
                read = _pp_table(table_rows, page["w"])
                if read and read[0] == "table":
                    blocks.append(_placed(read[1], pno))
                elif read:
                    for column_text in read[1]:
                        blocks.append(_placed(_text(column_text), pno))
                else:
                    for r in table_rows:
                        blocks.append(_placed(_text("  ".join(_pp_line_text(l) for l in r)), pno))
                table_rows.clear()

        def flush_all():
            flush_para()
            flush_items()
            flush_table()

        # Right edge of the page's text column: a paragraph line that stops
        # well short of it ended its paragraph, however close the next line.
        single = [r[0] for r in rows if len(r) == 1]
        col_left = min((l["x0"] for l in single), default=0.0)
        col_right = max((l["x1"] for l in single), default=page["w"])
        short_line = 0.15 * max(col_right - col_left, 1.0)

        pending_images = _pp_body_images(page, html_pages[pi] if pi < len(html_pages) else None) \
            if load_image else []

        def emit_images_above(y: float):
            while pending_images and pending_images[0]["y0"] < y:
                block = _pp_image_block(pending_images.pop(0), load_image, budget)
                if block:
                    flush_all()
                    blocks.append(_placed(block, pno))

        if slides:
            diagram = _pp_diagram_page(page, pno, rows, furniture, heading_size, ranks,
                                       html_pages[pi] if pi < len(html_pages) else None, slides, budget)
            if diagram is not None:
                blocks.extend(diagram)
                continue

        prev_bottom = None
        for row in rows:
            emit_images_above(min(l["y0"] for l in row))
            text = " ".join(_pp_line_text(l) for l in row)
            top, bottom = min(l["y0"] for l in row), max(l["y1"] for l in row)
            height = bottom - top
            gap = (top - prev_bottom) if prev_bottom is not None else 0.0
            prev_bottom = bottom
            key = _pp_key(text)
            region = ("header" if bottom <= page["h"] * _PP_MARGIN and key in furniture["header"]
                      else "footer" if top >= page["h"] * (1 - _PP_MARGIN) and key in furniture["footer"]
                      else "")
            if not region and len(row) > 1:
                # A margin row like "Company ... 3" splits into a recurring part
                # and a page number: judge the pieces.
                parts = [_pp_key(_pp_line_text(l)) for l in row]
                for reg in ("header", "footer"):
                    in_margin = bottom <= page["h"] * _PP_MARGIN if reg == "header" else top >= page["h"] * (1 - _PP_MARGIN)
                    if in_margin and all(p in furniture[reg] for p in parts):
                        region = reg
            if region:
                flush_all()
                for l in row:
                    blocks.append(_placed(_text(_pp_line_text(l)), pno, region))
                continue

            # A bullet glyph makes a list item at any size (deck bullets are
            # large); a numbered row that is heading-sized is a heading
            # ("1. Overview"), which is why headings are tried before numbers.
            bullet = _pp_bullet(row)
            if items and not bullet and len(row) == 1 and row[0]["x0"] > min(item_x) + 4 and gap < height:
                # Wrapped continuation of the last list item, at any size.
                items[-1] = (f"{items[-1][0]} {text}", 0)
                continue
            size = heading_size(row)
            if size and not (bullet and not bullet[1]):
                flush_all()
                blocks.append(_placed(_heading(text, ranks.get(size, 3)), pno))
                continue

            if bullet:
                flush_para()
                flush_table()
                _, is_ordered, content = bullet
                if not items:
                    ordered[0] = is_ordered
                items.append((" ".join(_pp_line_text(l) for l in content), 0))
                item_x.append(row[0]["x0"])
                continue
            if table_rows and len(row) == 1 and gap <= line_gap + 0.5 * height \
                    and _pp_fold_into_cell(table_rows, row[0]):
                # A cell's text wrapped onto a second line.
                continue
            if items and len(row) == 1 and row[0]["x0"] > min(item_x) + 4 and gap < height:
                # Wrapped continuation of the last list item.
                items[-1] = (f"{items[-1][0]} {text}", 0)
                continue
            flush_items()

            if len(row) >= 2:
                flush_para()
                if table_rows and not _pp_continues_table(table_rows, row, gap, height):
                    flush_table()
                table_rows.append(row)
                continue
            flush_table()

            line = row[0]
            if para:
                last = para[-1]
                same_size = abs(_pp_line_size(last) - _pp_line_size(line)) <= 0.6
                aligned = abs(line["x0"] - para[0]["x0"]) <= 4 or abs(line["x0"] - last["x0"]) <= 4
                indented = line["x0"] > last["x0"] + 4
                close = gap <= line_gap + 0.25 * (last["y1"] - last["y0"])
                ended = last["x1"] < col_right - short_line
                if ended or indented or not (same_size and aligned and close):
                    flush_para()
            para.append(line)
        flush_all()
        emit_images_above(float("inf"))
    return blocks, len(pages)


def run_poppler(pdf: Path, slides: bool = False) -> dict:
    """Structured blocks from poppler alone: headings by font size, lists,
    tables from aligned columns, paragraphs reflowed, page furniture tagged.
    Needs only poppler-utils (pdftotext, pdftohtml, pdftoppm) and the stdlib.

    `slides` (backend "poppler-slides", chosen by the CLI when converting a
    PDF to PPTX/ODP) also turns diagram pages into a picture of the page with
    their text as speaker notes."""
    bbox = subprocess.run(["pdftotext", "-bbox-layout", str(pdf), "-"],
                          capture_output=True, text=True, check=False)
    if bbox.returncode != 0:
        raise RuntimeError(f"pdftotext -bbox-layout exited {bbox.returncode}: {bbox.stderr.strip()}")
    import tempfile
    with tempfile.TemporaryDirectory(prefix="docparse-poppler-") as tmp:
        html_xml = None
        try:
            # Without -i, pdftohtml also writes each image beside the XML and
            # records where it sits on the page.
            html = subprocess.run(["pdftohtml", "-xml", "-q", "-fmt", "png", str(pdf),
                                   str(Path(tmp) / "page")],
                                  capture_output=True, text=True, check=False)
            xml_path = Path(tmp) / "page.xml"
            if html.returncode == 0 and xml_path.exists():
                html_xml = xml_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            pass  # geometry-only: sizes from word boxes, no bold, links or images

        def load_image(src: str) -> bytes:
            path = (Path(tmp) / Path(src).name).resolve()
            if path.parent != Path(tmp).resolve():
                raise ValueError("image outside the extraction directory")
            return path.read_bytes()

        slide_tools = None
        if slides:
            def coverage(pno: int, page: dict, text_boxes: list, image_boxes: list) -> float:
                out = Path(tmp) / f"cov-{pno}"
                subprocess.run(["pdftoppm", "-r", "24", "-f", str(pno), "-l", str(pno), "-singlefile",
                                str(pdf), str(out)], capture_output=True, check=True)
                ppm = (Path(tmp) / f"cov-{pno}.ppm").read_bytes()
                return _pp_ppm_coverage(ppm, page["w"], page["h"], text_boxes + image_boxes)

            def render(pno: int, top_pt: float, bottom_pt: float) -> bytes | None:
                dpi = 110
                out = Path(tmp) / f"diagram-{pno}"
                page_w = next(p["w"] for i, p in enumerate(_pp_parse_bbox(bbox.stdout)) if i + 1 == pno)
                subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(pno), "-l", str(pno), "-singlefile",
                                "-png", "-x", "0", "-y", str(int(top_pt * dpi / 72)),
                                "-W", str(int(page_w * dpi / 72)), "-H", str(int((bottom_pt - top_pt) * dpi / 72)),
                                str(pdf), str(out)], capture_output=True, check=True)
                return (Path(tmp) / f"diagram-{pno}.png").read_bytes()

            slide_tools = {"coverage": coverage, "render": render}

        blocks, pages = _poppler_blocks(bbox.stdout, html_xml, load_image, slide_tools)
    meta = _empty_meta()
    meta["pageCount"] = pages or _pdf_page_count(pdf)
    return {"metadata": meta, "blocks": blocks}


BACKENDS = {
    "pdftotext": run_pdftotext,
    "poppler": run_poppler,
    "poppler-slides": lambda pdf: run_poppler(pdf, slides=True),
    "docling": run_docling,
    "liteparse": run_liteparse,
    "words": run_words,
}

# Modes whose job is to return data other than blocks, so the "extracted no
# content" guard below does not apply to them.
NON_BLOCK_BACKENDS = {"words"}


_PLACEHOLDER_RE = re.compile(r"<!--.*?-->", re.S)


def _has_substance(blocks: list[dict]) -> bool:
    """True if any block carries real content, ignoring markdown placeholders.

    Docling emits `<!-- image -->` for a page it could not read text from. Those
    are structurally valid blocks with no information in them, so "did we get
    any blocks?" is the wrong question — "did we get anything a reader could
    use?" is the right one. Tables and lists count as substance even with no
    text of their own.
    """
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("kind") in ("table", "list", "image"):
            return True
        if _PLACEHOLDER_RE.sub("", b.get("text", "")).strip():
            return True
    return False


def main() -> int:
    if len(sys.argv) != 3:
        print("ERR: usage: adapter.py <backend> <pdf_path>", file=sys.stderr)
        return 1

    backend, pdf_arg = sys.argv[1], sys.argv[2]
    if backend not in BACKENDS:
        print(f"ERR: unknown backend '{backend}'; available: {','.join(BACKENDS)}", file=sys.stderr)
        return 1

    pdf = Path(pdf_arg)
    if not pdf.exists():
        print(f"ERR: pdf not found: {pdf_arg}", file=sys.stderr)
        return 1

    # Guarantee pure-JSON stdout: backends (docling/transformers, etc.) print
    # progress bars and model-loading chatter that would otherwise corrupt the
    # JSON the AILANG bridge parses. Redirect everything they emit to stderr
    # while the backend runs; only the final json.dump below reaches stdout.
    try:
        with contextlib.redirect_stdout(sys.stderr):
            doc = BACKENDS[backend](pdf)
    except ImportError as e:
        print(f"ERR: backend '{backend}' not installed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERR: {backend} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    # Universal page-count fallback: any backend that couldn't determine its own
    # page count (e.g. docling's export_to_dict has no 'pages' in some versions)
    # gets an authoritative count from pdfinfo.
    meta = doc.setdefault("metadata", _empty_meta())
    if not meta.get("pageCount"):
        meta["pageCount"] = _pdf_page_count(pdf)

    # Empty guard: a backend that extracts nothing is a failure, not an empty
    # success. Fail loudly so the AILANG bridge surfaces it instead of writing
    # a 1-byte "succeeded" file (the silent-failure shape we're eliminating).
    #
    # Counting blocks is not enough. Docling on a PDF with no recoverable text
    # returns placeholder blocks rather than none:
    #     {"kind": "text", "text": "<!-- image -->"}
    # That is a non-empty block list, so a naive count sails through this guard
    # and the caller indexes "<!-- image -->" as the document's content — a
    # silent empty success wearing a success exit code. Judge on substance.
    if backend not in NON_BLOCK_BACKENDS and not _has_substance(doc.get("blocks") or []):
        print(
            f"ERR: backend '{backend}' extracted no content (0 blocks) from "
            f"{pdf.name} (no text layer?).",
            file=sys.stderr,
        )
        return 1

    json.dump(doc, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
