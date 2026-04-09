"""Tests for type deserialization — Block ADT, ParseResult, metadata, errors."""
import pytest
from ailang_parse.types import (
    Block, Cell, DocMetadata, Summary, ParseResult,
    HealthResult, FormatsResult, KeyInfo, Quota, Usage, UsageInfo,
    Element, ElementMetadata,
    DocParseError, AuthError, QuotaError,
)


# ── Cell ──

class TestCell:
    def test_from_string(self):
        cell = Cell.from_raw("hello")
        assert cell.text == "hello"
        assert cell.col_span == 1
        assert cell.merged is False

    def test_from_dict(self):
        cell = Cell.from_raw({"text": "merged", "colSpan": 3, "merged": True})
        assert cell.text == "merged"
        assert cell.col_span == 3
        assert cell.merged is True

    def test_from_dict_defaults(self):
        cell = Cell.from_raw({})
        assert cell.text == ""
        assert cell.col_span == 1
        assert cell.merged is False

    def test_from_other(self):
        cell = Cell.from_raw(42)
        assert cell.text == "42"


# ── Block ──

class TestBlock:
    def test_text_block(self):
        b = Block.from_dict({"type": "text", "text": "Hello world", "style": "Normal"})
        assert b.type == "text"
        assert b.text == "Hello world"
        assert b.style == "Normal"

    def test_heading_block(self):
        b = Block.from_dict({"type": "heading", "text": "Title", "level": 2})
        assert b.type == "heading"
        assert b.level == 2

    def test_table_block(self):
        b = Block.from_dict({
            "type": "table",
            "headers": ["A", "B"],
            "rows": [["1", "2"], [{"text": "3", "colSpan": 2, "merged": True}]],
        })
        assert b.type == "table"
        assert len(b.headers) == 2
        assert b.headers[0].text == "A"
        assert len(b.rows) == 2
        assert b.rows[1][0].col_span == 2

    def test_change_block(self):
        b = Block.from_dict({
            "type": "change",
            "text": "deleted text",
            "changeType": "deletion",
            "author": "Alice",
            "date": "2024-01-01",
        })
        assert b.change_type == "deletion"
        assert b.author == "Alice"

    def test_list_block(self):
        b = Block.from_dict({"type": "list", "items": ["a", "b"], "ordered": True})
        assert b.items == ["a", "b"]
        assert b.ordered is True

    def test_image_block(self):
        b = Block.from_dict({
            "type": "image",
            "description": "chart",
            "mime": "image/png",
            "dataLength": 1024,
        })
        assert b.description == "chart"
        assert b.mime == "image/png"
        assert b.data_length == 1024

    def test_section_block(self):
        b = Block.from_dict({
            "type": "section",
            "kind": "header",
            "blocks": [{"type": "text", "text": "inner"}],
        })
        assert b.kind == "header"
        assert len(b.children) == 1
        assert b.children[0].text == "inner"

    def test_defaults(self):
        b = Block.from_dict({})
        assert b.type == ""
        assert b.text == ""
        assert b.level == 0
        assert b.headers == []
        assert b.rows == []
        assert b.children == []


# ── Metadata / Summary ──

class TestMetadata:
    def test_from_dict(self):
        m = DocMetadata.from_dict({
            "title": "Report",
            "author": "Bob",
            "created": "2024-01-01",
            "modified": "2024-06-01",
            "pageCount": 5,
        })
        assert m.title == "Report"
        assert m.page_count == 5

    def test_defaults(self):
        m = DocMetadata.from_dict({})
        assert m.title == ""
        assert m.page_count == 0


class TestSummary:
    def test_from_dict(self):
        s = Summary.from_dict({"totalBlocks": 10, "headings": 3, "tables": 2, "images": 1, "changes": 4})
        assert s.total_blocks == 10
        assert s.changes == 4


# ── ParseResult ──

