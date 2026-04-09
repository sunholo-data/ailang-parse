package docparse

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"time"
)

const DefaultBaseURL = "https://docparse.ailang.sunholo.com"

const configDirName = "ailang-parse"
const credentialsFile = "credentials.json"

// configDir returns the platform-appropriate config directory for AILANG Parse.
//
//   - Linux/macOS: $XDG_CONFIG_HOME/ailang-parse or ~/.config/ailang-parse
//   - Windows: %APPDATA%\ailang-parse
func configDir() string {
	if runtime.GOOS == "windows" {
		base := os.Getenv("APPDATA")
		if base == "" {
			home, _ := os.UserHomeDir()
			base = filepath.Join(home, "AppData", "Roaming")
		}
		return filepath.Join(base, configDirName)
	}
	base := os.Getenv("XDG_CONFIG_HOME")
	if base == "" {
		home, _ := os.UserHomeDir()
		base = filepath.Join(home, ".config")
	}
	return filepath.Join(base, configDirName)
}

// savedCredentials is the on-disk format for stored API keys.
type savedCredentials struct {
	APIKey  string `json:"api_key"`
	BaseURL string `json:"base_url"`
	KeyID   string `json:"key_id"`
	Tier    string `json:"tier"`
	Label   string `json:"label"`
}

// loadSavedKey reads stored credentials for the given base URL.
func loadSavedKey(baseURL string) *savedCredentials {
	credPath := filepath.Join(configDir(), credentialsFile)
	data, err := os.ReadFile(credPath)
	if err != nil {
		return nil
	}
	var cred savedCredentials
	if err := json.Unmarshal(data, &cred); err != nil {
		return nil
	}
	if len(cred.APIKey) < 3 || cred.APIKey[:3] != "dp_" {
		return nil
	}
	savedBase := cred.BaseURL
	if savedBase == "" {
		savedBase = DefaultBaseURL
	}
	if savedBase != baseURL {
		return nil
	}
	return &cred
}

// ResolveAPIKey returns any saved API key from the DOCPARSE_API_KEY env var
// or the credentials file, without filtering by base URL.
//
// Used by the MCP CLI bridge, which forwards to whatever endpoint the user
// configured via AILANG_PARSE_MCP_URL and just needs *a* key to inject.
// Library callers that need strict base-URL matching should use the
// internal loadSavedKey via the Client constructor instead.
func ResolveAPIKey() string {
	if k := os.Getenv("DOCPARSE_API_KEY"); k != "" {
		return k
	}
	credPath := filepath.Join(configDir(), credentialsFile)
	data, err := os.ReadFile(credPath)
	if err != nil {
		return ""
	}
	var cred savedCredentials
	if err := json.Unmarshal(data, &cred); err != nil {
		return ""
	}
	if len(cred.APIKey) >= 3 && cred.APIKey[:3] == "dp_" {
		return cred.APIKey
	}
	return ""
}

// saveKey persists credentials to disk with restrictive permissions.
func saveKey(apiKey, baseURL, keyID, tier, label string) error {
	dir := configDir()
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	cred := savedCredentials{
		APIKey:  apiKey,
		BaseURL: baseURL,
		KeyID:   keyID,
		Tier:    tier,
		Label:   label,
	}
	data, err := json.MarshalIndent(cred, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(filepath.Join(dir, credentialsFile), data, 0600)
}

// Client is the AILANG Parse API client.
//
// API key resolution order:
//  1. Explicit apiKey parameter to New()
//  2. DOCPARSE_API_KEY environment variable
//  3. Saved credentials in ~/.config/ailang-parse/credentials.json
type Client struct {
	APIKey  string
	BaseURL string
	HTTP    *http.Client

	// KeyID is the id of the currently configured key, populated from
	// saved credentials or a successful DeviceAuth flow. Used by KeyInfo
	// when the caller has not passed an explicit id.
	KeyID string

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
// If apiKey is empty, it checks DOCPARSE_API_KEY env var and then saved credentials.
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

	// Resolve API key: explicit > env var > saved credentials
	if c.APIKey == "" {
		c.APIKey = os.Getenv("DOCPARSE_API_KEY")
	}
	if c.APIKey == "" {
		if saved := loadSavedKey(c.BaseURL); saved != nil {
			c.APIKey = saved.APIKey
			c.KeyID = saved.KeyID
		}
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
	// VerificationURL is the user-facing URL printed during the flow.
	VerificationURL string `json:"verification_url"`
	// PollURL is the /api/v1/auth/device/poll endpoint used during the flow.
	PollURL string `json:"poll_url"`
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
				c.KeyID = poll.KeyID
				_ = saveKey(poll.APIKey, c.BaseURL, poll.KeyID, poll.Tier, poll.Label)
				return &DeviceAuthResult{
					APIKey:          poll.APIKey,
					KeyID:           poll.KeyID,
					Tier:            poll.Tier,
					Label:           poll.Label,
					VerificationURL: deviceResp.VerificationURL,
					PollURL:         c.BaseURL + "/api/v1/auth/device/poll",
				}, nil
			}

			if poll.Error != "" && poll.Error != "AUTHORIZATION_PENDING" {
				return nil, fmt.Errorf("device auth error: %s", poll.Error)
			}
		}
	}
}

