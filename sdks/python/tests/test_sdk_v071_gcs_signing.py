"""Tests for v0.7.1: parse_gs_uri signing strategy on Cloud Run / GCE.

The bug: v0.6.0 called ``blob.generate_signed_url()`` without the IAM
``service_account_email`` / ``access_token`` params, which fails on the
Cloud Run default service account (token-only credentials, no private
key). v0.7.1 auto-detects token-only creds and routes them through IAM
SignBlob instead.

These tests stub out ``google.cloud.storage`` and the credential types
so we can assert which call path is taken without hitting real GCS.
"""
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest

from ailang_parse import DocParse
from ailang_parse.client import (
    _can_sign_locally,
    _refresh_credentials_if_needed,
)


# ── _can_sign_locally helper ──

class TestCanSignLocally:
    def test_no_signer_attr(self):
        creds = SimpleNamespace(token="t")
        assert _can_sign_locally(creds) is False

    def test_signer_without_key(self):
        """compute_engine.Credentials.signer has no `key` (uses IAM)."""
        creds = SimpleNamespace(signer=SimpleNamespace(), token="t")
        assert _can_sign_locally(creds) is False

    def test_signer_with_key(self):
        """service_account.Credentials.signer has a `.key` private key."""
        creds = SimpleNamespace(
            signer=SimpleNamespace(key="-----BEGIN PRIVATE KEY-----"),
            token="t",
        )
        assert _can_sign_locally(creds) is True

    def test_none_credentials(self):
        assert _can_sign_locally(None) is False


# ── _refresh_credentials_if_needed helper ──

class TestRefreshIfNeeded:
    def test_valid_with_token_skips_refresh(self):
        called = []
        creds = SimpleNamespace(valid=True, token="abc",
                                refresh=lambda req: called.append(req))
        _refresh_credentials_if_needed(creds)
        assert called == []

    def test_swallows_refresh_errors(self):
        def boom(req):
            raise RuntimeError("network down")
        creds = SimpleNamespace(valid=False, token=None, refresh=boom)
        # Should not raise — downstream call will surface a precise error.
        _refresh_credentials_if_needed(creds)


# ── parse_gs_uri signing branch selection ──

def _stub_storage_module():
    """Build a fake google.cloud.storage module exposing the minimum API
    parse_gs_uri touches: Client().bucket().blob().generate_signed_url().
    Returns the module + a list capturing every generate_signed_url call.
    """
    calls = []

    class FakeBlob:
        def __init__(self, name):
            self.name = name

        def generate_signed_url(self, **kwargs):
            calls.append(kwargs)
            return "https://signed.example/" + self.name

    class FakeBucket:
        def __init__(self, name):
            self.name = name

        def blob(self, name):
            return FakeBlob(name)

    class FakeClient:
        def __init__(self, credentials=None):
            self.credentials = credentials

        def bucket(self, name):
            return FakeBucket(name)

    storage = SimpleNamespace(Client=FakeClient)
    return storage, calls


@pytest.fixture
def stubbed_storage(monkeypatch):
    storage, calls = _stub_storage_module()
    # `from google.cloud import storage` resolves through the import
    # machinery — install a placeholder package.
    google = sys.modules.get("google") or SimpleNamespace()
    google_cloud = sys.modules.get("google.cloud") or SimpleNamespace()
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage)
    google_cloud.storage = storage
    return calls


@pytest.fixture
def stubbed_parse_url(monkeypatch):
    """Replace parse_url so we can assert it received the signed URL
    without making an HTTP call."""
    captured = {}

    def fake_parse_url(self, url, output_format="blocks"):
        captured["url"] = url
        captured["output_format"] = output_format
        from ailang_parse import ParseResult
        return ParseResult(status="ok", text=url)

    monkeypatch.setattr(DocParse, "parse_url", fake_parse_url)
    return captured


