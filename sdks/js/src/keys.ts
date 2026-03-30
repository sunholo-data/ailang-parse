/** AILANG Parse key management — generate, list, revoke, rotate, usage. */

import type { KeyInfo, UsageInfo } from "./types.js";
import type { DocParse } from "./client.js";

export class KeyManager {
  private client: DocParse;

  constructor(client: DocParse) {
    this.client = client;
  }

  /**
   * Generate a new API key via the device auth flow.
   * Note: Direct key generation endpoint has been removed (v0.10.0).
   * Use the device auth flow instead:
   *   1. POST /api/v1/auth/device → get device_code + user_code
   *   2. POST /api/v1/auth/device/approve (with Firebase Bearer token)
   *   3. POST /api/v1/auth/device/poll → get api_key
   * @deprecated Use DeviceAuth flow instead
   */
  async generate(_label = "default", _userId = ""): Promise<KeyInfo> {
    throw new Error(
      "Direct key generation removed in v0.10.0. Use device auth flow: " +
      "POST /api/v1/auth/device → approve → poll"
    );
  }

  /** List API keys for a user. */
  async list(userId = ""): Promise<any> {
    return this.client._call("POST", "/api/v1/keys/list", [userId]);
  }

  /** Revoke an API key. */
  async revoke(keyId: string, userId = ""): Promise<any> {
    return this.client._call("POST", "/api/v1/keys/revoke", [keyId, userId]);
  }

  /** Rotate a key — generates new, revokes old, preserves tier. */
  async rotate(keyId: string, userId = ""): Promise<KeyInfo> {
    return this.client._call("POST", "/api/v1/keys/rotate", [keyId, userId]);
  }

  /** Get usage statistics for a key. */
  async usage(keyId: string, userId = ""): Promise<UsageInfo> {
    return this.client._call("POST", "/api/v1/keys/usage", [keyId, userId]);
  }
}
