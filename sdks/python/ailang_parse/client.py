"""AILANG Parse HTTP client — handles API communication and response unwrapping."""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from . import _credentials
from ._credentials import (
    DEFAULT_BASE_URL,
    load_saved_key as _load_saved_key,
    save_key as _save_key,
)
from .types import (
    DocParseError, AuthError, QuotaError,
    ParseResult, HealthResult, FormatsResult,
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
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
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

    # ── Core API methods ──

    def parse(self, filepath: str, output_format: str = "blocks") -> ParseResult:
        """Parse a document by sample ID or server-side filepath. Returns structured blocks.

        For uploading local files, use :meth:`parse_file` instead.
        """
        url = self.base_url + "/api/v1/parse"
        body: Dict[str, Any] = {"filepath": filepath, "outputFormat": output_format}
        if self.api_key:
            body["apiKey"] = self.api_key
        resp = self._session.post(url, json=body, timeout=self.timeout)
        if resp.status_code == 401:
            raise AuthError("Invalid or missing API key", 401)
        if resp.status_code == 429:
            raise QuotaError("Quota exceeded")
        if resp.status_code >= 400:
            raise DocParseError(f"API error: {resp.status_code} {resp.text}", resp.status_code)
        return self._build_parse_result(self._unwrap(resp.json()), output_format)

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
            resp = self._session.post(
                url,
                files={"filepath": (Path(filepath).name, f)},
                data={"outputFormat": output_format, "apiKey": self.api_key},
                timeout=self.timeout,
            )
        if resp.status_code == 401:
            raise AuthError("Invalid or missing API key", 401)
        if resp.status_code == 429:
            raise QuotaError("Quota exceeded")
        if resp.status_code >= 400:
            raise DocParseError(f"API error: {resp.status_code} {resp.text}", resp.status_code)
        return self._build_parse_result(self._unwrap(resp.json()), output_format)

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

    def key_info(self):
        """Return live usage + quota info for the *currently configured* key.

        Resolves the ``key_id`` in this order:

        1. ``self._key_id`` (set by saved credentials or :meth:`device_auth`)
        2. Fall back to ``self.keys.list("")`` and find the entry whose
           ``key`` matches ``self.api_key``. The resolved id is cached.

        Raises :class:`DocParseError` if neither path can resolve a key id —
        the AILANG API has no ``/auth/whoami`` endpoint, so the SDK needs
        either a saved credential or a list-able admin key.
        """
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
    def _raise_envelope_error(cls, msg: str, suggested_fix: str = "") -> None:
        """Raise AuthError for auth-like messages, otherwise DocParseError."""
        if cls._is_auth_error_message(msg):
            raise AuthError(msg, 401, suggested_fix=suggested_fix)
        raise DocParseError(msg, suggested_fix=suggested_fix)

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
            # Dict errors (e.g. device auth poll) — return as-is for caller handling
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
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            cls._raise_envelope_error(msg)
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

        if resp.status_code == 401:
            raise AuthError("Invalid or missing API key", 401)
        if resp.status_code == 429:
            raise QuotaError("Quota exceeded")
        if resp.status_code >= 400:
            raise DocParseError(f"API error: {resp.status_code} {resp.text}", resp.status_code)

        return self._unwrap(resp.json())
