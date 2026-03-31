/** AILANG Parse key management — list, revoke, rotate, usage.
 *
 * To generate a new key, use `client.deviceAuth({ label: "my-agent" })`.
 */

import type { KeyInfo, UsageInfo } from "./types.js";
import type { DocParse } from "./client.js";

export class KeyManager {
  private client: DocParse;

  constructor(client: DocParse) {
    this.client = client;
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
