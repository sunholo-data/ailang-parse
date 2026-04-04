"""Unstructured API compatibility — drop-in replacement for unstructured-client."""
from __future__ import annotations
import json
import os
from typing import List, Optional

import requests

from .types import Element, DocParseError

DEFAULT_BASE_URL = "https://docparse.ailang.sunholo.com"


class _GeneralApi:
    """Mimics unstructured_client.general.GeneralApi."""

    def __init__(self, session: requests.Session, base_url: str, timeout: int):
        self._session = session
        self._base_url = base_url
        self._timeout = timeout

    def partition(self, file: str = "", strategy: str = "auto", **kwargs) -> List[Element]:
        """Partition a document — returns Unstructured-format elements.

        Usage (identical to unstructured-client)::

            elements = client.general.partition(file="report.docx")

        Note: ``file`` must be a sample ID or server-side path, not a local
        file path.  The ``/general/v0/general`` endpoint does not yet support
        multipart file upload.  To upload local files, use
        :class:`~ailang_parse.DocParse` with :meth:`~ailang_parse.DocParse.parse_file`::

            from ailang_parse import DocParse
            result = DocParse(api_key="dp_...").parse_file("report.docx")
        """
        url = f"{self._base_url}/general/v0/general"
        resp = self._session.post(
            url,
            json={"filepath": file, "strategy": strategy},
            timeout=self._timeout,
        )

        if resp.status_code >= 400:
            raise DocParseError(f"API error: {resp.status_code}", resp.status_code)

        outer = resp.json()
        if "error" in outer and outer["error"]:
            raise DocParseError(outer["error"])

        result_str = outer.get("result", "[]")
        try:
            elements_raw = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            return []

        # Check for error in inner result
        if isinstance(elements_raw, dict) and "error" in elements_raw:
            err = elements_raw["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise DocParseError(msg)

        if isinstance(elements_raw, list):
            return [Element.from_dict(e) for e in elements_raw]
        return []


class UnstructuredClient:
    """Drop-in replacement for ``unstructured_client.UnstructuredClient``.

    Migration::

        # Before
        from unstructured_client import UnstructuredClient
        client = UnstructuredClient(server_url="https://api.unstructured.io")

        # After — one import change
        from ailang_parse import UnstructuredClient
        client = UnstructuredClient(
            server_url="https://api.parse.sunholo.com"
        )
        # All existing code works unchanged
    """

    def __init__(
        self,
        server_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        timeout: int = 60,
        **kwargs,  # Accept extra args for compat
    ):
        self._session = requests.Session()
        # Resolve key: explicit > env var > saved credentials
        if not api_key:
            api_key = os.environ.get("DOCPARSE_API_KEY", "")
        if not api_key:
            from .client import _load_saved_key
            saved = _load_saved_key(server_url.rstrip("/"))
            if saved:
                api_key = saved["api_key"]
        if api_key:
            self._session.headers["unstructured-api-key"] = api_key
        self._base_url = server_url.rstrip("/")
        self._timeout = timeout
        self.general = _GeneralApi(self._session, self._base_url, self._timeout)
