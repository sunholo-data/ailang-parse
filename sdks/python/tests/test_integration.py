"""Integration tests — hit the real AILANG Parse API.

Run:  DOCPARSE_API_KEY=dp_... uv run pytest tests/test_integration.py -v

Skipped automatically when DOCPARSE_API_KEY is not set.
"""
import os
import pytest

from ailang_parse import DocParse, UnstructuredClient
from ailang_parse.types import DocParseError

SKIP = not os.environ.get("DOCPARSE_API_KEY")
REASON = "DOCPARSE_API_KEY not set"

# Use a known sample file that ships with the API
SAMPLE_FILE = "sample_docx_basic"


@pytest.fixture(scope="module")
def client():
    return DocParse()


# ── Unauthenticated endpoints ──

@pytest.mark.skipif(SKIP, reason=REASON)
class TestHealthIntegration:
    def test_health(self, client):
        h = client.health()
        assert h.status in ("ok", "healthy")
        assert h.version  # non-empty
        assert h.service == "docparse"
        assert h.formats_parse > 0
        assert h.formats_generate > 0


@pytest.mark.skipif(SKIP, reason=REASON)
class TestFormatsIntegration:
    def test_formats(self, client):
        f = client.formats()
        assert "docx" in f.parse
        assert "pdf" in f.parse
        assert "html" in f.generate
        assert len(f.ai_required) > 0


# ── Authenticated endpoints ──

@pytest.mark.skipif(SKIP, reason=REASON)
class TestParseIntegration:
    def test_parse_sample_docx(self, client):
        """Parse a sample document. Requires a valid API key with parse access."""
        try:
            r = client.parse(SAMPLE_FILE)
        except DocParseError as e:
            pytest.skip(f"Parse not available with current key: {e}")
        assert r.status in ("ok", "success")
        assert r.filename  # non-empty
        assert len(r.blocks) > 0
        assert r.summary.total_blocks > 0

    def test_parse_blocks_have_types(self, client):
        try:
            r = client.parse(SAMPLE_FILE)
        except DocParseError as e:
            pytest.skip(f"Parse not available: {e}")
        valid_types = {"text", "heading", "table", "list", "image", "audio", "video", "section", "change"}
        for block in r.blocks:
            assert block.type in valid_types, f"unexpected block type: {block.type}"

    def test_parse_markdown_output(self, client):
        """Markdown output may return raw text instead of structured blocks."""
        try:
            r = client.parse(SAMPLE_FILE, output_format="markdown")
        except DocParseError as e:
            pytest.skip(f"Parse not available: {e}")
        # Markdown may return as raw text or structured result
        assert r is not None


@pytest.mark.skipif(SKIP, reason=REASON)
class TestUnstructuredCompatIntegration:
    def test_partition(self):
        uc = UnstructuredClient()
        try:
            elements = uc.general.partition(file=SAMPLE_FILE)
        except DocParseError as e:
            pytest.skip(f"Partition not available: {e}")
        assert len(elements) > 0
        for el in elements:
            assert el.type  # non-empty
            assert isinstance(el.text, str)


@pytest.mark.skipif(SKIP, reason=REASON)
class TestParseFileIntegration:
    """Test multipart file upload with a local file."""

    def test_parse_file_docx(self, client, tmp_path):
        """Create a minimal DOCX and upload it."""
        import zipfile
        docx_path = tmp_path / "test.docx"
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '</Types>')
            zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '</Relationships>')
            zf.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Integration test content</w:t></w:r></w:p></w:body>'
                '</w:document>')

        try:
            r = client.parse_file(str(docx_path))
        except DocParseError as e:
            pytest.skip(f"Parse file not available: {e}")
        assert r.status in ("ok", "success")
        assert len(r.blocks) > 0
