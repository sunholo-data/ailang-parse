"""Tests for v0.7.0 SDK additions:
extras field, always-emit ImageBlock, embed_comments, table-cell escaping.
"""
import pytest

from ailang_parse import (
    ParseResult, Block, Cell,
    FlattenPolicy, Chunk, ChunkMetadata,
)


# ── extras (Part 1) ──

class TestChunkMetadataExtras:
    def test_empty_extras_omitted_from_dict(self):
        md = ChunkMetadata(block_type="text")
        assert "extras" not in md.to_dict()

    def test_extras_in_dict_when_populated(self):
        md = ChunkMetadata(block_type="text", extras={"tenant": "acme", "score": 0.93})
        d = md.to_dict()
        assert d["extras"] == {"tenant": "acme", "score": 0.93}

    def test_callable_on_table_can_set_extras(self):
        def with_extra(b, md):
            md.extras["custom"] = "yes"
            return [Chunk(text="t", metadata=md)]
        pr = ParseResult(blocks=[Block(type="table",
                                       headers=[Cell(text="h")],
                                       rows=[[Cell(text="c")]])])
        chunks = pr.flatten(FlattenPolicy(on_table=with_extra))
        assert chunks[0].metadata.extras["custom"] == "yes"


# ── always-emit ImageBlock (Part 2) ──

class TestImageEmission:
    def test_empty_description_emits_placeholder(self):
        pr = ParseResult(blocks=[
            Block(type="image", description="", mime="image/png", data_length=12345)
        ])
        chunks = pr.flatten(FlattenPolicy(embed_images=True))
        assert len(chunks) == 1
        assert chunks[0].text == "[image: image/png, 12345 bytes]"
        assert chunks[0].metadata.extras["image_has_description"] is False
        assert chunks[0].metadata.extras["image_data_length"] == 12345

    def test_description_preserved_when_present(self):
        pr = ParseResult(blocks=[
            Block(type="image", description="A graph",
                  mime="image/png", data_length=42)
        ])
        chunks = pr.flatten(FlattenPolicy(embed_images=True))
        assert chunks[0].text == "A graph"
        assert chunks[0].metadata.extras["image_has_description"] is True

    def test_transcription_preferred_over_placeholder(self):
        pr = ParseResult(blocks=[
            Block(type="image", description="", transcription="OCR text",
                  mime="image/png", data_length=1)
        ])
        chunks = pr.flatten(FlattenPolicy(embed_images=True))
        assert chunks[0].text == "OCR text"
        # has_description is False — transcription is OCR/audio, not AI desc
        assert chunks[0].metadata.extras["image_has_description"] is False

    def test_placeholder_handles_unknown_mime(self):
        pr = ParseResult(blocks=[
            Block(type="image", description="", mime="", data_length=0)
        ])
        chunks = pr.flatten(FlattenPolicy(embed_images=True))
        assert chunks[0].text == "[image: unknown, 0 bytes]"

    def test_embed_images_off_skips_all(self):
        pr = ParseResult(blocks=[
            Block(type="image", description="A graph", mime="image/png")
        ])
        chunks = pr.flatten(FlattenPolicy(embed_images=False))
        assert all(c.metadata.block_type != "image" for c in chunks)

    def test_consumer_can_filter_placeholders(self):
        """Verify the README recipe for v0.6.0-style 'skip empty' behaviour."""
        pr = ParseResult(blocks=[
            Block(type="image", description="A graph", mime="image/png"),
            Block(type="image", description="", mime="image/png"),
        ])
        chunks = pr.flatten(FlattenPolicy(embed_images=True))
        filtered = [
            c for c in chunks
            if c.metadata.block_type != "image"
            or c.metadata.extras.get("image_has_description")
        ]
        assert len(filtered) == 1
        assert filtered[0].text == "A graph"


# ── embed_comments + CommentBlock (Part 3) ──

