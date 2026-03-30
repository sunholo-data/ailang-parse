package docparse

import (
	"context"
	"encoding/json"
	"fmt"
)

// KeyManager provides API key management methods.
type KeyManager struct {
	client *Client
}

// Generate is deprecated. Direct key generation was removed in v0.10.0.
// Use the device auth flow instead:
//  1. POST /api/v1/auth/device       → get device_code + user_code
//  2. POST /api/v1/auth/device/approve (with Firebase Bearer token)
//  3. POST /api/v1/auth/device/poll   → get api_key
//
// Deprecated: Use DeviceAuth methods instead.
func (km *KeyManager) Generate(ctx context.Context, label, userID string) (*KeyInfo, error) {
	return nil, fmt.Errorf(
		"direct key generation removed in v0.10.0; use device auth flow: " +
			"POST /api/v1/auth/device → approve → poll")
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
