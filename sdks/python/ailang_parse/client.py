"""AILANG Parse HTTP client — handles API communication and response unwrapping."""
from __future__ import annotations
import json
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

        outer = resp.json()

        # serve-api wraps responses: {"result": "<json string>", "module": ..., "elapsed_ms": N}
        if "error" in outer and outer["error"]:
            raise DocParseError(outer["error"])

        result_str = outer.get("result", "")
        if not result_str:
            return outer

        # Inner result is a JSON string that needs a second parse
        try:
            return json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            return {"raw": result_str}
