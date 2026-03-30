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

	// Unwrap serve-api envelope
	var outer serveAPIResponse
	if err := json.Unmarshal(data, &outer); err != nil {
		return nil, fmt.Errorf("unmarshal envelope: %w", err)
	}
	if outer.Error != "" {
		return nil, fmt.Errorf("API error: %s", outer.Error)
	}

	return []byte(outer.Result), nil
}