class TestComments:
    def test_comment_chunk_with_all_metadata(self):
        pr = ParseResult(blocks=[
            Block(type="comment", text="Please clarify",
                  author="Alice", date="2026-05-16", resolved=False)
        ])
        chunks = pr.flatten(FlattenPolicy(embed_comments=True))
        assert len(chunks) == 1
        c = chunks[0]
        assert c.metadata.block_type == "comment"
        assert c.text == "Please clarify"
        assert c.metadata.change_author == "Alice"
        assert c.metadata.extras["resolved"] is False
        assert c.metadata.extras["date"] == "2026-05-16"

    def test_resolved_comment_carries_flag(self):
        pr = ParseResult(blocks=[
            Block(type="comment", text="Done", author="Bob", resolved=True)
        ])
        chunks = pr.flatten(FlattenPolicy(embed_comments=True))
        assert chunks[0].metadata.extras["resolved"] is True

    def test_embed_comments_off_skips_all(self):
        pr = ParseResult(blocks=[
            Block(type="comment", text="hi", author="A"),
        ])
        chunks = pr.flatten(FlattenPolicy(embed_comments=False))
        assert all(c.metadata.block_type != "comment" for c in chunks)

    def test_empty_text_comment_skipped(self):
        pr = ParseResult(blocks=[
            Block(type="comment", text="", author="A"),
        ])
        chunks = pr.flatten(FlattenPolicy(embed_comments=True))
        assert all(c.metadata.block_type != "comment" for c in chunks)

    def test_no_comment_blocks_means_no_comment_chunks(self):
        """Forward-compat check: with no comment blocks in input,
        embed_comments=True is a no-op."""
        pr = ParseResult(blocks=[Block(type="text", text="just text")])
        chunks = pr.flatten(FlattenPolicy(embed_comments=True))
        assert all(c.metadata.block_type != "comment" for c in chunks)


# ── table-cell escape knobs (Part 4) ──

def _table_pr() -> ParseResult:
    return ParseResult(blocks=[Block(
        type="table",
        headers=[Cell(text="H1"), Cell(text="H2")],
        rows=[[Cell(text="a\nb"), Cell(text="c|d")]],
    )])


class TestTableCellEscaping:
    def test_preserve_is_default(self):
        chunks = _table_pr().flatten()
        row = next(c for c in chunks if c.metadata.block_type == "table_row")
        # Internal newline preserved -> output is ambiguous (v0.6.0 behaviour)
        assert "a\nb" in row.text
        assert "c|d" in row.text

    def test_newlines_space(self):
        chunks = _table_pr().flatten(
            FlattenPolicy(on_table_cell_newlines="space"))
        row = next(c for c in chunks if c.metadata.block_type == "table_row")
        assert "a b" in row.text
        assert "\n" not in row.text.split("\n", 1)[1] if "\n" in row.text else True

    def test_newlines_escape(self):
        chunks = _table_pr().flatten(
            FlattenPolicy(on_table_cell_newlines="escape"))
        row = next(c for c in chunks if c.metadata.block_type == "table_row")
        assert "a\\nb" in row.text  # literal backslash + n

    def test_pipes_escape(self):
        chunks = _table_pr().flatten(
            FlattenPolicy(on_table_cell_pipes="escape"))
        row = next(c for c in chunks if c.metadata.block_type == "table_row")
        assert "c\\|d" in row.text

    def test_pipes_space(self):
        chunks = _table_pr().flatten(
            FlattenPolicy(on_table_cell_pipes="space"))
        row = next(c for c in chunks if c.metadata.block_type == "table_row")
        assert "c d" in row.text

    def test_independent_modes(self):
        chunks = _table_pr().flatten(FlattenPolicy(
            on_table_cell_newlines="space",
            on_table_cell_pipes="escape",
        ))
        row = next(c for c in chunks if c.metadata.block_type == "table_row")
        assert "a b" in row.text
        assert "c\\|d" in row.text

    def test_escape_also_applies_to_whole_table_mode(self):
        chunks = _table_pr().flatten(FlattenPolicy(
            on_table="whole",
            on_table_cell_newlines="space",
        ))
        whole = next(c for c in chunks if c.metadata.block_type == "table")
        assert "a b" in whole.text

    def test_invalid_newlines_mode_raises(self):
        with pytest.raises(ValueError, match="on_table_cell_newlines"):
            FlattenPolicy(on_table_cell_newlines="bogus")

    def test_invalid_pipes_mode_raises(self):
        with pytest.raises(ValueError, match="on_table_cell_pipes"):
            FlattenPolicy(on_table_cell_pipes="bogus")
