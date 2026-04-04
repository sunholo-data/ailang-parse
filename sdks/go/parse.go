package docparse

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
)

// ParseOptions configures a parse request.
type ParseOptions struct {
	OutputFormat string // "blocks" (default), "markdown", "html"
}

// Parse parses a document file and returns structured blocks.
func (c *Client) Parse(ctx context.Context, filePath string, opts ...ParseOptions) (*ParseResult, error) {
	format := "blocks"
	if len(opts) > 0 && opts[0].OutputFormat != "" {
		format = opts[0].OutputFormat
	}

	body := map[string]string{
		"filepath":     filePath,
		"outputFormat": format,
	}
	if c.APIKey != "" {
		body["apiKey"] = c.APIKey
	}
	b, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshal body: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/api/v1/parse", bytes.NewReader(b))
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

	inner, err := c.unwrap(data)
	if err != nil {
		return nil, err
	}

	var result ParseResult
	if err := json.Unmarshal(inner, &result); err != nil {
		return nil, fmt.Errorf("unmarshal parse result: %w", err)
	}
	return &result, nil
}

// ParseFile uploads a local file and parses it. Returns structured blocks.
//
// Uses multipart/form-data to upload the file directly to the API.
// Works on all tiers (Free: 10 MB, Pro: 25 MB, Business: 50 MB).
func (c *Client) ParseFile(ctx context.Context, path string, opts ...ParseOptions) (*ParseResult, error) {
	format := "blocks"
	if len(opts) > 0 && opts[0].OutputFormat != "" {
		format = opts[0].OutputFormat
	}

	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open file: %w", err)
	}
	defer f.Close()

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)

	part, err := writer.CreateFormFile("filepath", filepath.Base(path))
	if err != nil {
		return nil, fmt.Errorf("create form file: %w", err)
	}
	if _, err := io.Copy(part, f); err != nil {
		return nil, fmt.Errorf("copy file data: %w", err)
	}
	writer.WriteField("outputFormat", format)
	if c.APIKey != "" {
		writer.WriteField("apiKey", c.APIKey)
	}
	writer.Close()

	req, err := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/api/v1/parse", &body)
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
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

	inner, err := c.unwrap(data)
	if err != nil {
		return nil, err
	}

	var result ParseResult
	if err := json.Unmarshal(inner, &result); err != nil {
		return nil, fmt.Errorf("unmarshal parse result: %w", err)
	}
	return &result, nil
}

// Health checks the API health.
func (c *Client) Health(ctx context.Context) (*HealthResult, error) {
	data, err := c.call(ctx, "GET", "/api/v1/health", nil)
	if err != nil {
		return nil, err
	}

	var result HealthResult
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("unmarshal health: %w", err)
	}
	return &result, nil
}

// Formats lists supported parse and generate formats.
func (c *Client) Formats(ctx context.Context) (*FormatsResult, error) {
	data, err := c.call(ctx, "GET", "/api/v1/formats", nil)
	if err != nil {
		return nil, err
	}

	var result FormatsResult
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("unmarshal formats: %w", err)
	}
	return &result, nil
}
