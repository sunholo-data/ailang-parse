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

// UnstructuredClient is a drop-in replacement for the Unstructured API client.
//
// Migration:
//
//	// Before
//	client := unstructured.New("https://api.unstructured.io")
//
//	// After
//	client := ailangparse.NewUnstructuredClient("https://api.parse.sunholo.com")
type UnstructuredClient struct {
	client *Client
}

// NewUnstructuredClient creates an Unstructured-compatible client.
func NewUnstructuredClient(serverURL string, apiKey ...string) *UnstructuredClient {
	key := ""
	if len(apiKey) > 0 {
		key = apiKey[0]
	}
	return &UnstructuredClient{
		client: New(key, WithBaseURL(serverURL)),
	}
}

// Partition partitions a document into Unstructured-format elements.
//
// Accepts a local file path (uploaded via multipart) or a sample ID (sent as JSON).
// Usage is identical to the Unstructured client.
func (uc *UnstructuredClient) Partition(ctx context.Context, filePath string, strategy ...string) ([]Element, error) {
	strat := "auto"
	if len(strategy) > 0 {
		strat = strategy[0]
	}

	url := uc.client.BaseURL + "/general/v0/general"
	var req *http.Request

	// Check if filePath is a local file — if so, upload via multipart
	if f, err := os.Open(filePath); err == nil {
		defer f.Close()
		var body bytes.Buffer
		writer := multipart.NewWriter(&body)
		part, err := writer.CreateFormFile("files", filepath.Base(filePath))
		if err != nil {
			return nil, fmt.Errorf("create form file: %w", err)
		}
		if _, err := io.Copy(part, f); err != nil {
			return nil, fmt.Errorf("copy file data: %w", err)
		}
		writer.WriteField("strategy", strat)
		writer.Close()

		req, err = http.NewRequestWithContext(ctx, "POST", url, &body)
		if err != nil {
			return nil, fmt.Errorf("create request: %w", err)
		}
		req.Header.Set("Content-Type", writer.FormDataContentType())
	} else {
		// Sample ID or server-side path — send as JSON
		jsonBody := map[string]string{"filepath": filePath, "strategy": strat}
		b, _ := json.Marshal(jsonBody)
		req, err = http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(b))
		if err != nil {
			return nil, fmt.Errorf("create request: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")
	}

	if uc.client.APIKey != "" {
		req.Header.Set("unstructured-api-key", uc.client.APIKey)
	}
	resp, err := uc.client.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()
	rawData, err := io.ReadAll(resp.Body)
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
		return nil, newDocParseError(fmt.Sprintf("API error %d: %s", resp.StatusCode, string(rawData)), resp.StatusCode)
	}
	data, err := uc.client.unwrap(rawData)
	if err != nil {
		return nil, err
	}

	var elements []Element
	if err := json.Unmarshal(data, &elements); err != nil {
		return nil, fmt.Errorf("unmarshal elements: %w", err)
	}
	return elements, nil
}