// unwrap extracts the inner result from a serve-api response envelope.
//
// Auth-like envelope error strings ("Invalid or expired API key",
// "Unauthorized", etc.) are returned as *AuthError so callers can detect
// them via errors.As / errors.Is(err, ErrAuth) — even when the server
// reports them inside a 200-OK envelope rather than as a 401.
func (c *Client) unwrap(data []byte) ([]byte, error) {
	var outer serveAPIResponse
	if err := json.Unmarshal(data, &outer); err != nil {
		return nil, fmt.Errorf("unmarshal envelope: %w", err)
	}
	if outer.Error != "" {
		// Try structured error: {error: {code, message, details, ...}, request_id: "..."}
		// or legacy: {error: "CODE", message: "...", suggested_fix: "..."}
		msg := outer.Error
		var suggestedFix, requestID string
		var details map[string]interface{}

		// Try new-style dict error envelope
		var dictEnvelope struct {
			Error struct {
				Message      string                 `json:"message"`
				SuggestedFix string                 `json:"suggested_fix"`
				Details      map[string]interface{} `json:"details"`
			} `json:"error"`
			RequestID string `json:"request_id"`
		}
		if json.Unmarshal(data, &dictEnvelope) == nil && dictEnvelope.Error.Message != "" {
			msg = dictEnvelope.Error.Message
			suggestedFix = dictEnvelope.Error.SuggestedFix
			details = dictEnvelope.Error.Details
			requestID = dictEnvelope.RequestID
		} else {
			// Fall back to legacy flat envelope
			var structured struct {
				Message      string `json:"message"`
				SuggestedFix string `json:"suggested_fix"`
			}
			if json.Unmarshal(data, &structured) == nil {
				if structured.Message != "" {
					msg = structured.Message
				}
				suggestedFix = structured.SuggestedFix
			}
		}
		if details != nil || requestID != "" {
			return nil, envelopeErrorFull(msg, suggestedFix, requestID, details)
		}
		if suggestedFix != "" {
			return nil, envelopeErrorWithFix(msg, suggestedFix)
		}
		return nil, envelopeError(msg)
	}
	inner := []byte(outer.Result)
	// If no result field, return the raw response (e.g. health, formats)
	if len(inner) == 0 {
		return data, nil
	}
	// Check for error in inner result (API wraps errors in envelope too)
	var innerObj struct {
		Error     json.RawMessage `json:"error,omitempty"`
		RequestID string          `json:"request_id,omitempty"`
	}
	if json.Unmarshal(inner, &innerObj) == nil && len(innerObj.Error) > 0 && string(innerObj.Error) != "null" {
		var errObj struct {
			Message      string                 `json:"message"`
			SuggestedFix string                 `json:"suggested_fix"`
			Details      map[string]interface{} `json:"details"`
		}
		if json.Unmarshal(innerObj.Error, &errObj) == nil && errObj.Message != "" {
			return nil, envelopeErrorFull(errObj.Message, errObj.SuggestedFix, innerObj.RequestID, errObj.Details)
		}
		return nil, envelopeError(string(innerObj.Error))
	}
	return inner, nil
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
		return nil, newAuthError("")
	}
	if resp.StatusCode == 429 {
		return nil, newQuotaError("")
	}
	if resp.StatusCode >= 400 {
		return nil, newDocParseError(fmt.Sprintf("API error %d: %s", resp.StatusCode, string(data)), resp.StatusCode)
	}

	return c.unwrap(data)
}
