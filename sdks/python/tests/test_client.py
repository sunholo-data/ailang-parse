"""Tests for DocParse client — mock HTTP server, unwrap logic, error handling."""
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest
from ailang_parse.client import DocParse
from ailang_parse.types import DocParseError, AuthError, QuotaError


# ── Mock server ──

class MockHandler(BaseHTTPRequestHandler):
    """Serves canned responses for testing."""

    # Class-level response config — tests set these before making requests.
    response_status = 200
    response_body = {}

    def do_GET(self):
        self._respond()

    def do_POST(self):
        # Read body (ignore it — we just echo canned responses)
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self._respond()

    def _respond(self):
        body = json.dumps(self.response_body).encode()
        self.send_response(self.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # silence logs


@pytest.fixture(scope="module")
def mock_server():
    """Start a local HTTP server for the test module."""
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def _set_response(status=200, body=None):
    MockHandler.response_status = status
    MockHandler.response_body = body or {}


# ── Unwrap tests ──

class TestUnwrap:
    def test_unwrap_with_result_string(self):
        inner = {"status": "ok", "blocks": []}
        outer = {"result": json.dumps(inner)}
        assert DocParse._unwrap(outer) == inner

    def test_unwrap_error(self):
        with pytest.raises(DocParseError, match="something broke"):
            DocParse._unwrap({"error": "something broke"})

    def test_unwrap_no_result(self):
        outer = {"status": "ok"}
        assert DocParse._unwrap(outer) == outer

    def test_unwrap_non_json_result(self):
        outer = {"result": "plain text"}
        assert DocParse._unwrap(outer) == {"raw": "plain text"}


# ── Client construction ──

class TestClientConstruction:
    def test_explicit_key(self):
        c = DocParse(api_key="dp_test123")
        assert c.api_key == "dp_test123"

    def test_env_var_key(self, monkeypatch):
        monkeypatch.setenv("DOCPARSE_API_KEY", "dp_fromenv")
        c = DocParse()
        assert c.api_key == "dp_fromenv"

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("DOCPARSE_API_KEY", "dp_fromenv")
        c = DocParse(api_key="dp_explicit")
        assert c.api_key == "dp_explicit"

    def test_no_key(self, monkeypatch):
        monkeypatch.delenv("DOCPARSE_API_KEY", raising=False)
        c = DocParse(base_url="http://nokey.test")
        assert c.api_key == ""

    def test_custom_base_url(self):
        c = DocParse(base_url="http://localhost:8080/")
        assert c.base_url == "http://localhost:8080"  # trailing slash stripped


# ── API methods via mock server ──

class TestHealth:
    def test_health_ok(self, mock_server):
        _set_response(200, {
            "result": json.dumps({
                "status": "ok",
                "version": "1.2.3",
                "service": "docparse",
                "formats_parse": 12,
                "formats_generate": 9,
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        h = c.health()
        assert h.status == "ok"
        assert h.version == "1.2.3"
        assert h.formats_parse == 12

    def test_health_server_error(self, mock_server):
        _set_response(500, {"error": "internal"})
        c = DocParse(api_key="dp_test", base_url=mock_server)
        with pytest.raises(DocParseError):
            c.health()


class TestFormats:
    def test_formats_ok(self, mock_server):
        _set_response(200, {
            "result": json.dumps({
                "parse": ["docx", "pdf", "html"],
                "generate": ["docx", "html"],
                "ai_required": ["pdf"],
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        f = c.formats()
        assert "docx" in f.parse
        assert "pdf" in f.ai_required


class TestParse:
    def test_parse_ok(self, mock_server):
        _set_response(200, {
            "result": json.dumps({
                "status": "ok",
                "filename": "sample.docx",
                "format": "docx",
                "blocks": [
                    {"type": "heading", "text": "Title", "level": 1},
                    {"type": "text", "text": "Body paragraph"},
                ],
                "metadata": {"title": "Sample", "author": "Test"},
                "summary": {"totalBlocks": 2, "headings": 1},
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse("sample.docx")
        assert r.status == "ok"
        assert len(r.blocks) == 2
        assert r.blocks[0].type == "heading"
        assert r.metadata.title == "Sample"
        assert r.summary.total_blocks == 2

    def test_parse_file_uploads_local_file(self, mock_server, tmp_path):
        """Regression test: parse_file must build a multipart upload from a real
        local path. Previously this method referenced ``Path`` without importing
        it, so any caller hit a NameError at runtime."""
        _set_response(200, {
            "result": json.dumps({
                "status": "ok",
                "filename": "upload.docx",
                "format": "docx",
                "blocks": [{"type": "text", "text": "hello"}],
                "metadata": {},
                "summary": {"totalBlocks": 1},
            })
        })
        local = tmp_path / "upload.docx"
        local.write_bytes(b"PK\x03\x04 fake docx bytes")
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse_file(str(local))
        assert r.status == "ok"
        assert r.blocks[0].text == "hello"


# ── Error handling ──

class TestErrors:
    def test_401_raises_auth_error(self, mock_server):
        _set_response(401, {"error": "unauthorized"})
        c = DocParse(api_key="dp_bad", base_url=mock_server)
        with pytest.raises(AuthError):
            c.health()

    def test_429_raises_quota_error(self, mock_server):
        _set_response(429, {"error": "quota exceeded"})
        c = DocParse(api_key="dp_test", base_url=mock_server)
        with pytest.raises(QuotaError):
            c.health()

    def test_envelope_error(self, mock_server):
        _set_response(200, {"error": "parse failed"})
        c = DocParse(api_key="dp_test", base_url=mock_server)
        with pytest.raises(DocParseError, match="parse failed"):
            c.parse("bad.docx")
