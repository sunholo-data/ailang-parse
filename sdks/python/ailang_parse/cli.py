"""ailang-parse CLI — MCP stdio server for Claude Desktop and other MCP clients.

Bridges MCP stdio transport to the hosted AILANG Parse API.
Stdlib only — no external dependencies (so the CLI works in minimal envs).

Usage:
    ailang-parse mcp

Claude Desktop (claude_desktop_config.json):
    { "command": "uvx", "args": ["ailang-parse", "mcp"] }
    # or
    { "command": "python", "args": ["-m", "ailang_parse.cli", "mcp"] }

Environment variables:
    AILANG_PARSE_MCP_URL  Override the MCP endpoint (default: hosted API)
    DOCPARSE_API_KEY      Pre-set API key (optional — device auth works without it)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from ._credentials import resolve_api_key

DEFAULT_ENDPOINT = "https://docparse.ailang.sunholo.com/mcp/"

# Module-level session state — captured from server's first response
_session_id: str | None = None
_saved_api_key: str | None = None


def _inject_api_key(msg: dict) -> None:
    """Inject saved apiKey into tools/call params if the agent left it empty."""
    if not _saved_api_key:
        return
    if msg.get("method") != "tools/call":
        return
    args = msg.get("params", {}).get("arguments")
    if not isinstance(args, dict):
        return
    if "apiKey" in args and not args["apiKey"]:
        args["apiKey"] = _saved_api_key


def _log(msg: str) -> None:
    """Write to stderr (stdout is reserved for MCP protocol)."""
    print(f"[ailang-parse-mcp] {msg}", file=sys.stderr, flush=True)


def _write(obj: dict) -> None:
    """Write a JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _forward(msg: dict, endpoint: str) -> None:
    """Forward a single JSON-RPC message to the MCP HTTP endpoint."""
    global _session_id

    _inject_api_key(msg)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if _session_id:
        headers["Mcp-Session-Id"] = _session_id

    if _saved_api_key:
        headers["Authorization"] = f"Bearer {_saved_api_key}"

    body = json.dumps(msg).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req) as resp:
            _handle_response(resp)
    except urllib.error.HTTPError as e:
        # Read error body for context
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            err_body = ""
        raise RuntimeError(f"HTTP {e.code}: {err_body}")


def _handle_response(resp) -> None:
    """Parse server response (SSE or JSON), capture session ID, write to stdout."""
    global _session_id

    sid = resp.headers.get("Mcp-Session-Id")
    if sid:
        _session_id = sid

    status = resp.status
    # Notifications get 202/204 with no body
    if status in (202, 204):
        return

    content_type = resp.headers.get("Content-Type", "")
    body = resp.read().decode("utf-8", errors="replace")

    if "text/event-stream" in content_type:
        # SSE response — each "data: {...}" line is a JSON-RPC message
        for line in body.split("\n"):
            if line.startswith("data: "):
                data = line[6:].strip()
                if data:
                    sys.stdout.write(data + "\n")
                    sys.stdout.flush()
    else:
        # Direct JSON response
        text = body.strip()
        if text:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()


def _run_mcp() -> int:
    """Run the MCP stdio bridge until stdin closes."""
    global _saved_api_key
    endpoint = os.environ.get("AILANG_PARSE_MCP_URL", DEFAULT_ENDPOINT)
    _log(f"Connecting to {endpoint}")
    _saved_api_key = resolve_api_key()
    if _saved_api_key:
        _log(f"Using saved API key (…{_saved_api_key[-4:]})")
    else:
        _log("No API key found — agent will need to call mcpAuth on first parse")

    # Read newline-delimited JSON-RPC, process serially
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip malformed input

        try:
            _forward(msg, endpoint)
        except Exception as e:
            err_msg = str(e)
            method = msg.get("method", "unknown") if isinstance(msg, dict) else "unknown"
            # Send JSON-RPC error for requests (has id), skip for notifications
            if isinstance(msg, dict) and msg.get("id") is not None:
                _write({
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "error": {
                        "code": -32000,
                        "message": f"MCP bridge error: {err_msg}",
                    },
                })
            _log(f"Error forwarding {method}: {err_msg}")

    return 0


def _print_help() -> None:
    try:
        from . import __version__ as version
    except ImportError:
        version = "unknown"
    sys.stderr.write(f"ailang-parse v{version} — AILANG Parse CLI\n\n")
    sys.stderr.write("Commands:\n")
    sys.stderr.write("  mcp    Start MCP stdio server (for Claude Desktop, Cursor, etc.)\n\n")
    sys.stderr.write("Claude Desktop config:\n")
    sys.stderr.write('  { "command": "uvx", "args": ["ailang-parse", "mcp"] }\n\n')
    sys.stderr.write("More info: https://www.sunholo.com/docparse/mcp.html\n")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    if cmd == "mcp":
        return _run_mcp()
    _print_help()
    return 0 if cmd in ("--help", "-h") else 1


if __name__ == "__main__":
    sys.exit(main())
