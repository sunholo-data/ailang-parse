"""Raw OOXML adapter for OfficeDocBench.

No external dependencies — uses only Python stdlib (zipfile + xml.etree.ElementTree).

Opens .docx/.pptx/.xlsx files as ZIP archives and parses the underlying XML
directly. This is the most comprehensive extraction possible since it reads
the same OOXML structures that professional parsers use.

Extracts: body text, headings, tables (with merged cells), track changes,
comments, headers/footers, text boxes, images, footnotes, speaker notes,
metadata, sheet names, and lists.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter

# ── OOXML namespaces ───────────────────────────────────────────────
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "pr": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}

# Register all namespaces so ET.tostring doesn't mangle prefixes
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def _tag(ns: str, local: str) -> str:
    """Build a Clark-notation tag like {uri}local."""
    return f"{{{NS[ns]}}}{local}"


def _text_of(elem: ET.Element | None) -> str:
    """Get all text content under an element, recursively."""
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _read_xml(zf: zipfile.ZipFile, path: str) -> ET.Element | None:
    """Read and parse an XML entry from the ZIP, or return None."""
    try:
        return ET.fromstring(zf.read(path))
    except (KeyError, ET.ParseError):
        return None


class OOXMLAdapter(OfficeDocBenchAdapter):

    def name(self) -> str:
        return "Raw OOXML"

    def version(self) -> str:
        return "1.0.0-stdlib"

    def parse(self, filepath: Path) -> dict[str, Any]:
        ext = filepath.suffix.lower().lstrip(".")
        if ext == "docx":
            return self._parse_docx(filepath)
        elif ext == "pptx":
            return self._parse_pptx(filepath)
        elif ext == "xlsx":
            return self._parse_xlsx(filepath)
        else:
            raise ValueError(f"Unsupported format: {ext}")

    # ── DOCX ───────────────────────────────────────────────────────

    def _parse_docx(self, filepath: Path) -> dict[str, Any]:
        text_elements: list[dict[str, Any]] = []
        headings: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        track_changes: list[dict[str, Any]] = []
        comments: list[dict[str, Any]] = []
        headers_footers: list[dict[str, Any]] = []
        footnotes: list[dict[str, Any]] = []
        text_boxes: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []
        lists_out: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}

        with zipfile.ZipFile(filepath) as zf:
            # ── Metadata ──
            metadata = self._extract_metadata(zf)

            # ── Body text, headings, tables, track changes, images, text boxes ──
            doc = _read_xml(zf, "word/document.xml")
            if doc is not None:
                body = doc.find(_tag("w", "body"))
                if body is not None:
                    self._walk_docx_body(
                        body, text_elements, headings, tables,
                        track_changes, images, text_boxes, lists_out,
                    )

            # ── Comments ──
            comments_xml = _read_xml(zf, "word/comments.xml")
            if comments_xml is not None:
                for comment in comments_xml.findall(_tag("w", "comment")):
                    author = comment.get(_tag("w", "author"), "")
                    text = _text_of(comment)
                    if text:
                        comments.append({"author": author, "text": text})

            # ── Headers / Footers ──
            for entry in zf.namelist():
                if re.match(r"word/header\d+\.xml", entry):
                    hdr = _read_xml(zf, entry)
                    if hdr is not None:
                        text = _text_of(hdr)
                        if text:
                            headers_footers.append({"type": "header", "text": text})
                elif re.match(r"word/footer\d+\.xml", entry):
                    ftr = _read_xml(zf, entry)
                    if ftr is not None:
                        text = _text_of(ftr)
                        if text:
                            headers_footers.append({"type": "footer", "text": text})

            # ── Footnotes / Endnotes ──
            for fn_path in ("word/footnotes.xml", "word/endnotes.xml"):
                fn_xml = _read_xml(zf, fn_path)
                if fn_xml is not None:
                    tag = "footnote" if "footnote" in fn_path else "endnote"
                    for fn in fn_xml.findall(_tag("w", tag)):
                        fn_type = fn.get(_tag("w", "type"), "")
                        if fn_type in ("separator", "continuationSeparator"):
                            continue
                        text = _text_of(fn)
                        if text:
                            footnotes.append({"text": text})

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": track_changes,
            "comments": comments,
            "headers_footers": headers_footers,
            "footnotes": footnotes,
            "speaker_notes": [],
            "text_boxes": text_boxes,
            "images": images,
            "lists": lists_out,
            "metadata": metadata,
        }

    def _walk_docx_body(
        self,
        body: ET.Element,
        text_elements: list[dict],
        headings: list[dict],
        tables: list[dict],
        track_changes: list[dict],
        images: list[dict],
        text_boxes: list[dict],
        lists_out: list[dict],
    ) -> None:
        """Walk the w:body element extracting all content types."""
        for child in body:
            tag = child.tag

            if tag == _tag("w", "p"):
                self._process_paragraph(
                    child, text_elements, headings, track_changes,
                    images, text_boxes, lists_out,
                )

            elif tag == _tag("w", "tbl"):
                tables.append(self._process_table(child))

            # Track changes at block level
            elif tag == _tag("w", "ins"):
                author = child.get(_tag("w", "author"), "")
                text = _text_of(child)
                if text:
                    track_changes.append({"type": "insertion", "author": author, "text": text})

            elif tag == _tag("w", "del"):
                author = child.get(_tag("w", "author"), "")
                text = self._del_text(child)
                if text:
                    track_changes.append({"type": "deletion", "author": author, "text": text})

    def _process_paragraph(
        self,
        para: ET.Element,
        text_elements: list[dict],
        headings: list[dict],
        track_changes: list[dict],
        images: list[dict],
        text_boxes: list[dict],
        lists_out: list[dict],
    ) -> None:
        """Process a single w:p paragraph element."""
        # Check for heading style
        ppr = para.find(_tag("w", "pPr"))
        style_name = ""
        heading_level = 0
        is_list = False

        if ppr is not None:
            pstyle = ppr.find(_tag("w", "pStyle"))
            if pstyle is not None:
                style_name = pstyle.get(_tag("w", "val"), "")
                # Detect heading level from style name
                heading_match = re.match(r"[Hh]eading\s*(\d)", style_name)
                if heading_match:
                    heading_level = int(heading_match.group(1))
                elif style_name.startswith("Title"):
                    heading_level = 1

            # Detect outline level
            if not heading_level:
                outline_lvl = ppr.find(_tag("w", "outlineLvl"))
                if outline_lvl is not None:
                    try:
                        heading_level = int(outline_lvl.get(_tag("w", "val"), "0")) + 1
                    except ValueError:
                        pass

            # Detect list
            num_pr = ppr.find(_tag("w", "numPr"))
            if num_pr is not None:
                is_list = True

        # Extract text from runs
        text_parts = []
        for elem in para.iter():
            if elem.tag == _tag("w", "t"):
                text_parts.append(elem.text or "")
            elif elem.tag == _tag("w", "tab"):
                text_parts.append("\t")
            elif elem.tag == _tag("w", "br"):
                text_parts.append(" ")

        # Track changes within paragraph
        for ins in para.findall(".//" + _tag("w", "ins")):
            author = ins.get(_tag("w", "author"), "")
            ins_text = _text_of(ins)
            if ins_text:
                track_changes.append({"type": "insertion", "author": author, "text": ins_text})

        for deletion in para.findall(".//" + _tag("w", "del")):
            author = deletion.get(_tag("w", "author"), "")
            del_text = self._del_text(deletion)
            if del_text:
                track_changes.append({"type": "deletion", "author": author, "text": del_text})

        # Text boxes (w:txbxContent inside mc:AlternateContent or w:pict)
        for txbx in para.findall(".//" + _tag("wps", "txbx")):
            txbx_content = txbx.find(_tag("w", "txbxContent"))
            if txbx_content is not None:
                txbx_text = _text_of(txbx_content)
                if txbx_text:
                    text_boxes.append({"text": txbx_text})

        # Also check for VML text boxes
        for textbox in para.findall(".//" + _tag("v", "textbox")):
            txbx_content = textbox.find(_tag("w", "txbxContent"))
            if txbx_content is not None:
                txbx_text = _text_of(txbx_content)
                if txbx_text:
                    text_boxes.append({"text": txbx_text})

        # Images (w:drawing)
        for drawing in para.findall(".//" + _tag("w", "drawing")):
            # Look for docPr which has name/descr attributes
            for doc_pr in drawing.findall(".//" + _tag("wp", "docPr")):
                desc = doc_pr.get("descr", "") or doc_pr.get("name", "")
                images.append({"description": desc})

        # Also check for VML images (v:imagedata)
        for imagedata in para.findall(".//" + _tag("v", "imagedata")):
            images.append({"description": imagedata.get("title", "") or ""})

        text = "".join(text_parts).strip()
        if not text:
            return

        if heading_level:
            headings.append({"text": text, "level": min(heading_level, 6)})
        elif is_list:
            lists_out.append({"items": [text], "ordered": False})
        else:
            text_elements.append({"text": text, "style": style_name or "Normal"})

    def _process_table(self, tbl: ET.Element) -> dict[str, Any]:
        """Process a w:tbl table element."""
        row_count = 0
        cell_texts = []
        has_merged = False

        for tr in tbl.findall(_tag("w", "tr")):
            row_count += 1
            for tc in tr.findall(_tag("w", "tc")):
                # Check for merged cells
                tc_pr = tc.find(_tag("w", "tcPr"))
                if tc_pr is not None:
                    grid_span = tc_pr.find(_tag("w", "gridSpan"))
                    if grid_span is not None:
                        span = int(grid_span.get(_tag("w", "val"), "1"))
                        if span > 1:
                            has_merged = True
                    v_merge = tc_pr.find(_tag("w", "vMerge"))
                    if v_merge is not None:
                        has_merged = True

                cell_text = _text_of(tc)
                if cell_text:
                    cell_texts.append(cell_text)

        return {
            "row_count": row_count,
            "has_merged_cells": has_merged,
            "cell_text": " ".join(cell_texts),
        }

    def _del_text(self, elem: ET.Element) -> str:
        """Extract deleted text from w:del elements (uses w:delText, not w:t)."""
        parts = []
        for dt in elem.findall(".//" + _tag("w", "delText")):
            if dt.text:
                parts.append(dt.text)
        return " ".join(parts)

    # ── PPTX ───────────────────────────────────────────────────────

    def _parse_pptx(self, filepath: Path) -> dict[str, Any]:
        text_elements: list[dict[str, Any]] = []
        headings: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []
        speaker_notes: list[dict[str, Any]] = []
        lists_out: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}

        with zipfile.ZipFile(filepath) as zf:
            metadata = self._extract_metadata(zf)

            # Find slide files
            slide_files = sorted(
                e for e in zf.namelist()
                if re.match(r"ppt/slides/slide\d+\.xml", e)
            )

            for slide_path in slide_files:
                slide = _read_xml(zf, slide_path)
                if slide is None:
                    continue

                # Extract text from shapes
                for sp in slide.findall(".//" + _tag("p", "sp")):
                    self._process_pptx_shape(sp, text_elements, headings, lists_out)

                # Tables
                for tbl in slide.findall(".//" + _tag("a", "tbl")):
                    tables.append(self._process_pptx_table(tbl))

                # Images (p:pic)
                for pic in slide.findall(".//" + _tag("p", "pic")):
                    nv_pr = pic.find(".//" + _tag("p", "cNvPr"))
                    if nv_pr is not None:
                        desc = nv_pr.get("descr", "") or nv_pr.get("name", "")
                        images.append({"description": desc})

            # Speaker notes
            notes_files = sorted(
                e for e in zf.namelist()
                if re.match(r"ppt/notesSlides/notesSlide\d+\.xml", e)
            )
            for notes_path in notes_files:
                notes = _read_xml(zf, notes_path)
                if notes is None:
                    continue
                # Get all text runs, skip placeholder numbers
                note_texts = []
                for txbody in notes.findall(".//" + _tag("p", "txBody")):
                    for p_elem in txbody.findall(_tag("a", "p")):
                        p_text = ""
                        for r_elem in p_elem.findall(_tag("a", "r")):
                            t_elem = r_elem.find(_tag("a", "t"))
                            if t_elem is not None and t_elem.text:
                                p_text += t_elem.text
                        if p_text.strip() and not re.match(r"^\d+$", p_text.strip()):
                            note_texts.append(p_text.strip())
                if note_texts:
                    speaker_notes.append({"text": " ".join(note_texts)})

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": [],
            "comments": [],
            "headers_footers": [],
            "footnotes": [],
            "speaker_notes": speaker_notes,
            "text_boxes": [],
            "images": images,
            "lists": lists_out,
            "metadata": metadata,
        }

    def _process_pptx_shape(
        self,
        sp: ET.Element,
        text_elements: list[dict],
        headings: list[dict],
        lists_out: list[dict],
    ) -> None:
        """Process a PPTX shape element to extract text."""
        # Check if this is a title placeholder
        is_title = False
        nv_sp_pr = sp.find(_tag("p", "nvSpPr"))
        if nv_sp_pr is not None:
            nv_pr = nv_sp_pr.find(_tag("p", "nvPr"))
            if nv_pr is not None:
                ph = nv_pr.find(_tag("p", "ph"))
                if ph is not None:
                    ph_type = ph.get("type", "")
                    if ph_type in ("title", "ctrTitle"):
                        is_title = True

        tx_body = sp.find(_tag("p", "txBody"))
        if tx_body is None:
            return

        for p_elem in tx_body.findall(_tag("a", "p")):
            text_parts = []
            for r_elem in p_elem.findall(_tag("a", "r")):
                t_elem = r_elem.find(_tag("a", "t"))
                if t_elem is not None and t_elem.text:
                    text_parts.append(t_elem.text)

            text = "".join(text_parts).strip()
            if not text:
                continue

            if is_title:
                headings.append({"text": text, "level": 1})
            else:
                # Check for bullet/list
                ppr = p_elem.find(_tag("a", "pPr"))
                if ppr is not None and ppr.find(_tag("a", "buChar")) is not None:
                    lists_out.append({"items": [text], "ordered": False})
                elif ppr is not None and ppr.find(_tag("a", "buAutoNum")) is not None:
                    lists_out.append({"items": [text], "ordered": True})
                else:
                    text_elements.append({"text": text, "style": "paragraph"})

    def _process_pptx_table(self, tbl: ET.Element) -> dict[str, Any]:
        """Process a PPTX a:tbl table element."""
        row_count = 0
        cell_texts = []
        has_merged = False

        for tr in tbl.findall(_tag("a", "tr")):
            row_count += 1
            for tc in tr.findall(_tag("a", "tc")):
                grid_span = tc.get("gridSpan")
                row_span = tc.get("rowSpan")
                if grid_span and int(grid_span) > 1:
                    has_merged = True
                if row_span and int(row_span) > 1:
                    has_merged = True

                cell_text = _text_of(tc)
                if cell_text:
                    cell_texts.append(cell_text)

        return {
            "row_count": row_count,
            "has_merged_cells": has_merged,
            "cell_text": " ".join(cell_texts),
        }

    # ── XLSX ───────────────────────────────────────────────────────

    def _parse_xlsx(self, filepath: Path) -> dict[str, Any]:
        tables: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}

        with zipfile.ZipFile(filepath) as zf:
            metadata = self._extract_metadata(zf)

            # Shared strings table
            shared_strings: list[str] = []
            sst = _read_xml(zf, "xl/sharedStrings.xml")
            if sst is not None:
                for si in sst.findall(_tag("ss", "si")):
                    shared_strings.append(_text_of(si))

            # Sheet names from workbook
            sheet_names: list[str] = []
            wb = _read_xml(zf, "xl/workbook.xml")
            if wb is not None:
                sheets_elem = wb.find(_tag("ss", "sheets"))
                if sheets_elem is not None:
                    for sheet in sheets_elem.findall(_tag("ss", "sheet")):
                        name = sheet.get("name", "")
                        if name:
                            sheet_names.append(name)
            if sheet_names:
                metadata["sheet_names"] = sheet_names

            # Parse each worksheet
            sheet_files = sorted(
                e for e in zf.namelist()
                if re.match(r"xl/worksheets/sheet\d+\.xml", e)
            )

            for sheet_path in sheet_files:
                sheet = _read_xml(zf, sheet_path)
                if sheet is None:
                    continue

                # Check for merged cells
                has_merged = False
                merge_cells = sheet.find(_tag("ss", "mergeCells"))
                if merge_cells is not None and len(merge_cells) > 0:
                    has_merged = True

                # Extract cell data
                row_count = 0
                cell_texts = []

                sheet_data = sheet.find(_tag("ss", "sheetData"))
                if sheet_data is not None:
                    for row in sheet_data.findall(_tag("ss", "row")):
                        row_count += 1
                        for cell in row.findall(_tag("ss", "c")):
                            cell_type = cell.get("t", "")
                            v_elem = cell.find(_tag("ss", "v"))
                            if v_elem is not None and v_elem.text:
                                if cell_type == "s":
                                    # Shared string reference
                                    try:
                                        idx = int(v_elem.text)
                                        if idx < len(shared_strings):
                                            cell_texts.append(shared_strings[idx])
                                    except ValueError:
                                        pass
                                else:
                                    cell_texts.append(v_elem.text)
                            # Inline strings
                            is_elem = cell.find(_tag("ss", "is"))
                            if is_elem is not None:
                                cell_texts.append(_text_of(is_elem))

                if row_count > 0:
                    tables.append({
                        "row_count": row_count,
                        "has_merged_cells": has_merged,
                        "cell_text": " ".join(cell_texts),
                    })

        return {
            "text_elements": [],
            "headings": [],
            "tables": tables,
            "track_changes": [],
            "comments": [],
            "headers_footers": [],
            "footnotes": [],
            "speaker_notes": [],
            "text_boxes": [],
            "images": [],
            "lists": [],
            "metadata": metadata,
        }

    # ── Shared: Metadata ──────────────────────────────────────────

    def _extract_metadata(self, zf: zipfile.ZipFile) -> dict[str, Any]:
        """Extract metadata from docProps/core.xml."""
        metadata: dict[str, Any] = {}
        core = _read_xml(zf, "docProps/core.xml")
        if core is None:
            return metadata

        # Title
        title = core.find(_tag("dc", "title"))
        if title is not None and title.text:
            metadata["title"] = title.text.strip()

        # Author
        creator = core.find(_tag("dc", "creator"))
        if creator is not None and creator.text:
            metadata["author"] = creator.text.strip()

        # Created
        created = core.find(_tag("dcterms", "created"))
        if created is not None and created.text:
            metadata["created"] = created.text.strip()

        # Modified
        modified = core.find(_tag("dcterms", "modified"))
        if modified is not None and modified.text:
            metadata["modified"] = modified.text.strip()

        return metadata

    def supported_formats(self) -> set[str]:
        return {"docx", "pptx", "xlsx"}
