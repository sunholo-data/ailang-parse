"""AILANG Parse key management — generate, list, revoke, rotate, usage."""
from __future__ import annotations
from typing import TYPE_CHECKING

from .types import KeyInfo, UsageInfo

if TYPE_CHECKING:
    from .client import DocParse


class KeyManager:
    """API key management. Access via ``client.keys``."""

    def __init__(self, client: "DocParse"):
        self._client = client

    def generate(self, label: str = "default", user_id: str = "", auth_token: str = "") -> KeyInfo:
        """Generate a new API key.

        .. deprecated:: 0.10.0
            Direct key generation removed. Use the device auth flow instead:
            1. POST /api/v1/auth/device → get device_code + user_code
            2. POST /api/v1/auth/device/approve (with Firebase Bearer token)
            3. POST /api/v1/auth/device/poll → get api_key
        """
        raise NotImplementedError(
            "Direct key generation removed in v0.10.0. Use device auth flow: "
            "POST /api/v1/auth/device → approve → poll"
        )

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
