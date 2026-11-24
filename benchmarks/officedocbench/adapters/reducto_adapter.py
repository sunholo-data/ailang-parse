"""Reducto (reducto.ai) Parse adapter for OfficeDocBench.

Requires: REDUCTO_API_KEY environment variable (inject it from your secret
manager, e.g. ``op run --env-file=... --``). Uses the REST API directly
through httpx: POST /upload -> POST /parse (V3 config).

Configured at Reducto's strongest documented settings, so the comparison
cannot be dismissed as a default-settings run:

- ``settings.model: r-1`` (the flagship model; the API default is still
  ``legacy`` until December 2026)
- tables as HTML (Reducto's docs: "HTML handles merged cells and complex
  headers better than Markdown")
- ``formatting.include``: change tracking, comments, hyperlinks
- ``spreadsheet.clustering: accurate`` (the 5x-cost LLM table detection),
  formulas and cell colours, large tables kept whole
- ``extract_document_properties`` for author and dates
- chunking disabled: one chunk holding every block in reading order

Mapping reads only Reducto's response:

- Block types are Reducto's own: ``Title`` / ``Section Header`` become
  headings, ``List Item`` becomes a list entry, ``Header`` / ``Footer``
  page furniture, ``Comment`` a comment (author, date, anchored text,
  reply id are in ``block.extra``), ``Figure`` an image.
- Tracked changes are only what Reducto marks as such
  (``<change>`` with ``<s>`` deleted / ``<u>`` inserted text). A bare
  ``<u>`` outside ``<change>`` is underline formatting, not an insertion.
- PPTX slides are Reducto's pages (``bbox.page``), named by the slide's
  first Title block. Spreadsheet sheets use the shared Markdown-provider
  rule (top-level headings in reading order are sheet names).
- Reducto gives no sheet cell coordinates, so spreadsheet cells are scored
  at table-local positions, as for every provider without native ones.

Raw responses: set REDUCTO_RAW_DIR to keep every parse response. With
REDUCTO_REUSE_RAW=1 as well, a stored response for the same file bytes is
remapped instead of re-parsed (explicit opt-in, never a hidden fallback),
so mapping fixes do not spend credits.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter
from .structure import add_sheet_scopes, cell, markdown_output, table_cells

API = os.environ.get("REDUCTO_API_BASE", "https://platform.reducto.ai")
TIMEOUT_SECONDS = 600

CONFIG: dict[str, Any] = {
    "settings": {"model": "r-1", "extract_document_properties": True},
    "formatting": {
        "table_output_format": "html",
        "include": ["change_tracking", "comments", "hyperlinks"],
    },
    "retrieval": {"chunking": {"chunk_mode": "disabled"}},
    "spreadsheet": {
        "clustering": "accurate",
        "split_large_tables": {"enabled": False},
        "include": ["cell_colors", "formula"],
    },
}

_SPREADSHEETS = {".xlsx", ".ods", ".csv", ".tsv"}
_CHANGE = re.compile(r"<change>(.*?)</change>", re.DOTALL)
_CHANGE_PART = re.compile(r"<(s|u)>(.*?)</\1>", re.DOTALL)
_TAGS = re.compile(r"</?(change|u|s|mark|b|i|sup|sub)>")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_RUN_FLAGS = {
    "b": "bold",
    "strong": "bold",
    "i": "italic",
    "em": "italic",
    "u": "underline",
    "s": "strike",
    "del": "strike",
    "code": "code",
}
_BULLET = re.compile(r"^\s*[•◦▪▫‣⁃●○■□–\-*]\s+")
_ORDERED = re.compile(r"^\s*(\d+|[a-zA-Z]|[ivxlcIVXLC]+)[.)]\s+")
_STYLE_COLOUR = re.compile(
    r"(?:^|;)\s*(background-color|color)\s*:\s*(#[0-9A-Fa-f]{6})"
)


def _clean(text: str) -> str:
    """Drop Reducto's inline change/format markup, keeping the text."""
    return _TAGS.sub("", text or "")