class TestParseGsUriBranches:
    def test_token_only_creds_use_iam_signing(self, stubbed_storage, stubbed_parse_url):
        """Cloud Run default: signer has no `key`, but service_account_email
        is set. Must use the IAM SignBlob path."""
        calls = stubbed_storage
        creds = SimpleNamespace(
            signer=SimpleNamespace(),  # no .key
            service_account_email="run-sa@proj.iam.gserviceaccount.com",
            token="ya29.fake-token",
            valid=True,
        )

        client = DocParse(api_key="dp_x")
        client.parse_gs_uri("gs://bucket/key.pdf", credentials=creds)

        assert len(calls) == 1
        kwargs = calls[0]
        assert kwargs["service_account_email"] == "run-sa@proj.iam.gserviceaccount.com"
        assert kwargs["access_token"] == "ya29.fake-token"
        assert kwargs["version"] == "v4"
        assert kwargs["method"] == "GET"
        assert stubbed_parse_url["url"].startswith("https://signed.example/")

    def test_sa_json_creds_sign_locally(self, stubbed_storage, stubbed_parse_url):
        """JSON-key creds: signer has a `key`, no IAM kwargs should be
        passed."""
        calls = stubbed_storage
        creds = SimpleNamespace(
            signer=SimpleNamespace(key="PRIVATE-KEY"),
            service_account_email="sa@proj.iam.gserviceaccount.com",
            token="not-needed",
            valid=True,
        )

        client = DocParse(api_key="dp_x")
        client.parse_gs_uri("gs://bucket/key.pdf", credentials=creds)

        assert len(calls) == 1
        kwargs = calls[0]
        assert "service_account_email" not in kwargs
        assert "access_token" not in kwargs

    def test_explicit_sa_email_overrides(self, stubbed_storage, stubbed_parse_url):
        """Explicit service_account_email= wins over credentials attr."""
        calls = stubbed_storage
        creds = SimpleNamespace(
            signer=SimpleNamespace(),
            service_account_email="default@proj.iam.gserviceaccount.com",
            token="t",
            valid=True,
        )

        client = DocParse(api_key="dp_x")
        client.parse_gs_uri(
            "gs://bucket/key.pdf",
            credentials=creds,
            service_account_email="impersonated@proj.iam.gserviceaccount.com",
        )

        assert calls[0]["service_account_email"] == "impersonated@proj.iam.gserviceaccount.com"

    def test_token_only_creds_without_email_falls_through(
            self, stubbed_storage, stubbed_parse_url):
        """End-user gcloud creds: no signer key, no service_account_email.
        We let generate_signed_url be called without IAM kwargs; it will
        fail loudly with the native error message — better than masking."""
        calls = stubbed_storage
        creds = SimpleNamespace(
            signer=SimpleNamespace(),
            token="t",
            valid=True,
        )

        client = DocParse(api_key="dp_x")
        client.parse_gs_uri("gs://bucket/key.pdf", credentials=creds)

        kwargs = calls[0]
        assert "service_account_email" not in kwargs

    def test_invalid_gs_uri_rejected(self, stubbed_storage):
        client = DocParse(api_key="dp_x")
        with pytest.raises(ValueError, match="gs://"):
            client.parse_gs_uri("https://foo/bar.pdf")
        with pytest.raises(ValueError, match="object key"):
            client.parse_gs_uri("gs://bucket-only")
        with pytest.raises(ValueError, match="empty"):
            client.parse_gs_uri("gs://bucket/")

    def test_ttl_propagates_to_expiration(self, stubbed_storage, stubbed_parse_url):
        calls = stubbed_storage
        creds = SimpleNamespace(
            signer=SimpleNamespace(key="K"),
            service_account_email="sa@p.iam.gserviceaccount.com",
            valid=True,
        )
        client = DocParse(api_key="dp_x")
        client.parse_gs_uri("gs://bucket/k.pdf", credentials=creds, ttl=300)

        assert calls[0]["expiration"] == timedelta(seconds=300)
