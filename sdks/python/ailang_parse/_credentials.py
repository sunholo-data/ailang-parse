"""Credential storage helpers — stdlib only.

Used by both the high-level client (``ailang_parse.client``) and the stdlib-only
MCP CLI bridge (``ailang_parse.cli``). Keeping this module dependency-free means
the bridge runs in minimal environments without pulling in ``requests``.

Storage location:

- Linux/macOS: ``$XDG_CONFIG_HOME/ailang-parse/credentials.json`` (default ``~/.config/ailang-parse/credentials.json``)
- Windows: ``%APPDATA%\\ailang-parse\\credentials.json``

File format:

.. code-block:: json

    {
      "api_key": "dp_...",
      "base_url": "https://docparse.ailang.sunholo.com",
      "key_id": "...",
      "tier": "free",
      "label": "..."
    }
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_BASE_URL = "https://docparse.ailang.sunholo.com"
CONFIG_DIR_NAME = "ailang-parse"
CREDENTIALS_FILE = "credentials.json"


def config_dir() -> Path:
    """Return the platform-appropriate config directory for AILANG Parse."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / CONFIG_DIR_NAME


def credentials_path() -> Path:
    """Return the absolute path to the credentials file."""
    return config_dir() / CREDENTIALS_FILE


def load_saved_key(base_url: str = DEFAULT_BASE_URL) -> Optional[Dict[str, Any]]:
    """Load saved credentials matching ``base_url``, or ``None`` if absent."""
    path = credentials_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("api_key", "").startswith("dp_"):
        return None
    if data.get("base_url", DEFAULT_BASE_URL) != base_url:
        return None
    return data


def save_key(
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    key_id: str = "",
    tier: str = "free",
    label: str = "",
) -> None:
    """Persist credentials to disk with restrictive permissions (0600 file, 0700 dir)."""
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(d, stat.S_IRWXU)  # 0700

    path = d / CREDENTIALS_FILE
    payload = {
        "api_key": api_key,
        "base_url": base_url,
        "key_id": key_id,
        "tier": tier,
        "label": label,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    if sys.platform != "win32":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def resolve_api_key() -> Optional[str]:
    """Resolve any saved API key from env var or credentials file.

    Unlike :func:`load_saved_key`, this does **not** filter by ``base_url`` —
    it returns whatever key is on disk. Used by the MCP CLI bridge, which
    forwards to whatever endpoint the user configured via ``AILANG_PARSE_MCP_URL``
    and just needs *a* key to inject.
    """
    env_key = os.environ.get("DOCPARSE_API_KEY")
    if env_key:
        return env_key
    path = credentials_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    key = data.get("api_key")
    if isinstance(key, str) and key.startswith("dp_"):
        return key
    return None
