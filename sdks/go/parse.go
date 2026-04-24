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
	"strconv"
	"strings"
)

// ParseOptions configures a parse request.
type ParseOptions struct {
	OutputFormat string // "blocks" (default), "markdown", "html", "markdown+metadata", "a2ui", "a2ui+editable"
	SourceURL    string // URL to fetch and parse (instead of a local file path)
}

// Parse parses a document file and returns structured blocks.
func (c *Client) Parse(ctx context.Context, filePath string, opts ...ParseOptions) (*ParseResult, error) {
	format := "blocks"
	var sourceURL string
	if len(opts) > 0 {
		if opts[0].OutputFormat != "" {
			format = opts[0].OutputFormat
		}
		sourceURL = opts[0].SourceURL
	}

	body := map[string]string{
		"filepath":     filePath,
		"outputFormat": format,
	}
	if sourceURL != "" {
		body["sourceUrl"] = sourceURL
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
	respHeader := resp.Header
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

	inner, err := c.unwrap(data)
	if err != nil {
		return nil, err
	}
	result, err := buildParseResult(inner, format)
	if err != nil {
		return nil, err
	}
	result.ResponseMeta = extractResponseMeta(respHeader)
	return result, nil
}

// ParseURL is a convenience method that parses a document at a remote URL.
func (c *Client) ParseURL(ctx context.Context, url string, outputFormat string) (*ParseResult, error) {
	opts := ParseOptions{
		OutputFormat: outputFormat,
		SourceURL:    url,
	}
	return c.Parse(ctx, "", opts)
}

// buildParseResult builds a ParseResult from the inner unwrapped bytes.
// For outputFormat="markdown" / "html" the API returns a raw rendered string
// (not a JSON object), which we surface as ParseResult.Text instead of
// failing to unmarshal it.
func buildParseResult(inner []byte, format string) (*ParseResult, error) {
	trimmed := bytes.TrimSpace(inner)
	if len(trimmed) > 0 && trimmed[0] != '{' && trimmed[0] != '[' {
		return &ParseResult{
			Status: "ok",
			Format: format,
			Text:   string(inner),
		}, nil
	}
	if len(trimmed) > 0 && trimmed[0] == '[' {
		var nodes []interface{}
		if err := json.Unmarshal(inner, &nodes); err != nil {
			return nil, fmt.Errorf("unmarshal a2ui nodes: %w", err)
		}
		return &ParseResult{Status: "ok", Format: format, Nodes: nodes}, nil
	}
	var result ParseResult
	if err := json.Unmarshal(inner, &result); err != nil {
		return nil, fmt.Errorf("unmarshal parse result: %w", err)
	}
	// markdown+metadata responses have no status field — default to "ok".
	if result.Status == "" && result.Format != "" {
		result.Status = "ok"
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
	respHeader := resp.Header

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

	inner, err := c.unwrap(data)
	if err != nil {
		return nil, err
	}
	result, err := buildParseResult(inner, format)
	if err != nil {
		return nil, err
	}
	result.ResponseMeta = extractResponseMeta(respHeader)
	return result, nil
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

// extractResponseMeta reads quota and request metadata from HTTP response headers.
func extractResponseMeta(h http.Header) *ResponseMeta {
	return &ResponseMeta{
		RequestID:           h.Get("X-Request-Id"),
		Tier:                h.Get("X-DocParse-Tier"),
		QuotaRemainingDay:   headerInt(h, "X-DocParse-Quota-Remaining-Day"),
		QuotaRemainingMonth: headerInt(h, "X-DocParse-Quota-Remaining-Month"),
		QuotaRemainingAI:    headerInt(h, "X-DocParse-Quota-Remaining-Ai"),
		Format:              h.Get("X-AilangParse-Format"),
		Replayable:          strings.EqualFold(h.Get("X-AilangParse-Replayable"), "true"),
	}
}

func headerInt(h http.Header, key string) int {
	v := h.Get(key)
	if v == "" {
		return -1
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return -1
	}
	return n
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
