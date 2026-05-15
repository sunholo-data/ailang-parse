"""AILANG Parse HTTP client — handles API communication and response unwrapping."""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def _replayable_header(resp: "requests.Response") -> bool:
    return (resp.headers.get("X-AilangParse-Replayable", "") or
            resp.headers.get("x-ailangparse-replayable", "")).lower() == "true"


from . import _credentials
from ._credentials import (
    DEFAULT_BASE_URL,
    load_saved_key as _load_saved_key,
    save_key as _save_key,
)
from .types import (
    DocParseError, AuthError, QuotaError,
    ParseResult, ResponseMeta, HealthResult, FormatsResult,
    RetryPolicy,
)


class DocParse:
    """AILANG Parse API client.

    API key resolution order:

    1. Explicit ``api_key`` parameter
    2. ``DOCPARSE_API_KEY`` environment variable
    3. Saved credentials in ``~/.config/ailang-parse/credentials.json``

    Usage::

        from ailang_parse import DocParse

        # Explicit key
        client = DocParse(api_key="dp_a1b2c3d4...")

        # Or auto-load from env / saved credentials
        client = DocParse()
        result = client.parse("report.docx")
        print(result.blocks)

    The default ``timeout`` is 120 seconds.  AI-backed formats (PDF, images)
    routinely exceed that on large documents — set ``timeout=300`` (or higher)
    when parsing PDFs through a remote model.

    Pass ``retry=RetryPolicy(max_retries=3)`` to enable automatic retry on
    5xx responses; the default policy does not retry.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 120,
        retry: Optional["RetryPolicy"] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry = retry or RetryPolicy()
        self._session = requests.Session()

        # Resolve API key: explicit > env var > saved credentials
        self._key_id = ""
        if not api_key:
            api_key = os.environ.get("DOCPARSE_API_KEY", "")
        if not api_key:
            saved = _load_saved_key(self.base_url)
            if saved:
                api_key = saved["api_key"]
                self._key_id = saved.get("key_id", "")

        self.api_key = api_key
        if api_key:
            self._session.headers["x-api-key"] = api_key

        from .keys import KeyManager
        self.keys = KeyManager(self)

    # ── Error handling ──

    @staticmethod
    def _raise_for_response(resp: "requests.Response") -> None:
        """Raise the right exception type from a non-2xx response.

        Populates ``request_id``, ``replayable``, ``details``, and
        ``suggested_fix`` on the exception by reading the response
        headers (via :class:`ResponseMeta`) and the JSON body when
        present.  No-op for 2xx responses.
        """
        if resp.status_code < 400:
            return
        meta = ResponseMeta.from_headers(dict(resp.headers))
        try:
            body = resp.json()
            if not isinstance(body, dict):
                body = None
        except (ValueError, json.JSONDecodeError):
            body = None
        msg = (body or {}).get("error") or (body or {}).get("message") or resp.text
        if isinstance(msg, dict):
            msg = msg.get("message", str(msg))
        suggested = (body or {}).get("suggested_fix", "") or \
                    (body or {}).get("suggestedFix", "")

        common = dict(
            request_id=meta.request_id,
            suggested_fix=suggested,
            details=body,
            replayable=meta.replayable,
        )
        if resp.status_code == 401:
            raise AuthError(msg or "Invalid or missing API key", **common)
        if resp.status_code == 429:
            raise QuotaError(
                msg or "Quota exceeded",
                tier=meta.tier,
                **common,
            )
        raise DocParseError(
            f"API error: {resp.status_code} {msg}",
            status_code=resp.status_code,
            **common,
        )

    def _post(self, url: str, **kwargs) -> "requests.Response":
        """POST with retry policy applied. Use for endpoints that the
        retry policy should govern (parse, parse_file). Other endpoints
        (auth, health, formats) call ``self._session`` directly."""
        return self._send("POST", url, **kwargs)

    def _send(self, method: str, url: str, **kwargs) -> "requests.Response":
        attempt = 0
        last_exc: Optional[Exception] = None
        while True:
            try:
                resp = self._session.request(method, url, **kwargs)
            except requests.RequestException as e:
                # Network-layer errors. Retry on the same statuses we'd
                # retry for HTTP-layer 5xx, capped by max_retries.
                last_exc = e
                if attempt >= self.retry.max_retries:
                    raise
                time.sleep(self.retry.delay_for(attempt))
                attempt += 1
                continue
            if not self.retry.should_retry(resp.status_code,
                                           _replayable_header(resp)) \
                    or attempt >= self.retry.max_retries:
                return resp
            time.sleep(self.retry.delay_for(attempt))
            attempt += 1

    # ── Core API methods ──

    def parse(self, filepath: str, output_format: str = "blocks",
              source_url: str = "") -> ParseResult:
        """Parse a document by sample ID, server-side filepath, or signed URL.

        For uploading local files, use :meth:`parse_file` instead.
        For parsing a URL directly, use :meth:`parse_url` for convenience.

        Args:
            filepath: Sample ID (e.g. ``"sample_docx_formatting"``) or server path.
            output_format: ``"blocks"`` (default), ``"markdown"``, ``"html"``,
                ``"markdown+metadata"``, ``"a2ui"``, or ``"a2ui+editable"``.
            source_url: HTTPS signed URL (GCS, S3, etc.). When provided, the
                server fetches the document from this URL instead of reading
                a local file.
        """
        url = self.base_url + "/api/v1/parse"
        body: Dict[str, Any] = {"filepath": filepath, "outputFormat": output_format}
        if self.api_key:
            body["apiKey"] = self.api_key
        if source_url:
            body["sourceUrl"] = source_url
        resp = self._post(url, json=body, timeout=self.timeout)
        self._raise_for_response(resp)
        meta = ResponseMeta.from_headers(dict(resp.headers))
        result = self._build_parse_result(self._unwrap(resp.json()), output_format)
        result.response_meta = meta
        return result

    def parse_url(self, url: str, output_format: str = "blocks") -> ParseResult:
        """Parse a document from a signed URL (GCS, S3, Azure Blob, etc.).

        The server fetches the document from the URL — no local file needed.
        The URL must be HTTPS and the server enforces tier-based size limits
        (Free: 10 MB, Pro: 25 MB, Business: 50 MB).

        Usage::

            result = client.parse_url(
                "https://storage.googleapis.com/bucket/doc.docx?X-Goog-Signature=...",
                output_format="markdown+metadata",
            )
            print(result.markdown)
        """
        return self.parse(filepath="", output_format=output_format, source_url=url)

    def parse_gs_uri(self, gs_uri: str, *, ttl: int = 900,
                     output_format: str = "blocks",
                     credentials: Optional[Any] = None) -> ParseResult:
        """Sign a ``gs://`` URI and parse the referenced document.

        Convenience wrapper around :meth:`parse_url` that signs a Google
        Cloud Storage URI as a v4 GET URL before sending it to the API.
        Useful when consumer code already holds a ``gs://bucket/key``
        reference and would otherwise rewrite the same signing boilerplate.

        Requires the optional ``[gcs]`` extra::

            pip install 'ailang-parse[gcs]'

        Auth resolution defaults to Application Default Credentials.  Pass
        an explicit ``credentials`` object (any ``google.auth.credentials``
        instance) to override.

        Args:
            gs_uri: ``gs://bucket/key`` reference to a document.
            ttl: Signed URL lifetime in seconds (default 900 = 15 min).
            output_format: Same as :meth:`parse`.
            credentials: Optional ``google.auth.credentials.Credentials``.

        Raises:
            ImportError: ``google-cloud-storage`` is not installed.
            ValueError: ``gs_uri`` is not a well-formed ``gs://`` URI.

        Usage::

            result = client.parse_gs_uri(
                "gs://my-bucket/path/to/doc.pdf",
                ttl=900,
                output_format="markdown+metadata",
            )
        """
        try:
            from google.cloud import storage  # type: ignore
        except ImportError as e:
            raise ImportError(
                "parse_gs_uri requires the 'gcs' extra. "
                "Install with: pip install 'ailang-parse[gcs]'"
            ) from e
        from datetime import timedelta

        if not gs_uri.startswith("gs://"):
            raise ValueError(
                f"parse_gs_uri requires a gs:// URI, got {gs_uri!r}"
            )
        rest = gs_uri[len("gs://"):]
        if "/" not in rest:
            raise ValueError(
                f"gs:// URI missing object key: {gs_uri!r}"
            )
        bucket_name, blob_name = rest.split("/", 1)
        if not bucket_name or not blob_name:
            raise ValueError(f"gs:// URI has empty bucket or key: {gs_uri!r}")

        sc = storage.Client(credentials=credentials) if credentials \
            else storage.Client()
        blob = sc.bucket(bucket_name).blob(blob_name)
        signed = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl),
            method="GET",
        )
        return self.parse_url(signed, output_format=output_format)

    def parse_file(self, filepath: str, output_format: str = "blocks") -> ParseResult:
        """Upload a local file and parse it. Returns structured blocks.

        Uses multipart/form-data to upload the file directly to the API.
        Works on all tiers (Free: 10 MB, Pro: 25 MB, Business: 50 MB).

        Usage::

            result = client.parse_file("report.docx")
            print(result.blocks)
        """
        url = self.base_url + "/api/v1/parse"
        with open(filepath, "rb") as f:
            resp = self._post(
                url,
                files={"filepath": (Path(filepath).name, f)},
                data={"outputFormat": output_format, "apiKey": self.api_key},
                timeout=self.timeout,
            )
        self._raise_for_response(resp)
        meta = ResponseMeta.from_headers(dict(resp.headers))
        result = self._build_parse_result(self._unwrap(resp.json()), output_format)
        result.response_meta = meta
        return result

    @staticmethod
    def _build_parse_result(data: Any, output_format: str) -> ParseResult:
        """Build a ParseResult, handling raw markdown/html and markdown+metadata.

        For ``output_format="markdown"`` / ``"html"`` the API returns a raw
        rendered string instead of a JSON object. ``_unwrap`` surfaces that
        as ``{"raw": "<str>"}``; we promote it to ``ParseResult.text``.

        For ``output_format="markdown+metadata"`` the API returns a JSON object
        with ``markdown``, ``metadata``, ``summary``, and ``sections``. It goes
        through ``from_dict`` normally but has no ``status`` field — we default
        it to ``"ok"``.
        """
        if isinstance(data, dict) and "raw" in data and isinstance(data["raw"], str):
            return ParseResult(
                status="ok",
                format=output_format,
                text=data["raw"],
            )
        if isinstance(data, list):
            return ParseResult(status="ok", format=output_format, nodes=data)
        result = ParseResult.from_dict(data)
        if not result.status and result.format:
            result.status = "ok"
        return result

    def health(self) -> HealthResult:
        """Check API health."""
        data = self._call("GET", "/api/v1/health")
        return HealthResult.from_dict(data)

    def formats(self) -> FormatsResult:
        """List supported formats."""
        data = self._call("GET", "/api/v1/formats")
        return FormatsResult.from_dict(data)

    def key_info(self, key_id: str = ""):
        """Return live usage + quota info for the *currently configured* key.

        Args:
            key_id: Explicit key ID to look up. When provided, skips all
                resolution logic and queries usage directly.

        Resolves the ``key_id`` in this order:

        1. Explicit ``key_id`` parameter
        2. ``self._key_id`` (set by saved credentials or :meth:`device_auth`)
        3. Fall back to ``self.keys.list("")`` and find the entry whose
           ``key`` matches ``self.api_key``. The resolved id is cached.

        Raises :class:`DocParseError` if no path can resolve a key id —
        the AILANG API has no ``/auth/whoami`` endpoint, so the SDK needs
        either a saved credential, a list-able admin key, or an explicit
        ``key_id``.
        """
        if key_id:
            return self.keys.usage(key_id)
        if not self.api_key:
            raise DocParseError(
                "client.key_info() requires an API key on the client"
            )
        if not self._key_id:
            try:
                listing = self.keys.list("")
            except DocParseError as e:
                raise DocParseError(
                    "client.key_info() requires a saved credential or "
                    "device_auth flow — pass key_id explicitly to "
                    f"client.keys.usage(): {e}"
                )
            keys = listing.get("keys", []) if isinstance(listing, dict) else []
            for k in keys:
                if not isinstance(k, dict):
                    continue
                if k.get("key") == self.api_key or k.get("api_key") == self.api_key:
                    self._key_id = k.get("key_id") or k.get("keyId") or ""
                    if self._key_id:
                        break
            if not self._key_id:
                raise DocParseError(
                    "client.key_info() could not resolve key_id — "
                    "pass key_id explicitly to client.keys.usage()"
                )
        return self.keys.usage(self._key_id)

    # ── Device Auth (RFC 8628) ──

    def device_auth(
        self,
        label: str = "default",
        scope: str = "parse",
        open_browser: bool = True,
        poll_interval: Optional[float] = None,
        timeout: float = 900,
    ) -> Dict[str, Any]:
        """Run the device authorization flow to obtain an API key.

        Requests a device code, prints the verification URL (and optionally
        opens the browser), then polls until the user approves.  On success
        the key is stored on this client instance.

        Returns dict with ``api_key``, ``key_id``, ``tier``, ``label``,
        ``verification_url`` and ``poll_url`` (the
        ``/api/v1/auth/device/poll`` endpoint used during the flow).
        """
        # 1. Request device code (unauthenticated)
        resp = self._session.post(
            self.base_url + "/api/v1/auth/device",
            json={"label": label, "scope": scope},
            timeout=30,
        )
        resp.raise_for_status()
        data = self._unwrap(resp.json())

        device_code = data["device_code"]
        user_code = data["user_code"]
        url = data.get("verification_url", "")
        interval = poll_interval or data.get("interval", 5)

        # 2. Print instructions
        print(f"\n  Authorize this device:")
        print(f"  {url}")
        print(f"  Code: {user_code}\n", flush=True)

        # 3. Open browser
        if open_browser and url:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

        # 4. Poll until approved or timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(interval)
            poll_resp = self._session.post(
                self.base_url + "/api/v1/auth/device/poll",
                json={"deviceCode": device_code},
                timeout=30,
            )
            poll_data = self._unwrap(poll_resp.json())

            if poll_data.get("status") == "approved" and poll_data.get("api_key"):
                self.api_key = poll_data["api_key"]
                self._session.headers["x-api-key"] = self.api_key
                self._key_id = poll_data.get("key_id", "")
                result = {
                    "api_key": poll_data["api_key"],
                    "key_id": poll_data.get("key_id", ""),
                    "tier": poll_data.get("tier", "free"),
                    "label": poll_data.get("label", label),
                    "verification_url": url,
                    "poll_url": self.base_url + "/api/v1/auth/device/poll",
                }
                _save_key(
                    api_key=result["api_key"],
                    base_url=self.base_url,
                    key_id=result["key_id"],
                    tier=result["tier"],
                    label=result["label"],
                )
                return result

            err = poll_data.get("error", "")
            if isinstance(err, dict):
                err_code = err.get("code", "")
                if err_code and err_code != "AUTHORIZATION_PENDING":
                    raise DocParseError(err.get("message", str(err)))
            elif err and err != "AUTHORIZATION_PENDING":
                raise DocParseError(poll_data.get("message", err))

        raise DocParseError("Device authorization timed out")

    @staticmethod
    def _is_auth_error_message(msg: str) -> bool:
        """Detect auth-related error messages from server-side envelope errors."""
        if not msg:
            return False
        m = msg.lower()
        return (
            "invalid or expired api key" in m
            or "invalid api key" in m
            or "missing api key" in m
            or "unauthorized" in m
            or "api key required" in m
        )

    @classmethod
    def _raise_envelope_error(cls, msg: str, suggested_fix: str = "",
                              details: Optional[Dict[str, Any]] = None,
                              request_id: str = "") -> None:
        """Raise AuthError for auth-like messages, otherwise DocParseError."""
        if cls._is_auth_error_message(msg):
            raise AuthError(msg, 401, suggested_fix=suggested_fix,
                            details=details, request_id=request_id)
        raise DocParseError(msg, suggested_fix=suggested_fix,
                            details=details, request_id=request_id)

    @classmethod
    def _unwrap(cls, outer: Dict[str, Any]) -> Dict[str, Any]:
        """Unwrap serve-api response envelope."""
        if "error" in outer and outer["error"]:
            err = outer["error"]
            if isinstance(err, str):
                # Check for structured error with message + suggested_fix
                suggested = outer.get("suggested_fix", "")
                msg = outer.get("message", err)
                cls._raise_envelope_error(msg, suggested_fix=suggested)
            if isinstance(err, dict):
                # Structured error envelope: {error: {code, message, details, ...}, request_id}
                msg = err.get("message", str(err))
                suggested = err.get("suggested_fix", "")
                details = err.get("details")
                request_id = outer.get("request_id", "")
                cls._raise_envelope_error(msg, suggested_fix=suggested,
                                          details=details, request_id=request_id)
            # Unknown error shape — return as-is for caller handling
            return outer
        result_str = outer.get("result", "")
        if not result_str:
            return outer
        try:
            inner = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            return {"raw": result_str}
        # Check for error in inner result (API wraps errors in envelope too)
        if isinstance(inner, dict) and "error" in inner and inner["error"]:
            err = inner["error"]
            if isinstance(err, dict):
                msg = err.get("message", str(err))
                suggested = err.get("suggested_fix", "")
                details = err.get("details")
                request_id = inner.get("request_id", "")
                cls._raise_envelope_error(msg, suggested_fix=suggested,
                                          details=details, request_id=request_id)
            else:
                cls._raise_envelope_error(str(err))
        return inner

    # ── HTTP layer ──

    def _call(self, method: str, path: str, args: Optional[list] = None) -> Dict[str, Any]:
        """Make an API call and unwrap the serve-api response envelope."""
        url = self.base_url + path

        if method == "GET":
            resp = self._session.get(url, timeout=self.timeout)
        else:
            body = {"args": args} if args else {}
            resp = self._session.post(
                url, json=body, timeout=self.timeout
            )

        self._raise_for_response(resp)

        return self._unwrap(resp.json())
