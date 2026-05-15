"""Tests for v0.6.0 SDK additions: error metadata, RetryPolicy, flatten()."""
import pytest

from ailang_parse import (
    DocParse, DocParseError, AuthError, QuotaError,
    RetryPolicy,
    ParseResult, Block, Cell,
    Chunk, ChunkMetadata, FlattenPolicy, DEFAULT_FLATTEN_POLICY,
)


# ── Error constructor parity (Part 1a) ──

class TestErrorConstructors:
    def test_DocParseError_kwargs(self):
        e = DocParseError("boom", status_code=500, request_id="req-1",
                          replayable=True, suggested_fix="restart",
                          details={"trace": "x"})
        assert e.request_id == "req-1"
        assert e.replayable is True
        assert e.status_code == 500
        assert e.suggested_fix == "restart"
        assert e.details == {"trace": "x"}

    def test_AuthError_kwargs(self):
        e = AuthError(message="bad key", request_id="req-2")
        assert e.status_code == 401
        assert e.request_id == "req-2"

    def test_AuthError_default_message(self):
        e = AuthError()
        assert "Invalid" in str(e)
        assert e.status_code == 401

    def test_AuthError_legacy_positional(self):
        e = AuthError("bad key", 401)
        assert e.status_code == 401
        assert "bad key" in str(e)

    def test_QuotaError_kwargs(self):
        e = QuotaError(message="nope", tier="free", used=100, limit=100,
                       request_id="req-3")
        assert e.status_code == 429
        assert e.tier == "free"
        assert e.used == 100
        assert e.request_id == "req-3"

    def test_QuotaError_default_message(self):
        e = QuotaError()
        assert "Quota" in str(e)
        assert e.status_code == 429


# ── RetryPolicy (Part 5) ──

class TestRetryPolicy:
    def test_default_does_not_retry(self):
        rp = RetryPolicy()
        assert rp.max_retries == 0
        assert not rp.should_retry(502, False)
        assert not rp.should_retry(500, True)

    def test_retries_on_listed_statuses(self):
        rp = RetryPolicy(max_retries=3)
        assert rp.should_retry(502, False)
        assert rp.should_retry(503, False)
        assert rp.should_retry(504, False)
        assert not rp.should_retry(500, False)
        assert not rp.should_retry(200, False)

    def test_respects_replayable(self):
        rp = RetryPolicy(max_retries=3, respect_replayable=True)
        assert rp.should_retry(500, True)
        assert rp.should_retry(599, True)
        assert not rp.should_retry(400, True)  # 4xx is not retried

    def test_replayable_off(self):
        rp = RetryPolicy(max_retries=3, respect_replayable=False)
        assert not rp.should_retry(500, True)

    def test_backoff_caps_at_max(self):
        rp = RetryPolicy(max_retries=10, backoff_base=1.0, backoff_max=30.0)
        assert rp.delay_for(0) == 1.0
        assert rp.delay_for(3) == 8.0
        assert rp.delay_for(10) == 30.0


# ── DocParse defaults (Part 2) ──

class TestDocParseDefaults:
    def test_timeout_default_120s(self):
        client = DocParse(api_key="dp_xxx")
        assert client.timeout == 120

    def test_retry_default_off(self):
        client = DocParse(api_key="dp_xxx")
        assert client.retry.max_retries == 0

    def test_retry_explicit(self):
        client = DocParse(api_key="dp_xxx",
                          retry=RetryPolicy(max_retries=5))
        assert client.retry.max_retries == 5


# ── flatten() (Part 4) ──

