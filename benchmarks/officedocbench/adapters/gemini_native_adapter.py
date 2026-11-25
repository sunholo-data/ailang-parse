"""Gemini Native Office + File Slicing adapter for OfficeDocBench.

Evaluates Google's Gemini API native Microsoft Office & OpenDocument ingestion
with server-side file slicing controls (introduced 2026-11-23):
  https://blog.google/innovation-and-ai/technology/developers-tools/file-slicing-controls/

Requires: GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable for the
Gemini Developer API (Vertex AI v1beta1 does not yet accept Office/ODF MIME
types as of 2026-11-24).

Uses the REST API directly via urllib/httpx:
  1. POST /upload/v1beta/files?uploadType=media  (upload once)
  2. POST /v1beta/interactions                   (native Office + slicing layers)
  3. DELETE /v1beta/{file_name}                  (best-effort cleanup)

Model & mode knobs (env vars):
  GEMINI_NATIVE_MODEL      default "gemini-4-neon"
  GEMINI_NATIVE_RESOLUTION default "medium" ("low" | "medium" | "high")
  GEMINI_NATIVE_RAW_DIR    save raw JSON responses for offline remapping
  GEMINI_NATIVE_REUSE_RAW  if "1", remap cached raw responses matching SHA-256
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .base_adapter import OfficeDocBenchAdapter
from .structure import add_sheet_scopes, markdown_output

API_BASE = os.environ.get(
    "GEMINI_API_BASE", "https://generativelanguage.googleapis.com"
)
DEFAULT_MODEL = os.environ.get("GEMINI_NATIVE_MODEL", "gemini-4-neon")
DEFAULT_RESOLUTION = os.environ.get("GEMINI_NATIVE_RESOLUTION", "medium")
TIMEOUT_SECONDS = 300

MIME_BY_EXT: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".html": "text/html",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
}

_SPREADSHEETS = {".xlsx", ".ods", ".csv", ".tsv"}
_DOCUMENTS = {".docx", ".pptx", ".odt", ".odp"}

_PROMPT = (
    "Extract ALL content and structure from this document faithfully into JSON. "
    "Return ONLY a single JSON object with these keys:\n"
    '  "markdown": string — full document body in GitHub-flavored Markdown (preserve headings #..######, tables, lists, bold/italic/code, links),\n'
    '  "comments": [{"author": str, "text": str, "annotated_text": str}],\n'
    '  "track_changes": [{"type": "insertion"|"deletion", "author": str, "text": str}],\n'
    '  "headers_footers": [{"type": "header"|"footer", "text": str}],\n'
    '  "footnotes": [{"text": str}],\n'
    '  "speaker_notes": [{"text": str}],\n'
    '  "metadata": {"title": str, "author": str, "sheet_names": [str]}\n'
    "Include EVERY cell, formula (when present), table row, comment, tracked change, "
    "header/footer, footnote, and speaker note. Do NOT summarize or omit anything."
)


def _strip_json_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        nl = s.find("\n")
        s = s[nl + 1 :] if nl >= 0 else s[3:]
        s = s.strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    return s


def _build_media_item(uri: str, mime: str, suffix: str, resolution: str) -> dict[str, Any]:
    """Build the Interactions API input item with format-appropriate slicing options."""
    if suffix in _SPREADSHEETS and suffix in (".xlsx", ".ods"):
        return {
            "type": "document",
            "uri": uri,
            "mime_type": mime,
            "processing": {
                "type": "static",
                "spreadsheet_options": {
                    "content_layers": ["data", "formulas"],
                },
            },
        }
    if suffix in _DOCUMENTS:
        item: dict[str, Any] = {
            "type": "document",
            "uri": uri,
            "mime_type": mime,
            "processing": {
                "type": "static",
                "page_options": {
                    "content_layers": ["page_text", "page_image"],
                },
            },
        }
        if resolution:
            item["resolution"] = resolution
        return item
    return {
        "type": "document",
        "uri": uri,
        "mime_type": mime,
    }


def _http_json(
    method: str,
    url: str,
    api_key: str,
    body: bytes | dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    hdrs = {"x-goog-api-key": api_key}
    if headers:
        hdrs.update(headers)
    data: bytes | None = None
    if isinstance(body, dict):
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif isinstance(body, bytes):
        data = body
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini API HTTP {e.code} on {method} {url}: {detail}") from e


def _extract_interaction_text(resp: dict[str, Any]) -> str:
    if isinstance(resp.get("output_text"), str) and resp["output_text"]:
        return resp["output_text"]
    parts: list[str] = []
    for step in resp.get("steps") or []:
        if isinstance(step, dict) and step.get("type") == "model_output":
            for item in step.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    parts.append(item["text"])
    if parts:
        return "\n".join(parts)
    for out in resp.get("outputs") or []:
        if isinstance(out, dict) and out.get("type") == "text" and out.get("text"):
            parts.append(out["text"])
    return "\n".join(parts)


class GeminiNativeAdapter(OfficeDocBenchAdapter):
    """OfficeDocBench adapter for Gemini native Office + File Slicing."""

    def __init__(
        self,
        model: str | None = None,
        resolution: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("GEMINI_NATIVE_MODEL", DEFAULT_MODEL)
        self._resolution = (
            resolution
            if resolution is not None
            else os.environ.get("GEMINI_NATIVE_RESOLUTION", DEFAULT_RESOLUTION)
        )

    def name(self) -> str:
        return f"Gemini Native ({self._model})"

    def version(self) -> str:
        return f"{self._model}:{self._resolution or 'default'}"

    def provider_config(self) -> dict[str, Any]:
        return {
            "model": self._model,
            "resolution": self._resolution,
            "endpoint": "interactions",
            "slicing": True,
        }

    def supported_formats(self) -> set[str]:
        return {"docx", "pptx", "xlsx", "odt", "odp", "ods", "html", "md", "csv", "tsv"}

    def _api_key(self) -> str:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) not set for GeminiNativeAdapter"
            )
        return key

    def parse(self, filepath: Path) -> dict[str, Any]:
        suffix = filepath.suffix.lower()
        mime = MIME_BY_EXT.get(suffix)
        if not mime:
            raise RuntimeError(f"Unsupported format for GeminiNativeAdapter: {suffix}")

        raw_bytes = filepath.read_bytes()
        sha = hashlib.sha256(raw_bytes).hexdigest()
        raw_dir_env = os.environ.get("GEMINI_NATIVE_RAW_DIR", "")
        reuse_raw = os.environ.get("GEMINI_NATIVE_REUSE_RAW") == "1"
        raw_path = Path(raw_dir_env) / f"{filepath.name}.{sha[:12]}.json" if raw_dir_env else None

        if reuse_raw and raw_path and raw_path.exists():
            raw_resp = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            raw_resp = self._call_gemini(raw_bytes, mime, suffix)
            if raw_path:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(raw_resp, indent=2), encoding="utf-8")

        return self.convert_response(raw_resp, filepath)

    def _call_gemini(self, raw_bytes: bytes, mime: str, suffix: str) -> dict[str, Any]:
        api_key = self._api_key()
        upload = _http_json(
            "POST",
            f"{API_BASE}/upload/v1beta/files?uploadType=media",
            api_key,
            body=raw_bytes,
            headers={"Content-Type": mime},
        )
        file_obj = upload.get("file", upload)
        file_uri = file_obj.get("uri", "")
        file_name = file_obj.get("name", "")
        if not file_uri:
            raise RuntimeError(f"Gemini Files API upload returned no URI: {upload}")

        try:
            media_item = _build_media_item(file_uri, mime, suffix, self._resolution)
            payload = {
                "model": self._model,
                "input": [
                    media_item,
                    {"type": "text", "text": _PROMPT},
                ],
            }
            return _http_json(
                "POST",
                f"{API_BASE}/v1beta/interactions",
                api_key,
                body=payload,
            )
        finally:
            if file_name:
                try:
                    _http_json("DELETE", f"{API_BASE}/v1beta/{file_name}", api_key)
                except Exception:
                    pass

    def convert_response(
        self, raw_resp: dict[str, Any], filepath: Path
    ) -> dict[str, Any]:
        suffix = filepath.suffix.lower()
        text = _extract_interaction_text(raw_resp)
        cleaned = _strip_json_fence(text)

        parsed: dict[str, Any] = {}
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                parsed = obj
        except json.JSONDecodeError:
            # Fallback: treat raw text as Markdown if the model ignored JSON framing
            parsed = {"markdown": text}

        md = parsed.get("markdown") if isinstance(parsed.get("markdown"), str) else ""
        output = markdown_output(md)
        structure = output.setdefault("structure", {})

        comments = []
        for c in parsed.get("comments") or []:
            if isinstance(c, dict) and c.get("text"):
                comments.append(
                    {
                        "author": str(c.get("author") or ""),
                        "text": str(c.get("text") or ""),
                        "annotated_text": str(c.get("annotated_text") or ""),
                        "anchored": bool(c.get("annotated_text")),
                        "parent_id": "",
                        "resolved": False,
                        "scope": "",
                    }
                )

        track_changes = []
        for tc in parsed.get("track_changes") or []:
            if isinstance(tc, dict) and tc.get("text"):
                kind = str(tc.get("type") or "").lower()
                if kind in ("insert", "insertion"):
                    kind = "insertion"
                elif kind in ("delete", "deletion"):
                    kind = "deletion"
                track_changes.append(
                    {
                        "type": kind,
                        "author": str(tc.get("author") or ""),
                        "text": str(tc.get("text") or ""),
                    }
                )

        headers_footers = [
            {"type": str(hf.get("type") or "header"), "text": str(hf.get("text") or "")}
            for hf in (parsed.get("headers_footers") or [])
            if isinstance(hf, dict) and hf.get("text")
        ]
        footnotes = [
            {"text": str(fn.get("text") or "")}
            for fn in (parsed.get("footnotes") or [])
            if isinstance(fn, dict) and fn.get("text")
        ]
        speaker_notes = [
            {"text": str(sn.get("text") or "")}
            for sn in (parsed.get("speaker_notes") or [])
            if isinstance(sn, dict) and sn.get("text")
        ]

        meta = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
        output["metadata"] = {
            "title": str(meta.get("title") or ""),
            "author": str(meta.get("author") or ""),
            "created": "",
            "modified": "",
            "sheet_names": [str(s) for s in (meta.get("sheet_names") or []) if s],
        }

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

        if suffix in _SPREADSHEETS:
            add_sheet_scopes(output)

        output.update(
            {
                "track_changes": track_changes,
                "comments": comments,
                "headers_footers": headers_footers,
                "footnotes": footnotes,
                "speaker_notes": speaker_notes,
                "text_boxes": [],
            }
        )
        return output
