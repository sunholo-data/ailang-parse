package docparse

import (
	"context"
	"encoding/json"
	"fmt"
)

// KeyManager provides API key management methods.
//
// To generate a new key, use client.DeviceAuth(ctx, "my-agent").
type KeyManager struct {
	client *Client
}

// List returns API keys for a user.
func (km *KeyManager) List(ctx context.Context, userID string) (json.RawMessage, error) {
	data, err := km.client.call(ctx, "POST", "/api/v1/keys/list", []string{userID})
	if err != nil {
		return nil, err
	}
	return json.RawMessage(data), nil
}

// Revoke revokes an API key.
func (km *KeyManager) Revoke(ctx context.Context, keyID, userID string) error {
	_, err := km.client.call(ctx, "POST", "/api/v1/keys/revoke", []string{keyID, userID})
	return err
}

// Rotate generates a new key and revokes the old one, preserving tier.
func (km *KeyManager) Rotate(ctx context.Context, keyID, userID string) (*KeyInfo, error) {
	data, err := km.client.call(ctx, "POST", "/api/v1/keys/rotate", []string{keyID, userID})
	if err != nil {
		return nil, err
	}
	var result KeyInfo
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("unmarshal key info: %w", err)
	}
	return &result, nil
}

// KeyInfo returns live usage + quota info for the *currently configured* key.
// An optional keyID can be passed to skip all resolution logic and query
// usage directly.
//
// Resolution order for the key id:
//  1. Explicit keyID variadic parameter.
//  2. c.KeyID (set by saved credentials or DeviceAuth)
//  3. Otherwise call Keys.List("") and find the entry whose `key` field
//     matches c.APIKey. The resolved id is cached on the client.
//
// Returns an error if no path can resolve a key id — the AILANG API
// has no /auth/whoami endpoint, so the SDK needs either a saved credential,
// a list-able admin key, or an explicit keyID.
func (c *Client) KeyInfo(ctx context.Context, keyID ...string) (*UsageInfo, error) {
	if len(keyID) > 0 && keyID[0] != "" {
		return c.Keys.Usage(ctx, keyID[0], "")
	}
	if c.APIKey == "" {
		return nil, newDocParseError("client.KeyInfo() requires an API key on the client", 0)
	}
	if c.KeyID == "" {
		listing, err := c.Keys.List(ctx, "")
		if err != nil {
			return nil, newDocParseError(
				"client.KeyInfo() requires a saved credential or DeviceAuth flow — "+
					"pass keyID explicitly to client.Keys.Usage(): "+err.Error(), 0)
		}
		var parsed struct {
			Keys []struct {
				KeyID  string `json:"key_id"`
				KeyID2 string `json:"keyId"`
				Key    string `json:"key"`
				APIKey string `json:"api_key"`
			} `json:"keys"`
		}
		if err := json.Unmarshal(listing, &parsed); err == nil {
			for _, k := range parsed.Keys {
				if k.Key == c.APIKey || k.APIKey == c.APIKey {
					if k.KeyID != "" {
						c.KeyID = k.KeyID
					} else {
						c.KeyID = k.KeyID2
					}
					if c.KeyID != "" {
						break
					}
				}
			}
		}
		if c.KeyID == "" {
			return nil, newDocParseError(
				"client.KeyInfo() could not resolve key_id — pass it explicitly to client.Keys.Usage()", 0)
		}
	}
	return c.Keys.Usage(ctx, c.KeyID, "")
}

// Usage returns usage statistics for a key.
func (km *KeyManager) Usage(ctx context.Context, keyID, userID string) (*UsageInfo, error) {
	data, err := km.client.call(ctx, "POST", "/api/v1/keys/usage", []string{keyID, userID})
	if err != nil {
		return nil, err
	}
	var result UsageInfo
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("unmarshal usage info: %w", err)
	}
	return &result, nil
}
