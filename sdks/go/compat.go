package docparse

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
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
// Note: filepath must be a sample ID or server-side path, not a local file path.
// The /general/v0/general endpoint does not yet support multipart file upload.
// To upload local files, use [Client.ParseFile] instead.
func (uc *UnstructuredClient) Partition(ctx context.Context, filepath string, strategy ...string) ([]Element, error) {
	strat := "auto"
	if len(strategy) > 0 {
		strat = strategy[0]
	}

	body := map[string]string{"filepath": filepath, "strategy": strat}
	b, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, "POST", uc.client.BaseURL+"/general/v0/general", bytes.NewReader(b))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
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
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("API error %d: %s", resp.StatusCode, string(rawData))
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
