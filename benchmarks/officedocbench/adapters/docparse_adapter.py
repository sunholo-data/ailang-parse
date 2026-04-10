"""AILANG Parse adapter for OfficeDocBench — reference implementation.

Runs AILANG Parse on a file and converts the output to the
OfficeDocBench adapter output schema. Uses batch mode (compile once)
and AILANG_NO_TRACE=1 for fair timing comparisons.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "metrics"))
from normalize import NormalizedElement, normalize_ailang

from .base_adapter import OfficeDocBenchAdapter


REPO_DIR = Path(__file__).parent.parent.parent.parent
OUTPUT_DIR = REPO_DIR / "docparse" / "data"


class DocParseAdapter(OfficeDocBenchAdapter):
    """Reference adapter using AILANG Parse."""

    def __init__(self):
        self._batch_cache: dict[str, dict] = {}

    def name(self) -> str:
        return "AILANG Parse"

    def version(self) -> str:
        return "0.3.0"

    def parse(self, filepath: Path) -> dict[str, Any]:
        """Run AILANG Parse on a single file. Uses batch cache if available."""
        basename = filepath.name
        if basename in self._batch_cache:
            return self._batch_cache.pop(basename)

        env = {**os.environ, "AILANG_NO_TRACE": "1"}
        result = subprocess.run(
            ["ailang", "run", "--entry", "main", "--caps", "IO,FS,Env",
             "--max-recursion-depth", "50000",
             "docparse/main.ail", str(filepath)],
            capture_output=True, text=True, cwd=str(REPO_DIR),
            timeout=120, env=env,
        )

        if result.returncode != 0:
            raise RuntimeError(f"AILANG Parse failed (exit {result.returncode}): {result.stderr[:200]}")

        output_json_path = OUTPUT_DIR / f"{basename}.json"
        if not output_json_path.exists():
            raise RuntimeError(f"No output file: {output_json_path}")

        with open(output_json_path) as f:
            raw = json.load(f)

        return self._convert(raw)

    def parse_batch(self, filepaths: list[Path]) -> dict[str, dict[str, Any]]:
        """Parse all files in one AILANG invocation (compile once).

        Returns {filename: converted_output} for each successfully parsed file.
        """
        if not filepaths:
            return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {**os.environ, "AILANG_NO_TRACE": "1", "DOCPARSE_OUTPUT_DIR": tmpdir}
            cmd = [
                "ailang", "run", "--batch", "--entry", "main",
                "--caps", "IO,FS,Env", "--max-recursion-depth", "50000",
                "docparse/main.ail",
            ] + [str(f) for f in filepaths]

            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(REPO_DIR), timeout=300, env=env,
            )

            outputs = {}
            for fp in filepaths:
                out_path = Path(tmpdir) / f"{fp.name}.json"
                if out_path.exists():
                    with open(out_path) as f:
                        raw = json.load(f)
                    outputs[fp.name] = self._convert(raw)

        self._batch_cache = outputs
        return outputs

    def supported_formats(self) -> set[str]:
        return {"docx", "pptx", "xlsx", "odt", "odp", "ods", "epub", "html", "csv", "tsv", "md"}

    def _convert(self, raw: dict) -> dict[str, Any]:
        """Convert AILANG Parse JSON to adapter output schema."""
        elements = normalize_ailang(raw)
        doc = raw.get("document", {})
        blocks = doc.get("blocks", [])

        text_elements = []
        headings = []
        tables = []
        track_changes = []
        comments = []
        headers_footers = []
        footnotes = []
        speaker_notes = []
        text_boxes = []
        images = []
        lists_out = []

        for el in elements:
            if el.type == "text":
                text_elements.append({"text": el.text, "style": el.metadata.get("source_type", "")})
            elif el.type == "heading":
                headings.append({"text": el.text, "level": el.level})
            elif el.type == "table":
                tables.append({
                    "row_count": el.metadata.get("row_count", 0),
                    "has_merged_cells": el.metadata.get("has_merge_info", False),
                    "cell_text": el.text,
                })
            elif el.type == "change":
                track_changes.append({
                    "type": el.metadata.get("change_type", ""),
                    "author": el.metadata.get("author", ""),
                    "text": el.text,
                })
            elif el.type == "header":
                # A header with section=textbox is a text box inside a header
                if el.metadata.get("section") == "textbox":
                    text_boxes.append({"text": el.text})
                else:
                    headers_footers.append({"type": "header", "text": el.text})
            elif el.type == "footer":
                # A footer with section=textbox is a text box inside a footer
                if el.metadata.get("section") == "textbox":
                    text_boxes.append({"text": el.text})
                else:
                    headers_footers.append({"type": "footer", "text": el.text})
            elif el.type == "image":
                images.append({"description": el.metadata.get("image_description", "")})
            elif el.type == "list_item":
                # List items get grouped below
                pass

            # Section-based features
            section = el.metadata.get("section")
            if section == "comment":
                author = ""
                m = re.match(r"\[([^\]]+)\]", el.text)
                if m:
                    author = m.group(1)
                comments.append({"author": author, "text": el.text})
            elif section == "textbox" and el.type == "text":
                text_boxes.append({"text": el.text})
            elif section == "notes":
                speaker_notes.append({"text": el.text})
            elif section in ("footnote", "endnote", "footnotes"):
                footnotes.append({"text": el.text})

        # Group list items from raw blocks
        lists_out = self._extract_lists(blocks)

        # Metadata
        meta = doc.get("metadata", {})
        sheet_names = self._extract_sheet_names(blocks)
        metadata = {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "created": meta.get("created", ""),
            "modified": meta.get("modified", ""),
            "sheet_names": sheet_names,
        }

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": track_changes,
            "comments": comments,
            "headers_footers": headers_footers,
            "footnotes": footnotes,
            "speaker_notes": speaker_notes,
            "text_boxes": text_boxes,
            "images": images,
            "lists": lists_out,
            "metadata": metadata,
        }

    def _extract_lists(self, blocks: list[dict]) -> list[dict]:
        """Extract list blocks from raw JSON."""
        result = []
        for block in blocks:
            if block.get("type") == "list":
                items = block.get("items", [])
                result.append({
                    "items": [str(i) if not isinstance(i, str) else i for i in items],
                    "ordered": block.get("ordered", False),
                })
            elif block.get("type") == "section":
                result.extend(self._extract_lists(block.get("blocks", [])))
        return result

    def _extract_sheet_names(self, blocks: list[dict]) -> list[str]:
        """Extract sheet names from section blocks."""
        names = []
        for block in blocks:
            if block.get("type") == "section":
                kind = block.get("kind", "")
                if kind.startswith("sheet:"):
                    names.append(kind.removeprefix("sheet:").strip())
                names.extend(self._extract_sheet_names(block.get("blocks", [])))
        return names
