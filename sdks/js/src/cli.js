#!/usr/bin/env node

/**
 * @ailang/parse CLI — MCP stdio server for Claude Desktop and other MCP clients.
 *
 * Bridges MCP stdio transport to the hosted AILANG Parse API.
 * No external dependencies — uses Node's built-in fetch (Node >= 18).
 *
 * Usage:
 *   npx @ailang/parse mcp
 *
 * Claude Desktop (claude_desktop_config.json):
 *   { "command": "npx", "args": ["-y", "@ailang/parse", "mcp"] }
 *
 * Environment variables:
 *   AILANG_PARSE_MCP_URL  Override the MCP endpoint (default: hosted API)
 *   DOCPARSE_API_KEY      Pre-set API key (optional — device auth works without it)
 */

import { createInterface } from "node:readline";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { resolveApiKey } from "./credentials.js";

const cmd = process.argv[2];

if (cmd !== "mcp") {
  let pkg = "unknown";
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    pkg = JSON.parse(readFileSync(join(here, "..", "package.json"), "utf8")).version;
  } catch {}
  process.stderr.write(`@ailang/parse v${pkg} — AILANG Parse CLI\n\n`);
  process.stderr.write("Commands:\n");
  process.stderr.write("  mcp    Start MCP stdio server (for Claude Desktop, Cursor, etc.)\n\n");
  process.stderr.write("Claude Desktop config:\n");
  process.stderr.write('  { "command": "npx", "args": ["-y", "@ailang/parse", "mcp"] }\n\n');
  process.stderr.write("More info: https://www.sunholo.com/docparse/mcp.html\n");
  process.exit(cmd === "--help" || cmd === "-h" ? 0 : 1);
}

// ── MCP stdio-to-HTTP bridge ──────────────────────────────────────────

const ENDPOINT =
  process.env.AILANG_PARSE_MCP_URL ||
  "https://docparse.ailang.sunholo.com/mcp/";

const SAVED_API_KEY = resolveApiKey();

let sessionId = null;

// Log to stderr (stdout is reserved for MCP protocol)
function log(msg) {
  process.stderr.write(`[ailang-parse-mcp] ${msg}\n`);
}

log(`Connecting to ${ENDPOINT}`);
if (SAVED_API_KEY) {
  log(`Using saved API key (…${SAVED_API_KEY.slice(-4)})`);
} else {
  log(`No API key found — agent will need to call mcpAuth on first parse`);
}

// Inject the saved apiKey into tools/call params if the tool's schema declares
// apiKey but the agent supplied an empty value. Mutates msg in place.
// We only inject when the field already exists (so we never add params the
// tool's schema doesn't accept).
function injectApiKey(msg) {
  if (!SAVED_API_KEY) return;
  if (msg?.method !== "tools/call") return;
  const args = msg?.params?.arguments;
  if (!args || typeof args !== "object") return;
  if ("apiKey" in args && !args.apiKey) {
    args.apiKey = SAVED_API_KEY;
  }
}

// Serialize requests — MCP protocol is sequential
const queue = [];
let processing = false;
let stdinEnded = false;

function maybeExit() {
  if (stdinEnded && !processing && queue.length === 0) process.exit(0);
}

async function processQueue() {
  if (processing) return;
  processing = true;
  while (queue.length > 0) {
    const msg = queue.shift();
    try {
      await forward(msg);
    } catch (err) {
      if (msg.id != null) {
        write({
          jsonrpc: "2.0",
          id: msg.id,
          error: {
            code: -32000,
            message: `MCP bridge error: ${err.message}`,
          },
        });
      }
      log(`Error forwarding ${msg.method || "unknown"}: ${err.message}`);
    }
  }
  processing = false;
  maybeExit();
}

// Read newline-delimited JSON-RPC from stdin
const rl = createInterface({ input: process.stdin, terminal: false });

rl.on("line", (line) => {
  line = line.trim();
  if (!line) return;

  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return; // skip malformed input
  }

  queue.push(msg);
  processQueue();
});

rl.on("close", () => {
  stdinEnded = true;
  maybeExit();
});

async function forward(msg) {
  injectApiKey(msg);

  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };

  if (sessionId) {
    headers["Mcp-Session-Id"] = sessionId;
  }

  // Also send as Authorization header — server may use either path
  if (SAVED_API_KEY) {
    headers["Authorization"] = `Bearer ${SAVED_API_KEY}`;
  }

  const resp = await fetch(ENDPOINT, {
    method: "POST",
    headers,
    body: JSON.stringify(msg),
  });

  // Track session ID from server
  const sid = resp.headers.get("mcp-session-id");
  if (sid) sessionId = sid;

  // Notifications get 202/204 with no body
  if (resp.status === 202 || resp.status === 204) {
    return;
  }

  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status}: ${body.slice(0, 200)}`);
  }

  const contentType = resp.headers.get("content-type") || "";

  if (contentType.includes("text/event-stream")) {
    // SSE response — each "data: {...}" line is a JSON-RPC message
    const text = await resp.text();
    for (const eventLine of text.split("\n")) {
      if (eventLine.startsWith("data: ")) {
        const data = eventLine.slice(6).trim();
        if (data) {
          process.stdout.write(data + "\n");
        }
      }
    }
  } else {
    // Direct JSON response
    const text = await resp.text();
    if (text.trim()) {
      process.stdout.write(text.trim() + "\n");
    }
  }
}

function write(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}
