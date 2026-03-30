package docparse

import (
	"context"
	"encoding/json"
	"fmt"
)

// ParseOptions configures a parse request.
type ParseOptions struct {
	OutputFormat string // "blocks" (default), "markdown", "html"
}

// Parse parses a document file and returns structured blocks.
func (c *Client) Parse(ctx context.Context, filepath string, opts ...ParseOptions) (*ParseResult, error) {
	format := "blocks"
	if len(opts) > 0 && opts[0].OutputFormat != "" {
		format = opts[0].OutputFormat
	}

	data, err := c.call(ctx, "POST", "/api/v1/parse", []string{filepath, format})
	if err != nil {
		return nil, err
	}

	var result ParseResult
	if err := json.Unmarshal(data, &result); err != nil {
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
