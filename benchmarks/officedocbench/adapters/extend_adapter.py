"""Extend (extend.ai) Parse adapter for OfficeDocBench.

Requires: EXTEND_API_KEY environment variable (inject it from your secret
manager, e.g. ``op run --env-file=... --``). Uses the REST API directly
(API version 2026-02-09) through httpx: upload -> POST /parse_runs -> poll.

Configured at Extend's strongest documented settings, so the comparison
cannot be dismissed as a default-settings run:

- engine ``parse_performance`` (Parse 2.0, 2 credits/page)
- agentic text and table correction, advanced chart extraction, formulas
- ``formattingDetection: change_tracking`` (Extend's tracked-change mode)
- tables as HTML, which carries ``data-cell`` / ``data-formula`` for Excel
- ``excelParsingMode: advanced`` with cell metadata and formatting

What the provider returns, observed on this corpus (2026-11-03):

- DOCX and PPTX are rendered to PDF before parsing
  (``output.metadata.finalMimeType == "application/pdf"``). Comments,
  speaker notes, bookmarks and authorship are not in the response.
- Visible tracked changes come back inline as
  ``<change><ins>..</ins></change>`` / ``<del>``, without author or move
  semantics.
- XLSX and ODS are read natively: one page chunk per sheet,
  ``metadata.sheet.name`` on each block, A1 references (``data-cell``),
  formulas, merge ranges and fill/font colours (inline ``style``) in the
  HTML. A sheet often arrives split into several tables; cell assertions
  use Extend's own ``data-cell`` coordinates, one logical table per sheet.
- HTML and Markdown input is returned as-is (Extend's docs: "parsed as-is",
  0 credits) in a single text block. Markdown goes through markdown_output
  unchanged; HTML markup is read by ``_html_to_markdown``. Scores for these
  two formats therefore mostly measure pass-through, not Extend's parsing.
- ODP, EPUB and TSV are rejected at upload (``INVALID_REQUEST``), so they
  are declared unsupported rather than recorded as parse errors.

Raw responses: set EXTEND_RAW_DIR to keep every parse run's JSON. With
EXTEND_REUSE_RAW=1 as well, a stored response for the same file bytes is
remapped instead of re-parsed (explicit opt-in, never a hidden fallback),
so mapping fixes do not spend credits.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter
from .structure import cell, markdown_output, table_cells

API = os.environ.get("EXTEND_API_BASE", "https://api.extend.ai")
API_VERSION = "2026-02-09"
POLL_SECONDS = 2.0
TIMEOUT_SECONDS = 600

CONFIG: dict[str, Any] = {
    "target": "markdown",
    "engine": "parse_performance",
    "chunkingStrategy": {"type": "page"},
    "blockOptions": {
        "figures": {"enabled": True, "advancedChartExtractionEnabled": True},
        "tables": {"targetFormat": "html", "agentic": {"enabled": True}},
        "text": {"agentic": {"enabled": True}},
        "formulas": {"enabled": True},
    },
    "advancedOptions": {
        "excelParsingMode": "advanced",
        "excelIncludeCellMetadata": True,
        "excelIncludeCellFormatting": True,
        "excelSkipHiddenContent": False,
        "formattingDetection": [{"type": "change_tracking"}],
    },
}

_CHANGE = re.compile(r"<(ins|del)>(.*?)</\1>", re.DOTALL)
_TAGS = re.compile(r"</?(change|ins|del)>")
_FURNITURE = {"header", "footer", "page_number"}
_SPREADSHEETS = {".xlsx", ".ods"}
_CONTAINERS = {
    "html",
    "body",
    "main",
    "article",
    "section",
    "div",
    "header",
    "footer",
    "nav",
    "aside",
    "figure",
    "dl",
    "dd",
    "dt",
    "center",
}
_BLOCKS = _CONTAINERS | {
    "p",
    "blockquote",
    "caption",
    "figcaption",
    "pre",
    "table",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}


def _inline(node) -> str:
    """Markdown for an element's inline content (emphasis, links, code)."""
    from bs4 import NavigableString

    out = []
    for child in node.children:
        if isinstance(child, NavigableString):
            out.append(re.sub(r"\s+", " ", str(child)))
            continue
        name, inner = child.name, _inline(child)
        if name in ("strong", "b") and inner.strip():
            out.append(f"**{inner.strip()}**")
        elif name in ("em", "i") and inner.strip():
            out.append(f"*{inner.strip()}*")
        elif name == "code":
            out.append(f"`{child.get_text()}`")
        elif name == "a" and child.get("href"):
            out.append(f"[{inner.strip()}]({child['href']})")
        elif name == "img":
            out.append(f"![{child.get('alt', '')}]({child.get('src', '')})")
        elif name == "br":
            out.append(" ")
        else:
            out.append(inner)
    return "".join(out)


