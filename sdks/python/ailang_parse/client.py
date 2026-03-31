"""AILANG Parse HTTP client — handles API communication and response unwrapping."""
from __future__ import annotations
import json
import sys
import time
from typing import Any, Dict, Optional

import requests

from .types import (
    DocParseError, AuthError, QuotaError,
    ParseResult, HealthResult, FormatsResult,
)

DEFAULT_BASE_URL = "https://api.parse.sunholo.com"


class DocParse:
    """AILANG Parse API client.

    Usage::

        from ailang_parse import DocParse

        client = DocParse(api_key="dp_a1b2c3d4...")
        result = client.parse("report.docx")
        print(result.blocks)
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        if api_key:
            self._session.headers["x-api-key"] = api_key

        from .keys import KeyManager
        self.keys = KeyManager(self)

    # ── Core API methods ──

    def parse(self, filepath: str, output_format: str = "blocks") -> ParseResult:
        """Parse a document file. Returns structured blocks."""
        data = self._call("POST", "/api/v1/parse", args=[filepath, output_format])
        return ParseResult.from_dict(data)

    def health(self) -> HealthResult:
        """Check API health."""
        data = self._call("GET", "/api/v1/health")
        return HealthResult.from_dict(data)

    def formats(self) -> FormatsResult:
        """List supported formats."""
        data = self._call("GET", "/api/v1/formats")
        return FormatsResult.from_dict(data)

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

        Returns dict with ``api_key``, ``key_id``, ``tier``, ``label``.
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
                return {
                    "api_key": poll_data["api_key"],
                    "key_id": poll_data.get("key_id", ""),
                    "tier": poll_data.get("tier", "free"),
                    "label": poll_data.get("label", label),
                }

            err = poll_data.get("error", "")
            if err and err != "AUTHORIZATION_PENDING":
                raise DocParseError(poll_data.get("message", err))

        raise DocParseError("Device authorization timed out")

    @staticmethod
    def _unwrap(outer: Dict[str, Any]) -> Dict[str, Any]:
        """Unwrap serve-api response envelope."""
        if "error" in outer and outer["error"]:
            raise DocParseError(str(outer["error"]))
        result_str = outer.get("result", "")
        if not result_str:
            return outer
        try:
            return json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            return {"raw": result_str}

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
            raise QuotaError("Quota exceeded", status_code=429)
        if resp.status_code >= 400:
            raise DocParseError(f"API error: {resp.status_code} {resp.text}", resp.status_code)

        return self._unwrap(resp.json())
