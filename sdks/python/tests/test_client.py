"""Tests for DocParse client — mock HTTP server, unwrap logic, error handling."""
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest
from ailang_parse.client import DocParse
from ailang_parse.types import DocParseError, AuthError, QuotaError, ResponseMeta


# ── Mock server ──

class MockHandler(BaseHTTPRequestHandler):
    """Serves canned responses for testing."""

    # Class-level response config — tests set these before making requests.
    response_status = 200
    response_body = {}
    response_headers = {}  # extra headers to include in every response
    last_request_body = None  # captured POST body (bytes)

    def do_GET(self):
        self._respond()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            MockHandler.last_request_body = self.rfile.read(length)
        else:
            MockHandler.last_request_body = None
        self._respond()

    def _respond(self):
        body = json.dumps(self.response_body).encode()
        self.send_response(self.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in self.response_headers.items():
            self.send_header(k, v)
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


def _set_response(status=200, body=None, headers=None):
    MockHandler.response_status = status
    MockHandler.response_body = body or {}
    MockHandler.response_headers = headers or {}
    MockHandler.last_request_body = None


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

    def test_unwrap_outer_auth_error_raises_auth_error(self):
        # Server returns envelope-level error string for a bad key
        with pytest.raises(AuthError):
            DocParse._unwrap({"error": "Invalid or expired API key"})

    def test_unwrap_inner_auth_error_raises_auth_error(self):
        inner = {"error": {"message": "Invalid or expired API key"}}
        outer = {"result": json.dumps(inner)}
        with pytest.raises(AuthError):
            DocParse._unwrap(outer)

    def test_unwrap_inner_unauthorized_raises_auth_error(self):
        inner = {"error": "Unauthorized"}
        outer = {"result": json.dumps(inner)}
        with pytest.raises(AuthError):
            DocParse._unwrap(outer)

    def test_unwrap_non_auth_error_still_docparse_error(self):
        with pytest.raises(DocParseError) as exc_info:
            DocParse._unwrap({"error": "malformed document"})
        # Must NOT be an AuthError
        assert not isinstance(exc_info.value, AuthError)


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

    def test_parse_file_markdown_returns_text(self, mock_server, tmp_path):
        """Regression for #2: when output_format='markdown', the API returns
        a raw string. The SDK must surface it as ParseResult.text instead of
        silently producing an empty result."""
        _set_response(200, {"result": "# Title\n\nBody paragraph\n"})
        local = tmp_path / "doc.md"
        local.write_bytes(b"# hi")
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse_file(str(local), output_format="markdown")
        assert r.status == "ok"
        assert r.text == "# Title\n\nBody paragraph\n"
        assert r.format == "markdown"
        assert r.blocks == []

    def test_parse_html_returns_text(self, mock_server):
        """Same as markdown — output_format='html' returns raw string."""
        _set_response(200, {"result": "<h1>Title</h1>"})
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse("doc.html", output_format="html")
        assert r.status == "ok"
        assert r.text == "<h1>Title</h1>"
        assert r.format == "html"

    def test_parse_markdown_metadata_returns_sections(self, mock_server):
        """Regression for markdown+metadata: returns structured result with
        markdown body, metadata, summary, and heading-sliced sections."""
        inner = {
            "format": "markdown+metadata",
            "filename": "report.docx",
            "markdown": "# Title\n\nBody paragraph",
            "metadata": {"title": "Report", "author": "Alice"},
            "summary": {"totalBlocks": 3, "headings": 1},
            "sections": [
                {"heading": "", "level": 0, "markdown": "Preamble"},
                {"heading": "Title", "level": 1, "markdown": "Body paragraph"},
            ],
        }
        _set_response(200, {"result": json.dumps(inner)})
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse("report.docx", output_format="markdown+metadata")
        assert r.status == "ok"
        assert r.format == "markdown+metadata"
        assert r.markdown == "# Title\n\nBody paragraph"
        assert r.metadata.title == "Report"
        assert r.summary.headings == 1
        assert len(r.sections) == 2
        assert r.sections[0].heading == ""
        assert r.sections[0].level == 0
        assert r.sections[1].heading == "Title"
        assert r.sections[1].level == 1
        assert r.sections[1].markdown == "Body paragraph"
        # blocks should be empty for this format
        assert r.blocks == []

    def test_structured_error_carries_suggested_fix(self, mock_server):
        """Server returns structured error with error code + suggested_fix."""
        _set_response(200, {
            "error": "AUTH_REQUIRED",
            "message": "An API key is required for hosted parsing.",
            "suggested_fix": "Call mcpAuth to start device authorization.",
        })
        c = DocParse(api_key="", base_url=mock_server)
        with pytest.raises(DocParseError) as exc_info:
            c.parse("report.docx")
        assert exc_info.value.suggested_fix == "Call mcpAuth to start device authorization."

    def test_parse_file_bad_key_envelope_raises_auth_error(self, mock_server, tmp_path):
        """Regression for #1: server returns 200 + envelope error for a bad
        key inside parse_file. Must raise AuthError, not generic DocParseError."""
        _set_response(200, {"error": "Invalid or expired API key"})
        local = tmp_path / "doc.docx"
        local.write_bytes(b"PK")
        c = DocParse(api_key="dp_bad", base_url=mock_server)
        with pytest.raises(AuthError):
            c.parse_file(str(local))

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


# ── KeyManager (uses _call internally) ──

class TestKeyManager:
    def test_list(self, mock_server):
        _set_response(200, {
            "result": json.dumps({"status": "ok", "keys": [{"key_id": "k1"}]})
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        out = c.keys.list(user_id="u1")
        assert out["status"] == "ok"
        assert out["keys"][0]["key_id"] == "k1"

    def test_revoke(self, mock_server):
        _set_response(200, {"result": json.dumps({"status": "revoked"})})
        c = DocParse(api_key="dp_test", base_url=mock_server)
        out = c.keys.revoke(key_id="k1", user_id="u1")
        assert out["status"] == "revoked"

    def test_rotate_returns_keyinfo(self, mock_server):
        _set_response(200, {
            "result": json.dumps({
                "status": "active",
                "key": "dp_newkey",
                "keyId": "k2",
                "label": "rotated",
                "tier": "free",
                "created": "2026-04-08",
                "quota": {"requestsPerDay": 50},
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        info = c.keys.rotate(key_id="k1")
        assert info.key == "dp_newkey"
        assert info.tier == "free"
        assert info.quota.requests_per_day == 50

    def test_usage_returns_usageinfo(self, mock_server):
        _set_response(200, {
            "result": json.dumps({
                "status": "ok",
                "keyId": "k1",
                "tier": "free",
                "usage": {"requestsToday": 3, "requestsThisMonth": 10, "totalRequests": 100},
                "quota": {"requestsPerDay": 50, "requestsPerMonth": 1000,
                          "aiLimitPerRequest": 5, "fsLimitPerRequest": 10},
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        u = c.keys.usage(key_id="k1")
        assert u.usage.requests_today == 3
        assert u.quota.requests_per_day == 50

    def test_key_info_uses_stored_key_id(self, mock_server, tmp_path, monkeypatch):
        """If the client has a stored key_id (from saved credentials),
        key_info() should call usage() directly without listing."""
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("DOCPARSE_API_KEY", raising=False)
        _credentials.save_key(
            api_key="dp_saved", base_url=mock_server, key_id="k_saved", tier="pro",
        )
        _set_response(200, {
            "result": json.dumps({
                "status": "ok", "keyId": "k_saved", "tier": "pro",
                "usage": {"requestsToday": 7, "requestsThisMonth": 70, "totalRequests": 700},
                "quota": {"requestsPerDay": 100},
            })
        })
        c = DocParse(base_url=mock_server)
        assert c._key_id == "k_saved"
        info = c.key_info()
        assert info.usage.requests_today == 7
        assert info.tier == "pro"

    def test_key_info_falls_back_to_list(self, mock_server):
        """Without a stored key_id, key_info() should call keys.list() and
        find the entry whose 'key' field matches the configured api_key."""
        _set_response(200, {
            "result": json.dumps({
                "status": "ok",
                "keys": [
                    {"key_id": "k_other", "key": "dp_other"},
                    {"key_id": "k_match", "key": "dp_test"},
                ],
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        # First call: keys.list() — sets _key_id
        # We can't easily mock two responses with the simple handler, so just
        # verify that the resolution path runs and caches.
        # Stub out keys.usage to avoid the second HTTP roundtrip.
        from ailang_parse.types import UsageInfo
        called = {}
        def fake_usage(key_id, *a, **k):
            called["key_id"] = key_id
            return UsageInfo(status="ok", key_id=key_id)
        c.keys.usage = fake_usage  # type: ignore[assignment]
        info = c.key_info()
        assert called["key_id"] == "k_match"
        assert c._key_id == "k_match"
        # Second call: cached, no list lookup
        called.clear()
        c.key_info()
        assert called["key_id"] == "k_match"

    def test_key_info_no_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("DOCPARSE_API_KEY", raising=False)
        c = DocParse(base_url="http://nokey.test")
        with pytest.raises(DocParseError):
            c.key_info()

    def test_keymanager_propagates_auth_error(self, mock_server):
        # Server returns 200 envelope but with auth error string
        _set_response(200, {"error": "Invalid or expired API key"})
        c = DocParse(api_key="dp_bad", base_url=mock_server)
        with pytest.raises(AuthError):
            c.keys.list(user_id="u1")


# ── Unstructured compat ──

class TestUnstructuredCompat:
    def test_partition_returns_elements(self, mock_server):
        from ailang_parse.compat import UnstructuredClient
        _set_response(200, {
            "result": json.dumps([
                {"type": "NarrativeText", "element_id": "abc", "text": "Hello",
                 "metadata": {"filename": "test.docx"}},
                {"type": "Title", "element_id": "def", "text": "Heading", "metadata": {}},
            ])
        })
        uc = UnstructuredClient(server_url=mock_server, api_key="dp_test")
        elements = uc.general.partition(file="sample.docx")
        assert len(elements) == 2
        assert elements[0].type == "NarrativeText"
        assert elements[0].text == "Hello"

    def test_partition_401_raises_auth_error(self, mock_server):
        from ailang_parse.compat import UnstructuredClient
        _set_response(401, {"error": "unauthorized"})
        uc = UnstructuredClient(server_url=mock_server, api_key="dp_bad")
        with pytest.raises(AuthError):
            uc.general.partition(file="sample.docx")

    def test_partition_429_raises_quota_error(self, mock_server):
        from ailang_parse.compat import UnstructuredClient
        _set_response(429, {"error": "quota"})
        uc = UnstructuredClient(server_url=mock_server, api_key="dp_test")
        with pytest.raises(QuotaError):
            uc.general.partition(file="sample.docx")

    def test_partition_envelope_auth_error_routes_to_auth_error(self, mock_server):
        # 200 with auth-error envelope — the production failure mode
        from ailang_parse.compat import UnstructuredClient
        _set_response(200, {"error": "Invalid or expired API key"})
        uc = UnstructuredClient(server_url=mock_server, api_key="dp_bad")
        with pytest.raises(AuthError):
            uc.general.partition(file="sample.docx")

    def test_partition_inner_auth_error_routes_to_auth_error(self, mock_server):
        from ailang_parse.compat import UnstructuredClient
        _set_response(200, {
            "result": json.dumps({"error": {"message": "Invalid or expired API key"}})
        })
        uc = UnstructuredClient(server_url=mock_server, api_key="dp_bad")
        with pytest.raises(AuthError):
            uc.general.partition(file="sample.docx")

    def test_partition_non_auth_envelope_error(self, mock_server):
        from ailang_parse.compat import UnstructuredClient
        _set_response(200, {"error": "parse failed"})
        uc = UnstructuredClient(server_url=mock_server, api_key="dp_test")
        with pytest.raises(DocParseError) as exc_info:
            uc.general.partition(file="sample.docx")
        assert not isinstance(exc_info.value, AuthError)


# ── Credentials file ──

class TestCredentials:
    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        _credentials.save_key(
            api_key="dp_round_trip",
            base_url="https://example.test",
            key_id="k1", tier="pro", label="my-laptop",
        )
        loaded = _credentials.load_saved_key("https://example.test")
        assert loaded is not None
        assert loaded["api_key"] == "dp_round_trip"
        assert loaded["tier"] == "pro"
        assert loaded["label"] == "my-laptop"

    def test_load_returns_none_when_missing(self, tmp_path, monkeypatch):
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert _credentials.load_saved_key("https://example.test") is None

    def test_load_filters_by_base_url(self, tmp_path, monkeypatch):
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        _credentials.save_key(api_key="dp_a", base_url="https://a.test")
        # Asking for a different base URL should miss
        assert _credentials.load_saved_key("https://b.test") is None
        assert _credentials.load_saved_key("https://a.test") is not None

    def test_load_rejects_malformed_json(self, tmp_path, monkeypatch):
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = _credentials.credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        assert _credentials.load_saved_key() is None

    def test_load_rejects_non_dp_prefix(self, tmp_path, monkeypatch):
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = _credentials.credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"api_key": "garbage_no_prefix"}))
        assert _credentials.load_saved_key() is None

    def test_resolve_api_key_prefers_env(self, tmp_path, monkeypatch):
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("DOCPARSE_API_KEY", "dp_env_wins")
        _credentials.save_key(api_key="dp_disk", base_url="https://x.test")
        assert _credentials.resolve_api_key() == "dp_env_wins"

    def test_resolve_api_key_falls_back_to_disk(self, tmp_path, monkeypatch):
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("DOCPARSE_API_KEY", raising=False)
        _credentials.save_key(api_key="dp_disk", base_url="https://x.test")
        assert _credentials.resolve_api_key() == "dp_disk"

    def test_client_loads_saved_key(self, tmp_path, monkeypatch):
        # End-to-end: client constructor picks up the on-disk key
        from ailang_parse import _credentials
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("DOCPARSE_API_KEY", raising=False)
        _credentials.save_key(
            api_key="dp_from_disk",
            base_url="https://disk.test",
        )
        c = DocParse(base_url="https://disk.test")
        assert c.api_key == "dp_from_disk"


# ── sourceUrl in parse() ──

class TestParseSourceUrl:
    def test_parse_sends_source_url_in_body(self, mock_server):
        """parse() with source_url= should include sourceUrl in the POST body."""
        _set_response(200, {
            "result": json.dumps({
                "status": "ok",
                "filename": "remote.docx",
                "format": "docx",
                "blocks": [{"type": "text", "text": "from URL"}],
                "metadata": {},
                "summary": {"totalBlocks": 1},
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse("remote.docx", source_url="https://storage.example.com/doc.docx?sig=abc")
        assert r.status == "ok"
        # Verify the request body contained sourceUrl
        body = json.loads(MockHandler.last_request_body)
        assert body["sourceUrl"] == "https://storage.example.com/doc.docx?sig=abc"

    def test_parse_omits_source_url_when_empty(self, mock_server):
        """When source_url is not provided, sourceUrl should not appear in the body."""
        _set_response(200, {
            "result": json.dumps({
                "status": "ok", "filename": "local.docx", "format": "docx",
                "blocks": [], "metadata": {}, "summary": {"totalBlocks": 0},
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        c.parse("local.docx")
        body = json.loads(MockHandler.last_request_body)
        assert "sourceUrl" not in body

    def test_parse_url_delegates_to_parse(self, mock_server):
        """parse_url() should delegate to parse() with source_url set."""
        _set_response(200, {
            "result": json.dumps({
                "status": "ok", "filename": "", "format": "pdf",
                "blocks": [{"type": "text", "text": "hello"}],
                "metadata": {}, "summary": {"totalBlocks": 1},
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse_url("https://bucket.example.com/report.pdf?token=xyz")
        assert r.status == "ok"
        body = json.loads(MockHandler.last_request_body)
        assert body["sourceUrl"] == "https://bucket.example.com/report.pdf?token=xyz"
        assert body["filepath"] == ""


# ── Response meta captured in parse result ──

class TestResponseMetaCapture:
    def test_parse_populates_response_meta(self, mock_server):
        """After a successful parse(), result.response_meta should be populated
        from the HTTP response headers."""
        _set_response(
            200,
            {
                "result": json.dumps({
                    "status": "ok", "filename": "test.docx", "format": "docx",
                    "blocks": [{"type": "text", "text": "hi"}],
                    "metadata": {}, "summary": {"totalBlocks": 1},
                })
            },
            headers={
                "X-Request-Id": "req_meta_test",
                "X-DocParse-Tier": "pro",
                "X-DocParse-Quota-Remaining-Day": "42",
                "X-DocParse-Quota-Remaining-Month": "900",
                "X-DocParse-Quota-Remaining-Ai": "100",
                "X-AilangParse-Format": "docx",
                "X-AilangParse-Replayable": "true",
            },
        )
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse("test.docx")
        assert r.response_meta is not None
        assert r.response_meta.request_id == "req_meta_test"
        assert r.response_meta.tier == "pro"
        assert r.response_meta.quota_remaining_day == 42
        assert r.response_meta.quota_remaining_month == 900
        assert r.response_meta.quota_remaining_ai == 100
        assert r.response_meta.format == "docx"
        assert r.response_meta.replayable is True

    def test_parse_response_meta_defaults_when_no_headers(self, mock_server):
        """When the server sends no custom headers, response_meta should still
        exist with default values."""
        _set_response(200, {
            "result": json.dumps({
                "status": "ok", "filename": "plain.docx", "format": "docx",
                "blocks": [], "metadata": {}, "summary": {"totalBlocks": 0},
            })
        })
        c = DocParse(api_key="dp_test", base_url=mock_server)
        r = c.parse("plain.docx")
        assert r.response_meta is not None
        assert r.response_meta.request_id == ""
        assert r.response_meta.tier == ""
        assert r.response_meta.quota_remaining_day == -1
        assert r.response_meta.replayable is False