def _html_to_markdown(markup: str) -> str:
    """Markdown for HTML that Extend passed through unconverted.

    Reads only the markup in Extend's response: headings, paragraphs,
    lists (with nesting), emphasis, links, code and tables (kept as HTML,
    which markdown_output reads with its usual table mapping).
    """
    if "<" not in markup:
        return markup
    from bs4 import BeautifulSoup, NavigableString

    blocks: list[str] = []

    def walk(node) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    blocks.append(text)
                continue
            name = child.name
            if name in ("script", "style", "head", "title", "meta"):
                continue
            if re.fullmatch(r"h[1-6]", name):
                blocks.append("#" * int(name[1]) + " " + _inline(child).strip())
            elif name in ("p", "blockquote", "caption", "figcaption"):
                text = _inline(child).strip()
                if text:
                    blocks.append(text)
            elif name == "pre":
                blocks.append("```\n" + child.get_text().rstrip("\n") + "\n```")
            elif name == "table":
                blocks.append(str(child))
            elif name in ("ul", "ol"):
                blocks.append(_list(child, 0))
            elif name in _CONTAINERS and child.find(_BLOCKS):
                walk(child)
            else:
                text = _inline(child).strip()
                if text:
                    blocks.append(text)

    def _list(node, indent: int) -> str:
        lines = []
        ordered = node.name == "ol"
        for n, li in enumerate(node.find_all("li", recursive=False), 1):
            marker = f"{n}. " if ordered else "- "
            nested = [
                c for c in li.children if getattr(c, "name", None) in ("ul", "ol")
            ]
            for sub in nested:
                sub.extract()
            lines.append(" " * indent + marker + _inline(li).strip())
            for sub in nested:
                lines.append(_list(sub, indent + len(marker)))
        return "\n".join(lines)

    walk(BeautifulSoup(markup, "html.parser"))
    return "\n\n".join(b for b in blocks if b.strip())


def _clean(text: str) -> str:
    """Drop Extend's change markup, keeping the text it wraps."""
    return _TAGS.sub("", text or "")


def _html_rows(markup: str) -> list[list[dict[str, Any]]]:
    """Logical grid of an Extend HTML table, keeping ``data-formula``.

    Same span expansion as structure.html_rows; the formula attribute is
    the only addition (Extend's Excel metadata, read from its output).
    """
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
            c: dict[str, Any] = {
                "text": _clean(node.get_text(" ", strip=True)),
                "colSpan": cs,
            }
            if node.get("data-formula"):
                c["formula"] = node["data-formula"]
            row.append(c)
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