def _make_doc() -> ParseResult:
    """A representative document covering every block variant flatten handles."""
    return ParseResult(
        status="ok",
        blocks=[
            Block(type="heading", text="Intro", level=1),
            Block(type="text", text="Hello world. " * 5),
            Block(type="section", kind="Body", children=[
                Block(type="heading", text="Methodology", level=2),
                Block(type="text", text="We did things."),
                Block(type="table",
                      headers=[Cell(text="Name"), Cell(text="Score")],
                      rows=[[Cell(text="A"), Cell(text="1")],
                            [Cell(text="B"), Cell(text="2")]]),
                Block(type="list", items=["one", "two", "three"]),
            ]),
            Block(type="image", description="A graph", mime="image/png"),
            Block(type="change", text="Reworded", author="Alice",
                  change_type="insert"),
        ],
    )


class TestFlatten:
    def test_default_emits_text_heading_table_rows_list(self):
        chunks = _make_doc().flatten()
        types = [c.metadata.block_type for c in chunks]
        assert "heading" in types
        assert "text" in types
        assert "table_row" in types
        assert "list" in types
        # defaults skip image + change
        assert "image" not in types
        assert "change" not in types

    def test_section_path_tracked(self):
        chunks = _make_doc().flatten()
        body_chunks = [c for c in chunks if c.metadata.block_type == "table_row"]
        assert all(c.metadata.section_path == ["Body"] for c in body_chunks)

    def test_section_path_off(self):
        chunks = _make_doc().flatten(FlattenPolicy(section_path=False))
        assert all(c.metadata.section_path == [] for c in chunks)

    def test_embed_images_and_changes(self):
        chunks = _make_doc().flatten(
            FlattenPolicy(embed_images=True, embed_changes=True))
        types = [c.metadata.block_type for c in chunks]
        assert "image" in types
        assert "change" in types
        change = next(c for c in chunks if c.metadata.block_type == "change")
        assert change.metadata.change_author == "Alice"
        assert change.metadata.change_type == "insert"

    def test_whole_table_mode(self):
        chunks = _make_doc().flatten(FlattenPolicy(on_table="whole"))
        table_chunks = [c for c in chunks if c.metadata.block_type == "table"]
        assert len(table_chunks) == 1
        assert "Name | Score" in table_chunks[0].text
        assert "A | 1" in table_chunks[0].text
        assert "B | 2" in table_chunks[0].text

    def test_table_row_carries_headers(self):
        chunks = _make_doc().flatten()
        rows = [c for c in chunks if c.metadata.block_type == "table_row"]
        assert len(rows) == 2
        assert rows[0].text.startswith("Name | Score\n")
        assert rows[0].metadata.row_index == 0
        assert rows[1].metadata.row_index == 1
        assert rows[0].metadata.table_id == rows[1].metadata.table_id

    def test_callable_on_table_override(self):
        def to_one(block, md):
            return [Chunk(text="<elided>", metadata=md)]
        chunks = _make_doc().flatten(FlattenPolicy(on_table=to_one))
        assert any(c.text == "<elided>" for c in chunks)

    def test_long_text_splits_under_max_chars(self):
        pr = ParseResult(blocks=[
            Block(type="text", text=("foo bar " * 200).strip()),
        ])
        chunks = pr.flatten(FlattenPolicy(max_chunk_chars=200))
        assert len(chunks) >= 2
        assert all(len(c.text) <= 220 for c in chunks)  # tolerance on word boundary

    def test_chunk_to_dict_is_json_friendly(self):
        chunks = _make_doc().flatten()
        d = chunks[0].to_dict()
        assert "text" in d
        assert "block_type" in d["metadata"]
        assert "section_path" in d["metadata"]
        # None-valued optional fields are omitted
        assert "table_id" not in d["metadata"]

    def test_heading_chunks_have_level(self):
        chunks = _make_doc().flatten()
        h1 = next(c for c in chunks
                  if c.metadata.block_type == "heading" and c.text == "Intro")
        assert h1.metadata.heading_level == 1

    def test_block_index_monotonic(self):
        chunks = _make_doc().flatten()
        # block_index should be assigned monotonically as we visit the tree
        idxs = [c.metadata.block_index for c in chunks]
        assert idxs == sorted(idxs)