def _html_runs(content: str) -> list[dict[str, Any]]:
    """Formatting runs from Reducto's inline HTML (<b>, <i>, <u>, <s>, ...).

    Every text node becomes a run with explicit flags, as markdown_output
    does for Markdown emphasis. Text inside <change> is a tracked change by
    Reducto's own markup, so it is not reported as formatting.
    Markdown links keep only their text.
    """
    from bs4 import BeautifulSoup, NavigableString

    runs = []
    soup = BeautifulSoup(_MD_LINK.sub(r"\1", content or ""), "html.parser")
    for node in soup.find_all(string=True):
        if not isinstance(node, NavigableString) or not node.strip():
            continue
        names = [a.name for a in node.parents if a.name]
        if "change" in names:
            continue
        run: dict[str, Any] = {
            "text": re.sub(r"\s+", " ", str(node)).strip(),
            "bold": False,
            "italic": False,
            "underline": False,
            "strike": False,
            "code": False,
        }
        for name in names:
            if name in _RUN_FLAGS:
                run[_RUN_FLAGS[name]] = True
            elif name in ("sup", "sub"):
                run["vertAlign"] = "superscript" if name == "sup" else "subscript"
        runs.append(run)
    return runs


def _list_line(content: str, widths: list[int]) -> str:
    """A Markdown list line for a Reducto List Item, nested by its tabs.

    Reducto marks nesting with leading tab characters ("\\t\\t1. ..."). The
    indent is the sum of the enclosing markers' widths, which is what
    CommonMark needs to nest the item; ``widths`` tracks the open levels.
    """
    raw = _clean(content)
    level = len(raw) - len(raw.lstrip("\t"))
    text = raw.strip()
    if _ORDERED.match(text):
        marker, rest = text.split(None, 1) if " " in text else (text, "")
    else:
        marker, rest = "-", _BULLET.sub("", text)
    del widths[level:]
    while len(widths) < level:
        widths.append(widths[-1] if widths else 2)
    indent = " " * sum(widths)
    widths.append(len(marker) + 1)
    return indent + marker + " " + rest.replace("\n", " ")


def _utc(value: str | None) -> str:
    """ISO timestamp with a zero offset written as ``Z`` (same instant)."""
    if not value:
        return ""
    return re.sub(r"\+00:00$", "Z", value)


