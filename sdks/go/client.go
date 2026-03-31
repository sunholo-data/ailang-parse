package docparse

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

const DefaultBaseURL = "https://api.parse.sunholo.com"

// Client is the AILANG Parse API client.
type Client struct {
	APIKey  string
	BaseURL string
	HTTP    *http.Client

	// Keys provides API key management methods.
	Keys *KeyManager
}

// Option configures the client.
type Option func(*Client)

// WithBaseURL sets a custom API base URL.
func WithBaseURL(url string) Option {
	return func(c *Client) { c.BaseURL = url }
}

// WithHTTPClient sets a custom HTTP client.
func WithHTTPClient(hc *http.Client) Option {
	return func(c *Client) { c.HTTP = hc }
}

// New creates a new AILANG Parse client.
func New(apiKey string, opts ...Option) *Client {
	c := &Client{
		APIKey:  apiKey,
		BaseURL: DefaultBaseURL,
		HTTP: &http.Client{
			Timeout: 60 * time.Second,
		},
	}
	for _, opt := range opts {
		opt(c)
	}
	c.Keys = &KeyManager{client: c}
	return c
}

// DeviceAuthResult holds the result of a successful device auth flow.
type DeviceAuthResult struct {
	APIKey string `json:"api_key"`
	KeyID  string `json:"key_id"`
	Tier   string `json:"tier"`
	Label  string `json:"label"`
}

// DeviceAuth runs the full RFC 8628 device authorization flow.
// It requests a device code, prints the verification URL, then polls until
// the user approves (or the context is cancelled / timeout expires).
// On success, the resulting API key is stored on the client.
func (c *Client) DeviceAuth(ctx context.Context, label string) (*DeviceAuthResult, error) {
	if label == "" {
		label = "default"
	}

	// 1. Request device code (unauthenticated)
	reqBody, _ := json.Marshal(map[string]string{"label": label, "scope": "parse"})
	req, err := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/api/v1/auth/device", bytes.NewReader(reqBody))
	if err != nil {
		return nil, fmt.Errorf("create device request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("device request: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	data, err := c.unwrap(body)
	if err != nil {
		return nil, fmt.Errorf("device response: %w", err)
	}

	var deviceResp struct {
		DeviceCode      string `json:"device_code"`
		UserCode        string `json:"user_code"`
		VerificationURL string `json:"verification_url"`
		Interval        int    `json:"interval"`
	}
	if err := json.Unmarshal(data, &deviceResp); err != nil {
		return nil, fmt.Errorf("parse device response: %w", err)
	}

	interval := time.Duration(deviceResp.Interval) * time.Second
	if interval == 0 {
		interval = 5 * time.Second
	}

	// 2. Print instructions
	fmt.Printf("\n  Authorize this device:\n  %s\n  Code: %s\n\n", deviceResp.VerificationURL, deviceResp.UserCode)

	// 3. Poll until approved
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-ticker.C:
			pollBody, _ := json.Marshal(map[string]string{"deviceCode": deviceResp.DeviceCode})
			pollReq, err := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/api/v1/auth/device/poll", bytes.NewReader(pollBody))
			if err != nil {
				return nil, err
			}
			pollReq.Header.Set("Content-Type", "application/json")

			pollResp, err := c.HTTP.Do(pollReq)
			if err != nil {
				return nil, fmt.Errorf("poll request: %w", err)
			}
			pollData, _ := io.ReadAll(pollResp.Body)
			pollResp.Body.Close()

			result, err := c.unwrap(pollData)
			if err != nil {
				return nil, fmt.Errorf("poll response: %w", err)
			}

			var poll struct {
				Status string `json:"status"`
				APIKey string `json:"api_key"`
				KeyID  string `json:"key_id"`
				Tier   string `json:"tier"`
				Label  string `json:"label"`
				Error  string `json:"error"`
			}
			json.Unmarshal(result, &poll)

			if poll.Status == "approved" && poll.APIKey != "" {
				c.APIKey = poll.APIKey
				return &DeviceAuthResult{
					APIKey: poll.APIKey,
					KeyID:  poll.KeyID,
					Tier:   poll.Tier,
					Label:  poll.Label,
				}, nil
			}

			if poll.Error != "" && poll.Error != "AUTHORIZATION_PENDING" {
				return nil, fmt.Errorf("device auth error: %s", poll.Error)
			}
		}
	}
}

// unwrap extracts the inner result from a serve-api response envelope.
func (c *Client) unwrap(data []byte) ([]byte, error) {
	var outer serveAPIResponse
	if err := json.Unmarshal(data, &outer); err != nil {
		return nil, fmt.Errorf("unmarshal envelope: %w", err)
	}
	if outer.Error != "" {
		return nil, fmt.Errorf("API error: %s", outer.Error)
	}
	return []byte(outer.Result), nil
}

// call makes an API request and unwraps the serve-api response envelope.
func (c *Client) call(ctx context.Context, method, path string, args []string) ([]byte, error) {
	url := c.BaseURL + path

	var body io.Reader
	if method != http.MethodGet && args != nil {
		payload := struct {
			Args []string `json:"args"`
		}{Args: args}
		b, err := json.Marshal(payload)
		if err != nil {
			return nil, fmt.Errorf("marshal args: %w", err)
		}
		body = bytes.NewReader(b)
	}

	req, err := http.NewRequestWithContext(ctx, method, url, body)
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if c.APIKey != "" {
		req.Header.Set("x-api-key", c.APIKey)
	}

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode == 401 {
		return nil, fmt.Errorf("auth error: invalid or missing API key")
	}
	if resp.StatusCode == 429 {
		return nil, fmt.Errorf("quota exceeded")
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("API error %d: %s", resp.StatusCode, string(data))
	}

	return c.unwrap(data)
}