class TestParseResult:
    def test_full(self):
        r = ParseResult.from_dict({
            "status": "ok",
            "filename": "test.docx",
            "format": "docx",
            "blocks": [{"type": "text", "text": "hi"}],
            "metadata": {"title": "T"},
            "summary": {"totalBlocks": 1},
        })
        assert r.status == "ok"
        assert r.filename == "test.docx"
        assert len(r.blocks) == 1
        assert r.metadata.title == "T"
        assert r.summary.total_blocks == 1

    def test_empty(self):
        r = ParseResult.from_dict({})
        assert r.blocks == []
        assert r.metadata.title == ""


# ── HealthResult / FormatsResult ──

class TestHealthResult:
    def test_from_dict(self):
        h = HealthResult.from_dict({"status": "ok", "version": "1.0", "service": "docparse", "formats_parse": 12, "formats_generate": 9})
        assert h.status == "ok"
        assert h.formats_parse == 12


class TestFormatsResult:
    def test_from_dict(self):
        f = FormatsResult.from_dict({"parse": ["docx", "pdf"], "generate": ["html"], "ai_required": ["pdf"]})
        assert "docx" in f.parse
        assert f.ai_required == ["pdf"]


# ── Key management types ──

class TestKeyTypes:
    def test_quota(self):
        q = Quota.from_dict({"requestsPerDay": 100, "requestsPerMonth": 1000, "aiLimitPerRequest": 5, "fsLimitPerRequest": 10})
        assert q.requests_per_day == 100

    def test_key_info(self):
        k = KeyInfo.from_dict({"status": "active", "key": "dp_abc", "keyId": "k1", "label": "test", "tier": "free", "created": "2024-01-01", "quota": {"requestsPerDay": 50}})
        assert k.key == "dp_abc"
        assert k.quota.requests_per_day == 50

    def test_usage_info(self):
        u = UsageInfo.from_dict({"status": "ok", "keyId": "k1", "tier": "free", "usage": {"requestsToday": 5}, "quota": {"requestsPerDay": 50}})
        assert u.usage.requests_today == 5


# ── Unstructured compat types ──

class TestElement:
    def test_from_dict(self):
        e = Element.from_dict({
            "type": "NarrativeText",
            "element_id": "abc123",
            "text": "Hello",
            "metadata": {"filename": "test.docx", "filetype": "docx"},
        })
        assert e.type == "NarrativeText"
        assert e.metadata.filename == "test.docx"


# ── FormatsResult helpers (#6) ──

class TestFormatsResultHelpers:
    def _f(self):
        return FormatsResult(
            parse=["docx", "pdf", "html"],
            generate=["docx", "html"],
            ai_required=["pdf"],
        )

    def test_supports_basic(self):
        assert self._f().supports("docx") is True
        assert self._f().supports("xlsx") is False

    def test_supports_case_insensitive(self):
        assert self._f().supports("DOCX") is True

    def test_supports_strips_leading_dot(self):
        assert self._f().supports(".docx") is True
        assert self._f().supports(".PDF") is True

    def test_supports_generate(self):
        assert self._f().supports("docx", "generate") is True
        assert self._f().supports("pdf", "generate") is False

    def test_is_deterministic(self):
        f = self._f()
        assert f.is_deterministic("docx") is True
        assert f.is_deterministic("html") is True
        assert f.is_deterministic("pdf") is False  # AI-required
        assert f.is_deterministic("xlsx") is False  # not supported

    def test_is_deterministic_case_insensitive(self):
        assert self._f().is_deterministic(".DOCX") is True


# ── ParseResult.text field (#2) ──

class TestParseResultText:
    def test_text_default_empty(self):
        r = ParseResult.from_dict({"status": "ok", "blocks": []})
        assert r.text == ""

    def test_text_populated_from_dict(self):
        r = ParseResult.from_dict({"status": "ok", "text": "# Heading"})
        assert r.text == "# Heading"


# ── Errors ──

class TestErrors:
    def test_docparse_error(self):
        e = DocParseError("fail", 500)
        assert str(e) == "fail"
        assert e.status_code == 500

    def test_auth_error(self):
        e = AuthError("bad key", 401)
        assert isinstance(e, DocParseError)
        assert e.status_code == 401

    def test_quota_error(self):
        e = QuotaError("over limit", tier="free", used=100, limit=50)
        assert e.status_code == 429
        assert e.tier == "free"
