/**
 * Credential storage helpers — Node stdlib only.
 *
 * Used by both the high-level client (`client.ts`) and the stdlib-only
 * MCP CLI bridge (`cli.js`). Plain JS so the bridge runs without any
 * TypeScript tooling and consumers don't pay a compile cost for it.
 *
 * Storage location:
 *   - macOS/Linux: $XDG_CONFIG_HOME/ailang-parse/credentials.json
 *                  (default ~/.config/ailang-parse/credentials.json)
 *   - Windows:     %APPDATA%\ailang-parse\credentials.json
 *
 * File format:
 *   {
 *     "api_key":  "dp_...",
 *     "base_url": "https://docparse.ailang.sunholo.com",
 *     "key_id":   "...",
 *     "tier":     "free",
 *     "label":    "..."
 *   }
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, platform } from "node:os";
import { join } from "node:path";

export const DEFAULT_BASE_URL = "https://docparse.ailang.sunholo.com";
const CONFIG_DIR_NAME = "ailang-parse";
const CREDENTIALS_FILE = "credentials.json";

/** Return the platform-appropriate config directory, or null in browsers. */
export function configDir() {
  try {
    if (platform() === "win32") {
      const base = process.env.APPDATA || join(homedir(), "AppData", "Roaming");
      return join(base, CONFIG_DIR_NAME);
    }
    const base = process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
    return join(base, CONFIG_DIR_NAME);
  } catch {
    return null; // browser — no filesystem
  }
}

/** Return the absolute credentials file path, or null in browsers. */
export function credentialsPath() {
  const dir = configDir();
  return dir ? join(dir, CREDENTIALS_FILE) : null;
}

/**
 * Load saved credentials matching `baseUrl`. Returns null if absent or
 * the saved entry is for a different base_url.
 */
export function loadSavedKey(baseUrl = DEFAULT_BASE_URL) {
  try {
    const path = credentialsPath();
    if (!path || !existsSync(path)) return null;
    const data = JSON.parse(readFileSync(path, "utf-8"));
    if (data?.api_key?.startsWith("dp_") && (data.base_url || DEFAULT_BASE_URL) === baseUrl) {
      return data;
    }
  } catch {}
  return null;
}

/**
 * Resolve any saved API key from env var or credentials file.
 *
 * Unlike `loadSavedKey`, this does NOT filter by base_url — it returns
 * whatever key is on disk. Used by the MCP CLI bridge, which forwards
 * to whatever endpoint the user configured via AILANG_PARSE_MCP_URL
 * and just needs *a* key to inject.
 */
export function resolveApiKey() {
  if (process.env.DOCPARSE_API_KEY) return process.env.DOCPARSE_API_KEY;
  try {
    const path = credentialsPath();
    if (!path || !existsSync(path)) return null;
    const data = JSON.parse(readFileSync(path, "utf-8"));
    if (typeof data?.api_key === "string" && data.api_key.startsWith("dp_")) {
      return data.api_key;
    }
  } catch {}
  return null;
}

/** Persist credentials to disk with restrictive permissions (0600 file, 0700 dir). */
export function saveKey(apiKey, baseUrl = DEFAULT_BASE_URL, keyId = "", tier = "free", label = "") {
  try {
    const dir = configDir();
    if (!dir) return;
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    const path = join(dir, CREDENTIALS_FILE);
    const payload = JSON.stringify(
      { api_key: apiKey, base_url: baseUrl, key_id: keyId, tier, label },
      null,
      2,
    ) + "\n";
    writeFileSync(path, payload, { mode: 0o600 });
  } catch {
    // ignore — browser or permission error
  }
}
