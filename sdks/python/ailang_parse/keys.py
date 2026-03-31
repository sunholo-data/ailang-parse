"""AILANG Parse key management — list, revoke, rotate, usage."""
from __future__ import annotations
from typing import TYPE_CHECKING

from .types import KeyInfo, UsageInfo

if TYPE_CHECKING:
    from .client import DocParse


class KeyManager:
    """API key management. Access via ``client.keys``.

    To generate a new key, use ``client.device_auth(label="my-agent")``.
    """

    def __init__(self, client: "DocParse"):
        self._client = client

    def list(self, user_id: str = "", auth_token: str = "") -> dict:
        """List API keys for a user."""
        data = self._client._call("POST", "/api/v1/keys/list", args=[user_id])
        return data

    def revoke(self, key_id: str, user_id: str = "", auth_token: str = "") -> dict:
        """Revoke an API key."""
        data = self._client._call("POST", "/api/v1/keys/revoke", args=[key_id, user_id])
        return data

    def rotate(self, key_id: str, user_id: str = "", auth_token: str = "") -> KeyInfo:
        """Rotate a key — generates new key, revokes old one, preserves tier."""
        data = self._client._call("POST", "/api/v1/keys/rotate", args=[key_id, user_id])
        return KeyInfo.from_dict(data)

    def usage(self, key_id: str, user_id: str = "", auth_token: str = "") -> UsageInfo:
        """Get usage statistics for a key."""
        data = self._client._call("POST", "/api/v1/keys/usage", args=[key_id, user_id])
        return UsageInfo.from_dict(data)