_REF = re.compile(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$")
_STYLE_COLOUR = re.compile(
    r"(?:^|;)\s*(background-color|color)\s*:\s*(#[0-9A-Fa-f]{6})"
)


def _col_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _sheet_cells(markup: str, table: int, scope: str) -> list[dict[str, Any]]:
    """Cells at Extend's own sheet coordinates, with merges and colours."""
    from bs4 import BeautifulSoup

    out = []
    for node in BeautifulSoup(markup or "", "html.parser").find_all(["td", "th"]):
        ref = _REF.match(node.get("data-cell") or "")
        if not ref:
            continue
        c1, r1 = _col_number(ref[1]), int(ref[2])
        c2 = _col_number(ref[3]) if ref[3] else c1
        r2 = int(ref[4]) if ref[4] else r1
        c: dict[str, Any] = {
            "table": table,
            "scope": scope,
            "row": r1,
            "col": c1,
            "text": _clean(node.get_text(" ", strip=True)),
            "col_span": c2 - c1 + 1,
            "merged": False,
        }
        if node.get("data-formula"):
            c["formula"] = node["data-formula"]
        for prop, value in _STYLE_COLOUR.findall(node.get("style") or ""):
            c["fill" if prop == "background-color" else "color"] = value.lower()
        out.append(c)
        for r in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                if (r, col) != (r1, c1):
                    out.append(
                        {
                            "table": table,
                            "scope": scope,
                            "row": r,
                            "col": col,
                            "text": "",
                            "col_span": 1,
                            "merged": True,
                        }
                    )
    return out


class ExtendAdapter(OfficeDocBenchAdapter):
    def name(self) -> str:
        return "Extend"

    def version(self) -> str:
        return f"{CONFIG['engine']}@api-{API_VERSION}"

    def provider_config(self) -> dict[str, Any]:
        """Recorded in results provenance: the exact request config.

        ``raw_reuse`` marks a remap of stored responses, whose per-file
        timings are mapping time, not Extend's parse latency.
        """
        reuse = os.environ.get("EXTEND_REUSE_RAW", "").lower() in ("1", "true", "yes")
        return {"request": CONFIG, "raw_reuse": reuse}

    def supported_formats(self) -> set[str]:
        # From the upload endpoint's own INVALID_REQUEST list (2026-11-03),
        # restricted to formats present in OfficeDocBench.
        return {"docx", "pptx", "xlsx", "odt", "ods", "html", "md", "csv"}

    # ------------------------------------------------------------- request

    def parse(self, filepath: Path) -> dict[str, Any]:
        return self.convert_json(self._run(filepath), filepath)

    def _raw_path(self, filepath: Path) -> Path | None:
        raw_dir = os.environ.get("EXTEND_RAW_DIR")
        if not raw_dir:
            return None
        digest = hashlib.sha256(filepath.read_bytes()).hexdigest()[:16]
        return Path(raw_dir) / f"{filepath.name}.{digest}.json"

    def _run(self, filepath: Path) -> dict[str, Any]:
        raw_path = self._raw_path(filepath)
        reuse = os.environ.get("EXTEND_REUSE_RAW", "").lower() in ("1", "true", "yes")
        if raw_path and reuse and raw_path.exists():
            return json.loads(raw_path.read_text())

        key = os.environ.get("EXTEND_API_KEY")
        if not key:
            raise RuntimeError("EXTEND_API_KEY not set")
        import httpx

        headers = {
            "Authorization": f"Bearer {key}",
            "x-extend-api-version": API_VERSION,
        }
        with httpx.Client(timeout=120, headers=headers) as client:
            up = client.post(
                f"{API}/files/upload",
                files={"file": (filepath.name, filepath.read_bytes())},
            )
            if up.status_code >= 400:
                return self._failed(raw_path, f"upload HTTP {up.status_code}", up.text)
            created = client.post(
                f"{API}/parse_runs",
                json={"file": {"id": up.json()["id"]}, "config": CONFIG},
            )
            if created.status_code >= 400:
                return self._failed(
                    raw_path, f"parse_runs HTTP {created.status_code}", created.text
                )
            run = created.json()
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while run.get("status") not in ("PROCESSED", "FAILED"):
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Extend run {run.get('id')} timed out")
                time.sleep(POLL_SECONDS)
                got = client.get(f"{API}/parse_runs/{run['id']}")
                got.raise_for_status()
                run = got.json()

        if raw_path:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps(run, indent=1))
        return run

    @staticmethod
    def _failed(raw_path: Path | None, reason: str, body: str) -> dict[str, Any]:
        """A request the API refused, recorded like a FAILED run.

        Kept in EXTEND_RAW_DIR so a remap reproduces the failure instead of
        silently re-requesting it.
        """
        run = {
            "status": "FAILED",
            "failureReason": reason,
            "failureMessage": body[:300],
        }
        if raw_path:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps(run, indent=1))
        return run

    # ------------------------------------------------------------- mapping

    def convert_json(self, run: dict[str, Any], filepath: Path) -> dict[str, Any]:
        """Map an existing parse-run response; no upload or parsing request."""
        if run.get("status") != "PROCESSED":
            raise RuntimeError(
                f"Extend run {run.get('status')}: "
                f"{run.get('failureReason')} {run.get('failureMessage')}"
            )
        chunks = (run.get("output") or {}).get("chunks") or []
        if not any(b for ch in chunks for b in ch.get("blocks") or []):
            raise RuntimeError("Extend returned no blocks")

        suffix = filepath.suffix.lower()
        body: list[str] = []
        headers_footers: list[dict[str, str]] = []
        track_changes: list[dict[str, str]] = []
        images: list[dict[str, str]] = []
        table_blocks: list[tuple[str, str]] = []  # (html, scope)
        containers: list[dict[str, str]] = []

        for ch in chunks:
            blocks = ch.get("blocks") or []
            scope = ""
            if suffix == ".pptx":
                first = next(
                    (
                        b
                        for b in blocks
                        if b.get("type") in ("heading", "section_heading")
                    ),
                    None,
                )
                scope = _clean(first["content"]).lstrip("# ").strip() if first else ""
                containers.append({"kind": "slide", "name": scope})
            for b in blocks:
                btype, content = b.get("type", ""), b.get("content") or ""
                for kind, text in _CHANGE.findall(content):
                    track_changes.append(
                        {
                            "type": "insert" if kind == "ins" else "delete",
                            "author": "",
                            "text": _clean(text).strip(),
                        }
                    )
                if suffix in _SPREADSHEETS:
                    sheet = ((b.get("metadata") or {}).get("sheet") or {}).get(
                        "name", ""
                    )
                    if sheet and (not containers or containers[-1]["name"] != sheet):
                        containers.append({"kind": "sheet", "name": sheet})
                    scope = sheet
                if btype in _FURNITURE:
                    if btype != "page_number":
                        headers_footers.append(
                            {"type": btype, "text": _clean(content).strip()}
                        )
                    continue
                if btype == "figure":
                    images.append({"description": _clean(content).strip() or "figure"})
                if btype == "table":
                    table_blocks.append((content, scope))
                body.append(_clean(content))

        if suffix == ".html":
            # Extend returns HTML input unconverted ("parsed as-is"); read
            # the structure that markup carries, as markdown_output already
            # does for HTML tables in any provider's output.
            body = [_html_to_markdown(b) for b in body]
        output = markdown_output("\n\n".join(body))
        structure = output["structure"]

        # Tables: rebuild cells from Extend's HTML so formulas and sheet
        # scopes survive (markdown_output's generic HTML reader drops them).
        tables, cells = [], []
        for idx, (html, scope) in enumerate(table_blocks):
            rows = _html_rows(html)
            cells += table_cells(rows, idx, scope)
            tables.append(
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
        if table_blocks and suffix in _SPREADSHEETS:
            # Extend splits a sheet into several tables but labels every
            # cell with its sheet coordinate (data-cell="A6" / "A6:D6").
            # Use those coordinates: one logical table per sheet, the same
            # identity the source-derived assertions use.
            cells = []
            sheets = list(dict.fromkeys(scope for _, scope in table_blocks))
            for html, scope in table_blocks:
                cells += _sheet_cells(html, sheets.index(scope), scope)
        if table_blocks:
            output["tables"] = tables
            structure["table_cells"] = cells

        if containers:
            structure["containers"] = containers
        if suffix in _SPREADSHEETS:
            output["metadata"]["sheet_names"] = [c["name"] for c in containers]

        output.update(
            {
                "track_changes": track_changes,
                "comments": [],  # not present in Extend's response
                "headers_footers": headers_footers,
                "footnotes": [],
                "speaker_notes": [],  # not present in Extend's response
                "text_boxes": [],
            }
        )
        if images:
            output["images"] = images
        return output
