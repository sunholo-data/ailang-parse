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
        {"kind": "table",   "rows": [[str]], "headers": [str], "caption": str}
      ]
    }

All errors print "ERR: <message>" to stderr and exit 1 (AILANG checks
Result[ProcessOutput, ProcessError] for non-zero exit).
"""

from __future__ import annotations

import contextlib
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


def run_docling(pdf: Path) -> dict:
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(pdf))
    md = result.document.export_to_markdown()
    blocks = _blocks_from_markdown(md)

    meta = _empty_meta()
    try:
        doc_dict = result.document.export_to_dict()
        if isinstance(doc_dict, dict):
            for k in ("title", "author"):
                v = doc_dict.get(k) or doc_dict.get("meta", {}).get(k, "")
                if isinstance(v, str):
                    meta[k] = v
            pages = doc_dict.get("pages") or []
            if isinstance(pages, list):
                meta["pageCount"] = len(pages)
    except Exception:
        pass
    return {"metadata": meta, "blocks": blocks}


def _liteparse_headings_from_textitems(textitems: list) -> set[str]:
    """Heuristic: any font size strictly larger than the modal (body-text) size
    marks a heading. Body text is whichever size appears most often."""
    from collections import Counter

    sizes = [getattr(ti, "fontSize", None) for ti in textitems]
    sizes = [s for s in sizes if isinstance(s, (int, float))]
    if not sizes:
        return set()
    body_size = Counter(sizes).most_common(1)[0][0]
    heading_texts: set[str] = set()
    for ti in textitems:
        size = getattr(ti, "fontSize", None)
        text = getattr(ti, "text", "").strip()
        if isinstance(size, (int, float)) and size > body_size and text and len(text) < 200:
            heading_texts.add(text)
    return heading_texts


def run_liteparse(pdf: Path) -> dict:
    from liteparse import LiteParse

    result = LiteParse().parse(str(pdf), ocr_enabled=False)
    all_textitems = []
    for page in result.pages:
        all_textitems.extend(getattr(page, "textItems", []) or [])
    heading_texts = _liteparse_headings_from_textitems(all_textitems)

    blocks: list[dict] = []
    para: list[str] = []

    def flush():
        if para:
            text = " ".join(p.strip() for p in para if p.strip()).strip()
            if text:
                blocks.append(_text(text))
            para.clear()

    for page in result.pages:
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                flush()
                continue
            if line in heading_texts:
                flush()
                # Higher font-size → lower (more important) heading level.
                blocks.append(_heading(line, 2))
            else:
                para.append(line)
        flush()

    meta = _empty_meta()
    meta["pageCount"] = result.num_pages
    return {"metadata": meta, "blocks": blocks}


BACKENDS = {
    "pdftotext": run_pdftotext,
    "docling": run_docling,
    "liteparse": run_liteparse,
}


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
    if not doc.get("blocks"):
        print(
            f"ERR: backend '{backend}' extracted no content (0 blocks) from "
            f"{pdf.name}. For scanned/image-only PDFs with no text layer, "
            f"use --pdf-backend ai.",
            file=sys.stderr,
        )
        return 1

    json.dump(doc, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
