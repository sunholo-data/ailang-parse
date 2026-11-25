"""Unit tests for GeminiNativeAdapter (offline mapping & slicing payload checks)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.gemini_native_adapter import (
    GeminiNativeAdapter,
    _build_media_item,
    _strip_json_fence,
)


def test_strip_json_fence() -> None:
    assert _strip_json_fence('{"a": 1}') == '{"a": 1}'
    assert _strip_json_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_json_fence('```\n{"a": 1}\n```') == '{"a": 1}'


def test_build_media_item_docx_and_xlsx() -> None:
    docx_item = _build_media_item(
        "https://generativelanguage.googleapis.com/v1beta/files/abc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
        "high",
    )
    assert docx_item["type"] == "document"
    assert docx_item["resolution"] == "high"
    assert docx_item["processing"]["page_options"]["content_layers"] == [
        "page_text",
        "page_image",
    ]

    xlsx_item = _build_media_item(
        "https://generativelanguage.googleapis.com/v1beta/files/xyz",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
        "medium",
    )
    assert xlsx_item["type"] == "document"
    assert xlsx_item["processing"]["spreadsheet_options"]["content_layers"] == [
        "data",
        "formulas",
    ]


def test_convert_response_maps_structure_and_review_markup(tmp_path: Path) -> None:
    adapter = GeminiNativeAdapter(model="gemini-4-neon", resolution="medium")
    payload = {
        "markdown": "# Q1 Report\n\nRevenue grew **12%**.\n\n| Metric | Value |\n|---|---|\n| ARR | $4.2M |\n",
        "comments": [
            {"author": "Alice", "text": "Verify Q1 figure", "annotated_text": "$4.2M"}
        ],
        "track_changes": [
            {"type": "insertion", "author": "Bob", "text": "adjusted"}
        ],
        "headers_footers": [{"type": "header", "text": "Confidential"}],
        "footnotes": [{"text": "Unaudited figures."}],
        "speaker_notes": [{"text": "Pause before Q&A."}],
        "metadata": {"title": "Q1 Report", "author": "Finance", "sheet_names": []},
    }
    raw_resp = {
        "steps": [
            {"type": "thought", "signature": "..."},
            {
                "type": "model_output",
                "content": [{"type": "text", "text": f"```json\n{json.dumps(payload)}\n```"}],
            },
        ]
    }
    out = adapter.convert_response(raw_resp, tmp_path / "report.docx")

    assert out["headings"] == [{"text": "Q1 Report", "level": 1}]
    assert len(out["tables"]) == 1
    assert out["comments"][0]["author"] == "Alice"
    assert out["comments"][0]["anchored"] is True
    assert out["structure"]["comment_anchors"][0]["annotated_text"] == "$4.2M"
    assert out["track_changes"] == [
        {"type": "insertion", "author": "Bob", "text": "adjusted"}
    ]
    assert out["headers_footers"] == [{"type": "header", "text": "Confidential"}]
    assert out["footnotes"] == [{"text": "Unaudited figures."}]
    assert out["speaker_notes"] == [{"text": "Pause before Q&A."}]
    assert out["metadata"]["title"] == "Q1 Report"


def test_reuse_raw_cache(tmp_path: Path, monkeypatch) -> None:
    sample = tmp_path / "demo.docx"
    sample.write_bytes(b"fake-docx-bytes")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    import hashlib

    sha = hashlib.sha256(b"fake-docx-bytes").hexdigest()
    cached = raw_dir / f"demo.docx.{sha[:12]}.json"
    cached.write_text(
        json.dumps({"output_text": json.dumps({"markdown": "# Cached Title\n\nBody text."})}),
        encoding="utf-8",
    )

    monkeypatch.setenv("GEMINI_NATIVE_RAW_DIR", str(raw_dir))
    monkeypatch.setenv("GEMINI_NATIVE_REUSE_RAW", "1")
    adapter = GeminiNativeAdapter()
    out = adapter.parse(sample)
    assert out["headings"] == [{"text": "Cached Title", "level": 1}]
