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


def _docling_blocks(items: list[tuple[Any, int]]) -> list[dict]:
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
        return DocumentConverter(format_options={
            InputFormat.PDF: PdfFormatOption(backend=PyPdfiumDocumentBackend)})
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
    blocks = _docling_blocks(_docling_items(result.document))
    # A scanned page is laid out as ONE picture, and docling files its OCR text
    # as that picture's children, which the default walk skips. Only when that
    # leaves nothing substantive, walk again descending into pictures, so
    # text-layer PDFs with figures are unchanged.
    if not _has_substance(blocks):
        blocks = _docling_blocks(_docling_items(result.document, traverse_pictures=True))

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


BACKENDS = {
    "pdftotext": run_pdftotext,
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
