"""AILANG Parse HTTP client — handles API communication and response unwrapping."""
from __future__ import annotations
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .types import (
    DocParseError, AuthError, QuotaError,
    ParseResult, HealthResult, FormatsResult,
)

DEFAULT_BASE_URL = "https://docparse.ailang.sunholo.com"
_CONFIG_DIR_NAME = "ailang-parse"
_CREDENTIALS_FILE = "credentials.json"


def _config_dir() -> Path:
    """Return the platform-appropriate config directory for AILANG Parse.

    - Linux/macOS: ``$XDG_CONFIG_HOME/ailang-parse`` or ``~/.config/ailang-parse``
    - Windows: ``%APPDATA%\\ailang-parse``
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / _CONFIG_DIR_NAME


def _load_saved_key(base_url: str) -> Optional[Dict[str, Any]]:
    """Load saved credentials for *base_url*, or return None."""
    cred_path = _config_dir() / _CREDENTIALS_FILE
    if not cred_path.exists():
        return None
    try:
        data = json.loads(cred_path.read_text())
        if isinstance(data, dict) and data.get("api_key", "").startswith("dp_"):
            if data.get("base_url", DEFAULT_BASE_URL) == base_url:
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_key(
    api_key: str,
    base_url: str,
    key_id: str = "",
    tier: str = "free",
    label: str = "",
) -> None:
    """Persist credentials to disk with restrictive permissions."""
    d = _config_dir()
    d.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(d, stat.S_IRWXU)  # 0700

    cred_path = d / _CREDENTIALS_FILE
    payload = {
        "api_key": api_key,
        "base_url": base_url,
        "key_id": key_id,
        "tier": tier,
        "label": label,
    }
    cred_path.write_text(json.dumps(payload, indent=2) + "\n")
    if sys.platform != "win32":
        os.chmod(cred_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


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
        if not api_key:
            api_key = os.environ.get("DOCPARSE_API_KEY", "")
        if not api_key:
            saved = _load_saved_key(self.base_url)
            if saved:
                api_key = saved["api_key"]

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
        return ParseResult.from_dict(self._unwrap(resp.json()))

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
        return ParseResult.from_dict(self._unwrap(resp.json()))

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
                result = {
                    "api_key": poll_data["api_key"],
                    "key_id": poll_data.get("key_id", ""),
                    "tier": poll_data.get("tier", "free"),
                    "label": poll_data.get("label", label),
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
    def _unwrap(outer: Dict[str, Any]) -> Dict[str, Any]:
        """Unwrap serve-api response envelope."""
        if "error" in outer and outer["error"]:
            err = outer["error"]
            if isinstance(err, str):
                raise DocParseError(err)
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
            raise DocParseError(msg)
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
