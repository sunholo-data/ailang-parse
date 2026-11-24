"""LlamaParse adapter for OfficeDocBench.

Requires: uv pip install llama-parse
Requires: LLAMA_CLOUD_API_KEY environment variable

Driving LlamaParse the way its own docs recommend for structure-heavy docs:
- premium_mode for the best model
- result_type="json" + walking the per-page item tree (richer than the
  markdown result, which the previous version of this adapter was regexing)
- output_tables_as_HTML for real merged-cell information
- extract_charts, save_images for image scoring
- hide_headers/hide_footers explicitly false to keep page furniture
- a parsing_instruction to nudge the model toward structural extraction

Raw responses: set LLAMAPARSE_RAW_DIR to keep every file's raw answer (the
JSON job results, or the Markdown documents of the fallback, or the
failure). With LLAMAPARSE_REUSE_RAW=1 as well, a stored answer for the same
file bytes is remapped instead of re-requested (explicit opt-in, never a
hidden fallback; recorded as raw_reuse in provenance), so one paid run can
be remapped after mapping fixes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import warnings
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter
from .structure import attach_formatting, markdown_output

# llama-parse 0.6.x prints a DeprecationWarning on import recommending the
# new unified SDK; the SDK still works fine and OfficeDocBench is pinned to
# this version intentionally for reproducibility.
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"llama_parse.*")


class LlamaParseAdapter(OfficeDocBenchAdapter):
    def name(self) -> str:
        return "LlamaParse"

    def version(self) -> str:
        try:
            from importlib.metadata import version as pkg_version

            return pkg_version("llama-parse")
        except Exception:
            return "unknown"

    @staticmethod
    def _premium() -> bool:
        # Premium mode is 15× the standard credit cost — opt-in only.
        # Set LLAMAPARSE_PREMIUM=1 in the environment for "publication" runs;
        # default-off keeps day-to-day benchmark refreshes affordable.
        return os.environ.get("LLAMAPARSE_PREMIUM", "").lower() in ("1", "true", "yes")

    @staticmethod
    def _reuse() -> bool:
        return os.environ.get("LLAMAPARSE_REUSE_RAW", "").lower() in ("1", "true", "yes")

    def provider_config(self) -> dict[str, Any]:
        """Recorded in results provenance.

        ``raw_reuse`` marks a remap of stored responses, whose per-file
        timings are mapping time, not LlamaParse's parse latency.
        """
        return {"premium_mode": self._premium(), "raw_reuse": self._reuse()}

    def _parser(self):
        from llama_parse import LlamaParse

        return LlamaParse(
            result_type="markdown",
            premium_mode=self._premium(),
            output_tables_as_HTML=True,
            extract_charts=True,
            adaptive_long_table=True,
            save_images=True,
            hide_headers=False,
            hide_footers=False,
            user_prompt=(
                "Preserve all structural elements: headings with their levels, "
                "tables with merged cells (use HTML rowspan/colspan), headers, "
                "footers, footnotes, list nesting, and image captions."
            ),
        )

    def parse(self, filepath: Path) -> dict[str, Any]:
        return self.convert_raw(self._run(filepath), filepath)

    def _raw_path(self, filepath: Path) -> Path | None:
        raw_dir = os.environ.get("LLAMAPARSE_RAW_DIR")
        if not raw_dir:
            return None
        digest = hashlib.sha256(filepath.read_bytes()).hexdigest()[:16]
        return Path(raw_dir) / f"{filepath.name}.{digest}.json"

    def _run(self, filepath: Path) -> dict[str, Any]:
        """The provider's raw answer for a file: stored, or requested now.

        LLAMAPARSE_RAW_DIR keeps every answer (failures too), keyed by the
        file's bytes. With LLAMAPARSE_REUSE_RAW=1 a stored answer is
        remapped instead of re-requested (explicit opt-in, never a hidden
        fallback), so mapping fixes do not spend credits.
        """
        raw_path = self._raw_path(filepath)
        if raw_path and self._reuse() and raw_path.exists():
            return json.loads(raw_path.read_text())

        if not os.environ.get("LLAMA_CLOUD_API_KEY"):
            raise RuntimeError("LLAMA_CLOUD_API_KEY not set")
        try:
            parser = self._parser()
        except ImportError:
            raise RuntimeError("llama-parse not installed: uv pip install llama-parse")

        # Per-page JSON is richer than the flattened markdown — it carries
        # typed items (heading/text/table/list/image) plus image and chart
        # metadata. Fall back to markdown if the JSON endpoint is unavailable
        # for some file types.
        json_result = None
        try:
            json_result = parser.get_json_result(str(filepath))
        except Exception:
            json_result = None

        run: dict[str, Any]
        if not json_result or (isinstance(json_result, list) and not any(json_result)):
            try:
                documents = parser.load_data(str(filepath))
            except Exception as exc:
                run = {"failed": True, "failureMessage": str(exc)[:300]}
            else:
                run = {
                    "json_result": None,
                    "documents": [
                        doc.text if hasattr(doc, "text") else str(doc)
                        for doc in documents or []
                    ],
                }
        else:
            run = {"json_result": json_result}

        if raw_path:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps(run, indent=1))
        return run

    def convert_raw(self, run: dict[str, Any], filepath: Path) -> dict[str, Any]:
        """Map a stored or fresh raw answer; no parsing request."""
        if run.get("failed"):
            raise RuntimeError(f"LlamaParse failed: {run.get('failureMessage')}")
        if run.get("json_result"):
            return self.convert_json(run["json_result"], filepath)
        # Empty/missing JSON and no Markdown documents is a soft failure
        # (e.g. credit exhaustion where the SDK swallows the API error and
        # returns []). Treat that as a hard error so the eval records ERROR
        # rather than silently scoring the file with empty data.
        if not run.get("documents"):
            raise RuntimeError(
                "LlamaParse returned no content (likely credit exhaustion or job failure)"
            )
        return markdown_output("\n\n".join(run["documents"]))

    def convert_json(self, json_result, filepath):
        """Map an existing provider response; no upload or parsing request."""
        jobs = json_result if isinstance(json_result, list) else [json_result]
        for job in jobs:
            if job.get("error"):
                raise RuntimeError(str(job["error"]))
        output = self._from_json(json_result)
        markdown = "\n\n".join(
            page.get("md", "") for job in jobs for page in job.get("pages", [])
        )
        rich = markdown_output(markdown)
        output["structure"] = rich["structure"]
        attach_formatting(output["text_elements"], rich["structure"]["runs"])
        output["hyperlinks"] = rich["hyperlinks"]
        if rich["tables"]:
            output["tables"] = rich["tables"]
        pages = [page for job in jobs for page in job.get("pages", [])]
        if filepath.suffix.lower() in (".xlsx", ".pptx"):
            kind = "sheet" if filepath.suffix.lower() == ".xlsx" else "slide"
            structure = output["structure"]
            structure["containers"], structure["table_cells"], structure["notes"] = (
                [],
                [],
                [],
            )
            table_offset = 0
            for page in pages:
                title_item = next(
                    (
                        item
                        for item in page.get("items", [])
                        if item.get("type") == "heading"
                    ),
                    {},
                )
                title = (
                    (title_item.get("value") or title_item.get("md") or "")
                    .lstrip("# ")
                    .strip()
                )
                structure["containers"].append({"kind": kind, "name": title})
                mapped = markdown_output(page.get("md") or "")
                for c in mapped["structure"]["table_cells"]:
                    c["table"] += table_offset
                    c["scope"] = title
                    structure["table_cells"].append(c)
                table_offset += len(mapped["tables"])
                notes = page.get("slideSpeakerNotes") or ""
                if isinstance(notes, str) and notes.strip():
                    structure["notes"].append({"scope": title, "text": notes})
            if kind == "sheet":
                output["metadata"]["sheet_names"] = [
                    c["name"] for c in structure["containers"]
                ]
            output["speaker_notes"] = [{"text": n["text"]} for n in structure["notes"]]
        if rich["lists"]:
            output["lists"] = rich["lists"]
        return output

    # ------------------------------------------------------------------ JSON

    def _from_json(self, json_result: Any) -> dict[str, Any]:
        text_elements: list[dict[str, Any]] = []
        headings: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        lists_out: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []
        headers_footers: list[dict[str, Any]] = []

        # get_json_result returns a list of job results; each has "pages"
        results = json_result if isinstance(json_result, list) else [json_result]

        for job in results:
            pages = job.get("pages", []) if isinstance(job, dict) else []
            for page in pages:
                # Per-page header/footer often surface as items with type
                # "header"/"footer" when hide_headers=False.
                for item in page.get("items", []) or []:
                    itype = item.get("type", "")
                    md = item.get("md") or item.get("value") or ""
                    if itype == "heading":
                        headings.append(
                            {
                                "text": (item.get("value") or md).strip(),
                                "level": int(item.get("lvl", 1) or 1),
                            }
                        )
                    elif itype == "table":
                        rows = item.get("rows") or []
                        cell_text_parts: list[str] = []
                        has_merged = False
                        for row in rows:
                            for cell in row or []:
                                if isinstance(cell, dict):
                                    cell_text_parts.append(str(cell.get("value", "")))
                                    if (
                                        cell.get("rowspan", 1) > 1
                                        or cell.get("colspan", 1) > 1
                                    ):
                                        has_merged = True
                                else:
                                    cell_text_parts.append(str(cell))
                        # Fall back to parsing the HTML md if rows is empty
                        if not cell_text_parts and md:
                            html = md
                            if "rowspan" in html or "colspan" in html:
                                has_merged = True
                            cell_text_parts.append(re.sub(r"<[^>]+>", " ", html))
                        tables.append(
                            {
                                "row_count": max(len(rows), 1),
                                "has_merged_cells": has_merged,
                                "cell_text": " ".join(p for p in cell_text_parts if p),
                            }
                        )
                    elif itype in ("list", "list_item"):
                        items_in = item.get("items") or [item.get("value", "")]
                        lists_out.append(
                            {
                                "items": [str(x) for x in items_in if x],
                                "ordered": bool(item.get("ordered", False)),
                            }
                        )
                    elif itype == "header":
                        headers_footers.append(
                            {
                                "type": "header",
                                "text": (item.get("value") or md).strip(),
                            }
                        )
                    elif itype == "footer":
                        headers_footers.append(
                            {
                                "type": "footer",
                                "text": (item.get("value") or md).strip(),
                            }
                        )
                    elif itype in ("image", "chart"):
                        images.append(
                            {"description": (item.get("value") or md or itype).strip()}
                        )
                    else:
                        # text, paragraph, code, quote, anything else
                        value = (item.get("value") or md or "").strip()
                        if value:
                            text_elements.append(
                                {"text": value, "style": itype or "text"}
                            )

                # Page-level images list (separate from items)
                for img in page.get("images", []) or []:
                    name = img.get("name") or img.get("description") or "image"
                    images.append({"description": str(name)})

        return {
            "text_elements": text_elements,
            "headings": headings,
            "tables": tables,
            "track_changes": [],  # LlamaParse does not extract w:ins/w:del
            "comments": [],  # LlamaParse does not extract w:comment
            "headers_footers": headers_footers,
            "footnotes": [],  # not surfaced as a typed item
            "speaker_notes": [],
            "text_boxes": [],
            "images": images,
            "lists": lists_out,
            "metadata": {},  # no document-properties endpoint
        }

    def supported_formats(self) -> set[str]:
        # LlamaParse Cloud accepts a broad set; list the formats present in OfficeDocBench
        return {
            "docx",
            "pptx",
            "xlsx",
            "odt",
            "odp",
            "ods",
            "html",
            "md",
            "epub",
            "csv",
            "tsv",
        }