def _html_rows(markup: str) -> list[list[dict[str, Any]]]:
    """Logical grid of a Reducto HTML table, keeping formula and colours.

    Same span expansion as structure.html_rows; ``data-formula`` and
    inline ``style`` colours are the only additions, read from the markup.
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
                "text": _MD_LINK.sub(r"\1", _clean(node.get_text(" ", strip=True))),
                "colSpan": cs,
            }
            if rs > 1:
                c["rowSpan"] = rs
            if node.get("data-formula"):
                c["formula"] = node["data-formula"]
            for prop, value in _STYLE_COLOUR.findall(node.get("style") or ""):
                c["fill" if prop == "background-color" else "color"] = value.lower()
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


class ReductoAdapter(OfficeDocBenchAdapter):
    _api_version: str | None = None

    def name(self) -> str:
        return "Reducto"

    def version(self) -> str:
        return f"{CONFIG['settings']['model']}@{self._server_version()}"

    def _server_version(self) -> str:
        """Reducto's own build string from GET /version, read once."""
        if self._api_version is None:
            pinned = os.environ.get("REDUCTO_API_VERSION")
            if pinned:
                self._api_version = pinned
            else:
                import httpx

                key = os.environ.get("REDUCTO_API_KEY", "")
                try:
                    got = httpx.get(
                        f"{API}/version",
                        timeout=30,
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    got.raise_for_status()
                    self._api_version = str(got.json())
                except (httpx.HTTPError, ValueError):
                    self._api_version = "unknown"
        return self._api_version

    def provider_config(self) -> dict[str, Any]:
        """Recorded in results provenance: the exact request config.

        ``raw_reuse`` marks a remap of stored responses, whose per-file
        timings are mapping time, not Reducto's parse latency.
        """
        reuse = os.environ.get("REDUCTO_REUSE_RAW", "").lower() in ("1", "true", "yes")
        return {"request": CONFIG, "raw_reuse": reuse}

    def supported_formats(self) -> set[str]:
        # Probed 2026-11-18: DOCX, PPTX, XLSX and CSV are documented input
        # types; HTML, Markdown and TSV are not in the docs' list but parse
        # (billed as native pages). ODT, ODS, ODP and EPUB are refused at
        # parse with HTTP 415 DOCUMENT_CORRUPT on valid files, so they are
        # declared unsupported rather than recorded as parse errors.
        return {"docx", "pptx", "xlsx", "csv", "tsv", "html", "md"}

    # ------------------------------------------------------------- request

    def parse(self, filepath: Path) -> dict[str, Any]:
        return self.convert_json(self._run(filepath), filepath)

    def _raw_path(self, filepath: Path) -> Path | None:
        raw_dir = os.environ.get("REDUCTO_RAW_DIR")
        if not raw_dir:
            return None
        digest = hashlib.sha256(filepath.read_bytes()).hexdigest()[:16]
        return Path(raw_dir) / f"{filepath.name}.{digest}.json"

    def _run(self, filepath: Path) -> dict[str, Any]:
        raw_path = self._raw_path(filepath)
        reuse = os.environ.get("REDUCTO_REUSE_RAW", "").lower() in ("1", "true", "yes")
        if raw_path and reuse and raw_path.exists():
            return json.loads(raw_path.read_text())

        key = os.environ.get("REDUCTO_API_KEY")
        if not key:
            raise RuntimeError("REDUCTO_API_KEY not set")
        import httpx

        headers = {"Authorization": f"Bearer {key}"}
        with httpx.Client(timeout=TIMEOUT_SECONDS, headers=headers) as client:
            up = client.post(
                f"{API}/upload",
                files={"file": (filepath.name, filepath.read_bytes())},
            )
            if up.status_code >= 400:
                return self._failed(raw_path, f"upload HTTP {up.status_code}", up.text)
            got = client.post(
                f"{API}/parse", json={"input": up.json()["file_id"], **CONFIG}
            )
            if got.status_code >= 400:
                return self._failed(raw_path, f"parse HTTP {got.status_code}", got.text)
            run = got.json()
            result = run.get("result") or {}
            if result.get("type") == "url":
                # Responses over ~6MB come back as a presigned URL.
                chunks = httpx.get(result["url"], timeout=TIMEOUT_SECONDS)
                chunks.raise_for_status()
                body = chunks.json()
                run["result"] = {
                    "type": "full",
                    "chunks": body.get("chunks", body)
                    if isinstance(body, dict)
                    else body,
                    "fetched_from_url": True,
                }

        if raw_path:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps(run, indent=1))
        return run

    @staticmethod
    def _failed(raw_path: Path | None, reason: str, body: str) -> dict[str, Any]:
        """A request the API refused, kept so a remap reproduces it."""
        run = {"failed": True, "failureReason": reason, "failureMessage": body[:300]}
        if raw_path:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps(run, indent=1))
        return run

    # ------------------------------------------------------------- mapping

    def convert_json(self, run: dict[str, Any], filepath: Path) -> dict[str, Any]:
        """Map an existing parse response; no upload or parsing request."""
        if run.get("failed"):
            raise RuntimeError(
                f"Reducto {run.get('failureReason')}: {run.get('failureMessage')}"
            )
        chunks = (run.get("result") or {}).get("chunks") or []
        # A completed parse with no blocks is an empty answer (a blank deck),
        # not a failure; the runner still refuses empty output unless the
        # fixture's truth allows it (allow_empty_output).
        blocks = [b for ch in chunks for b in ch.get("blocks") or []]

        suffix = filepath.suffix.lower()
        body: list[str] = []
        headers_footers: list[dict[str, str]] = []
        track_changes: list[dict[str, str]] = []
        comments: list[dict[str, Any]] = []
        images: list[dict[str, str]] = []
        table_blocks: list[tuple[str, str]] = []  # (html, scope)
        containers: list[dict[str, str]] = []
        runs: list[dict[str, Any]] = []
        links: list[dict[str, str]] = []
        widths: list[int] = []
        slide_names: dict[int, str] = {}

        if suffix == ".pptx":
            for b in blocks:
                page = (b.get("bbox") or {}).get("page")
                if b.get("type") == "Title" and page not in slide_names:
                    slide_names[page] = _clean(b.get("content")).strip()
            pages = sorted({(b.get("bbox") or {}).get("page") for b in blocks} - {None})
            containers = [
                {"kind": "slide", "name": slide_names.get(p, "")} for p in pages
            ]

        for b in blocks:
            btype = b.get("type", "")
            content = b.get("content") or ""
            extra = b.get("extra") or {}
            page = (b.get("bbox") or {}).get("page")
            scope = slide_names.get(page, "") if suffix == ".pptx" else ""

            for change in _CHANGE.findall(content):
                for tag, text in _CHANGE_PART.findall(change):
                    track_changes.append(
                        {
                            "type": "delete" if tag == "s" else "insert",
                            "author": "",
                            "text": _clean(text).strip(),
                        }
                    )
            if btype != "List Item":
                widths = []

            if btype in ("Header", "Footer"):
                headers_footers.append(
                    {"type": btype.lower(), "text": _clean(content).strip()}
                )
                continue
            if btype == "Page Number":
                continue
            if btype == "Comment":
                anchor = extra.get("anchored_text") or ""
                comments.append(
                    {
                        "author": extra.get("author") or "",
                        "text": _clean(content).strip(),
                        "annotated_text": anchor,
                        "anchored": bool(anchor),
                        "resolved": bool(extra.get("resolved")),
                        "parent_id": extra.get("reply_to_comment_id") or "",
                        "date": extra.get("date") or "",
                        "scope": scope,
                    }
                )
                continue
            runs += _html_runs(content)
            if btype == "Figure":
                images.append({"description": _clean(content).strip() or "figure"})
            if btype == "Table":
                # markdown_output does not read Markdown inside HTML cells.
                for text, url in _MD_LINK.findall(content):
                    links.append({"text": text, "url": url})
                table_blocks.append((content, scope))
                body.append(content)
                continue
            if btype == "Title":
                body.append("# " + _clean(content).strip().lstrip("# "))
                continue
            if btype == "Section Header":
                text = _clean(content).strip()
                body.append(text if text.startswith("#") else "## " + text)
                continue
            if btype == "List Item":
                body.append(_list_line(content, widths))
                continue
            body.append(_clean(content))

        output = markdown_output("\n\n".join(body))
        structure = output["structure"]

        # Tables: rebuild cells from Reducto's HTML so formulas, colours
        # and slide scopes survive.
        tables, cells = [], []
        for idx, (html, scope) in enumerate(table_blocks):
            rows = _html_rows(html)
            cells += table_cells(rows, idx, scope)
            tables.append(
                {
                    "rows": rows,
                    "row_count": max(len(rows) - 1, 0),
                    "has_merged_cells": any(
                        cell(c).get("colSpan", 1) > 1
                        or cell(c).get("rowSpan", 1) > 1
                        or cell(c).get("merged")
                        for r in rows
                        for c in r
                    ),
                    "cell_text": " ".join(cell(c)["text"] for r in rows for c in r),
                }
            )
        if table_blocks:
            output["tables"] = tables
            structure["table_cells"] = cells
        # Reducto writes emphasis as inline HTML, which markdown_output
        # cannot attribute; its runs are replaced by the HTML-derived ones.
        structure["runs"] = runs
        if links:
            structure["hyperlinks"] = structure.get("hyperlinks", []) + links
            output["hyperlinks"] = structure["hyperlinks"]

        if comments:
            structure["comment_anchors"] = [
                {
                    k: c[k]
                    for k in (
                        "text",
                        "author",
                        "annotated_text",
                        "anchored",
                        "parent_id",
                        "resolved",
                        "scope",
                    )
                }
                for c in comments
            ]
        if containers:
            structure["containers"] = containers

        props = run.get("document_properties") or {}
        output["metadata"] = {
            "title": props.get("title") or "",
            "author": props.get("author") or "",
            "created": _utc(props.get("created_at")),
            "modified": _utc(props.get("modified_at")),
        }
        if suffix in _SPREADSHEETS:
            add_sheet_scopes(output)

        output.update(
            {
                "track_changes": track_changes,
                "comments": comments,
                "headers_footers": headers_footers,
                "footnotes": [],
                "speaker_notes": [],  # not present in Reducto's response
                "text_boxes": [],
            }
        )
        if images:
            output["images"] = images
        return output
